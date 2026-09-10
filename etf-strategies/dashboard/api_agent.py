"""dashboard/api_agent.py — 拟人 Agent「小满」Web API 路由（反向代理模式）。

Dashboard 不再直接读 agent.db，所有 /api/agent/* 请求转发到 Agent 进程 HTTP API。
Agent 地址由 AGENT_API_URL 环境变量指定（默认 http://127.0.0.1:8020）。
认证：通过 AGENT_API_KEY 环境变量作为 X-Api-Key 头。
Agent 不可达时返回 status: "offline"，不报错。
"""

import json
import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from dashboard.auth import get_current_user

AGENT_API_URL = os.environ.get("AGENT_API_URL", "http://127.0.0.1:8020").rstrip("/")
AGENT_API_KEY = os.environ.get("AGENT_API_KEY", "").strip()
_DEFAULT_TIMEOUT = 120

router = APIRouter(prefix="/api/agent", dependencies=[Depends(get_current_user)])
_http = httpx.Client(
    timeout=_DEFAULT_TIMEOUT,
    headers={"X-Api-Key": AGENT_API_KEY} if AGENT_API_KEY else {},
)


def _agent_url(path: str) -> str:
    return f"{AGENT_API_URL}/api/agent{path}"


def _proxy_get(path: str, params: dict | None = None):
    try:
        r = _http.get(_agent_url(path), params=params)
        return r.json()
    except Exception:
        return None


def _proxy_post(path: str, body: dict | None = None):
    try:
        r = _http.post(_agent_url(path), json=body)
        return r.json()
    except Exception:
        return None


def _proxy_delete(path: str):
    try:
        r = _http.delete(_agent_url(path))
        return r.json()
    except Exception:
        return None


def _agent_offline_response():
    return {
        "alive": False,
        "online": False,
        "state": "offline",
        "heartbeat_age_seconds": None,
        "dsh_ready": False,
        "attendance": "leave",
        "current_task": None,
        "mood": {"label": "小满不在线", "icon": "😴"},
        "published_on": None,
        "last_rss_fetch_at": None,
        "current_state": None,
        "current_state_label": None,
        "state_until": None,
    }


# ═══════════════════════════════════════════
# 状态
# ═══════════════════════════════════════════


@router.get("/status")
def agent_status():
    """角色状态：代理到 Agent 进程，不可达时返回 offline。"""
    result = _proxy_get("/status")
    if result is None:
        return _agent_offline_response()
    return result


# ═══════════════════════════════════════════
# 介绍页
# ═══════════════════════════════════════════


@router.get("/profile")
def agent_profile():
    result = _proxy_get("/profile")
    if result is None:
        return {
            "persona_md": "",
            "basic": [],
            "activity": [],
            "recent_articles": [],
            "recent_reads": [],
            "social_platforms": [],
            "interests": [],
            "hobbies": [],
        }
    return result


@router.get("/activities")
def agent_activities(date: str = "", page: int = 1, page_size: int = 20):
    result = _proxy_get(
        "/activities", params={"date": date, "page": page, "page_size": page_size}
    )
    if result is None:
        return {
            "activities": [],
            "total": 0,
            "page": 1,
            "page_size": 20,
            "total_pages": 0,
        }
    return result


# ═══════════════════════════════════════════
# 上线/下线/状态切换
# ═══════════════════════════════════════════


@router.post("/online")
def agent_online():
    result = _proxy_post("/online")
    if result is None:
        return {"ok": False, "error": "Agent 不可达"}
    return result


@router.post("/offline")
def agent_offline():
    result = _proxy_post("/offline")
    if result is None:
        return {"ok": False, "error": "Agent 不可达"}
    return result


@router.post("/state")
async def agent_set_state(request: Request):
    body = await request.json()
    result = _proxy_post("/state", body)
    if result is None:
        return {"ok": False, "error": "Agent 不可达"}
    return result


# ═══════════════════════════════════════════
# 提示/待办
# ═══════════════════════════════════════════


