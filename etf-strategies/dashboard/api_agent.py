"""dashboard/api_agent.py — 拟人 Agent「小满」Web API 路由.

挂载：app.py 中 `app.include_router(api_agent.router)`（需认证，prefix /api/agent）。

路由：
  GET    /api/agent/status                  角色状态（进程存活/今日发文/LLM 配置/上线状态）
  POST   /api/agent/online                  小满上线
  POST   /api/agent/offline                 小满下线
  POST   /api/agent/sessions                新建会话
  GET    /api/agent/sessions                会话列表
  DELETE /api/agent/sessions/{sid}          删除会话
  POST   /api/agent/sessions/{sid}/messages 发送消息 → SSE 流式回复
  GET    /api/agent/articles                文章列表
  GET    /api/agent/articles/{aid}          文章详情
"""

import json

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from agent import db as agent_db, dsh_runner
from agent.channels import web
from agent.core import lifecycle
from dashboard.auth import get_current_user

router = APIRouter(prefix="/api/agent", dependencies=[Depends(get_current_user)])


async def _run_thread(fn):
    """把阻塞调用挪到线程池（SSE 生成器内不阻塞事件循环）。"""
    return await anyio.to_thread.run_sync(fn)


# ═══════════════════════════════════════════
# 状态
# ═══════════════════════════════════════════


def _state(
    alive: bool, attendance: str, current_task: dict | None, online: bool
) -> str:
    """机器可读状态枚举（桌宠/状态栏共用）：offline / leave / working / slack。"""
    if not online:
        return "offline"
    if not alive:
        return "offline"
    if attendance != "on":
        return "leave"
    if current_task:
        return "working"
    return "slack"


@router.get("/status")
def agent_status():
    """角色状态：进程存活（heartbeat 距今 <15min）、出勤（上班/请假）、当前任务、行为状态。"""
    hb_age = lifecycle.heartbeat_age_seconds()
    sched_status = None
    try:
        from dashboard import scheduler as sched

        sched_status = sched.engine.status()
    except Exception:
        pass
    attendance = (sched_status or {}).get("attendance") or "leave"
    current = (sched_status or {}).get("current_task")
    alive = hb_age is not None and hb_age < 60 * 15
    online = agent_db.meta_get("xiaoman_online") == "1"

    state_id = agent_db.meta_get("xiaoman_current_state") or "daydream"
    state_until = agent_db.meta_get("xiaoman_state_until")

    return {
        "alive": alive,
        "online": online,
        "state": _state(alive, attendance, current, online),
        "heartbeat_age_seconds": hb_age,
        "dsh_ready": dsh_runner.find_dsh_bin() is not None,
        "attendance": attendance,
        "current_task": current,
        "mood": _mood(attendance, current, online),
        "published_on": agent_db.meta_get("published_on"),
        "last_rss_fetch_at": agent_db.meta_get("last_rss_fetch_at"),
        "current_state": state_id,
        "current_state_label": lifecycle._state_label(state_id),
        "state_until": state_until,
    }


def _mood(attendance, current_task, online):
    """小满状态成语文案：请假中 / 摸鱼中 / 正在做XXX。"""
    if not online:
        return {"label": "未上线", "icon": "😴"}
    if attendance != "on":
        return {"label": "请假中", "icon": "🏖️"}
    if current_task:
        return {
            "label": f"正在做：{current_task.get('name', '任务')}",
            "icon": "💼",
            "task": current_task,
        }
    return {"label": "摸鱼中", "icon": "🐟"}


# ═══════════════════════════════════════════
# 上线/下线
# ═══════════════════════════════════════════


@router.post("/online")
def agent_online():
    """小满上线。"""
    agent_db.meta_set("xiaoman_online", "1")
    return {"ok": True, "online": True}


@router.post("/offline")
def agent_offline():
    """小满下线。"""
    agent_db.meta_set("xiaoman_online", "0")
    return {"ok": True, "online": False}


# ═══════════════════════════════════════════
# 会话
# ═══════════════════════════════════════════


@router.post("/sessions")
def create_session(body: dict):
    title = (body.get("title") or "").strip() or "新会话"
    sid = agent_db.session_create(title)
    return {"id": sid, "title": title}


@router.get("/sessions")
def list_sessions():
    return {"sessions": agent_db.session_list()}


