"""dashboard/api_agent.py — 拟人 Agent「小满」Web API 路由.

挂载：app.py 中 `app.include_router(api_agent.router)`（需认证，prefix /api/agent）。

路由：
  GET    /api/agent/status                  角色状态（进程存活/今日发文/LLM 配置/上线状态/行为状态机）
  GET    /api/agent/profile                 认识小满（人设/兴趣/最近动态/最近在读/爱逛的地方）
  POST   /api/agent/online                  小满上线
  POST   /api/agent/offline                 小满下线
  POST   /api/agent/sessions                新建会话
  GET    /api/agent/sessions                会话列表
  DELETE /api/agent/sessions/{sid}          删除会话
  POST   /api/agent/sessions/{sid}/messages 发送消息 → SSE 流式回复
  GET    /api/agent/notices                 提示/待办列表 + 未读数
  POST   /api/agent/notices/{id}/read       标记已读
  POST   /api/agent/notices/read-all        全部标记已读
  POST   /api/agent/notices/{id}/reply      待办回复（回调 dispatch）
  POST   /api/agent/notices/{id}/dismiss    忽略（视为已读）
  GET    /api/agent/articles                文章列表
  GET    /api/agent/articles/{aid}          文章详情
"""

import json
from datetime import datetime

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from agent import config, db as agent_db, dsh_runner
from agent.channels import web
from agent.core import lifecycle
from dashboard.auth import get_current_user

# 状态机中属于"认真学习/工作"的状态（桌宠工作姿态 + 状态 pill 工作色）；其余为摸鱼活动
_PRODUCTIVE_STATES = {"reading", "writing", "thinking"}

router = APIRouter(prefix="/api/agent", dependencies=[Depends(get_current_user)])


async def _run_thread(fn):
    """把阻塞调用挪到线程池（SSE 生成器内不阻塞事件循环）。"""
    return await anyio.to_thread.run_sync(fn)


# ═══════════════════════════════════════════
# 状态
# ═══════════════════════════════════════════


def _state(
    alive: bool,
    attendance: str,
    current_task: dict | None,
    online: bool,
    state_id: str | None = None,
) -> str:
    """机器可读状态枚举（桌宠/状态栏共用）：offline / leave / working / slack。

    working 有两类：调度器在跑定时任务，或小满状态机正处于学习/写作/思考等
    "认真"状态（reading/writing/thinking）；其余摸鱼活动归 slack。
    """
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

    # 2026-09-08 优化：批量一次取全部 metadata key（原逐个 meta_get = N 次云往返）
    meta = agent_db.meta_get_many([
        "xiaoman_online", "xiaoman_current_state", "xiaoman_state_until",
        "published_on", "last_rss_fetch_at",
    ])
    online = meta.get("xiaoman_online") == "1"
    state_id = meta.get("xiaoman_current_state") or "daydream"
    state_until = meta.get("xiaoman_state_until")
    state_label = lifecycle._state_label(state_id)

    return {
        "alive": alive,
        "online": online,
        "state": _state(alive, attendance, current, online, state_id),
        "heartbeat_age_seconds": hb_age,
        "dsh_ready": dsh_runner.find_dsh_bin() is not None,
        "attendance": attendance,
        "current_task": current,
        "mood": _mood(attendance, current, online, state_id, state_label),
        # 仅当最后发文日=今天时才返回该字段，否则置空，避免前端误显示"今日已发文"
        "published_on": meta.get("published_on")
        if meta.get("published_on") == datetime.now().strftime("%Y-%m-%d")
        else None,
        "last_rss_fetch_at": meta.get("last_rss_fetch_at"),
        "current_state": state_id,
        "current_state_label": state_label,
        "state_until": state_until,
    }


def _mood(attendance, current_task, online, state_id=None, state_label=None):
    """小满状态成语文案：未上线 / 请假中 / 正在做XXX / 状态机当前活动。

    没有调度任务时，不再笼统显示"摸鱼中"，而是反映行为状态机的实时状态
    （📖 阅读中 / 🎮 打游戏中 / 🌙 发呆中…），让"她在干嘛"可见。
    """
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
# 介绍页（人设 / 做过的事 / 爱好 / 爱逛的地方）
# ═══════════════════════════════════════════

_ACT_LABEL = {
    "read": "📖 阅读",
    "article": "📝 写文章",
    "post": "✍️ 发动态",
}


def _persona_basic(persona_md):
    """解析人设卡「## 基本」节 → [{k, v}]（认识页侧栏"关于我"只用这块）。"""
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
    """小满"做过的事"（动作事件模型，只读活动台账）。

    date_filter: 可选，格式 YYYY-MM-DD，按开始日期筛选。
    offset: 分页偏移量。
    """
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


