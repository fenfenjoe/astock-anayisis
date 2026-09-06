"""dashboard/api_agent.py — 拟人 Agent「小满」Web API 路由.

挂载：app.py 中 `app.include_router(api_agent.router)`（需认证，prefix /api/agent）。

路由：
  GET    /api/agent/status                  角色状态（进程存活/今日发文/LLM 配置/上线状态/行为状态机）
  GET    /api/agent/profile                 认识小满（人设/兴趣/最近动态/最近在读/爱逛站点）
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

# 内置 RSS 热榜 → 可点击的人类站点首页（介绍页"爱逛的地方"用）
_SITE_HOME = {
    "cls": ("财联社·电报", "https://www.cls.cn/telegraph"),
    "wallstreetcn": ("华尔街见闻", "https://wallstreetcn.com/news/global"),
    "zhihu": ("知乎热榜", "https://www.zhihu.com/hot"),
    "xueqiu": ("雪球·今日话题", "https://xueqiu.com/today"),
}

router = APIRouter(prefix="/api/agent", dependencies=[Depends(get_current_user)])


async def _run_thread(fn):
    """把阻塞调用挪到线程池（SSE 生成器内不阻塞事件循环）。"""
    return await anyio.to_thread.run_sync(fn)


# ═══════════════════════════════════════════
# 状态
# ═══════════════════════════════════════════


def _state(
    alive: bool, attendance: str, current_task: dict | None, online: bool,
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
    online = agent_db.meta_get("xiaoman_online") == "1"

    state_id = agent_db.meta_get("xiaoman_current_state") or "daydream"
    state_until = agent_db.meta_get("xiaoman_state_until")
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
        "published_on": agent_db.meta_get("published_on")
        if agent_db.meta_get("published_on") == datetime.now().strftime("%Y-%m-%d")
        else None,
        "last_rss_fetch_at": agent_db.meta_get("last_rss_fetch_at"),
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


def _build_activities(limit=30):
    """小满"做过的事"（动作事件模型，只读活动台账，不含与你聊天）。

    行类型：
    - 事件：阅读（一次会话一条，备注读了哪几篇）/ 写文章（备注写了哪篇）——完成后关闭（有结束时间）；
    - 常驻状态段：空闲时她"正在摸鱼/发呆/打游戏…"，结束后关闭。
    进行中 = 台账里 ended_at 为 NULL 的那条（真实在执行/正停留在该状态）。

    tokens：真实 usage 需 dsh 层暴露后才能计量（用户已确认不估算）→ 一律 None。
    访问小红书 / 逛站等接入采集后，在这里追加对应事件来源即可。
    """
    acts = []
    for a in agent_db.activity_list(limit=120):
        raw = a.get("label") or a.get("kind") or "状态"
        parts = raw.split(" ", 1)
        emoji = parts[0] if len(parts) == 2 else raw
        name = parts[1].strip() if len(parts) == 2 else raw
        note = (a.get("note") or "").strip()
        acts.append({
            "kind": a.get("kind") or "episode",
            "label": emoji,                       # 列头只放图标
            "title": name,                        # 正文放名称（如"阅读"/"写文章"）
            "url": None,
            "at": a.get("started_at"),
            "ended": a.get("ended_at"),
            "meta": note or ("手动" if a.get("source") == "manual" else "自动"),
            "tokens": a.get("tokens"),
        })
    # 进行中（未结束）排最前，其余按开始时间倒序
    acts.sort(key=lambda x: (x.get("ended") is None, x.get("at") or ""), reverse=True)
    return acts[:limit]


@router.get("/profile")
def agent_profile():
    """认识小满页聚合数据：人设卡 + 最近动态 + 最近阅读 + 爱逛站点 + 兴趣爱好。"""
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

    # 爱逛的地方：内置热榜站点 + 自定义启用素材源
    feed_ids = {f["id"] for f in config.RSS_FEEDS}
    sites = [
        {"name": name, "url": url, "kind": "内置热榜"}
        for _id, (name, url) in _SITE_HOME.items()
        if _id in feed_ids
    ]
    try:
        for s in agent_db.source_list(enabled_only=True):
            sites.append({
                "name": s.get("name"),
                "url": s.get("url"),
                "kind": "常驻站点" if s.get("kind") == "website" else "单篇",
            })
    except Exception:
        pass

    # 兴趣：知识域 + 状态机里的摸鱼爱好（排除认真态/睡眠）
    interests = ["A股", "ETF", "宏观经济", "国际时事", "产业趋势", "财经大V观点"]
    hobbies = [
        label for sid, label in lifecycle._STATE_LABELS.items()
        if sid not in (_PRODUCTIVE_STATES | {"sleep", "nap"})
    ][:8]

    return {
        "persona_md": persona_md,
        "basic": _persona_basic(persona_md),      # 侧栏「关于我」精简版
        "activity": _build_activities(),          # 右侧「做过的事」（token 待真实 usage）
        "recent_articles": recent_articles,
        "recent_reads": recent_reads,
        "sites": sites,
        "interests": interests,
        "hobbies": hobbies,
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
    # 严格零本地：memory 模式下立刻把这条活动记录回传 TOS（重启/下次登录可见）
    try:
        if agent_db.USE_MEMORY:
            agent_db.cloud_backup()
    except Exception:
        pass
    return {"ok": True, "state": sw}


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
                    sid, "assistant", m,
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
