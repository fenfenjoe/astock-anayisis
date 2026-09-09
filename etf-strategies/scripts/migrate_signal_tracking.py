#!/usr/bin/env python3
"""信号云库化迁移脚本（记忆体系 Phase 3 · 方案 v1.10 §9.2/§9.3）

把本地 `harness/automation/config/signal_tracking.json` 中全部历史信号一次性迁移
写入云库 `signal_tracking` 表（signal_id 主键，25 字段全量，幂等可重跑）。

设计要点（方案 §9.2 决策 25/28/39/47）：
- 云库为权威：迁移后复盘/周报直接写云库；signal_tracking.json 过渡期仅作只读缓存。
- 幂等：按 signal_id upsert（on_conflict），重跑不会产生重复行，数量核对一致。
- 迁移后把 signal_tracking.json 改名 .bak 保留一周（决策 47）。

用法：
    python scripts/migrate_signal_tracking.py          # 只读预演（打印计划）
    python scripts/migrate_signal_tracking.py --apply  # 实际写入云库
    python scripts/migrate_signal_tracking.py --apply --rename-bak  # 写入+改名.bak
"""
import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "etf-strategies"))

# 从 etf-strategies/.env 加载 SUPABASE_URL / SUPABASE_SERVICE_KEY
def _load_env():
    env_path = ROOT / "etf-strategies" / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


# JSON 字段 → 云表列映射（键名相同；trigger_date → signal_date）
_COLUMN_MAP = {
    "signal_id": "signal_id",
    "trigger_date": "signal_date",
    "priority": "priority",
    "ticker": "ticker",
    "name": "name",
    "trade_type": "trade_type",
    "direction": "direction",
    "urgency": "urgency",
    "expected_trigger_rate": "expected_trigger_rate",
    "target_price": "target_price",
    "stop_price": "stop_price",
    "target_pct": "target_pct",
    "stop_pct": "stop_pct",
    "expected_return_date": "expected_return_date",
    "entry_price": "entry_price",
    "shares": "shares",
    "status": "status",
    "status_history": "status_history",
    "avoided_loss": "avoided_loss",
    "settle_date": "settle_date",
    "exit_date": "exit_date",
    "settle_price": "settle_price",
    "pnl": "pnl",
    "holding_days": "holding_days",
    "outcome": "outcome",
    "cost_basis": "cost_basis",
    "sell_price": "sell_price",
}
# 本地 JSON 无、云表有、需留空的列（复盘回填列）
_EXTRA_COLUMNS = [
    "trigger_condition", "valid_window", "position", "source",
    "eval_decision_quality", "eval_execution_quality",
]
# 卖出信号才有的列（其余信号留空）
_SELL_COLUMNS = ["cost_basis", "sell_price"]


def _to_row(sig: dict) -> dict:
    # 固定列集合（全部 35 列显式出现），保证 PostgREST 批量 upsert 各行键一致
    row = {ckey: None for ckey in list(_COLUMN_MAP.values()) + _EXTRA_COLUMNS + _SELL_COLUMNS}
    for jkey, ckey in _COLUMN_MAP.items():
        val = sig.get(jkey)
        if val is not None:
            row[ckey] = val
    now = date.today().isoformat()
    row.setdefault("created_at", now)
    row["updated_at"] = now
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="实际写入云库（默认只读预演）")
    ap.add_argument("--rename-bak", action="store_true", help="迁移成功后 signal_tracking.json 改名 .bak")
    ap.add_argument("--tracking", default=None, help="signal_tracking.json 路径")
    args = ap.parse_args()

    tracking_path = Path(args.tracking) if args.tracking else (
        ROOT / "my_doc" / "每日复盘" / "harness" / "automation" / "config" / "signal_tracking.json"
    )
    if not tracking_path.exists():
        print(f"[ERR] 找不到 signal_tracking.json: {tracking_path}")
        sys.exit(1)

    data = json.loads(tracking_path.read_text(encoding="utf-8"))
    signals = data.get("signals", [])
    rows = [_to_row(s) for s in signals]
    print(f"本地信号数: {len(signals)}")

    _load_env()
    import cloud_db
    if not cloud_db.enabled():
        print("[ERR] 云库未配置（SUPABASE_URL/SERVICE_KEY 缺失），无法迁移")
        sys.exit(1)

    # 预演：查云库现有行数
    existing = cloud_db.select("signal_tracking", columns="signal_id", limit=1000)
    existing_ids = {r["signal_id"] for r in existing}
    print(f"云库现有信号行: {len(existing_ids)}")

    if not args.apply:
        print("\n[预演模式] 将 upsert 以下信号（--apply 实际写入）:")
        for r in rows:
            mark = "已有(更新)" if r["signal_id"] in existing_ids else "新增"
            print(f"  {mark}: {r['signal_id']} | {r.get('signal_date')} | {r.get('priority')} | {r.get('ticker')} {r.get('name')} | status={r.get('status')}")
        print(f"\n合计: 新增 {sum(1 for r in rows if r['signal_id'] not in existing_ids)} 条, "
              f"更新 {sum(1 for r in rows if r['signal_id'] in existing_ids)} 条")
        return

    # 实际写入：按 signal_id upsert
    ok = cloud_db.upsert_many("signal_tracking", rows, on_conflict="signal_id")
    print(f"\n云库写入成功: {ok} 条（应等于 {len(rows)}）")

    # 核对
    after = cloud_db.select("signal_tracking", columns="signal_id", limit=1000)
    after_ids = {r["signal_id"] for r in after}
    missing = [r["signal_id"] for r in rows if r["signal_id"] not in after_ids]
    if missing:
        print(f"[WARN] 云库缺少 {len(missing)} 条: {missing}")
    else:
        print(f"[OK] 全部 {len(rows)} 条信号已入库，数量核对一致")

    if args.rename_bak and not missing:
        bak = tracking_path.with_suffix(".json.bak")
        tracking_path.rename(bak)
        print(f"[OK] signal_tracking.json → {bak.name}（保留一周，之后删除）")


if __name__ == "__main__":
    main()
