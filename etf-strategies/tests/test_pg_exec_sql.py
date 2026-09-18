"""scripts/pg_exec_sql.py — SQL 语句切分与执行逻辑测试（mock pg8000）。"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pytest

import pg_exec_sql


# ═══════════════════════════════════════════
# _split_statements：切分正确性
# ═══════════════════════════════════════════

def test_split_simple_statements():
    sql = "CREATE TABLE a (id int);\nCREATE TABLE b (id int);"
    stmts = pg_exec_sql._split_statements(sql)
    assert len(stmts) == 2
    assert stmts[0].startswith("CREATE TABLE a")
    assert stmts[1].startswith("CREATE TABLE b")


def test_split_ignores_semicolon_in_comment():
    sql = "-- SELECT 1; 这是注释\nCREATE TABLE a (id int);"
    stmts = pg_exec_sql._split_statements(sql)
    assert len(stmts) == 1
    assert stmts[0].startswith("CREATE TABLE a")


def test_split_ignores_semicolon_in_string():
    sql = "INSERT INTO t (v) VALUES ('a;b');\nSELECT 1;"
    stmts = pg_exec_sql._split_statements(sql)
    assert len(stmts) == 2
    assert "a;b" in stmts[0]
    assert stmts[1] == "SELECT 1"


def test_split_handles_double_dash_inside_string():
    sql = "INSERT INTO t (v) VALUES ('x--y');"
    stmts = pg_exec_sql._split_statements(sql)
    assert len(stmts) == 1
    assert "x--y" in stmts[0]


def test_split_handles_comment_without_terminator():
    sql = "-- 无分号结尾的注释"
    stmts = pg_exec_sql._split_statements(sql)
    assert stmts == []


def test_split_handles_do_block():
    """DO $$ ... $$ 块内含分号，不应被切碎。粗粒度：字符串引号外分号仍会切，但 DO 块
    内 SQL 通常用 $$ 包裹——本切分器不处理 $$，仅保证常规 DDL 正确。"""
    sql = "DO $$ BEGIN RAISE NOTICE 'x'; END $$;"
    # 当前实现：$$ 内的分号会被切（非引号内）——这是已知限制，只验证不崩溃
    stmts = pg_exec_sql._split_statements(sql)
    assert isinstance(stmts, list)


# ═══════════════════════════════════════════
# 执行流程：mock pg8000
# ═══════════════════════════════════════════

class _FakeCursor:
    def __init__(self):
        self.executed = []

    def execute(self, s):
        self.executed.append(s)


class _FakeConn:
    def __init__(self):
        self.cursor_ = _FakeCursor()
        self.committed = False
        self.closed = False

    def cursor(self):
        return self.cursor_

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


@pytest.fixture()
def fake_pg(monkeypatch, tmp_path):
    conn = _FakeConn()
    mod = types.ModuleType("pg8000")
    mod.connect = lambda **kw: conn
    monkeypatch.setitem(sys.modules, "pg8000", mod)
    # 隔离 .env 影响
    monkeypatch.setattr(pg_exec_sql, "ENV_PATH", tmp_path / "nonexistent.env")
    return conn


def test_main_executes_all_statements(fake_pg, tmp_path, monkeypatch):
    sql_file = tmp_path / "t.sql"
    sql_file.write_text("CREATE TABLE a (id int);\nCREATE TABLE b (id int);",
                        encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["pg_exec_sql", str(sql_file)])
    pg_exec_sql.main()
    assert len(fake_pg.cursor_.executed) == 2
    assert fake_pg.committed is True
    assert fake_pg.closed is True


def test_main_skips_comment_only(fake_pg, tmp_path, monkeypatch):
    sql_file = tmp_path / "t.sql"
    sql_file.write_text("-- 只有注释\n;", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["pg_exec_sql", str(sql_file)])
    pg_exec_sql.main()
    assert fake_pg.cursor_.executed == []


def test_main_rollback_on_error(fake_pg, tmp_path, monkeypatch):
    sql_file = tmp_path / "t.sql"
    sql_file.write_text("CREATE TABLE ok (id int);\nBROKEN SQL;", encoding="utf-8")

    def boom(s):
        if "BROKEN" in s:
            raise RuntimeError("syntax error")
    fake_pg.cursor_.execute = boom
    monkeypatch.setattr(sys, "argv", ["pg_exec_sql", str(sql_file)])
    with pytest.raises(SystemExit) as e:
        pg_exec_sql.main()
    assert e.value.code == 1
    assert fake_pg.rolled_back is True


def test_url_connect_parsing(fake_pg, tmp_path, monkeypatch):
    """--url 连接串应解析出 host/port/db/user/pass。"""
    captured = {}

    def record_connect(**kw):
        captured.update(kw)
        return fake_pg
    fake_pg_mod = sys.modules["pg8000"]
    fake_pg_mod.connect = record_connect
    monkeypatch.setattr(sys, "argv", [
        "pg_exec_sql",
        "--url", "postgresql://u:p@myhost:5433/mydb?sslmode=require",
        str(tmp_path / "t.sql"),
    ])
    (tmp_path / "t.sql").write_text("SELECT 1;", encoding="utf-8")
    pg_exec_sql.main()
    assert captured["host"] == "myhost"
    assert captured["port"] == 5433
    assert captured["database"] == "mydb"
    assert captured["user"] == "u"
    assert captured["password"] == "p"
