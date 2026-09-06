"""dashboard/api_agent.py — 小满 Web API（SSE 聊天 / 会话 / 文章 / 状态）。

无网络：LLM 用 fake 流式生成器；agent.db 重定向到 tmp；认证用 dependency_overrides。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from agent import db as agent_db
from dashboard import api_agent as api_mod
from dashboard import app as app_mod
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    agent_db.init_db(tmp_path / "agent.db")

    async def _fake_user(request=None):
        return {"username": "tester", "role": "admin", "display_name": "tester"}

    app_mod.app.dependency_overrides[app_mod.get_current_user] = _fake_user

    def _fake_run_task(task, profile=None, cwd=None, timeout=None, run=None):
        return "success", "你好，我是小满。"

    monkeypatch.setattr(api_mod.dsh_runner, "run_task", _fake_run_task)

    # 不 with TestClient：不触发 lifespan（避免连真实 cache.db / 启动调度器）
    yield TestClient(app_mod.app)

    app_mod.app.dependency_overrides.clear()
    agent_db.init_db(None)


def test_status_endpoint(client):
    r = client.get("/api/agent/status")
    assert r.status_code == 200
    data = r.json()
    assert "alive" in data
    assert "dsh_ready" in data
    # 人格化状态字段
    assert "attendance" in data
    assert "mood" in data
    # 机器可读状态枚举（桌宠状态机用）
    assert "state" in data
    assert data["state"] in ("offline", "leave", "working", "slack")


def test_mood_demo():
    from dashboard import api_agent as api_mod
    assert api_mod._mood("leave", None, True)["label"] == "请假中"
    assert api_mod._mood("on", None, True)["label"] == "摸鱼中"
    mobj = api_mod._mood("on", {"name": "早盘分析", "started_at": "09:07"}, True)
    assert "正在做" in mobj["label"]
    assert api_mod._mood("on", None, False)["label"] == "未上线"


def test_state_derivation():
    """桌宠状态机四态推导：offline 优先 → leave → working → slack。"""
    from dashboard import api_agent as api_mod
    # 未上线 / 进程未运行 → offline
    assert api_mod._state(False, "on", {"task_id": "x", "name": "n"}, True) == "offline"
    assert api_mod._state(True, "on", {"task_id": "x", "name": "n"}, False) == "offline"
    # 请假（在线）→ leave
    assert api_mod._state(True, "leave", None, True) == "leave"
    # 上班 + 有任务 → working
    assert api_mod._state(True, "on",
                          {"task_id": "morning_analysis", "name": "早盘分析"}, True) == "working"
    # 上班 + 无任务 → slack
    assert api_mod._state(True, "on", None, True) == "slack"


def test_create_and_list_session(client):
    r = client.post("/api/agent/sessions", json={"title": "聊聊行情"})
    assert r.status_code == 200
    sid = r.json()["id"]
    lst = client.get("/api/agent/sessions").json()["sessions"]
    assert any(s["id"] == sid and s["title"] == "聊聊行情" for s in lst)


def test_chat_sse_streams_and_persists(client):
    sid = client.post("/api/agent/sessions", json={"title": "s"}).json()["id"]
    r = client.post(f"/api/agent/sessions/{sid}/messages",
                    json={"content": "你好呀"})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    # 流式增量逐条为独立 SSE 事件；拼接后等于完整回复
    deltas = []
    for line in r.text.splitlines():
        if line.startswith("data: "):
            payload = json.loads(line[len("data: "):])
            if "delta" in payload:
                deltas.append(payload["delta"])
    assert "".join(deltas) == "你好，我是小满。"
    # 落库：assistant 消息存在
    msgs = agent_db.messages_by_session(sid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["content"] == "你好，我是小满。"


def test_agent_set_state(client):
    """桌宠状态按钮契约：random/reading/slack 走 switch_state 落库并记台账；非法 action 400。

    前端 manualState() 消费 {"state": {id, label, changed}} —— 此测试锁定该形状。
    """
    r = client.post("/api/agent/state", json={"action": "slack"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["state"]["changed"] is True
    assert body["state"]["id"] and body["state"]["label"]
    # 落库后端：状态机 meta 与活动台账（做过的事）同步写入
    assert agent_db.meta_get("xiaoman_current_state") == body["state"]["id"]

    r = client.post("/api/agent/state", json={"action": "reading"})
    assert r.status_code == 200
    assert r.json()["state"]["id"] == "reading"

    r = client.post("/api/agent/state", json={"action": "bogus"})
    assert r.status_code == 400


def test_chat_multiline_reply_is_multi_messages(client, monkeypatch):
    """dsh 输出契约：每条消息 = 一行 → 后端逐条落库 + 逐条 SSE 下发（不再由前端切句）。"""
    def _multi(task, profile=None, cwd=None, timeout=None, run=None):
        return "success", "第一句。\n第二句呀～\n\n第三句！"

    monkeypatch.setattr(api_mod.dsh_runner, "run_task", _multi)
    sid = client.post("/api/agent/sessions", json={}).json()["id"]
    r = client.post(f"/api/agent/sessions/{sid}/messages",
                    json={"content": "在吗"})
    assert r.status_code == 200
    deltas = []
    for line in r.text.splitlines():
        if line.startswith("data: "):
            payload = json.loads(line[len("data: "):])
            if "delta" in payload:
                deltas.append(payload["delta"])
    # 空行被跳过，每行 = 一条消息（SSE 每条 delta 一个气泡）
    assert deltas == ["第一句。", "第二句呀～", "第三句！"]
    # 落库：每条 assistant 消息独立一行记录
    msgs = agent_db.messages_by_session(sid)
    roles = [m["role"] for m in msgs]
    assert roles == ["user", "assistant", "assistant", "assistant"]
    contents = [m["content"] for m in msgs if m["role"] == "assistant"]
    assert contents == ["第一句。", "第二句呀～", "第三句！"]


def test_chat_empty_content_400(client):
    sid = client.post("/api/agent/sessions", json={}).json()["id"]
    r = client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "  "})
    assert r.status_code == 400


def test_chat_missing_session_404(client):
    r = client.post("/api/agent/sessions/9999/messages", json={"content": "hi"})
    assert r.status_code == 404


def test_chat_llm_error_returns_error_event(client, monkeypatch):
    def _boom(task, profile=None, cwd=None, timeout=None, run=None):
        raise api_mod.dsh_runner.DshRunnerError("dsh failed: boom")

    monkeypatch.setattr(api_mod.dsh_runner, "run_task", _boom)
    sid = client.post("/api/agent/sessions", json={}).json()["id"]
    r = client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "hi"})
    assert "boom" in r.text
    # 错误也落库 assistant 消息（用户可见）
    msgs = agent_db.messages_by_session(sid)
    assert msgs[-1]["role"] == "assistant"


def test_chat_history_endpoint(client):
    sid = client.post("/api/agent/sessions", json={"title": "s"}).json()["id"]
    client.post(f"/api/agent/sessions/{sid}/messages", json={"content": "你好呀"})
    hist = client.get(f"/api/agent/sessions/{sid}/messages")
    assert hist.status_code == 200
    roles = [m["role"] for m in hist.json()["messages"]]
    assert roles == ["user", "assistant"]
    assert client.get("/api/agent/sessions/9999/messages").status_code == 404


def test_articles_list_and_detail(client):
    aid = agent_db.article_create(
        "学习笔记", "摘要", "正文内容", topics=["学习笔记"], sources=None)
    lst = client.get("/api/agent/articles").json()["articles"]
    assert any(a["id"] == aid and a["title"] == "学习笔记" for a in lst)
    detail = client.get(f"/api/agent/articles/{aid}")
    assert detail.status_code == 200
    assert detail.json()["content"] == "正文内容"
    assert client.get("/api/agent/articles/9999").status_code == 404


def test_profile_returns_basic_and_activity(client):
    """认识页 v2：侧栏「关于我」=人设卡基本节；右侧「做过的事」=活动台账
    （已结束的阅读事件显示结束时间；常驻状态进行中置顶；token 均未计量）。"""
    # 造两条台账：昨天读完的阅读事件（已结束）+ 当前正在打游戏（未结束）
    agent_db.activity_start("reading", "📖 阅读", "2026-09-05 17:35:00", source="auto")
    rid = agent_db.activity_open()["id"]
    agent_db.activity_set_note(rid, "读了 2 篇")
    agent_db.activity_close_open("2026-09-05 17:42:00")
    agent_db.activity_start("gaming", "🎮 打游戏", "2026-09-06 10:00:00", source="manual")

    r = client.get("/api/agent/profile")
    assert r.status_code == 200
    p = r.json()

    # 侧栏「关于我」：从 persona.md 基本节解析出"姓名"
    basic = p.get("basic", [])
    assert any(b["k"] == "姓名" and "小满" in b["v"] for b in basic)

    acts = p.get("activity", [])
    assert acts, "应至少有一条活动"
    # 进行中（打游戏）排最前且 ended 为空
    assert acts[0]["title"] == "打游戏" and acts[0]["ended"] is None
    # 昨天结束的"阅读"绝不显示进行中：有结束时间、备注带"读了 N 篇"
    read_row = next(a for a in acts if a["title"] == "阅读")
    assert read_row["ended"] == "2026-09-05 17:42:00"
    assert "读了 2 篇" in read_row["meta"]
    assert all(a.get("tokens") is None for a in acts)


def test_manual_state_records_activity(client):
    """桌宠按钮 → POST /api/agent/state（动作事件模型）：
    阅读=动作事件（只切 meta）；摸鱼=常驻状态段（落一条进行中记录）。"""
    r = client.post("/api/agent/state", json={"action": "reading"})
    assert r.status_code == 200
    j = r.json()
    assert j["state"]["id"] == "reading" and j["state"]["changed"] is True
    assert j["state"]["event"] is True
    assert client.get("/api/agent/status").json()["current_state"] == "reading"
    assert agent_db.activity_open() is None          # 阅读不占常驻段（由真实执行器开事件）
    assert agent_db.meta_get("xiaoman_state_seq") == "1"

    r2 = client.post("/api/agent/state", json={"action": "slack"})
    assert r2.status_code == 200
    assert r2.json()["state"]["id"] not in ("reading", "writing")
    open_act = agent_db.activity_open()
    assert open_act["kind"] != "reading" and open_act["ended_at"] is None
    assert open_act["source"] == "manual"
    assert open_act["tokens"] is None               # 真实 usage 未接入 → 未计量

    assert client.post("/api/agent/state", json={"action": "fly"}).status_code == 400


def test_delete_session(client):
    sid = client.post("/api/agent/sessions", json={}).json()["id"]
    assert client.delete(f"/api/agent/sessions/{sid}").json()["ok"] is True
    assert client.delete(f"/api/agent/sessions/{sid}").status_code == 404


def test_sources_website_crud(client):
    r = client.post("/api/agent/sources", json={
        "name": "华尔街见闻", "url": "https://wallstreetcn.com/live",
        "kind": "website", "note": "宏观"})
    assert r.status_code == 200
    sid = r.json()["id"]
    lst = client.get("/api/agent/sources").json()["sources"]
    assert any(s["id"] == sid and s["enabled"] == 1 for s in lst)
    # toggle 停用
    t = client.post(f"/api/agent/sources/{sid}/toggle").json()
    assert t["enabled"] == 0
    # 删除
    assert client.delete(f"/api/agent/sources/{sid}").json()["ok"] is True
    assert client.delete(f"/api/agent/sources/{sid}").status_code == 404


def test_sources_manual_feeds_knowledge(client):
    r = client.post("/api/agent/sources", json={
        "name": "一篇深度文", "url": "https://example.com/deep/1",
        "kind": "manual", "note": "值得学习"})
    assert r.status_code == 200
    # 手动喂 → 直接进素材池
    rows = agent_db.knowledge_unconsumed()
    assert any(k["url"] == "https://example.com/deep/1" for k in rows)


def test_sources_validation(client):
    assert client.post("/api/agent/sources", json={
        "name": "", "url": "x"}).status_code == 400
    assert client.post("/api/agent/sources", json={
        "name": "n", "url": "ftp://x"}).status_code == 400
    assert client.post("/api/agent/sources", json={
        "name": "n", "url": "http://ok", "kind": "bad"}).status_code == 400
