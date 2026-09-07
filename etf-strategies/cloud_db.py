"""cloud_db.py — 云端权威数据库访问层（火山 Supabase 版 / PostgREST Data API）.

替代 SQLite 本地库（agent.db / cache.db 的权威表）：所有权威数据直接读写云端
Postgres（PostgREST over HTTPS），天然支持多进程/多机器并发与跨机一致。

约定
----
- 读 .env：SUPABASE_URL（公网 Data API 根，如 https://<branch>.supabase.aidap-...volces.com）
           SUPABASE_SERVICE_KEY（service_role key，后端专用，绕过 RLS）
- 未配置时所有操作返回"空结果"并打印 WARNING（fail-safe 降级，便于本地无云测试）。
- 行字段与 SQLite 版保持同 shape（dict / list[dict]），JSON 字段自动解析。
- 时间戳沿用 TEXT 'YYYY-MM-DD HH:MM:SS'（与 SQLite 版一致，迁移零转换）。
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

# 与 SQLite 版一致的 JSON 文本字段（行级自动解析）
_JSON_FIELDS = ("sources", "topics")

_lock = threading.RLock()
_warned = set()


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
        resp = requests.request(
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
    """把 PostgREST 行转成与 SQLite 版一致的 dict（JSON 字段自动解析）。"""
    d = dict(r)
    for f in _JSON_FIELDS:
        if f in d and isinstance(d[f], str):
            try:
                d[f] = json.loads(d[f])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


# ═══════════════════════════════════════════
# 通用 CRUD helpers（PostgREST 语义）
# ═══════════════════════════════════════════

def select(table: str, *, columns="*", filters=None, order=None,
           limit=None, offset=None) -> list:
    """SELECT：filters 形如 [(col, op, val)]，op ∈ {eq, neq, gt, lt, gte, lte, is}。"""
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
    """UPDATE：filters 形如 [(col, op, val)]。返回受影响行。"""
    if not _ENABLED:
        return []
    body = {k: v for k, v in row.items() if v is not None}
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
