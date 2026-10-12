"""agent/api.py — 小满 Agent 内嵌 HTTP API（独立于 Dashboard 运行）。

Agent 进程内嵌 FastAPI，供 Dashboard 远程调用。端口由 AGENT_API_PORT 环境变量控制（默认 8020）。
认证：AGENT_API_KEY 环境变量，Dashboard 请求时带 X-Api-Key 头。
"""

import json
import os
from datetime import datetime

import anyio
import uvicorn
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader

from agent import config, db as agent_db, dsh_runner
from agent.channels import web
from agent.core import lifecycle

API_KEY = os.environ.get("AGENT_API_KEY", "").strip()
api_key_header = APIKeyHeader(name="X-Api-Key", auto_error=False)

_PRODUCTIVE_STATES = {"reading", "writing", "thinking"}


def verify_api_key(key: str | None = Depends(api_key_header)):
    if not API_KEY:
        return
    if key != API_KEY:
        raise HTTPException(401, "Invalid API Key")


app = FastAPI(title="小满 Agent API", version="1.0")
protected = Depends(verify_api_key)


async def _run_thread(fn):
    return await anyio.to_thread.run_sync(fn)


def _state(alive, attendance, current_task, online, state_id=None):
    if not online:
        return "offline"
    if not alive:
        return "offline"
    if attendance != "on":
        return "leave"
    if current_task:
        return "working"
    if state_id in _PRODUCTIVE_STATES:
        return "working"
    return "slack"


def _mood(attendance, current_task, online, state_id=None, state_label=None):
    if not online:
        return {"label": "未上线", "icon": "😴"}
    if attendance != "on":
        return {"label": "请假中", "icon": "🏖️"}
    if current_task:
        return {
            "label": f"正在做：{current_task.get('name', '任务')}",
            "icon": "💼",
            "task": current_task,
            "busy": True,
        }
    if state_label:
        return {
            "label": f"{state_label}中",
            "icon": "",
            "state": state_id,
            "busy": state_id in _PRODUCTIVE_STATES,
        }
    return {"label": "摸鱼中", "icon": "🐟"}


# ═══════════════════════════════════════════
# 状态
# ═══════════════════════════════════════════


@app.get("/api/agent/status", dependencies=[protected])
def agent_status():
    hb_age = lifecycle.heartbeat_age_seconds()
    alive = hb_age is not None and hb_age < 60 * 15

    meta = agent_db.meta_get_many(
        [
            "xiaoman_online",
            "xiaoman_current_state",
            "xiaoman_state_until",
            "published_on",
            "last_rss_fetch_at",
        ]
    )
    online = meta.get("xiaoman_online") == "1"
    state_id = meta.get("xiaoman_current_state") or "daydream"
    state_until = meta.get("xiaoman_state_until")
    state_label = lifecycle._state_label(state_id)

    # 定时任务进行中 → current_task 非空 → state=working（BUG-FIX 2026-09-15：
    # 原来硬编码 current_task=None，调度任务执行时桌宠永远不显示"工作中"）。
    try:
        from agent.core import scheduler_agent

        current_task = scheduler_agent.current_task() or None
    except Exception:
        current_task = None

    return {
        "alive": alive,
        "online": online,
        "state": _state(alive, "on", current_task, online, state_id),
        "heartbeat_age_seconds": hb_age,
        "dsh_ready": dsh_runner.find_dsh_bin() is not None,
        "attendance": "on",
        "current_task": current_task,
        "mood": _mood("on", current_task, online, state_id, state_label),
        "published_on": meta.get("published_on")
        if meta.get("published_on") == datetime.now().strftime("%Y-%m-%d")
        else None,
        "last_rss_fetch_at": meta.get("last_rss_fetch_at"),
        "current_state": state_id,
        "current_state_label": state_label,
        "state_until": state_until,
    }


# ═══════════════════════════════════════════
# 介绍页
# ═══════════════════════════════════════════

