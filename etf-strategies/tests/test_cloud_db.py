"""cloud_db.py — 云端权威数据库（PostgREST Data API）测试。

- 单元测试：mock `cloud_db._req`，不连真实云（默认路径）。
- 集成测试：设置 SUPABASE_URL/SUPABASE_SERVICE_KEY 时对真实云库跑 CRUD 冒烟（否则 skip）。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import cloud_db


@pytest.fixture(autouse=True)
def _mock_cloud(monkeypatch, request):
    """默认把所有函数 mock 掉：`_ENABLED=True` 且 `_req` 返回空，避免误连真实云。
    集成测试类（TestRealCloudSmoke）不 mock，走真实云。"""
    if "realcloud" in getattr(request.node, "keywords", {}):
        return
    monkeypatch.setattr(cloud_db, "_ENABLED", True)
    monkeypatch.setattr(cloud_db, "_req", lambda *a, **k: [])


# ═══════════════════════════════════════════
# 基本 helpers
# ═══════════════════════════════════════════

def test_row_dict_parses_json_fields():
    d = cloud_db._row_dict({"id": 1, "sources": '[{"title":"t"}]', "topics": '["a"]'})
    assert d["sources"] == [{"title": "t"}]
    assert d["topics"] == ["a"]


def test_row_dict_leaves_bad_json_as_str():
    d = cloud_db._row_dict({"sources": "not-json"})
    assert d["sources"] == "not-json"


def test_rows_normalizes_single_dict():
    assert cloud_db._rows({"id": 1}) == [{"id": 1}]
    assert cloud_db._rows([{"id": 1}]) == [{"id": 1}]
    assert cloud_db._rows(None) == []


def test_q_encodes_op():
    assert cloud_db.q("id", "eq", 3) == "id=eq.3"


# ═══════════════════════════════════════════
# select / select_one
# ═══════════════════════════════════════════

def test_select_passes_filters(monkeypatch):
    calls = {}

    def fake_req(method, path, *, params=None, json_body=None, timeout=30, prefer=None):
        calls.update(method=method, path=path, params=params)
        return [{"id": 7, "title": "x"}]

    monkeypatch.setattr(cloud_db, "_req", fake_req)
    rows = cloud_db.select("agent_sessions", filters=[("id", "eq", 7)], limit=5)
    assert rows[0]["id"] == 7
    assert calls["method"] == "GET"
    assert calls["path"] == "/rest/v1/agent_sessions"
    assert calls["params"]["id"] == "eq.7"
    assert calls["params"]["limit"] == "5"


def test_select_disabled_returns_empty(monkeypatch):
    monkeypatch.setattr(cloud_db, "_ENABLED", False)
    assert cloud_db.select("agent_sessions") == []


def test_select_one_returns_first(monkeypatch):
    monkeypatch.setattr(cloud_db, "_req", lambda *a, **k: [{"id": 1}, {"id": 2}])
    r = cloud_db.select_one("agent_sessions", filters=[("id", "eq", 1)])
    assert r == {"id": 1}


def test_select_one_none_when_empty(monkeypatch):
    monkeypatch.setattr(cloud_db, "_req", lambda *a, **k: [])
    assert cloud_db.select_one("agent_sessions") is None


# ═══════════════════════════════════════════
# insert
# ═══════════════════════════════════════════

def test_insert_serializes_json_and_returns_row(monkeypatch):
    captured = {}

    def fake_req(method, path, *, params=None, json_body=None, timeout=30, prefer=None):
        captured["json_body"] = json_body
        captured["prefer"] = prefer
        return [{"id": 10, "sources": "[]"}]

    monkeypatch.setattr(cloud_db, "_req", fake_req)
    r = cloud_db.insert("agent_messages", {"role": "user", "content": "hi", "sources": []})
    assert r["id"] == 10
    assert captured["json_body"][0]["sources"] == "[]"
    assert captured["prefer"] == "return=representation"


def test_insert_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(cloud_db, "_ENABLED", False)
    assert cloud_db.insert("agent_sessions", {"title": "t"}) is None


# ═══════════════════════════════════════════
# update
# ═══════════════════════════════════════════

def test_update_sends_patch_with_filters(monkeypatch):
    captured = {}

    def fake_req(method, path, *, params=None, json_body=None, timeout=30, prefer=None):
        captured.update(method=method, params=params, body=json_body, prefer=prefer)
        return [{"id": 5, "title": "renamed"}]

    monkeypatch.setattr(cloud_db, "_req", fake_req)
    rows = cloud_db.update("agent_sessions", {"title": "renamed"}, filters=[("id", "eq", 5)])
    assert rows[0]["title"] == "renamed"
    assert captured["method"] == "PATCH"
    assert captured["params"]["id"] == "eq.5"
    assert captured["prefer"] == "return=representation"


# ═══════════════════════════════════════════
# upsert
# ═══════════════════════════════════════════

def test_upsert_uses_merge_duplicates_prefer(monkeypatch):
    captured = {}

    def fake_req(method, path, *, params=None, json_body=None, timeout=30, prefer=None):
        captured.update(params=params, prefer=prefer)
        return [{"key": "k", "value": "v"}]

    monkeypatch.setattr(cloud_db, "_req", fake_req)
    r = cloud_db.upsert("agent_metadata", {"key": "k", "value": "v"}, on_conflict="key")
    assert r["value"] == "v"
    assert captured["params"]["on_conflict"] == "key"
    assert captured["prefer"] == "resolution=merge-duplicates,return=representation"


# ═══════════════════════════════════════════
# delete
# ═══════════════════════════════════════════

def test_delete_returns_count(monkeypatch):
    monkeypatch.setattr(cloud_db, "_req", lambda *a, **k: [{"id": 1}, {"id": 2}])
    assert cloud_db.delete("agent_sessions", filters=[("id", "eq", 1)]) == 2


# ═══════════════════════════════════════════
# 真实云库集成冒烟（有 env 才跑）
# ═══════════════════════════════════════════

@pytest.mark.skipif(
    not (cloud_db._URL and cloud_db._KEY),
    reason="未配置 SUPABASE_URL / SUPABASE_SERVICE_KEY，跳过真实云集成测试",
)
@pytest.mark.realcloud
class TestRealCloudSmoke:
    """对真实云库做 CRUD 冒烟（自清理，不留脏数据）。"""

    def test_crud_roundtrip(self):
        sess = cloud_db.insert("agent_sessions", {"persona": "xiaoman", "title": "ci-smoke"})
        assert sess and sess.get("id")
        sid = sess["id"]
        try:
            msg = cloud_db.insert("agent_messages", {
                "session_id": sid, "role": "user", "content": "ci",
                "sources": [{"title": "t", "url": "u"}],
            })
            assert msg and msg["id"]

            rows = cloud_db.select("agent_sessions", filters=[("id", "eq", sid)])
            assert rows and rows[0]["id"] == sid

            upd = cloud_db.update("agent_sessions", {"title": "ci-renamed"},
                                  filters=[("id", "eq", sid)])
            assert upd and upd[0]["title"] == "ci-renamed"

            reloaded = cloud_db.select("agent_messages", filters=[("id", "eq", msg["id"])])
            assert isinstance(reloaded[0]["sources"], list)
        finally:
            cloud_db.delete("agent_messages", filters=[("session_id", "eq", sid)])
            cloud_db.delete("agent_sessions", filters=[("id", "eq", sid)])

    def test_upsert_metadata(self):
        cloud_db.upsert("agent_metadata", {"key": "ci_key", "value": "v1"}, on_conflict="key")
        cloud_db.upsert("agent_metadata", {"key": "ci_key", "value": "v2"}, on_conflict="key")
        try:
            rows = cloud_db.select("agent_metadata", filters=[("key", "eq", "ci_key")])
            assert rows and rows[0]["value"] == "v2"
        finally:
            cloud_db.delete("agent_metadata", filters=[("key", "eq", "ci_key")])
