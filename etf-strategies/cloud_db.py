"""cloud_db.py — 云端权威数据库访问层（AIDAP Supabase / PostgreSQL 双后端）.

替代 SQLite 本地库（agent.db / cache.db 的权威表）：所有权威数据直接读写云端
Postgres，天然支持多进程/多机器并发与跨机一致。

后端选择（CLOUD_DB_BACKEND）
--------------------------
- 默认 / `postgrest`：PostgREST Data API（火山 Supabase 引擎，
  SUPABASE_URL + SUPABASE_SERVICE_KEY）。2026-09-17 前的唯一后端。
- `pgdirect`：pg8000 直连 PostgreSQL（火山 AIDAP PostgreSQL 引擎，
  PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD 或 PGDATABASE_URL 连接串）。
  用于迁移到无 Supabase 组件算力的 PostgreSQL 引擎（成本优化）。

约定
----
- 未配置时所有操作返回"空结果"并打印 WARNING（fail-safe 降级，便于本地无云测试）。
- 行字段与 SQLite 版保持同 shape（dict / list[dict]），JSON 字段自动解析。
- 时间戳沿用 TEXT 'YYYY-MM-DD HH:MM:SS'（与 SQLite 版一致，迁移零转换）。
- 对外 API 签名双后端一致：select/select_one/insert/insert_many/update/
  delete/upsert/upsert_many/q，上层（agent/db.py、dashboard/db.py 等）零改动。
"""

import json
import os
import threading
from urllib.parse import quote, urlencode

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
_ENABLED = bool(_URL and _KEY and requests is not None)

# ── 后端选择（2026-09-17 成本优化：迁移到 AIDAP PostgreSQL 引擎）────────
# CLOUD_DB_BACKEND ∈ {postgrest(默认), pgdirect}
_BACKEND = os.environ.get("CLOUD_DB_BACKEND", "postgrest").strip().lower()

# pgdirect 连接参数（pg8000 直连）
_PG_HOST = os.environ.get("PGHOST", "").strip()
_PG_PORT = int(os.environ.get("PGPORT", "5432") or 5432)
_PG_DATABASE = os.environ.get("PGDATABASE", "").strip()
_PG_USER = os.environ.get("PGUSER", "").strip()
_PG_PASSWORD = os.environ.get("PGPASSWORD", "").strip()
_PG_URL = os.environ.get("PGDATABASE_URL", "").strip()  # 完整连接串（可选，优先）

# pgdirect 可用：后端选中 + 连接信息齐备 + pg8000 可导入（懒加载）
_PG_ENABLED = False
if _BACKEND == "pgdirect":
    try:
        import pg8000  # noqa: F401  (懒加载校验，实际连接时再用)
        if _PG_URL or (_PG_HOST and _PG_USER):
            _PG_ENABLED = True
        else:
            print("[cloud_db] WARNING: CLOUD_DB_BACKEND=pgdirect 但缺少 PG 连接信息"
                  "（PGDATABASE_URL 或 PGHOST/PGUSER），pgdirect 后端不可用")
    except ImportError:
        print("[cloud_db] WARNING: pg8000 未安装（pip install pg8000），"
              "pgdirect 后端不可用")

# 与 SQLite 版一致的 JSON 文本字段（行级自动解析）
# 2026-09-17 扩展为云库全部 JSONB 列（双后端一致双向处理）：
#   agent_messages.sources / agent_articles.topics+sources /
#   agent_notices.todo_data / tickets.log_entries /
#   strategy_kb.backtest_params / strategy_metrics.assets_json /
#   signal_tracking.status_history
_JSON_FIELDS = ("sources", "topics", "todo_data", "log_entries",
                "backtest_params", "assets_json", "status_history")

_lock = threading.RLock()
_warned = set()

# ── HTTP 连接池（2026-09-08 性能优化）───────────────────────────
# 根因：原 `requests.request(...)` 每次调用都新建 TCP 连接 + TLS 握手，
# 公网 HTTPS 到火山 Supabase 单次冷连接实测 ~0.8s（首连甚至 15s），
# 每个页面 4~11 次串行请求 → 页载数秒。改用 per-thread requests.Session
# （keep-alive 连接复用）后，复用请求实测 ~0.09s（~9x 提速）。
# requests.Session 非线程安全 → 用 threading.local 每线程一个池，天然并发安全。
_tls = threading.local()


