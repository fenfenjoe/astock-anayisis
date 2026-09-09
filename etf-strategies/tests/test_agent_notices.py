"""agent 提示/待办（REQ-002）测试 — notices 生成器 + 回复回调 dispatch + API。

覆盖：
- notices.create_cookie_todo：无 Cookie 生成待办、有 Cookie/已有 open 待办去重
- notices.create_review_done_notice：复盘完成提示
- notices.dispatch_todo_reply：cookie_provide 回调（落库 + 重探测）、未知类型
- API：/api/agent/notices 列表/未读数/标记已读/回复/dismiss

无网络：探测 mock；db 用 tmp_path 本地。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from agent import config, db as agent_db
from agent.core import notices as notices_mod
from agent.core import reachability


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    agent_db.init_db(tmp_path / "agent.db")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "agent.db")
    yield
    agent_db.init_db(None)


def _probe_ok(monkeypatch):
    """RSSHub 探测拉到条目 → 可达。"""
    monkeypatch.setattr(
        reachability.knowledge, "fetch_feed",
        lambda feed, timeout=None: [{"title": "条目"}],
    )


# ═══════════════════════════════════════════
# notices 生成器
# ═══════════════════════════════════════════


class TestCookieTodoGenerator:
    def test_create_when_no_cookie(self):
        nid = notices_mod.create_cookie_todo("weibo")
        assert nid is not None
        n = agent_db.notice_get(nid)
        assert n["kind"] == "todo"
        assert n["todo_type"] == "cookie_provide"
        assert n["todo_data"]["platform_id"] == "weibo"
        assert n["status"] == "open"
        # 提示用户具体取哪个 key（微博 → SUB）
        assert "SUB" in n["content"]
        assert "完整 Cookie" in n["content"]

    def test_create_xhs_includes_web_session_key(self):
        nid = notices_mod.create_cookie_todo("xhs")
        n = agent_db.notice_get(nid)
        assert "web_session" in n["content"]
        assert "a1" in n["content"]

    def test_dedup_when_open_exists(self):
        nid1 = notices_mod.create_cookie_todo("weibo")
        nid2 = notices_mod.create_cookie_todo("weibo")
        assert nid1 is not None
        assert nid2 is None  # 已有 open 同平台待办 → 不重复生成

    def test_skip_when_cookie_present(self):
        agent_db.platform_cookie_set("weibo", "SUB=abc")
        assert notices_mod.create_cookie_todo("weibo") is None

    def test_skip_non_cookie_platform(self):
        # 财联社是 RSS 源，不走 Cookie 待办
        assert notices_mod.create_cookie_todo("cls") is None
        assert notices_mod.create_cookie_todo("x") is None

    def test_unknown_platform(self):
        assert notices_mod.create_cookie_todo("nope") is None

    def test_ensure_cookie_todos(self):
        """启动批量生成：weibo/xhs/zhihu/xueqiu 均无 Cookie → 生成 4 条；重复调用幂等。"""
        created = notices_mod.ensure_cookie_todos()
        ids = [agent_db.notice_get(i)["todo_data"]["platform_id"] for i in created]
        assert len(created) == 4  # weibo + xhs + zhihu + xueqiu
        assert set(ids) == {"weibo", "xhs", "zhihu", "xueqiu"}
        created2 = notices_mod.ensure_cookie_todos()
        assert created2 == []  # 已存在，不重复
        # 提供 Cookie 后再启动 → 仅缺失平台重新生成
        agent_db.platform_cookie_set("weibo", "SUB=abc")
        # 清理旧待办（视作已完成/忽略），否则去重会挡住新生成
        for nid in created:
            agent_db.notice_set_status(nid, "done")
        created3 = notices_mod.ensure_cookie_todos()
        ids3 = [agent_db.notice_get(i)["todo_data"]["platform_id"] for i in created3]
        assert "weibo" not in ids3  # weibo 已有 Cookie
        assert "xhs" in ids3
        assert "zhihu" in ids3
        assert "xueqiu" in ids3

    def test_create_zhihu_todo_includes_keys(self):
        """知乎 Cookie 待办：提示关键 key（z_c0/d_c0），与微博/小红书一致的询问机制。"""
        nid = notices_mod.create_cookie_todo("zhihu")
        assert nid is not None
        n = agent_db.notice_get(nid)
        assert n["todo_data"]["platform_id"] == "zhihu"
        assert "z_c0" in n["content"]
        assert "d_c0" in n["content"]
        assert "完整 Cookie" in n["content"]

    def test_create_xueqiu_todo_includes_keys(self):
        nid = notices_mod.create_cookie_todo("xueqiu")
        assert nid is not None
        n = agent_db.notice_get(nid)
        assert n["todo_data"]["platform_id"] == "xueqiu"
        assert "xq_a_token" in n["content"]


class TestReviewDoneNotice:
    def test_create(self):
        nid = notices_mod.create_review_done_notice("今日复盘完成，3 条信号已结算")
        n = agent_db.notice_get(nid)
        assert n["kind"] == "notice"
        assert n["source"] == "evening_review"
        assert n["title"] == "复盘完成"
        assert "信号已结算" in n["content"]


# ═══════════════════════════════════════════
# notices 回复回调 dispatch
# ═══════════════════════════════════════════


class TestReplyDispatch:
    def test_cookie_provide_stores_and_probes(self, monkeypatch):
        _probe_ok(monkeypatch)
        nid = notices_mod.create_cookie_todo("weibo")
        n = agent_db.notice_get(nid)
        res = notices_mod.dispatch_todo_reply(n, "SUB=abc123; subp=def")
        assert res["ok"] is True
        assert "可达" in res["message"]
        assert agent_db.platform_cookie_get("weibo") == "SUB=abc123; subp=def"
        assert agent_db.reachability_get("weibo")["reachable"] is True
        # 待办状态 → done（由 API 层调用 notice_reply）

    def test_cookie_provide_empty_reply(self):
        nid = notices_mod.create_cookie_todo("weibo")
        n = agent_db.notice_get(nid)
        res = notices_mod.dispatch_todo_reply(n, "   ")
        assert res["ok"] is False
        assert "太短" in res["message"]

    def test_unknown_todo_type(self):
        nid = agent_db.notice_create(
            "todo", "某待办", "说明", todo_type="bogus_type"
        )
        n = agent_db.notice_get(nid)
        res = notices_mod.dispatch_todo_reply(n, "回复")
        assert res["ok"] is False
        assert "未知待办类型" in res["message"]

    def test_todo_data_as_json_string_cloud(self, monkeypatch):
        """云模式回归：todo_data 可能以 JSON 字符串返回（未解析），dispatch 必须兼容。"""
        _probe_ok(monkeypatch)
        # 模拟 cloud 后端返回：todo_data 是 JSON 字符串（cloud_db._row_dict 未解析前的形态）
        n = {
            "id": 999,
            "kind": "todo",
            "status": "open",
            "title": "请提供微博的 Cookie",
            "content": "…",
            "todo_type": "cookie_provide",
            "todo_data": '{"platform_id": "weibo"}',
        }
        res = notices_mod.dispatch_todo_reply(n, "SUB=abc")
        assert res["ok"] is True
        assert "可达" in res["message"]


# ═══════════════════════════════════════════
# notices API
# ═══════════════════════════════════════════


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from dashboard import app as app_mod

    app_mod.app.dependency_overrides[app_mod.get_current_user] = lambda: {
        "id": 1, "username": "admin",
    }
    yield TestClient(app_mod.app)
    app_mod.app.dependency_overrides.clear()


class TestNoticesAPI:
    def test_list_and_unread(self, client):
        agent_db.notice_create("notice", "n1", "c1")
        agent_db.notice_create("todo", "t1", "c2", todo_type="cookie_provide")
        r = client.get("/api/agent/notices")
        assert r.status_code == 200
        d = r.json()
        assert d["unread_count"] == 2
        assert len(d["notices"]) == 2
        kinds = {x["kind"] for x in d["notices"]}
        assert kinds == {"notice", "todo"}
        assert d["total"] == 2 and d["total_pages"] == 1

    def test_list_pagination_and_ordering(self, client):
        """未处理在前、已处理在后；分页返回 total/total_pages。"""
        for i in range(3):
            agent_db.notice_create("notice", f"n{i}", "c")
        done = agent_db.notice_create("todo", "t_old", "c", todo_type="cookie_provide")
        agent_db.notice_reply(done, "SUB=abc")  # 已回复 → 已处理
        r = client.get("/api/agent/notices?page=1&page_size=2")
        assert r.status_code == 200
        d = r.json()
        assert d["total"] == 4 and d["total_pages"] == 2
        titles = [x["title"] for x in d["notices"]]
        # 第一页 2 条都是未处理（新→旧：n2, n1）；已回复的 t_old 不在这页
        assert titles == ["n2", "n1"]
        assert all(not x["read"] for x in d["notices"])
        r2 = client.get("/api/agent/notices?page=2&page_size=2")
        titles2 = [x["title"] for x in r2.json()["notices"]]
        assert titles2 == ["n0", "t_old"]  # 未处理剩 n0，已处理 t_old 在后
        # 已处理项 read=true（reply 视为已读）
        assert r2.json()["notices"][1]["read"] is True
        assert r2.json()["unread_count"] == 3

    def test_mark_read(self, client):
        nid = agent_db.notice_create("notice", "n1", "c1")
        r = client.post(f"/api/agent/notices/{nid}/read")
        assert r.status_code == 200
        assert agent_db.notice_unread_count() == 0
        assert agent_db.notice_get(nid)["read_at"] is not None

    def test_read_all(self, client):
        agent_db.notice_create("notice", "n1", "c1")
        agent_db.notice_create("todo", "t1", "c2", todo_type="cookie_provide")
        r = client.post("/api/agent/notices/read-all")
        assert r.status_code == 200
        assert agent_db.notice_unread_count() == 0

    def test_reply_todo(self, client, monkeypatch):
        _probe_ok(monkeypatch)
        nid = notices_mod.create_cookie_todo("xhs")
        r = client.post(f"/api/agent/notices/{nid}/reply", json={"reply": "a=1; b=2"})
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True
        # 状态机：open → done；返回更新后的 notice（含小满回复 result）
        assert d["notice"]["status"] == "done"
        assert d["notice"]["result"] is not None
        assert "可达" in d["notice"]["result"]
        assert d["notice"]["read"] is True
        n = agent_db.notice_get(nid)
        assert n["status"] == "done"
        assert n["reply"] == "a=1; b=2"
        assert agent_db.platform_cookie_get("xhs") == "a=1; b=2"
        assert d["unread_count"] == 0

    def test_reply_invalid_cookie_resets_open(self, client):
        """处理失败：回 open + result=失败原因 + read_at 清空（重新未读）→ 200 非 400。"""
        nid = notices_mod.create_cookie_todo("xhs")
        r = client.post(f"/api/agent/notices/{nid}/reply", json={"reply": "ab"})
        assert r.status_code == 200  # 状态机：失败也正常返回，前端展示失败原因
        d = r.json()
        assert d["ok"] is False
        assert "太短" in d["message"]
        # 重置未处理：可重试、保留用户回复、记失败原因、重新未读
        assert d["notice"]["status"] == "open"
        assert d["notice"]["reply"] == "ab"
        assert d["notice"]["read"] is False
        assert "太短" in d["notice"]["result"]
        assert d["unread_count"] == 1
        assert agent_db.notice_get(nid)["status"] == "open"

    def test_dismiss(self, client):
        nid = agent_db.notice_create("notice", "n1", "c1")
        r = client.post(f"/api/agent/notices/{nid}/dismiss")
        assert r.status_code == 200
        assert agent_db.notice_get(nid)["status"] == "dismissed"
        assert agent_db.notice_unread_count() == 0

    def test_reply_unknown_id(self, client):
        r = client.post("/api/agent/notices/9999/reply", json={"reply": "x"})
        assert r.status_code == 404
