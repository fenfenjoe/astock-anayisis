# -*- coding: utf-8 -*-
"""pg_exec_sql.py — pg8000 直连 PostgreSQL 执行 SQL 文件（建库/迁移 DDL）。

用途：AIDAP PostgreSQL 引擎 workspace 建库（Step 4）。旧 Supabase 引擎可用
byted-supabase-cli db query -f 执行；新 PostgreSQL 引擎若 CLI 不支持，用本脚本
pg8000 直连执行（psql 的 Python 替代）。

用法：
    python scripts/pg_exec_sql.py scripts/cloud_schema_pg.sql
    python scripts/pg_exec_sql.py --url "postgresql://user:pass@host:5432/db?sslmode=require" x.sql

连接信息优先级：--url > 环境变量 PGDATABASE_URL > PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD。
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 加载 .env（幂等：不覆盖已存在环境变量）
ENV_PATH = ROOT / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


def _connect(url: str | None):
    try:
        import pg8000
    except ImportError as e:
        print("ERROR: pg8000 未安装，请先 `pip install pg8000`（切换 pgdirect 必需）")
        raise SystemExit(1) from e

    # AIDAP PostgreSQL 引擎要求 SSL（sslmode=require）
    ssl_ctx = None
    if os.environ.get("PGSSLMODE", "require").strip().lower() not in ("disable",):
        import ssl

        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = True
        ssl_ctx.verify_mode = ssl.CERT_REQUIRED

    if url:
        from urllib.parse import urlparse, unquote

        u = urlparse(url)
        return pg8000.connect(
            host=u.hostname or "localhost",
            port=u.port or 5432,
            database=(u.path or "/").lstrip("/") or None,
            user=unquote(u.username or "") if u.username else None,
            password=unquote(u.password or "") if u.password else None,
            ssl_context=ssl_ctx,
        )
    return pg8000.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5432") or 5432),
        database=os.environ.get("PGDATABASE") or None,
        user=os.environ.get("PGUSER"),
        password=os.environ.get("PGPASSWORD"),
        ssl_context=ssl_ctx,
    )


def _split_statements(sql: str):
    """按分号切分 SQL 语句（跳过行注释与字符串内的分号，粗粒度够用）。"""
    stmts, buf, in_str, in_line_comment = [], [], None, False
    for ch in sql:
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            continue
        if in_str:
            buf.append(ch)
            if ch == in_str:
                in_str = None
            continue
        if ch == "-" and buf and buf[-1] == "-":
            buf.pop()
            in_line_comment = True
            continue
        if ch in ("'", '"'):
            in_str = ch
            buf.append(ch)
            continue
        if ch == ";":
            s = "".join(buf).strip()
            if s:
                stmts.append(s)
            buf = []
            continue
        buf.append(ch)
    s = "".join(buf).strip()
    if s:
        stmts.append(s)
    return stmts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sql_file", help="SQL 文件路径")
    ap.add_argument("--url", default=None, help="PG 连接串（优先于环境变量）")
    ap.add_argument("--echo", action="store_true", help="打印每条执行语句")
    args = ap.parse_args()

    sql = Path(args.sql_file).read_text(encoding="utf-8")
    stmts = _split_statements(sql)
    print(f"解析出 {len(stmts)} 条语句")

    conn = _connect(args.url)
    try:
        cur = conn.cursor()
        done = 0
        for s in stmts:
            # 跳过纯注释/空语句
            if not s or s.upper().startswith("SELECT") is False and not s:
                pass
            if args.echo:
                print(f"  >> {s[:80]}")
            cur.execute(s)
            done += 1
        conn.commit()
        print(f"执行完成：{done}/{len(stmts)} 条成功并提交")
    except Exception as e:
        conn.rollback()
        print(f"ERROR: 第 {done + 1} 条语句失败: {e}")
        print(f"  语句: {stmts[done][:120] if done < len(stmts) else '?'}")
        raise SystemExit(1) from e
    finally:
        conn.close()


if __name__ == "__main__":
    main()
