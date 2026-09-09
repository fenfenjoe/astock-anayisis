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


# ── 2026-09-08 云后端回归测试（mock _cd_select，无需真实云）─────────


def test_activity_count_cloud_uses_columns_kwarg(monkeypatch):
    """做过的事加载失败回归：cloud 分支曾传 select= 关键字导致 TypeError。

    mock _cd_select 断言调用只使用 columns=（cloud_db.select 的合法参数名），
    且 date_filter 分支正常返回计数。
    """
    calls = []

    def fake_select(table, **kw):
        calls.append((table, kw))
        return [{"id": 1}, {"id": 2}, {"id": 3}]

    monkeypatch.setattr(agent_db, "USE_CLOUD", True)
    monkeypatch.setattr(agent_db, "_cd_select", fake_select)

    assert agent_db.activity_count() == 3
    table, kw = calls[-1]
    assert table == "agent_activities"
    assert kw.get("columns") == "id"      # 必须用 columns，不能是 select
    assert "select" not in kw

    calls.clear()
    assert agent_db.activity_count(date_filter="2026-09-08") == 3
    table, kw = calls[-1]
    assert kw["columns"] == "id"
    assert len(kw["filters"]) == 2        # gte + lt 日期过滤

    monkeypatch.setattr(agent_db, "USE_CLOUD", False)


def test_article_create_cloud_sets_published_at(monkeypatch):
    """我的动态时间缺失回归：cloud 分支 article_create 必须写入 published_at。"""
    inserted = {}

    def fake_insert(table, row):
        inserted.update(row)
        return {"id": 99}

    monkeypatch.setattr(agent_db, "USE_CLOUD", True)
    monkeypatch.setattr(agent_db, "_cd_insert", fake_insert)

    aid = agent_db.article_create("标题", "摘要", "正文", topics=["动态"], kind="post")
    assert aid == 99
    assert inserted.get("published_at"), "cloud 分支必须显式写入 published_at"
    assert inserted["published_at"][:10] == agent_db._now_str()[:10]

    monkeypatch.setattr(agent_db, "USE_CLOUD", False)


def test_meta_get_many_cloud(monkeypatch):
    """agent_status 批量读回归：meta_get_many 一次 in 查询取全部 key。"""
    rows = [
        {"key": "a", "value": "1"},
        {"key": "b", "value": "2"},
    ]
    monkeypatch.setattr(agent_db, "USE_CLOUD", True)
    monkeypatch.setattr(
        agent_db, "_cd_select",
        lambda table, **kw: [dict(r) for r in rows if r["key"] in kw["filters"][0][2].strip("()").split(",")],
    )
    got = agent_db.meta_get_many(["a", "b", "missing"])
    assert got == {"a": "1", "b": "2", "missing": None}
    monkeypatch.setattr(agent_db, "USE_CLOUD", False)


# ═══════════════════════════════════════════
# 提示/待办（agent_notices）：REQ-002
# ═══════════════════════════════════════════


def test_init_creates_notices_table(adb):
    assert "agent_notices" in agent_db.list_tables()


def test_notice_create_and_get(adb):
    nid = agent_db.notice_create("notice", "今日复盘已完成", "三只信号已结算，详见报告")
    assert nid > 0
    n = agent_db.notice_get(nid)
    assert n["kind"] == "notice"
    assert n["status"] == "open"
    assert n["read_at"] is None
    assert n["reply"] is None


def test_todo_create_with_type(adb):
    tid = agent_db.notice_create(
        "todo", "请提供微博 Cookie", "复制浏览器 Cookie 串回复给我",
        todo_type="cookie_provide", source="agent",
    )
    t = agent_db.notice_get(tid)
    assert t["todo_type"] == "cookie_provide"
    assert t["source"] == "agent"
    # 非法 kind 拒绝
    with pytest.raises(ValueError):
        agent_db.notice_create("bogus", "x", "y")


def test_notice_list_filters(adb):
    agent_db.notice_create("notice", "n1", "c1")
    agent_db.notice_create("todo", "t1", "c2", todo_type="cookie_provide")
    all_n = agent_db.notice_list()
    assert len(all_n) == 2
    todos = agent_db.notice_list(kind="todo")
    assert len(todos) == 1 and todos[0]["title"] == "t1"
    notices = agent_db.notice_list(kind="notice")
    assert len(notices) == 1 and notices[0]["title"] == "n1"


