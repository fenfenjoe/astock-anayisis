"""agent/db.py — 云端后端（AGENT_DB_BACKEND=cloud）集成测试。

走真实 Supabase 云库（PostgREST Data API），自清理不留脏数据。
需环境变量：SUPABASE_URL / SUPABASE_SERVICE_KEY，否则 skip。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from agent import db as agent_db

pytestmark = [
    pytest.mark.realcloud,
    pytest.mark.skipif(
        not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY")),
        reason="未配置 SUPABASE_URL / SUPABASE_SERVICE_KEY，跳过云端 agent 集成测试",
    ),
]


@pytest.fixture()
def cloud(monkeypatch):
    """强制 agent.db 走云后端。"""
    monkeypatch.setattr(agent_db, "USE_CLOUD", True)
    # 确保 cloud_db 已启用（env 存在 → 已启用）
    assert agent_db._cd_enabled()
    yield
    # 清理：删除测试会话（消息级联）、source、metadata
    for s in agent_db.session_list():
        if s.get("title", "").startswith("cloudtest-"):
            agent_db.session_delete(s["id"])
    for s in agent_db.source_list(enabled_only=False):
        if s.get("name", "").startswith("cloudtest-"):
            agent_db.source_delete(s["id"])
    from cloud_db import select as _sel, delete as _del_
    for m in _sel("agent_metadata", filters=[("key", "like", "cloudtest-%")]):
        _del_("agent_metadata", filters=[("key", "eq", m["key"])])
    for k in _sel("agent_knowledge", filters=[("url", "like", "http://cloudtest.example/%")]):
        _del_("agent_knowledge", filters=[("id", "eq", k["id"])])
    for a in _sel("agent_articles", filters=[("title", "like", "cloudtest-%")]):
        _del_("agent_articles", filters=[("id", "eq", a["id"])])
    for o in _sel("agent_opinions", filters=[("opinion", "like", "cloudtest-%")]):
        _del_("agent_opinions", filters=[("id", "eq", o["id"])])


def _now():
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def test_cloud_session_and_messages_roundtrip(cloud):
    sid = agent_db.session_create("cloudtest-会话")
    assert sid is not None
    assert agent_db.session_get(sid)["title"] == "cloudtest-会话"

    agent_db.message_add(sid, "user", "你好")
    agent_db.message_add(sid, "assistant", "你好呀",
                         sources=[{"title": "来源", "url": "http://a/1"}])
    msgs = agent_db.messages_by_session(sid)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["sources"] == [{"title": "来源", "url": "http://a/1"}]

    # 会话列表含该会话
    titles = [s["title"] for s in agent_db.session_list()]
    assert "cloudtest-会话" in titles

    # 重命名
    agent_db.session_rename(sid, "cloudtest-改名")
    assert agent_db.session_get(sid)["title"] == "cloudtest-改名"

    # 删除 → 级联消息
    agent_db.session_delete(sid)
    assert agent_db.session_get(sid) is None
    assert agent_db.messages_by_session(sid) == []


def test_cloud_article_and_opinions(cloud):
    aid = agent_db.article_create(
        "cloudtest-标题", "摘要", "正文", topics=["宏观"],
        sources=[{"title": "s", "url": "http://s"}],
    )
    assert aid is not None
    a = agent_db.article_get(aid)
    assert a["title"] == "cloudtest-标题"
    assert a["topics"] == ["宏观"]
    assert a["kind"] == "article"
    arts = agent_db.article_list()
    assert any(x["id"] == aid for x in arts)

    agent_db.opinion_add("白酒", "cloudtest-观点", article_id=aid)
    ops = agent_db.opinions_by_topic("白酒")
    assert any(o["opinion"] == "cloudtest-观点" for o in ops)


def test_cloud_knowledge_dedup_and_consume(cloud):
    url = "http://cloudtest.example/a/1"
    ok1 = agent_db.knowledge_upsert("cls", "快讯", url, "摘要", None, _now())
    ok2 = agent_db.knowledge_upsert("cls", "快讯(重复)", url, "摘要2", None, _now())
    assert ok1 is True
    assert ok2 is False

    unread = agent_db.knowledge_unread(limit=10)
    assert any(k["url"] == url for k in unread)
    kid = [k for k in unread if k["url"] == url][0]["id"]

    agent_db.knowledge_set_memory(kid, viewpoint="看好", emotion="excited", memory="联想A")
    after = agent_db.knowledge_get(kid) if hasattr(agent_db, "knowledge_get") else None
    if after is None:
        rows = agent_db.knowledge_all(limit=200)
        after = [k for k in rows if k["id"] == kid][0]
    assert after["viewpoint"] == "看好"
    assert after["emotion"] == "excited"

    agent_db.knowledge_mark_consumed(kid)
    assert not any(k["id"] == kid for k in agent_db.knowledge_unconsumed())


def test_cloud_activities(cloud):
    sid = agent_db.activity_start("reading", "📖 阅读", _now(), source="auto")
    assert sid is not None
    open_act = agent_db.activity_open()
    assert open_act is not None and open_act["id"] == sid

    closed = agent_db.activity_close_open(_now())
    assert closed is not None and closed["id"] == sid
    # 关闭后：我们自己的活动不应再是 open（运行中的真实 agent 可能另开活动，故
    # 不断言全局无 open，只断言我们自己的活动已结束）
    acts = agent_db.activity_list(limit=50)
    mine = [a for a in acts if a["id"] == sid]
    assert mine and mine[0]["ended_at"] is not None, "我们创建的活动应已被关闭"
    assert not any(a["id"] == sid and a["ended_at"] is None for a in acts)  # 不应再是 open


def test_cloud_metadata_and_sources(cloud):
    agent_db.meta_set("cloudtest-key", "v1")
    assert agent_db.meta_get("cloudtest-key") == "v1"
    agent_db.meta_set("cloudtest-key", "v2")
    assert agent_db.meta_get("cloudtest-key") == "v2"

    s = agent_db.source_add("cloudtest-源", "https://example.com", kind="website")
    assert s is not None
    assert agent_db.source_get(s)["name"] == "cloudtest-源"
    agent_db.source_set_enabled(s, False)
    assert agent_db.source_get(s)["enabled"] is False
    # enabled_only=False 时可见
    assert any(x["id"] == s for x in agent_db.source_list(enabled_only=False))
