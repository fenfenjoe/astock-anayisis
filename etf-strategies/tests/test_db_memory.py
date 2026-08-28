"""严格零本地：SQLite 内存模式（DB_MODE=memory）— serialize/deserialize 云快照往返。

mock cloud_store（_cs_* 模块级），不连真实 TOS。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from dashboard import db as db_mod
from agent import db as agent_db_mod


class FakeCloud:
    """内存对象存储 mock：put/get/list。"""

    def __init__(self):
        self.objects = {}

    def put_object(self, key, data):
        self.objects[key] = bytes(data)

    def get_object(self, key):
        return self.objects.get(key)

    def list_objects(self, prefix):
        return [k for k in self.objects if k.startswith(prefix)]


@pytest.fixture()
def fake_cloud(monkeypatch):
    fc = FakeCloud()
    # dashboard db
    monkeypatch.setattr(db_mod, "_cs_get", fc.get_object)
    monkeypatch.setattr(db_mod, "_cs_put", fc.put_object)
    monkeypatch.setattr(db_mod, "_cs_list", fc.list_objects)
    # agent db
    monkeypatch.setattr(agent_db_mod, "_cs_get", fc.get_object)
    monkeypatch.setattr(agent_db_mod, "_cs_put", fc.put_object)
    monkeypatch.setattr(agent_db_mod, "_cs_list", fc.list_objects)
    return fc


@pytest.fixture()
def dash_mem(monkeypatch):
    monkeypatch.setattr(db_mod, "USE_MEMORY", True)
    monkeypatch.setattr(db_mod, "_mem_conn", None)


@pytest.fixture()
def agent_mem(monkeypatch):
    monkeypatch.setattr(agent_db_mod, "USE_MEMORY", True)
    monkeypatch.setattr(agent_db_mod, "_mem_conn", None)


def test_dash_memory_init_and_backup_restore(fake_cloud, dash_mem):
    db_mod.init_db()
    # 空库建表成功
    with db_mod.get_conn() as conn:
        conn.execute("INSERT INTO metadata(key, value) VALUES ('t', '1')")
    assert db_mod.cloud_backup() is True
    keys = fake_cloud.list_objects("sqlite/")
    assert any(k.endswith("/cache.db") for k in keys)

    # 模拟重启：新连接 + cloud_restore 载入
    monkeypatch_clear = None
    db_mod._mem_conn = None
    assert db_mod.cloud_restore() is True
    with db_mod.get_conn() as conn:
        row = conn.execute("SELECT value FROM metadata WHERE key='t'").fetchone()
        assert row["value"] == "1"


def test_dash_memory_no_snapshot_creates_schema(fake_cloud, dash_mem):
    db_mod.init_db()
    with db_mod.get_conn() as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='strategy_metrics'").fetchone()
        assert row is not None


def test_agent_memory_init_and_restore(fake_cloud, agent_mem):
    agent_db_mod.init_db(None)
    with agent_db_mod.get_conn() as conn:
        conn.execute(
            "INSERT INTO agent_metadata(key, value) VALUES ('k', 'v')")
    assert agent_db_mod.cloud_backup() is True
    keys = fake_cloud.list_objects("sqlite/")
    assert any(k.endswith("/agent.db") for k in keys)

    agent_db_mod._mem_conn = None
    assert agent_db_mod.cloud_restore() is True
    with agent_db_mod.get_conn() as conn:
        assert conn.execute(
            "SELECT value FROM agent_metadata WHERE key='k'").fetchone()["value"] == "v"


def test_file_mode_ignores_cloud(fake_cloud, tmp_path):
    # 默认 file 模式：cloud_restore/backup 返回 False，不影响文件库
    assert db_mod.cloud_restore() is False
    assert db_mod.cloud_backup() is False
    db_mod.init_db()
    assert db_mod.USE_MEMORY is False
