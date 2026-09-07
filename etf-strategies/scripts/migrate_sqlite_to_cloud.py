"""migrate_sqlite_to_cloud.py — 一次性存量数据迁移（cache.db → 火山 Supabase 云库）。

把现有本地 SQLite（cache.db）中所有"权威表"数据迁到云端 Postgres（PostgREST Data API），
供 DASHBOARD_DB_BACKEND=cloud 模式使用。幂等：可重复执行，不产生重复行。

迁移范围（权威表，与 dashboard/db.py 云后端一致）：
  users / portfolio_holdings / portfolio_trades / portfolio_meta / metadata(→portfolio_meta)
  daily_reports / scheduler_runs / strategy_kb / strategy_metrics / daily_signals

可重建缓存表（kline_daily / backtest_nav）不入云，留在本地。

用法：
  python scripts/migrate_sqlite_to_cloud.py [--dry-run] [--cache-db path]
需设置 SUPABASE_URL / SUPABASE_SERVICE_KEY（或 .env）。
"""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cloud_db import delete as cd_delete
from cloud_db import insert_many as cd_insert_many
from cloud_db import select as cd_select
from cloud_db import upsert as cd_upsert
from cloud_db import upsert_many as cd_upsert_many

DEFAULT_CACHE_DB = Path(__file__).resolve().parent.parent / "dashboard" / "data" / "cache.db"

# 表 → (云表名, sqlite 字段子集, 唯一键 on_conflict | None=整表替换, 需 JSON 解析的字段)
# 说明：
#  - upsert 表按自然键冲突合并，保留云上已存在的其它行（幂等且不破坏云数据）
#  - replace 表（无自然键/快照语义）先清空再插入
TABLES = [
    # users：username 唯一 → upsert
    ("users", "users",
     ["username", "password_hash", "display_name", "role", "is_active",
      "created_at", "last_login"], "username", []),
    # portfolio_holdings：code 唯一（云 schema 未约束，用 replace 保证幂等）
    ("portfolio_holdings", "portfolio_holdings",
     ["code", "name", "shares", "cost_price", "updated_at"], None, []),
    # portfolio_trades：无自然键，replace
    ("portfolio_trades", "portfolio_trades",
     ["trade_date", "name", "code", "quantity", "price", "side", "remark",
      "created_at"], None, []),
    # portfolio_meta：key 主键 → upsert
    ("portfolio_meta", "portfolio_meta", ["key", "value"], "key", []),
    # metadata（seeded 标记等）→ 并入 portfolio_meta
    ("metadata", "portfolio_meta", ["key", "value"], "key", []),
    # daily_reports：(report_date, report_type) 无唯一约束 → replace
    ("daily_reports", "daily_reports",
     ["report_date", "report_type", "markdown", "status", "generated_at",
      "source_file"], None, []),
    # scheduler_runs：无自然键，replace
    ("scheduler_runs", "scheduler_runs",
     ["task_id", "window_key", "trigger", "run_time", "status", "pid",
      "duration_sec", "output", "completed_at"], None, []),
    # strategy_kb：strategy_id 主键 → upsert；backtest_params JSON
    ("strategy_kb", "strategy_kb",
     ["strategy_id", "name", "class_name", "category", "intro",
      "stock_selection", "market_timing", "factors", "rebalance", "strengths",
      "weaknesses", "source_url", "process_desc", "backtest_params"],
     "strategy_id", ["backtest_params"]),
    # strategy_metrics：strategy_id 主键 → upsert；assets_json JSON
    ("strategy_metrics", "strategy_metrics",
     ["strategy_id", "name", "category", "category_cn", "annual_return",
      "sharpe", "max_drawdown", "calmar", "win_rate", "turnover",
      "excess_return", "assets_json", "description", "backtest_window"],
     "strategy_id", ["assets_json"]),
    # daily_signals：无自然键，replace
    ("daily_signals", "daily_signals",
     ["strategy_id", "signal_date", "asset_code", "asset_name",
      "target_weight", "prev_weight", "weight_change", "action", "updated_at"],
     None, []),
]


def _conn(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def migrate(db_path: Path, dry_run: bool = False) -> dict:
    if not db_path.exists():
        print(f"[migrate] 未找到 {db_path}，跳过")
        return {"skipped": True}

    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY")):
        print("[migrate] 错误：未设置 SUPABASE_URL / SUPABASE_SERVICE_KEY")
        sys.exit(2)

    report = {}
    conn = _conn(db_path)
    for src_table, cloud_table, cols, on_conflict, json_fields in TABLES:
        try:
            rows = [dict(r) for r in conn.execute(
                f"SELECT {', '.join(cols)} FROM {src_table}")]
        except sqlite3.OperationalError as e:
            print(f"[migrate] {src_table}: 跳过（{e}）")
            continue

        if not rows:
            print(f"[migrate] {src_table}: 0 行，跳过")
            report[f"{src_table}->{cloud_table}"] = 0
            continue

        # JSON 字段：sqlite 存 JSON 字符串 → 解析为对象（JSONB 列）
        for r in rows:
            for f in json_fields:
                if r.get(f) is not None and isinstance(r[f], str):
                    try:
                        r[f] = json.loads(r[f])
                    except (json.JSONDecodeError, TypeError):
                        r[f] = None

        if dry_run:
            print(f"[migrate][dry] {src_table} -> {cloud_table}: 将迁移 {len(rows)} 行")
            report[f"{src_table}->{cloud_table}"] = len(rows)
            continue

        if on_conflict:
            # upsert（按自然键合并，幂等）
            ok = cd_upsert_many(cloud_table, rows, on_conflict=on_conflict)
            print(f"[migrate] {src_table} -> {cloud_table}: upsert {ok}/{len(rows)}")
            report[f"{src_table}->{cloud_table}"] = ok
        else:
            # 整表替换（快照语义，幂等）
            if not rows:
                continue
            # 清空云表
            try:
                deleted = cd_delete(cloud_table, filters=[("id", "gt", 0)])
            except Exception as e:
                print(f"[migrate] {cloud_table} 清空失败: {e}")
                deleted = 0
            ok = cd_insert_many(cloud_table, rows)
            print(f"[migrate] {src_table} -> {cloud_table}: 替换 {ok}/{len(rows)}（旧 {deleted}）")
            report[f"{src_table}->{cloud_table}"] = ok

    conn.close()

    # 汇总校验：云上行数
    if not dry_run:
        print("\n[migrate] 云上行数校验：")
        for src_table, cloud_table, *_ in TABLES:
            col = "key" if cloud_table == "portfolio_meta" else (
                "strategy_id" if cloud_table in ("strategy_kb", "strategy_metrics") else "id")
            try:
                n = len(cd_select(cloud_table, columns=col))
                print(f"  {cloud_table:24s} {n} 行")
            except Exception as e:
                print(f"  {cloud_table:24s} ERR {e}")

    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="迁移 cache.db 权威表到云库")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划不执行")
    ap.add_argument("--cache-db", type=Path, default=DEFAULT_CACHE_DB)
    args = ap.parse_args()
    migrate(args.cache_db, dry_run=args.dry_run)