@router.get("/notices")
def list_notices(page: int = 1, page_size: int = 5):
    result = _proxy_get("/notices", params={"page": page, "page_size": page_size})
    if result is None:
        return {
            "notices": [],
            "unread_count": 0,
            "total": 0,
            "page": 1,
            "page_size": 5,
            "total_pages": 0,
        }
    return result


@router.get("/notices/unread-count")
def notices_unread_count():
    result = _proxy_get("/notices/unread-count")
    if result is None:
        return {"unread_count": 0}
    return result


@router.post("/notices/{nid}/read")
def notice_read(nid: int):
    result = _proxy_post(f"/notices/{nid}/read")
    if result is None:
        return {"ok": False}
    return result


@router.post("/notices/read-all")
def notice_read_all():
    result = _proxy_post("/notices/read-all")
    if result is None:
        return {"ok": False}
    return result


@router.post("/notices/{nid}/dismiss")
def notice_dismiss(nid: int):
    result = _proxy_post(f"/notices/{nid}/dismiss")
    if result is None:
        return {"ok": False}
    return result


@router.post("/notices/{nid}/reply")
async def notice_reply(nid: int, request: Request):
    body = await request.json()
    result = _proxy_post(f"/notices/{nid}/reply", body)
    if result is None:
        return {"ok": False, "message": "Agent 不可达"}
    return result


# ═══════════════════════════════════════════
# 会话
# ═══════════════════════════════════════════


@router.post("/sessions")
async def create_session(request: Request):
    body = await request.json()
    result = _proxy_post("/sessions", body)
    if result is None:
        return {"id": None, "title": "Agent 不可达"}
    return result


@router.get("/sessions")
def list_sessions():
    result = _proxy_get("/sessions")
    if result is None:
        return {"sessions": []}
    return result


@router.delete("/sessions/{sid}")
def delete_session(sid: int):
    result = _proxy_delete(f"/sessions/{sid}")
    if result is None:
        return {"ok": False}
    return result


@router.get("/sessions/{sid}/messages")
def get_session_messages(sid: int):
    result = _proxy_get(f"/sessions/{sid}/messages")
    if result is None:
        return {"messages": []}
    return result


@router.post("/sessions/{sid}/messages")
async def chat_message(sid: int, request: Request):
    body = await request.json()

    async def event_gen():
        try:
            async with httpx.AsyncClient(
                timeout=_DEFAULT_TIMEOUT,
                headers={"X-Api-Key": AGENT_API_KEY} if AGENT_API_KEY else {},
            ) as client:
                async with client.stream(
                    "POST", _agent_url(f"/sessions/{sid}/messages"), json=body
                ) as r:
                    async for chunk in r.aiter_text():
                        yield chunk
        except Exception as e:
            yield f"data: {json.dumps({'error': f'Agent 不可达: {e}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ═══════════════════════════════════════════
# 素材源
# ═══════════════════════════════════════════


@router.get("/sources")
def list_sources():
    result = _proxy_get("/sources")
    if result is None:
        return {"sources": []}
    return result


@router.post("/sources")
async def add_source(request: Request):
    body = await request.json()
    result = _proxy_post("/sources", body)
    if result is None:
        return {"error": "Agent 不可达"}
    return result


@router.delete("/sources/{sid}")
def delete_source(sid: int):
    result = _proxy_delete(f"/sources/{sid}")
    if result is None:
        return {"ok": False}
    return result


@router.post("/sources/{sid}/toggle")
def toggle_source(sid: int):
    result = _proxy_post(f"/sources/{sid}/toggle")
    if result is None:
        return {"ok": False}
    return result


# ═══════════════════════════════════════════
# 文章
# ═══════════════════════════════════════════


@router.get("/articles")
def list_articles(limit: int = 50, kind: str | None = None):
    params = {"limit": limit}
    if kind:
        params["kind"] = kind
    result = _proxy_get("/articles", params=params)
    if result is None:
        return {"articles": []}
    return result


@router.get("/articles/{aid}")
def get_article(aid: int):
    result = _proxy_get(f"/articles/{aid}")
    if result is None:
        raise HTTPException(404, "文章不存在或 Agent 不可达")
    return result
