"""agent/db.py — 五表 + CRUD 测试（独立 tmp db，不碰真实 cache.db/agent.db）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from agent import db as agent_db


@pytest.fixture()
def adb(tmp_path):
    agent_db.init_db(tmp_path / "agent.db")
    yield agent_db
    agent_db.init_db(None)  # 复位为默认路径


def test_init_creates_all_tables(adb):
    tables = agent_db.list_tables()
    for t in ("agent_sessions", "agent_messages", "agent_articles",
              "agent_opinions", "agent_knowledge", "agent_metadata",
              "agent_sources"):
        assert t in tables


def test_source_crud(adb):
    sid = agent_db.source_add("华尔街见闻", "https://wallstreetcn.com/live",
                              kind="website", note="宏观")
    assert sid > 0
    rows = agent_db.source_list()
    assert len(rows) == 1
    assert rows[0]["name"] == "华尔街见闻"
    assert rows[0]["enabled"] == 1
    # 手动喂的单条 URL 也走同表（kind=manual）
    agent_db.source_add("某篇文章", "https://example.com/a/1", kind="manual")
    assert len(agent_db.source_list()) == 2
    # 启用/停用
    agent_db.source_set_enabled(sid, 0)
    assert agent_db.source_get(sid)["enabled"] == 0
    # 删除
    agent_db.source_delete(sid)
    assert agent_db.source_get(sid) is None
    assert len(agent_db.source_list()) == 1


def test_session_crud(adb):
    sid = agent_db.session_create("第一会话")
    assert sid > 0
    sess = agent_db.session_get(sid)
    assert sess["title"] == "第一会话"
    lst = agent_db.session_list()
    assert len(lst) == 1
    agent_db.session_rename(sid, "改名")
    assert agent_db.session_get(sid)["title"] == "改名"
    agent_db.session_delete(sid)
    assert agent_db.session_list() == []


def test_message_add_and_list(adb):
    sid = agent_db.session_create("s")
    agent_db.message_add(sid, "user", "你好")
    agent_db.message_add(sid, "assistant", "你好呀",
                         sources=[{"title": "来源", "url": "http://a/1"}])
    msgs = agent_db.messages_by_session(sid)
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
    # sources 以 JSON 存取（读出来可解析）
    assert msgs[1]["sources"] is not None


def test_message_cascade_delete_with_session(adb):
    sid = agent_db.session_create("s")
    agent_db.message_add(sid, "user", "hi")
    agent_db.session_delete(sid)
    # 级联删除后消息表无残留（session 已删，直接查全部消息应为空）
    assert agent_db.messages_all() == []


def test_article_crud(adb):
    aid = agent_db.article_create(
        "标题", "摘要", "正文", topics=["宏观"],
        sources=[{"title": "s", "url": "http://s"}],
    )
    arts = agent_db.article_list()
    assert len(arts) == 1
    a = agent_db.article_get(aid)
    assert a["title"] == "标题"
    assert a["content"] == "正文"
    assert a["topics"] is not None
    # 默认 kind = article
    assert a["kind"] == "article"


def test_article_kind_filter(adb):
    aid_a = agent_db.article_create("长文", "", "正文1", kind="article")
    aid_p = agent_db.article_create("一条动态", "", "短内容", kind="post")
    assert agent_db.article_get(aid_a)["kind"] == "article"
    assert agent_db.article_get(aid_p)["kind"] == "post"
    # 全量
    assert len(agent_db.article_list()) == 2
    # kind 过滤
    posts = agent_db.article_list(kind="post")
    assert len(posts) == 1 and posts[0]["id"] == aid_p
    arts = agent_db.article_list(kind="article")
    assert len(arts) == 1 and arts[0]["id"] == aid_a


def test_article_list_newest_first(adb):
    agent_db.article_create("旧", "", "1", topics=[], sources=None)
    aid2 = agent_db.article_create("新", "", "2", topics=[], sources=None)
    arts = agent_db.article_list()
    assert arts[0]["id"] == aid2


def test_opinions(adb):
    agent_db.opinion_add("白酒", "茅台护城河在品牌", article_id=None)
    agent_db.opinion_add("白酒", "高端酒消费人群在变", article_id=None)
    rows = agent_db.opinions_by_topic("白酒")
    assert len(rows) == 2
    assert len(agent_db.opinions_all()) == 2


def test_knowledge_upsert_dedup(adb):
    ok1 = agent_db.knowledge_upsert(
        "cls", "快讯一", "http://a/1", "摘要", None, "2026-08-27 10:00")
    ok2 = agent_db.knowledge_upsert(
        "cls", "快讯一(重复)", "http://a/1", "摘要2", None, "2026-08-27 10:01")
    assert ok1 is True
    assert ok2 is False  # 同 url 去重，未新增
    rows = agent_db.knowledge_unconsumed()
    assert len(rows) == 1


def test_knowledge_consume(adb):
    agent_db.knowledge_upsert(
        "cls", "快讯", "http://a/2", "摘要", None, "2026-08-27 10:00")
    rows = agent_db.knowledge_unconsumed(limit=10)
    assert len(rows) == 1
    agent_db.knowledge_mark_consumed(rows[0]["id"])
    assert agent_db.knowledge_unconsumed() == []


def test_metadata(adb):
    agent_db.meta_set("k", "v")
    assert agent_db.meta_get("k") == "v"
    assert agent_db.meta_get("missing") is None
