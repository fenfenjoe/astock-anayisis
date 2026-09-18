"""cloud_db.py — PostgreSQL 直连后端（pgdirect / pg8000）测试。

- 单元测试：mock `cloud_db._pg_connect`（不连真实库），断言生成的 SQL 与参数。
- 设计：`CLOUD_DB_BACKEND=pgdirect` 时 cloud_db 走 pg8000 直连；
  默认（未设置）仍走 PostgREST（现有 test_cloud_db.py 覆盖）。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import cloud_db


# ── FakeConnection：模拟 pg8000 连接（cursor/execute/fetchall/commit/close）──

class FakeCursor:
    def __init__(self, result=None, rowcount=0):
        self._result = result
        self.rowcount = rowcount
        self.executed = None
        self.params = None

    def execute(self, sql, params=None):
        self.executed = sql
        self.params = params
        return self

    def fetchall(self):
        return self._result if self._result is not None else []

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConnection:
    def __init__(self, result=None, rowcount=0):
        self.cursor_ = FakeCursor(result, rowcount)
        self.committed = 0
        self.closed = False
        self.rolledback = 0

    def cursor(self):
        return self.cursor_

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolledback += 1

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _pg_backend(monkeypatch):
    """强制走 pgdirect 后端，并 mock 掉 _pg_connect（每次返回同一 FakeConnection）。"""
    monkeypatch.setattr(cloud_db, "_BACKEND", "pgdirect")
    monkeypatch.setattr(cloud_db, "_PG_ENABLED", True)
    _conn_holder = {"conn": FakeConnection(result=[], rowcount=0),
                    "orig_connect": cloud_db._pg_connect}
    monkeypatch.setattr(cloud_db, "_pg_connect", lambda: _conn_holder["conn"])
    return _conn_holder


def _rows_result(rows):
    """让 _pg_connect 返回带给定行的 fake 连接。"""
    conn = FakeConnection(result=rows, rowcount=len(rows))
    return lambda: conn


# ═══════════════════════════════════════════
# 过滤条件 → SQL WHERE 映射
# ═══════════════════════════════════════════

def test_where_maps_all_ops():
    from cloud_db import _pg_where
    sql, params = _pg_where([
        ("id", "eq", 7),
        ("kind", "neq", "x"),
        ("n", "gt", 1),
        ("m", "lt", 2),
        ("a", "gte", 3),
        ("b", "lte", 4),
        ("ended_at", "is", None),
        ("flag", "is", True),
        ("key", "in", "(a,b)"),
    ])
    assert sql == ("id = %s AND kind <> %s AND n > %s AND m < %s AND a >= %s "
                   "AND b <= %s AND ended_at IS NULL AND flag = %s AND key IN (%s, %s)")
    assert params == [7, "x", 1, 2, 3, 4, True, "a", "b"]


def test_where_in_parses_parens():
    from cloud_db import _pg_where
    sql, params = _pg_where([("key", "in", "(k1,k2,k3)")])
    assert sql == "key IN (%s, %s, %s)"
    assert params == ["k1", "k2", "k3"]


def test_where_like_sql_percent():
    """like 直接传 SQL % 通配（dashboard/db.py 的 prefix+"%" 用法）。"""
    from cloud_db import _pg_where
    sql, params = _pg_where([("key", "like", "east%")])
    assert sql == "key LIKE %s"
    assert params == ["east%"]


def test_where_like_postgrest_star_to_percent():
    """like 传 PostgREST * 通配（api_daily.py 的 *ticker* 用法）→ 转 SQL %。"""
    from cloud_db import _pg_where
    sql, params = _pg_where([("ticker", "like", "*510*")])
    assert sql == "ticker LIKE %s"
    assert params == ["%510%"]


def test_where_like_postgrest_suffix():
    from cloud_db import _pg_where
    sql, params = _pg_where([("signal_id", "like", "SIG-2026091*")])
    assert sql == "signal_id LIKE %s"
    assert params == ["SIG-2026091%"]


def test_select_with_like_filter():
    """端到端：select 用 like 过滤生成正确 SQL（模拟 api_daily 信号搜索）。"""
    rows = cloud_db.select("signal_tracking",
                           filters=[("ticker", "like", "*510300*")],
                           limit=10)
    sql = cloud_db._pg_connect().cursor_.executed
    assert "ticker LIKE %s" in sql
    assert cloud_db._pg_connect().cursor_.params == ["%510300%"]


# ═══════════════════════════════════════════
# JSONB 字段覆盖（全 7 个：sources/topics/todo_data/log_entries/
#   backtest_params/assets_json/status_history）
# ═══════════════════════════════════════════

def test_json_fields_cover_all_jsonb_columns():
    """云库全部 JSONB 字段都在 _JSON_FIELDS 内（双向序列化/解析覆盖）。"""
    expected = {"sources", "topics", "todo_data", "log_entries",
                "backtest_params", "assets_json", "status_history"}
    assert expected <= set(cloud_db._JSON_FIELDS)


def test_pg_serialize_dumps_new_jsonb_fields():
    """_pg_serialize 对新增 JSONB 字段（dict/list）转 JSON 字符串。"""
    body = cloud_db._pg_serialize({
        "strategy_id": "S1",
        "backtest_params": {"initial_capital": 100000, "commission": 0.0003},
        "assets_json": ["510300(沪深300ETF)"],
        "status_history": [{"from": "open", "to": "triggered"}],
        "log_entries": ["created"],
    })
    assert isinstance(body["backtest_params"], str)
    assert '"initial_capital": 100000' in body["backtest_params"]
    assert isinstance(body["assets_json"], str)
    assert isinstance(body["status_history"], str)
    assert isinstance(body["log_entries"], str)


def test_pg_serialize_keeps_str_unchanged():
    """上层已 dumps 的 str 保持原样（不二次处理）。"""
    body = cloud_db._pg_serialize({"backtest_params": '{"a": 1}'})
    assert body["backtest_params"] == '{"a": 1}'


def test_row_dict_parses_new_jsonb_fields():
    """_row_dict 解析新增 JSONB 字段的 str 形态为对象（pg8000 JSONB 可能返回 str/dict）。"""
    d = cloud_db._row_dict({
        "strategy_id": "S1",
        "backtest_params": '{"initial_capital": 100000}',
        "assets_json": '["510300(沪深300ETF)"]',
        "status_history": '[{"from": "open"}]',
        "log_entries": '["created"]',
    })
    assert d["backtest_params"] == {"initial_capital": 100000}
    assert d["assets_json"] == ["510300(沪深300ETF)"]
    assert d["status_history"] == [{"from": "open"}]
    assert d["log_entries"] == ["created"]


def test_row_dict_keeps_dict_unchanged():
    """pg8000 原生返回 dict 形态时保持原样。"""
    d = cloud_db._row_dict({"backtest_params": {"a": 1}})
    assert d["backtest_params"] == {"a": 1}


def test_where_empty():
    from cloud_db import _pg_where
    sql, params = _pg_where([])
    assert sql == ""
    assert params == []


# ═══════════════════════════════════════════
# select / select_one
# ═══════════════════════════════════════════

def test_select_builds_sql(monkeypatch):
    monkeypatch.setattr(cloud_db, "_pg_connect",
                        _rows_result([{"id": 1, "title": "a"}]))
    rows = cloud_db.select("agent_sessions", filters=[("id", "eq", 7)],
                           order="id.desc", limit=5, offset=10)
    assert rows == [{"id": 1, "title": "a"}]
    conn = cloud_db._pg_connect()
    sql = conn.cursor_.executed
    assert "FROM agent_sessions" in sql
    assert "WHERE id = %s" in sql
    assert "ORDER BY id DESC" in sql
    assert "LIMIT 5 OFFSET 10" in sql


def test_select_no_filters_no_order():
    rows = cloud_db.select("agent_sessions")
    sql = cloud_db._pg_connect().cursor_.executed
    assert "WHERE" not in sql
    assert sql.strip().startswith("SELECT")


def test_select_one_returns_first(monkeypatch):
    monkeypatch.setattr(cloud_db, "_pg_connect",
                        _rows_result([{"id": 1, "sources": '[{"t":1}]'}]))
    r = cloud_db.select_one("agent_articles", filters=[("id", "eq", 1)])
    assert r["id"] == 1
    assert r["sources"] == [{"t": 1}]  # JSON 字段自动解析


def test_select_one_none_when_empty():
    assert cloud_db.select_one("agent_sessions") is None


# ═══════════════════════════════════════════
# insert / insert_many
# ═══════════════════════════════════════════

def test_insert_builds_sql(monkeypatch):
    monkeypatch.setattr(cloud_db, "_pg_connect",
                        _rows_result([{"id": 10, "title": "hi"}]))
    r = cloud_db.insert("agent_messages", {"role": "user", "content": "hi", "sources": []})
    assert r["id"] == 10
    conn = cloud_db._pg_connect()
    sql = conn.cursor_.executed
    assert sql.startswith("INSERT INTO agent_messages")
    assert "RETURNING *" in sql
    # 参数化：JSON 序列化后的值在 params 里（不在 SQL 字符串中）
    assert "sources" in sql
    assert '"[]"' in conn.cursor_.params or "[]" in str(conn.cursor_.params)


def test_insert_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(cloud_db, "_PG_ENABLED", False)
    assert cloud_db.insert("agent_sessions", {"title": "t"}) is None


def test_insert_many_chunks(monkeypatch):
    calls = []
    def fake_connect():
        conn = FakeConnection(result=[{"id": 1}], rowcount=1)
        calls.append(conn)
        return conn
    monkeypatch.setattr(cloud_db, "_pg_connect", fake_connect)
    rows = [{"a": i} for i in range(250)]
    n = cloud_db.insert_many("t", rows, chunk=200)
    assert n == 2  # 200 + 50 → 2 次插入，返回 2 行


# ═══════════════════════════════════════════
# update
# ═══════════════════════════════════════════

def test_update_builds_sql(monkeypatch):
    monkeypatch.setattr(cloud_db, "_pg_connect",
                        _rows_result([{"id": 5, "title": "renamed"}]))
    rows = cloud_db.update("agent_sessions", {"title": "renamed"},
                           filters=[("id", "eq", 5)])
    assert rows[0]["title"] == "renamed"
    conn = cloud_db._pg_connect()
    sql = conn.cursor_.executed
    assert sql.startswith("UPDATE agent_sessions")
    assert "SET title = %s" in sql
    assert "WHERE id = %s" in sql
    assert "RETURNING *" in sql


def test_update_keeps_none_to_set_null(monkeypatch):
    captured = {}
    def fake_connect():
        conn = FakeConnection(result=[{"id": 1, "read_at": None}], rowcount=1)
        captured["conn"] = conn
        return conn
    monkeypatch.setattr(cloud_db, "_pg_connect", fake_connect)
    cloud_db.update("agent_notices", {"status": "open", "read_at": None},
                    filters=[("id", "eq", 1)])
    sql = captured["conn"].cursor_.executed
    assert "read_at = %s" in sql
    assert None in captured["conn"].cursor_.params


# ═══════════════════════════════════════════
# delete
# ═══════════════════════════════════════════

def test_delete_builds_sql(monkeypatch):
    monkeypatch.setattr(cloud_db, "_pg_connect",
                        _rows_result([{"id": 1}, {"id": 2}]))
    n = cloud_db.delete("agent_sessions", filters=[("id", "eq", 1)])
    assert n == 2
    sql = cloud_db._pg_connect().cursor_.executed
    assert sql.startswith("DELETE FROM agent_sessions")
    assert "WHERE id = %s" in sql


# ═══════════════════════════════════════════
# upsert
# ═══════════════════════════════════════════

def test_upsert_uses_on_conflict(monkeypatch):
    monkeypatch.setattr(cloud_db, "_pg_connect",
                        _rows_result([{"key": "k", "value": "v"}]))
    r = cloud_db.upsert("agent_metadata", {"key": "k", "value": "v"},
                        on_conflict="key")
    assert r["value"] == "v"
    sql = cloud_db._pg_connect().cursor_.executed
    assert sql.startswith("INSERT INTO agent_metadata")
    assert "ON CONFLICT (key) DO UPDATE" in sql
    assert "RETURNING *" in sql


def test_upsert_many_builds_sql(monkeypatch):
    calls = []
    def fake_connect():
        conn = FakeConnection(result=[{"id": i + 1} for i in range(2)], rowcount=2)
        calls.append(conn)
        return conn
    monkeypatch.setattr(cloud_db, "_pg_connect", fake_connect)
    n = cloud_db.upsert_many("agent_metadata",
                             [{"key": "a", "value": "1"}, {"key": "b", "value": "2"}],
                             on_conflict="key")
    assert n == 2
    sql = calls[0].cursor_.executed
    assert "ON CONFLICT (key) DO UPDATE" in sql


# ═══════════════════════════════════════════
# 行处理（JSON 字段）
# ═══════════════════════════════════════════

def test_row_dict_parses_json_in_pg_mode():
    d = cloud_db._row_dict({"id": 1, "todo_data": '{"platform_id": "weibo"}'})
    assert d["todo_data"] == {"platform_id": "weibo"}


# ═══════════════════════════════════════════
# 连接（SSL）：AIDAP PostgreSQL 引擎要求 sslmode=require
# ═══════════════════════════════════════════

def test_pg_connect_passes_ssl_context(monkeypatch, _pg_backend):
    """_pg_connect 必须传 ssl_context（AIDAP 要求 SSL 连接）。"""
    import cloud_db

    captured = {}
    fake_pg = type("FakePg", (), {"connect": staticmethod(
        lambda **kw: captured.update(kw) or object())})

    monkeypatch.setattr(cloud_db, "_PG_URL", "")
    monkeypatch.setattr(cloud_db, "_PG_HOST", "cp-xxx.pg7.aidap-global.cn-beijing.volces.com")
    monkeypatch.setattr(cloud_db, "_PG_PORT", 5432)
    monkeypatch.setattr(cloud_db, "_PG_DATABASE", "aidb")
    monkeypatch.setattr(cloud_db, "_PG_USER", "user_admin")
    monkeypatch.setattr(cloud_db, "_PG_PASSWORD", "secret")
    monkeypatch.delenv("PGSSLMODE", raising=False)
    monkeypatch.setitem(__import__("sys").modules, "pg8000", fake_pg)
    # 用 fixture 保存的真实 _pg_connect（autouse fixture 已覆盖成 lambda）
    real_connect = _pg_backend["orig_connect"]

    real_connect()
    assert captured["ssl_context"] is not None, "必须传 ssl_context（SSL 连接）"
    assert captured["host"] == "cp-xxx.pg7.aidap-global.cn-beijing.volces.com"
    assert captured["database"] == "aidb"
    assert captured["user"] == "user_admin"


def test_pg_connect_url_uses_unquoted_password(monkeypatch, _pg_backend):
    """连接串里的 URL 编码密码必须 unquote（AIDAP 密码含特殊字符 > %3E）。"""
    import cloud_db

    captured = {}
    fake_pg = type("FakePg", (), {"connect": staticmethod(
        lambda **kw: captured.update(kw) or object())})

    monkeypatch.setattr(cloud_db, "_PG_URL",
                        "postgresql://user_admin:3RDLOQ%3E2L9jKW0.29O@cp-x.pg7.aidap-global."
                        "cn-beijing.volces.com/aidb?sslmode=require&channel_binding=require")
    monkeypatch.setattr(cloud_db, "_PG_HOST", "")
    monkeypatch.delenv("PGSSLMODE", raising=False)
    monkeypatch.setitem(__import__("sys").modules, "pg8000", fake_pg)
    real_connect = _pg_backend["orig_connect"]

    real_connect()
    assert captured["password"] == "3RDLOQ>2L9jKW0.29O", "密码必须 unquote 还原特殊字符"
    assert captured["database"] == "aidb"