@router.delete("/sessions/{sid}")
def delete_session(sid: int):
    if not agent_db.session_get(sid):
        raise HTTPException(404, "会话不存在")
    agent_db.session_delete(sid)
    return {"ok": True}


@router.get("/sessions/{sid}/messages")
def get_session_messages(sid: int):
    """会话历史消息（前端切换会话时加载）。"""
    if not agent_db.session_get(sid):
        raise HTTPException(404, "会话不存在")
    return {"messages": agent_db.messages_by_session(sid)}


# ═══════════════════════════════════════════
# 聊天（SSE 流式）
# ═══════════════════════════════════════════


@router.post("/sessions/{sid}/messages")
async def chat_message(sid: int, request: Request):
    body = await request.json()
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(400, "消息不能为空")
    if not agent_db.session_get(sid):
        raise HTTPException(404, "会话不存在")

    agent_db.message_add(sid, "user", content)
    task, knowledge = web.chat_task(sid, content)
    sources = [{"title": k["title"], "url": k["url"]} for k in knowledge]

    async def event_gen():
        try:
            status, out = await _run_thread(lambda: dsh_runner.run_task(task))
            if status != "success":
                raise dsh_runner.DshRunnerError(f"dsh {status}: {out}")
            agent_db.message_add(sid, "assistant", out, sources=sources)
            # dsh headless 非流式：一次事件返回全文，前端打字机渲染
            yield f"data: {json.dumps({'delta': out}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True, 'sources': sources}, ensure_ascii=False)}\n\n"
        except Exception as e:
            err = str(e)
            agent_db.message_add(sid, "assistant", f"（小满暂时无法回复：{err}）")
            yield f"data: {json.dumps({'error': err}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ═══════════════════════════════════════════
# 素材源（① 自定义站点 / 手动喂 URL）
# ═══════════════════════════════════════════


@router.get("/sources")
def list_sources():
    """素材源列表（含停用的；前端展示全部 + enabled 状态）。"""
    return {"sources": agent_db.source_list(enabled_only=False)}


@router.post("/sources")
def add_source(body: dict):
    """注册素材源。

    kind=website：常驻站点（每日采集 directive 逛站找文章）
    kind=manual：手动喂单条 URL（立即入库 agent_knowledge，参与发文素材）
    """
    name = (body.get("name") or "").strip()
    url = (body.get("url") or "").strip()
    kind = (body.get("kind") or "website").strip()
    note = (body.get("note") or "").strip() or None
    if not name or not url:
        raise HTTPException(400, "name 和 url 不能为空")
    if kind not in ("website", "manual"):
        raise HTTPException(400, "kind 必须是 website 或 manual")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "url 必须以 http(s):// 开头")

    sid = agent_db.source_add(name, url, kind=kind, note=note)
    if kind == "manual":
        # 手动喂：直接进素材池（source=manual），标记为待消费
        agent_db.knowledge_upsert("manual", name, url, note or "", None, None)
    return {"id": sid, "kind": kind}


@router.delete("/sources/{sid}")
def delete_source(sid: int):
    if not agent_db.source_get(sid):
        raise HTTPException(404, "素材源不存在")
    agent_db.source_delete(sid)
    return {"ok": True}


@router.post("/sources/{sid}/toggle")
def toggle_source(sid: int):
    """启用/停用站点源。"""
    s = agent_db.source_get(sid)
    if not s:
        raise HTTPException(404, "素材源不存在")
    agent_db.source_set_enabled(sid, 0 if s["enabled"] else 1)
    return {"ok": True, "enabled": 0 if s["enabled"] else 1}


# ═══════════════════════════════════════════
# 文章
# ═══════════════════════════════════════════


@router.get("/articles")
def list_articles(limit: int = 50, kind: str | None = None):
    """文章/动态列表；kind=article|post 过滤（省略返回全部，时间倒序）。"""
    if kind and kind not in ("article", "post"):
        raise HTTPException(400, "kind 必须是 article 或 post")
    return {
        "articles": [
            web.article_card(a) for a in agent_db.article_list(limit, kind=kind)
        ]
    }


@router.get("/articles/{aid}")
def get_article(aid: int):
    a = agent_db.article_get(aid)
    if not a:
        raise HTTPException(404, "文章不存在")
    return a