def test_notice_unread_and_mark_read(adb):
    nid = agent_db.notice_create("notice", "n1", "c1")
    agent_db.notice_create("notice", "n2", "c2")
    assert agent_db.notice_unread_count() == 2
    agent_db.notice_mark_read(nid)
    assert agent_db.notice_unread_count() == 1
    # 幂等
    agent_db.notice_mark_read(nid)
    assert agent_db.notice_unread_count() == 1


def test_notice_mark_all_read(adb):
    agent_db.notice_create("notice", "n1", "c1")
    agent_db.notice_create("todo", "t1", "c2", todo_type="cookie_provide")
    agent_db.notice_mark_all_read()
    assert agent_db.notice_unread_count() == 0


def test_notice_reply_sets_done(adb):
    tid = agent_db.notice_create(
        "todo", "请提供微博 Cookie", "复制 Cookie 回复我", todo_type="cookie_provide"
    )
    agent_db.notice_reply(tid, "SUB=abc123", result="已收到，微博可达啦", success=True)
    t = agent_db.notice_get(tid)
    assert t["status"] == "done"
    assert t["reply"] == "SUB=abc123"
    assert t["result"] == "已收到，微博可达啦"
    assert t["reply_at"] is not None
    # 处理成功视为已读
    assert t["read_at"] is not None
    assert agent_db.notice_unread_count() == 0


def test_notice_reply_failure_resets_open(adb):
    """状态机：处理失败 → 回 open + 记失败原因 + read_at 清空（重新未读）。"""
    tid = agent_db.notice_create(
        "todo", "请提供微博 Cookie", "复制 Cookie 回复我", todo_type="cookie_provide"
    )
    agent_db.notice_reply(tid, "SUB=bad", result="Cookie 失效或探测失败", success=False)
    t = agent_db.notice_get(tid)
    assert t["status"] == "open"          # 重置未处理，可重试
    assert t["reply"] == "SUB=bad"        # 保留用户回复
    assert t["result"] == "Cookie 失效或探测失败"  # 小满失败原因
    assert t["read_at"] is None           # 重新计未读 → 小红点重新提醒
    assert agent_db.notice_unread_count() == 1


def test_notice_status_transitions(adb):
    tid = agent_db.notice_create("todo", "t1", "c1", todo_type="cookie_provide")
    agent_db.notice_set_status(tid, "dismissed")
    assert agent_db.notice_get(tid)["status"] == "dismissed"
    assert agent_db.notice_unread_count() == 0  # dismissed 不计未读
    with pytest.raises(ValueError):
        agent_db.notice_set_status(tid, "bogus")


def test_notice_list_processed_last(adb):
    """未处理（未读且 open）排前，已处理（已阅/已回复/已忽略）排后；组内新→旧。"""
    a = agent_db.notice_create("notice", "A", "c")
    agent_db.notice_create("notice", "B", "c")          # 未处理
    c = agent_db.notice_create("notice", "C", "c")
    agent_db.notice_create("todo", "T", "c", todo_type="cookie_provide")
    agent_db.notice_mark_read(a)                        # 已阅 → 已处理
    agent_db.notice_set_status(c, "dismissed")          # 已忽略 → 已处理
    titles = [n["title"] for n in agent_db.notice_list()]
    assert titles == ["T", "B", "C", "A"]  # 未处理(T,B 新→旧) → 已处理(C,A 新→旧)


def test_notice_list_pagination(adb):
    for i in range(15):
        agent_db.notice_create("notice", f"n{i:02d}", "c")
    page1 = agent_db.notice_list(limit=10, offset=0)
    page2 = agent_db.notice_list(limit=10, offset=10)
    assert len(page1) == 10 and len(page2) == 5
    # 组内新→旧：第一页是最新 10 条
    assert page1[0]["title"] == "n14"
    assert page1[-1]["title"] == "n05"
    assert page2[0]["title"] == "n04"
    assert agent_db.notice_count() == 15


def test_notice_count_filters(adb):
    agent_db.notice_create("notice", "n1", "c1")
    agent_db.notice_create("todo", "t1", "c2", todo_type="cookie_provide")
    assert agent_db.notice_count() == 2
    assert agent_db.notice_count(kind="todo") == 1
    assert agent_db.notice_count(status="open") == 2
