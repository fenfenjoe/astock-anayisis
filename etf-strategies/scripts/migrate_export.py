# -*- coding: utf-8 -*-
"""迁移导出：从现有 Supabase 云库全量导出全部表 → JSON 文件。

用法（需旧 workspace 处于 Running 状态）：
    python scripts/migrate_export.py --out _migrate_export.json

输出：{ "table": [ {row}, ... ], ... }（每行 dict，字段与云库一致）。
后续由 scripts/migrate_import.py 导入新 PostgreSQL workspace。

说明：
- 走 cloud_db.select 全量读取（KB 级数据，无分页压力）。
- 表清单优先用 information_schema 动态探测；探测失败（workspace 停止）时
  回退到已知清单（agent + dashboard 全部云表）。
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 加载 .env
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"'))

import cloud_db

# 已知云表清单（information_schema 探测失败时的兜底）
KNOWN_TABLES = [
    # agent
    "agent_sessions", "agent_messages", "agent_articles", "agent_opinions",
    "agent_knowledge", "agent_metadata", "agent_sources", "agent_activities",
    "platform_cookies", "platform_reachability", "agent_notices", "tickets",
    # dashboard
    "portfolio_meta", "strategy_metrics", "daily_signals", "strategy_kb",
    "users", "portfolio_holdings", "portfolio_trades", "daily_reports",
    "scheduler_runs", "signal_tracking",
]


def _discover_tables():
    """用 information_schema 探测 public schema 全部表。失败返回 None。"""
    try:
        rows = cloud_db.select(
            "information_schema.tables",  # 不可直接查（PostgREST 限定 public）
            columns="table_name",
        )
        return [r["table_name"] for r in rows]
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_migrate_export.json")
    args = ap.parse_args()

    if not cloud_db.enabled():
        print("ERROR: cloud_db 未启用（缺 SUPABASE_URL/KEY），无法导出")
        sys.exit(1)

    # PostgREST 无法直接查 information_schema → 用已知清单
    tables = KNOWN_TABLES
    print(f"导出 {len(tables)} 张表 → {args.out}")

    out = {}
    for t in tables:
        try:
            # 优先按 id 排序；部分表无 id 列（主键为其他列）→ 降级无排序全量读
            try:
                rows = cloud_db.select(t, columns="*", order="id.asc")
            except Exception:
                rows = cloud_db.select(t, columns="*")
        except Exception as e:
            print(f"  - {t}: 跳过（{e}）")
            continue
        out[t] = rows
        print(f"  - {t}: {len(rows)} 行")

    Path(args.out).write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"完成 → {args.out}")


if __name__ == "__main__":
    main()
