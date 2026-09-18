# -*- coding: utf-8 -*-
"""迁移导入：把 migrate_export.py 导出的 JSON 导入新 PostgreSQL workspace。

用法（需新 workspace Running + 已配置 pgdirect 后端 + pg8000 已安装）：
    python scripts/migrate_import.py --in _migrate_export.json

说明：
- 走 cloud_db（CLOUD_DB_BACKEND=pgdirect）逐表插入。
- 表必须已在新库创建（Step 4 schema 迁移后）。
- 保留原 id/时间戳/JSON 字段，避免业务引用断裂。
- 幂等思路：先清空目标表再插入（导出是快照，重复执行应可覆盖）。
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 加载 .env（含 PG 连接信息 + CLOUD_DB_BACKEND=pgdirect）
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"'))

import cloud_db


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", default="_migrate_export.json")
    args = ap.parse_args()

    if cloud_db._BACKEND != "pgdirect":
        print("WARNING: CLOUD_DB_BACKEND 不是 pgdirect，导入可能写到旧库！")
        print("  请设置 CLOUD_DB_BACKEND=pgdirect + PG 连接信息后重试")
        sys.exit(1)
    if not cloud_db._PG_ENABLED:
        print("ERROR: pgdirect 后端不可用（缺连接信息或 pg8000 未装）")
        sys.exit(1)

    data = json.loads(Path(args.infile).read_text(encoding="utf-8"))
    print(f"从 {args.infile} 导入 {len(data)} 张表")

    total = 0
    for table, rows in data.items():
        if not rows:
            print(f"  - {table}: 空，跳过")
            continue
        # 清空目标表（快照覆盖，幂等）
        try:
            cloud_db.delete(table, filters=[("id", "gt", 0)])
        except Exception:
            cloud_db.delete(table, filters=[("id", "neq", 0)])
        n = cloud_db.insert_many(table, rows)
        total += n
        print(f"  - {table}: 插入 {n}/{len(rows)} 行")
    print(f"完成，共导入 {total} 行")


if __name__ == "__main__":
    main()