@router.get("/profile")
def agent_profile():
    """认识小满页聚合数据：人设卡 + 最近动态 + 最近阅读 + 爱逛的地方 + 兴趣爱好。"""
    # 人设卡 markdown（personas/xiaoman/persona.md）
    persona_md = ""
    try:
        persona_file = config.PERSONAS_DIR / config.PERSONA_ID / "persona.md"
        persona_md = persona_file.read_text(encoding="utf-8")
    except Exception:
        persona_md = ""

    # 最近动态（文章 / 微博式短动态）
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

    # 最近在读（已读且留下记忆的素材）
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

    # 爱逛的地方：合并进 social_platforms（含 RSS 源财联社/华尔街见闻/知乎/雪球，见下）

    # 兴趣：知识域 + 状态机里的摸鱼爱好（排除认真态/睡眠；含逛微博/小红书/知乎/雪球）
    interests = ["A股", "ETF", "宏观经济", "国际时事", "产业趋势", "财经大V观点"]
    hobbies = [
        label
        for sid, label in lifecycle._STATE_LABELS.items()
        if sid not in (_PRODUCTIVE_STATES | {"sleep", "nap"})
    ][:15]

    # 爱逛的地方（方案 v1.10 §9.4 + 2026-09 合并）：配置 + 可访问性缓存
    # （服务器缓存，前端不实时探测；RSS 源可达=能拉到条目，Cookie 源可达=探测通过，X 固定置灰）
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
        # 探测模块/缓存不可用 → 全部保守置灰
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
        "basic": _persona_basic(persona_md),  # 侧栏「关于我」精简版
        "activity": _build_activities(),  # 右侧「做过的事」（精选展示，不分页）
        "recent_articles": recent_articles,
        "recent_reads": recent_reads,
        "social_platforms": social_platforms,
        "interests": interests,
        "hobbies": hobbies,
    }


@router.get("/activities")
def agent_activities(date: str = "", page: int = 1, page_size: int = 20):
    """小满「做过的事」分页查询，支持按日期筛选。

    date: 可选，格式 YYYY-MM-DD，筛选当天开始的活动。
    page: 页码，从 1 开始。
    page_size: 每页条数，默认 20，上限 100。
    """
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


@router.post("/state")
def agent_set_state(body: dict):
    """手动切换小满状态：random=随机 / reading=阅读 / slack=摸鱼。

    与自动状态机走同一个 switch_state：先结束上一条活动（记结束时间；token 为真实值，
    暂无计量通道 → 未计量），再为当前状态开一条新活动记录。
    """
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
# 提示/待办（agent_notices）：REQ-002 聊天页「📌 提示与待办」
# ═══════════════════════════════════════════


def _notice_card(n):
    """列表项展示数据（todo_data 已由 _row_dict 解析为 dict）。"""
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


@router.get("/notices")
def list_notices(page: int = 1, page_size: int = 5):
    """提示/待办列表（未处理在前、已处理在后；组内新→旧）+ 未读数 + 分页信息。

    page: 页码（从 1 开始）；page_size: 每页条数（默认 5，防堆积 + 面板不出现滚动条）。
    """
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


@router.get("/notices/unread-count")
def notices_unread_count():
    return {"unread_count": agent_db.notice_unread_count()}


@router.post("/notices/{nid}/read")
def notice_read(nid: int):
    n = agent_db.notice_get(nid)
    if not n:
        raise HTTPException(404, "提示/待办不存在")
    agent_db.notice_mark_read(nid)
    return {"ok": True, "unread_count": agent_db.notice_unread_count()}


@router.post("/notices/read-all")
def notice_read_all():
    agent_db.notice_mark_all_read()
    return {"ok": True, "unread_count": 0}


@router.post("/notices/{nid}/dismiss")
def notice_dismiss(nid: int):
    n = agent_db.notice_get(nid)
    if not n:
        raise HTTPException(404, "提示/待办不存在")
    agent_db.notice_mark_read(nid)  # 忽略视为已读
    agent_db.notice_set_status(nid, "dismissed")
    return {"ok": True, "unread_count": agent_db.notice_unread_count()}


@router.post("/notices/{nid}/reply")
def notice_reply(nid: int, body: dict):
    """待办回复（状态机：open → replied → done / 失败回 open）。

    回调成功后：status=done，result=小满处理成功的回复（已读）。
    回调失败：status 重置为 open（可重试），result=小满的失败原因，read_at 清空
    （重新计未读 → 小红点重新提醒）；reply 保留用户回复。
    """
    from agent.core import notices as notices_mod

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
            # dsh 输出契约：一条消息 = 一行（由小满自己决定拆几条，前端不再切文本）。
            # 逐条落库（每条 assistant 消息 = 一个气泡），再逐条 SSE 下发；来源挂在最后一条上。
            msgs = [ln.strip() for ln in out.splitlines() if ln.strip()]
            last = len(msgs) - 1
            for i, m in enumerate(msgs):
                agent_db.message_add(
                    sid,
                    "assistant",
                    m,
                    sources=sources if i == last else [],
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