def _session() -> "requests.Session":
    s = getattr(_tls, "session", None)
    if s is None:
        s = requests.Session()
        # 调大连接池与重试（网络抖动容忍），保持 keep-alive 复用
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=8, pool_maxsize=16, max_retries=1,
        )
        s.mount("https://", adapter)
        s.mount("http://", adapter)
        _tls.session = s
    return s


def _warn_once(tag: str, msg: str) -> None:
    with _lock:
        if tag not in _warned:
            _warned.add(tag)
            print(f"[cloud_db] WARNING: {msg}")


def enabled() -> bool:
    return _ENABLED


def _req(method: str, path: str, *, params: dict | None = None,
         json_body=None, timeout: int = 30, prefer: str | None = None):
    """PostgREST 请求。返回 (status, payload) 或抛异常。"""
    if not _ENABLED:
        _warn_once("disabled", "SUPABASE_URL/SUPABASE_SERVICE_KEY 未配置，云 DB 不可用（fail-safe 空结果）")
        raise CloudDBDisabled()

    url = _URL + path
    headers = {
        "apikey": _KEY,
        "Authorization": f"Bearer {_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    if params:
        # PostgREST 过滤/排序/分页参数
        qs = urlencode({k: v for k, v in params.items() if v is not None})
        if qs:
            url += "?" + qs

    try:
        # 走 per-thread 连接池（keep-alive），避免每次新建 TCP+TLS 连接
        resp = _session().request(
            method, url, headers=headers, json=json_body,
            params=None, timeout=timeout,
        )
    except requests.RequestException as e:
        raise CloudDBError(f"network: {e}") from e

    if resp.status_code >= 400:
        detail = resp.text[:400]
        raise CloudDBError(f"HTTP {resp.status_code}: {detail}")

    if resp.status_code in (204,):
        return None
    if not resp.content:
        return None
    try:
        return resp.json()
    except Exception:
        return None


class CloudDBError(Exception):
    """云 DB 请求失败。"""


class CloudDBDisabled(Exception):
    """云 DB 未配置（fail-safe 空结果路径）。"""


def _rows(payload) -> list:
    if payload is None:
        return []
    if isinstance(payload, list):
        return payload
    return [payload]


def _row_dict(r: dict) -> dict:
    """把行转成与 SQLite 版一致的 dict（JSON 字段自动解析）。"""
    d = dict(r)
    for f in _JSON_FIELDS:
        if f in d and isinstance(d[f], str):
            try:
                d[f] = json.loads(d[f])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


# ═══════════════════════════════════════════
# pgdirect 后端（pg8000 直连 PostgreSQL，2026-09-17）
# ═══════════════════════════════════════════
# 用于 AIDAP PostgreSQL 引擎（无 Supabase 组件算力 + 算力空闲自动挂起）。
# 与 PostgREST 后端保持同一对外 API 签名与语义；filters/order 参数格式不变。

_OP_MAP = {"eq": "=", "neq": "<>", "gt": ">", "lt": "<", "gte": ">=", "lte": "<="}


def _pg_connect():
    """创建 pg8000 连接。优先 PGDATABASE_URL 连接串，否则用 PG* 组件参数。

    AIDAP PostgreSQL 引擎要求 SSL（sslmode=require）+ channel_binding=require。
    pg8000 1.30+ 支持 ssl_context 参数（ssl.create_default_context() 即可，
    服务端证书由火山 CA 签发，系统信任链可验证）。
    """
    import pg8000  # 懒加载（已在模块级校验存在）

    ssl_ctx = None
    if os.environ.get("PGSSLMODE", "require").strip().lower() not in ("disable",):
        import ssl
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = True
        ssl_ctx.verify_mode = ssl.CERT_REQUIRED

    if _PG_URL:
        from urllib.parse import unquote, urlparse

        u = urlparse(_PG_URL)
        return pg8000.connect(
            host=u.hostname or "localhost",
            port=u.port or 5432,
            database=(u.path or "/").lstrip("/") or None,
            user=unquote(u.username or "") if u.username else None,
            password=unquote(u.password or "") if u.password else None,
            ssl_context=ssl_ctx,
        )
    return pg8000.connect(
        host=_PG_HOST, port=_PG_PORT, database=_PG_DATABASE or None,
        user=_PG_USER, password=_PG_PASSWORD,
        ssl_context=ssl_ctx,
    )


def _pg_where(filters) -> tuple[str, list]:
    """filters [(col, op, val)] → (SQL WHERE 子句, 参数列表)。

    op ∈ {eq, neq, gt, lt, gte, lte, is, in, like, ilike}。
    - in 的 val 形如 "(a,b,c)"（PostgREST 风格）。
    - like/ilike 兼容 PostgREST 通配符：val 中的 '*' 视为任意串（转 SQL '%'）；
      直接传 SQL '%' 也原样保留（dashboard/db.py 的 prefix+"%" 用法）。
    """
    clauses, params = [], []
    for col, op, val in (filters or []):
        if op == "is":
            if val is None:
                clauses.append(f"{col} IS NULL")
            else:
                clauses.append(f"{col} = %s")
                params.append(val)
        elif op in ("like", "ilike"):
            # PostgREST 通配 '*' → SQL '%'；SQL 通配 '%' 保留（两种用法兼容）
            pattern = str(val).replace("*", "%")
            clauses.append(f"{col} {'LIKE' if op == 'like' else 'ILIKE'} %s")
            params.append(pattern)
        elif op == "in":
            inner = str(val).strip().lstrip("(").rstrip(")")
            items = [i for i in inner.split(",") if i != ""]
            ph = ", ".join(["%s"] * len(items))
            clauses.append(f"{col} IN ({ph})")
            params.extend(items)
        else:
            clauses.append(f"{col} {_OP_MAP[op]} %s")
            params.append(val)
    return " AND ".join(clauses), params


def _pg_order(order) -> str:
    """PostgREST 风格 order "id.desc,name" → " ORDER BY id DESC, name"。"""
    if not order:
        return ""
    parts = []
    for token in order.split(","):
        token = token.strip()
        if not token:
            continue
        if "." in token:
            col, direction = token.split(".", 1)
            parts.append(f"{col} {direction.upper()}")
        else:
            parts.append(token)
    return " ORDER BY " + ", ".join(parts)


def _pg_rows(cursor) -> list:
    """cursor.fetchall() → 规范化 list[dict]（兼容 dict / tuple 两种行形态 + JSON 解析）。"""
    try:
        raw = cursor.fetchall() or []
    except Exception:
        return []
    if not raw:
        return []
    first = raw[0]
    if isinstance(first, dict):
        return [_row_dict(r) for r in raw]
    cols = [d[0] for d in (cursor.description or [])]
    return [_row_dict(dict(zip(cols, r))) for r in raw]


def _pg_serialize(row: dict) -> dict:
    """JSON 字段序列化（list/dict → JSON 字符串），供 INSERT/UPDATE 使用。"""
    body = dict(row)
    for f in _JSON_FIELDS:
        if f in body and isinstance(body[f], (list, dict)):
            body[f] = json.dumps(body[f], ensure_ascii=False)
    return body


def _pg_run(sql: str, params=None, *, fetch=True):
    """执行 SQL 并提交；返回查询行（fetch=True）或 None。异常时回滚并抛。"""
    conn = _pg_connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = _pg_rows(cur) if fetch else None
        conn.commit()
        return rows
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _pg_select(table, *, columns="*", filters=None, order=None,
               limit=None, offset=None) -> list:
    where, params = _pg_where(filters)
    sql = f"SELECT {columns} FROM {table}"
    if where:
        sql += f" WHERE {where}"
    sql += _pg_order(order)
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    if offset is not None:
        sql += f" OFFSET {int(offset)}"
    try:
        return _pg_run(sql, params) or []
    except Exception as e:
        raise CloudDBError(f"pg select {table}: {e}") from e


def _pg_insert(table, row: dict):
    body = {k: v for k, v in row.items() if v is not None}
    body = _pg_serialize(body)
    if not body:
        return None
    cols = ", ".join(body.keys())
    ph = ", ".join(["%s"] * len(body))
    sql = f"INSERT INTO {table} ({cols}) VALUES ({ph}) RETURNING *"
    rows = _pg_run(sql, list(body.values()))
    return rows[0] if rows else None


def _pg_insert_many(table, rows: list[dict], *, chunk: int = 200) -> int:
    total = 0
    for i in range(0, len(rows), chunk):
        chunk_rows = [_pg_serialize(r) for r in rows[i:i + chunk]]
        if not chunk_rows:
            continue
        all_cols = list(chunk_rows[0].keys())
        if not all_cols:
            continue
        cols_sql = ", ".join(all_cols)
        rows_sql = ", ".join(
            "(" + ", ".join(["%s"] * len(all_cols)) + ")" for _ in chunk_rows
        )
        values = [r.get(c) for r in chunk_rows for c in all_cols]
        sql = (f"INSERT INTO {table} ({cols_sql}) VALUES {rows_sql} RETURNING *")
        try:
            got = _pg_run(sql, values) or []
            total += len(got)
        except Exception as e:
            raise CloudDBError(f"pg insert_many {table}: {e}") from e
    return total


def _pg_update(table, row: dict, *, filters=None) -> list:
    body = _pg_serialize(row)
    if not body:
        return []
    set_sql = ", ".join(f"{c} = %s" for c in body.keys())
    where, where_params = _pg_where(filters)
    sql = f"UPDATE {table} SET {set_sql}"
    params = list(body.values())
    if where:
        sql += f" WHERE {where}"
        params.extend(where_params)
    sql += " RETURNING *"
    try:
        return _pg_run(sql, params) or []
    except Exception as e:
        raise CloudDBError(f"pg update {table}: {e}") from e


def _pg_delete(table, *, filters=None) -> int:
    where, params = _pg_where(filters)
    sql = f"DELETE FROM {table}"
    if where:
        sql += f" WHERE {where}"
    sql += " RETURNING *"
    try:
        return len(_pg_run(sql, params) or [])
    except Exception as e:
        raise CloudDBError(f"pg delete {table}: {e}") from e


def _pg_upsert(table, row: dict, *, on_conflict: str | None = None):
    body = {k: v for k, v in row.items() if v is not None}
    body = _pg_serialize(body)
    if not body:
        return None
    cols = ", ".join(body.keys())
    ph = ", ".join(["%s"] * len(body))
    sql = f"INSERT INTO {table} ({cols}) VALUES ({ph})"
    if on_conflict:
        conflict_col = on_conflict.strip().lstrip("(").rstrip(")")
        update_cols = [c for c in body.keys() if c not in {cc.strip() for cc in conflict_col.split(",")}]
        if update_cols:
            upd = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
            sql += f" ON CONFLICT ({conflict_col}) DO UPDATE SET {upd}"
        else:
            sql += f" ON CONFLICT ({conflict_col}) DO NOTHING"
    sql += " RETURNING *"
    rows = _pg_run(sql, list(body.values()))
    return rows[0] if rows else None


def _pg_upsert_many(table, rows: list[dict], *, on_conflict: str,
                    chunk: int = 200) -> int:
    total = 0
    conflict_col = on_conflict.strip().lstrip("(").rstrip(")")
    for i in range(0, len(rows), chunk):
        chunk_rows = [_pg_serialize(r) for r in rows[i:i + chunk]]
        if not chunk_rows:
            continue
        all_cols = list(chunk_rows[0].keys())
        if not all_cols:
            continue
        cols_sql = ", ".join(all_cols)
        rows_sql = ", ".join(
            "(" + ", ".join(["%s"] * len(all_cols)) + ")" for _ in chunk_rows
        )
        values = [r.get(c) for r in chunk_rows for c in all_cols]
        conflict_keys = {cc.strip() for cc in conflict_col.split(",")}
        update_cols = [c for c in all_cols if c not in conflict_keys]
        sql = f"INSERT INTO {table} ({cols_sql}) VALUES {rows_sql}"
        if update_cols:
            upd = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
            sql += f" ON CONFLICT ({conflict_col}) DO UPDATE SET {upd}"
        else:
            sql += f" ON CONFLICT ({conflict_col}) DO NOTHING"
        sql += " RETURNING *"
        try:
            got = _pg_run(sql, values) or []
            total += len(got)
        except Exception as e:
            raise CloudDBError(f"pg upsert_many {table}: {e}") from e
    return total


# ═══════════════════════════════════════════
# 通用 CRUD helpers（PostgREST 语义）
# ═══════════════════════════════════════════

def select(table: str, *, columns="*", filters=None, order=None,
           limit=None, offset=None) -> list:
    """SELECT：filters 形如 [(col, op, val)]，op ∈ {eq, neq, gt, lt, gte, lte, is, in}。"""
    if _BACKEND == "pgdirect":
        if not _PG_ENABLED:
            return []
        return _pg_select(table, columns=columns, filters=filters,
                          order=order, limit=limit, offset=offset)
    if not _ENABLED:
        return []
    params = {"select": columns}
    if order:
        params["order"] = order
    if limit is not None:
        params["limit"] = str(limit)
    if offset is not None:
        params["offset"] = str(offset)
    for col, op, val in (filters or []):
        # BUG-FIX(2026-09-07)：bool 值必须小写 true/false —— PostgREST 布尔字面量只认
        # eq.true / is.false，Python str(True)='True' 会被当字符串比较导致过滤异常/空结果。
        if isinstance(val, bool):
            val = "true" if val else "false"
        params[col] = f"{op}.{val if val is not None else 'null'}"
    try:
        payload = _req("GET", f"/rest/v1/{table}", params=params)
    except CloudDBDisabled:
        return []
    return [_row_dict(r) for r in _rows(payload)]


def select_one(table: str, *, columns="*", filters=None, order=None) -> dict | None:
    rows = select(table, columns=columns, filters=filters, order=order, limit=1)
    return rows[0] if rows else None


def insert(table: str, row: dict) -> dict | None:
    """INSERT 并返回插入行（含 id）。"""
    if _BACKEND == "pgdirect":
        if not _PG_ENABLED:
            return None
        return _pg_insert(table, row)
    if not _ENABLED:
        return None
    body = {k: v for k, v in row.items() if v is not None}
    # JSON 字段序列化
    for f in _JSON_FIELDS:
        if f in body and isinstance(body[f], (list, dict)):
            body[f] = json.dumps(body[f], ensure_ascii=False)
    try:
        payload = _req("POST", f"/rest/v1/{table}", params={"select": "*"},
                       json_body=[body], prefer="return=representation")
    except CloudDBDisabled:
        return None
    rows = _rows(payload)
    return _row_dict(rows[0]) if rows else None


def insert_many(table: str, rows: list[dict], *, chunk: int = 200) -> int:
    """批量 INSERT（单请求数组），返回成功插入行数。分块避免请求体过大。

    注意：数组内所有行键必须一致（PostgREST 要求），故不过滤 None 字段。
    """
    if _BACKEND == "pgdirect":
        if not _PG_ENABLED:
            return 0
        return _pg_insert_many(table, rows, chunk=chunk)
    if not _ENABLED:
        return 0
    total = 0
    for i in range(0, len(rows), chunk):
        chunk_rows = rows[i:i + chunk]
        body = []
        for r in chunk_rows:
            b = dict(r)
            for f in _JSON_FIELDS:
                if f in b and isinstance(b[f], (list, dict)):
                    b[f] = json.dumps(b[f], ensure_ascii=False)
            body.append(b)
        try:
            payload = _req("POST", f"/rest/v1/{table}", params={"select": "*"},
                           json_body=body, prefer="return=representation")
        except CloudDBDisabled:
            return total
        total += len(_rows(payload))
    return total


def update(table: str, row: dict, *, filters=None, columns="*") -> list:
    """UPDATE：filters 形如 [(col, op, val)]。返回受影响行。

    注意：row 中值为 None 的字段也会提交（PostgREST 把 null 解释为 SQL NULL，
    用于显式清空某列，如 read_at）；调用方如不想动某列就不要放进 row。
    """
    if _BACKEND == "pgdirect":
        if not _PG_ENABLED:
            return []
        return _pg_update(table, row, filters=filters)
    if not _ENABLED:
        return []
    body = {k: v for k, v in row.items()}
    for f in _JSON_FIELDS:
        if f in body and isinstance(body[f], (list, dict)):
            body[f] = json.dumps(body[f], ensure_ascii=False)
    params = {"select": columns}
    for col, op, val in (filters or []):
        # BUG-FIX(2026-09-07)：bool 值必须小写 true/false —— PostgREST 布尔字面量只认
        # eq.true / is.false，Python str(True)='True' 会被当字符串比较导致过滤异常/空结果。
        if isinstance(val, bool):
            val = "true" if val else "false"
        params[col] = f"{op}.{val if val is not None else 'null'}"
    try:
        payload = _req("PATCH", f"/rest/v1/{table}", params=params,
                       json_body=body, prefer="return=representation")
    except CloudDBDisabled:
        return []
    return [_row_dict(r) for r in _rows(payload)]


def delete(table: str, *, filters=None) -> int:
    """DELETE：filters 必填。返回受影响行数。"""
    if _BACKEND == "pgdirect":
        if not _PG_ENABLED:
            return 0
        return _pg_delete(table, filters=filters)
    if not _ENABLED:
        return 0
    params = {}
    for col, op, val in (filters or []):
        # BUG-FIX(2026-09-07)：bool 值必须小写 true/false —— PostgREST 布尔字面量只认
        # eq.true / is.false，Python str(True)='True' 会被当字符串比较导致过滤异常/空结果。
        if isinstance(val, bool):
            val = "true" if val else "false"
        params[col] = f"{op}.{val if val is not None else 'null'}"
    try:
        payload = _req("DELETE", f"/rest/v1/{table}", params=params,
                       prefer="return=representation")
        return len(_rows(payload))
    except CloudDBDisabled:
        return 0


def upsert(table: str, row: dict, *, on_conflict: str | None = None) -> dict | None:
    """UPSERT（INSERT ... ON CONFLICT）——PostgREST POST + Prefer: resolution=merge-duplicates。"""
    if _BACKEND == "pgdirect":
        if not _PG_ENABLED:
            return None
        return _pg_upsert(table, row, on_conflict=on_conflict)
    if not _ENABLED:
        return None
    body = {k: v for k, v in row.items() if v is not None}
    for f in _JSON_FIELDS:
        if f in body and isinstance(body[f], (list, dict)):
            body[f] = json.dumps(body[f], ensure_ascii=False)
    params = {"select": "*"}
    prefer = "return=representation"
    if on_conflict:
        params["on_conflict"] = on_conflict
        prefer = "resolution=merge-duplicates,return=representation"
    try:
        payload = _req(
            "POST", f"/rest/v1/{table}", params=params, json_body=[body],
            prefer=prefer,
        )
    except CloudDBDisabled:
        return None
    rows = _rows(payload)
    return _row_dict(rows[0]) if rows else None


def upsert_many(table: str, rows: list[dict], *, on_conflict: str,
                chunk: int = 200) -> int:
    """批量 UPSERT（按 on_conflict 键合并），返回成功行数。"""
    if _BACKEND == "pgdirect":
        if not _PG_ENABLED:
            return 0
        return _pg_upsert_many(table, rows, on_conflict=on_conflict, chunk=chunk)
    if not _ENABLED:
        return 0
    total = 0
    # 冲突键列名即所选主键；select 用 * 兼容无 id 列的表（如 portfolio_meta/key）
    params = {"select": "*"}
    if on_conflict:
        params["on_conflict"] = on_conflict
    prefer = "resolution=merge-duplicates,return=representation"
    for i in range(0, len(rows), chunk):
        chunk_rows = rows[i:i + chunk]
        body = []
        for r in chunk_rows:
            b = dict(r)
            for f in _JSON_FIELDS:
                if f in b and isinstance(b[f], (list, dict)):
                    b[f] = json.dumps(b[f], ensure_ascii=False)
            body.append(b)
        try:
            payload = _req("POST", f"/rest/v1/{table}", params=params,
                           json_body=body, prefer=prefer)
        except CloudDBDisabled:
            return total
        total += len(_rows(payload))
    return total


# ═══════════════════════════════════════════
# 兼容辅助：PostgREST 过滤参数编码
# ═══════════════════════════════════════════

def q(col: str, op: str, val) -> str:
    """生成 'col=op.value' 片段（select 使用）。"""
    return f"{col}={op}.{val if val is not None else 'null'}"