_ACT_LABEL = {"read": "📖 阅读", "article": "📝 写文章", "post": "✍️ 发动态"}

# 「关于我」侧栏文案（2026-10 精简：100~200 字，小满第一人称，不复刻人设卡字段）
ABOUT_ME = (
    "我是小满，名字来自二十四节气「小满胜万全」——懂知足，但该认真时很认真。"
    "元气满满的财经学习博主：聊 A 股、看 ETF、琢磨宏观与产业趋势，"
    "把涨跌讲成人话，把数据聊成故事。平时爱撸猫、喝奶茶、追剧，"
    "盘后认真复盘，是你们的云上朋友～"
)


def _persona_basic(persona_md):
    out = []
    capture = False
    for raw in (persona_md or "").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            capture = line == "## 基本"
            continue
        if not capture or not line.startswith("-"):
            continue
        item = line.lstrip("- ").strip()
        k, sep, v = item.partition("：")
        if not sep:
            k, sep, v = item.partition(":")
        if not sep:
            continue
        k = k.strip().strip("*").strip()
        v = v.strip().strip("*").strip()
        if k and v:
            out.append({"k": k, "v": v})
    return out


def _build_activities(limit=30, date_filter=None, offset=0):
    acts = []
    for a in agent_db.activity_list(
        limit=limit, date_filter=date_filter, offset=offset
    ):
        raw = a.get("label") or a.get("kind") or "状态"
        parts = raw.split(" ", 1)
        emoji = parts[0] if len(parts) == 2 else raw
        name = parts[1].strip() if len(parts) == 2 else raw
        note = (a.get("note") or "").strip()
        acts.append(
            {
                "kind": a.get("kind") or "episode",
                "label": emoji,
                "title": name,
                "url": None,
                "at": a.get("started_at"),
                "ended": a.get("ended_at"),
                "meta": note or ("手动" if a.get("source") == "manual" else "自动"),
                "tokens": a.get("tokens"),
            }
        )
    return acts


@app.get("/api/agent/profile", dependencies=[protected])
def agent_profile():
    persona_md = ""
    try:
        persona_file = config.PERSONAS_DIR / config.PERSONA_ID / "persona.md"
        persona_md = persona_file.read_text(encoding="utf-8")
    except Exception:
        persona_md = ""

    recent_articles = [
        {
            "id": a.get("id"),
            "title": a.get("title") or (a.get("content") or "")[:24],
            "kind": a.get("kind"),
            "published_at": a.get("published_at"),
            "summary": a.get("summary"),
        }
        for a in agent_db.article_list(limit=6)
    ]

    recent_reads = [
        {
            "title": k.get("title"),
            "url": k.get("url"),
            "source": k.get("source"),
            "read_at": k.get("read_at"),
            "viewpoint": k.get("viewpoint"),
        }
        for k in agent_db.knowledge_with_memory(limit=8)
    ]

    interests = ["A股", "ETF", "宏观经济", "国际时事", "产业趋势", "财经大V观点"]
    hobbies = [
        label
        for sid, label in lifecycle._STATE_LABELS.items()
        if sid not in (_PRODUCTIVE_STATES | {"sleep", "nap"})
    ][:15]

    try:
        from agent.core import reachability as reach_mod

        reach_cache = reach_mod.get_reachability()
        social_platforms = []
        for p in config.SOCIAL_PLATFORMS:
            r = reach_cache.get(p["id"], {})
            social_platforms.append(
                {
                    "id": p["id"],
                    "name": p["name"],
                    "url": p["url"],
                    "icon": p["icon"],
                    "needs_cookie": p.get("needs_cookie", False),
                    "playable": p.get("playable", False),
                    "reachable": bool(r.get("reachable")),
                    "checked_at": r.get("checked_at"),
                    "reason": r.get("reason"),
                }
            )
    except Exception:
        social_platforms = [
            {
                "id": p["id"],
                "name": p["name"],
                "url": p["url"],
                "icon": p["icon"],
                "needs_cookie": p.get("needs_cookie", False),
                "playable": p.get("playable", False),
                "reachable": False,
                "checked_at": None,
                "reason": "缓存不可用",
            }
            for p in config.SOCIAL_PLATFORMS
        ]

    return {
        "persona_md": persona_md,
        "about_me": ABOUT_ME,
        "basic": _persona_basic(persona_md),
        "activity": _build_activities(),
        "recent_articles": recent_articles,
        "recent_reads": recent_reads,
        "social_platforms": social_platforms,
        "interests": interests,
        "hobbies": hobbies,
    }


