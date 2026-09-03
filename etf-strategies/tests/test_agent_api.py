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
    assert api_mod._mood("leave", None)["label"] == "请假中"
    assert api_mod._mood("on", None)["label"] == "摸鱼中"
    mobj = api_mod._mood("on", {"name": "早盘分析", "started_at": "09:07"})
    assert "正在做" in mobj["label"]


def test_state_derivation():
    """桌宠状态机四态推导：offline 优先 → leave → working → slack。"""
    from dashboard import api_agent as api_mod
    # 进程未运行（无论出勤/任务）→ offline
    assert api_mod._state(False, "on", {"task_id": "x", "name": "n"}) == "offline"
    assert api_mod._state(False, "leave", None) == "offline"
    # 请假（alive）→ leave
    assert api_mod._state(True, "leave", None) == "leave"
    # 上班 + 有任务 → working
    assert api_mod._state(True, "on",
                          {"task_id": "morning_analysis", "name": "早盘分析"}) == "working"
    # 上班 + 无任务 → slack
    assert api_mod._state(True, "on", None) == "slack"


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