@app.get("/api/agent/activities", dependencies=[protected])
def agent_activities(date: str = "", page: int = 1, page_size: int = 20):
    page_size = min(max(page_size, 1), 100)
    date_filter = date.strip() if date else None
    offset = max(page - 1, 0) * page_size
    total = agent_db.activity_count(date_filter=date_filter)
    activities = _build_activities(
        limit=page_size, date_filter=date_filter, offset=offset
    )
    return {
        "activities": activities,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max((total + page_size - 1) // page_size, 0),
    }


# ═══════════════════════════════════════════
# 上线/下线
# ═══════════════════════════════════════════


@app.post("/api/agent/online", dependencies=[protected])
def agent_online():
    agent_db.meta_set("xiaoman_online", "1")
    return {"ok": True, "online": True}


@app.post("/api/agent/offline", dependencies=[protected])
def agent_offline():
    agent_db.meta_set("xiaoman_online", "0")
    return {"ok": True, "online": False}


@app.post("/api/agent/state", dependencies=[protected])
async def agent_set_state(request: Request):
    body = await request.json()
    action = (body.get("action") or "").strip().lower()
    now = datetime.now()
    from agent.core import behavior as behavior_mod

    if action == "random":
        target = behavior_mod.pick_random_state(now=now)
    elif action == "reading":
        target = behavior_mod.pick_manual_reading(now=now)
    elif action == "slack":
        target = behavior_mod.pick_manual_slack(now=now)
    else:
        raise HTTPException(400, "action 必须是 random | reading | slack 之一")
    sw = behavior_mod.switch_state(target, now=now, source="manual")
    return {"ok": True, "state": sw}


# ═══════════════════════════════════════════
# 提示/待办
# ═══════════════════════════════════════════


def _notice_card(n):
    return {
        "id": n["id"],
        "kind": n["kind"],
        "status": n["status"],
        "title": n["title"],
        "content": n["content"],
        "todo_type": n.get("todo_type"),
        "todo_data": n.get("todo_data") or {},
        "reply": n.get("reply"),
        "reply_at": n.get("reply_at"),
        "result": n.get("result"),
        "read": n.get("read_at") is not None,
        "source": n.get("source"),
        "created_at": n.get("created_at"),
    }


@app.get("/api/agent/notices", dependencies=[protected])
def list_notices(page: int = 1, page_size: int = 5):
    page = max(page, 1)
    page_size = max(min(page_size, 50), 1)
    total = agent_db.notice_count()
    notices = [
        _notice_card(n)
        for n in agent_db.notice_list(limit=page_size, offset=(page - 1) * page_size)
    ]
    return {
        "notices": notices,
        "unread_count": agent_db.notice_unread_count(),
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max((total + page_size - 1) // page_size, 0),
    }


@app.get("/api/agent/notices/unread-count", dependencies=[protected])
def notices_unread_count():
    return {"unread_count": agent_db.notice_unread_count()}


@app.post("/api/agent/notices/{nid}/read", dependencies=[protected])
def notice_read(nid: int):
    n = agent_db.notice_get(nid)
    if not n:
        raise HTTPException(404, "提示/待办不存在")
    agent_db.notice_mark_read(nid)
    return {"ok": True, "unread_count": agent_db.notice_unread_count()}


@app.post("/api/agent/notices/read-all", dependencies=[protected])
def notice_read_all():
    agent_db.notice_mark_all_read()
    return {"ok": True, "unread_count": 0}


@app.post("/api/agent/notices/{nid}/dismiss", dependencies=[protected])
def notice_dismiss(nid: int):
    n = agent_db.notice_get(nid)
    if not n:
        raise HTTPException(404, "提示/待办不存在")
    agent_db.notice_mark_read(nid)
    agent_db.notice_set_status(nid, "dismissed")
    return {"ok": True, "unread_count": agent_db.notice_unread_count()}


@app.post("/api/agent/notices/{nid}/reply", dependencies=[protected])
async def notice_reply(nid: int, request: Request):
    from agent.core import notices as notices_mod

    body = await request.json()
    n = agent_db.notice_get(nid)
    if not n:
        raise HTTPException(404, "提示/待办不存在")
    reply = (body.get("reply") or "").strip()
    if not reply:
        raise HTTPException(400, "回复不能为空")
    res = notices_mod.dispatch_todo_reply(n, reply)
    ok = bool(res.get("ok"))
    agent_db.notice_reply(nid, reply, result=res.get("message"), success=ok)
    updated = agent_db.notice_get(nid)
    return {
        "ok": ok,
        "message": res.get("message"),
        "notice": _notice_card(updated),
        "unread_count": agent_db.notice_unread_count(),
    }


@app.post("/api/agent/reachability/refresh", dependencies=[protected])
def reachability_refresh():
    """「爱逛的地方」刷新：全量重判定各平台可达性（云库 Cookie → 本机浏览器 → 待办）。"""
    from agent.core import reachability as reach_mod

    results = reach_mod.refresh_reachability()
    n_ok = sum(1 for r in results if r.get("reachable"))
    return {"ok": True, "results": results, "reachable_count": n_ok, "total": len(results)}


@app.post("/api/agent/browser/open-login", dependencies=[protected])
async def browser_open_login(request: Request):
    """打开小满专属浏览器窗口（headed）供用户登录平台。body: {"platform_id": "xhs"}。"""
    from agent.core import browser_cookies

    body = await request.json()
    pid = (body or {}).get("platform_id") or ""
    platform = next((p for p in config.SOCIAL_PLATFORMS if p["id"] == pid), None)
    if not platform:
        raise HTTPException(400, f"未知平台: {pid}")
    return browser_cookies.open_login_window(platform)


# ═══════════════════════════════════════════
# 会话
# ═══════════════════════════════════════════


@app.post("/api/agent/sessions", dependencies=[protected])
async def create_session(request: Request):
    body = await request.json()
    title = (body.get("title") or "").strip() or "新会话"
    sid = agent_db.session_create(title)
    return {"id": sid, "title": title}


@app.get("/api/agent/sessions", dependencies=[protected])
def list_sessions():
    return {"sessions": agent_db.session_list()}


@app.delete("/api/agent/sessions/{sid}", dependencies=[protected])
def delete_session(sid: int):
    if not agent_db.session_get(sid):
        raise HTTPException(404, "会话不存在")
    agent_db.session_delete(sid)
    return {"ok": True}


@app.get("/api/agent/sessions/{sid}/messages", dependencies=[protected])
def get_session_messages(sid: int):
    if not agent_db.session_get(sid):
        raise HTTPException(404, "会话不存在")
    return {"messages": agent_db.messages_by_session(sid)}


@app.post("/api/agent/sessions/{sid}/messages", dependencies=[protected])
async def chat_message(sid: int, request: Request):
    body = await request.json()
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(400, "消息不能为空")
    if not agent_db.session_get(sid):
        raise HTTPException(404, "会话不存在")

    if agent_db.meta_get("xiaoman_online") != "1":
        raise HTTPException(
            429,
            "小满现在已下班了，暂时无法回复~ 请在页面顶部点击【让小满上线】后再来聊天吧 💤",
        )

    agent_db.message_add(sid, "user", content)
    task, knowledge = web.chat_task(sid, content)
    sources = [{"title": k["title"], "url": k["url"]} for k in knowledge]

    async def event_gen():
        try:
            status, out = await _run_thread(lambda: dsh_runner.run_task(task))
            if status != "success":
                raise dsh_runner.DshRunnerError(f"dsh {status}: {out}")
            msgs = [ln.strip() for ln in out.splitlines() if ln.strip()]
            last = len(msgs) - 1
            for i, m in enumerate(msgs):
                agent_db.message_add(
                    sid, "assistant", m, sources=sources if i == last else []
                )
            for m in msgs:
                yield f"data: {json.dumps({'delta': m}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'done': True, 'sources': sources}, ensure_ascii=False)}\n\n"
        except Exception as e:
            err = str(e)
            agent_db.message_add(sid, "assistant", f"（小满暂时无法回复：{err}）")
            yield f"data: {json.dumps({'error': err}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ═══════════════════════════════════════════
# 素材源
# ═══════════════════════════════════════════


@app.get("/api/agent/sources", dependencies=[protected])
def list_sources():
    return {"sources": agent_db.source_list(enabled_only=False)}


@app.post("/api/agent/sources", dependencies=[protected])
async def add_source(request: Request):
    body = await request.json()
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
        agent_db.knowledge_upsert("manual", name, url, note or "", None, None)
    return {"id": sid, "kind": kind}


@app.delete("/api/agent/sources/{sid}", dependencies=[protected])
def delete_source(sid: int):
    if not agent_db.source_get(sid):
        raise HTTPException(404, "素材源不存在")
    agent_db.source_delete(sid)
    return {"ok": True}


@app.post("/api/agent/sources/{sid}/toggle", dependencies=[protected])
def toggle_source(sid: int):
    s = agent_db.source_get(sid)
    if not s:
        raise HTTPException(404, "素材源不存在")
    agent_db.source_set_enabled(sid, 0 if s["enabled"] else 1)
    return {"ok": True, "enabled": 0 if s["enabled"] else 1}


# ═══════════════════════════════════════════
# 文章
# ═══════════════════════════════════════════


@app.get("/api/agent/articles", dependencies=[protected])
def list_articles(limit: int = 50, kind: str | None = None):
    if kind and kind not in ("article", "post"):
        raise HTTPException(400, "kind 必须是 article 或 post")
    return {
        "articles": [
            web.article_card(a) for a in agent_db.article_list(limit, kind=kind)
        ]
    }


@app.get("/api/agent/articles/{aid}", dependencies=[protected])
def get_article(aid: int):
    a = agent_db.article_get(aid)
    if not a:
        raise HTTPException(404, "文章不存在")
    return a


# ═══════════════════════════════════════════
# 调度器任务执行（供 Dashboard 通知 Agent 执行）
# ═══════════════════════════════════════════


@app.post("/api/agent/scheduler/run/{task_id}", dependencies=[protected])
async def scheduler_run_task(task_id: str, request: Request):
    body = await request.json() if await request.body() else {}
    trigger = (body.get("trigger") or "manual").strip()
    from agent.core import scheduler_agent

    result = scheduler_agent.execute_task(task_id, trigger=trigger)
    return result


@app.post("/api/agent/scheduler/stop/{task_id}", dependencies=[protected])
def scheduler_stop_task(task_id: str):
    """停止正在执行的任务（用户从工作日志点击「停止」→ Dashboard → Agent）。"""
    from agent.core import scheduler_agent

    return scheduler_agent.stop_task(task_id)


@app.get("/api/agent/scheduler/status", dependencies=[protected])
def scheduler_status():
    from agent.core import scheduler_agent

    return scheduler_agent.status()


def run_api(port: int = 8020):
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
