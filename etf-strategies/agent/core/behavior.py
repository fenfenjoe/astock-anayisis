"""behavior.py — 行为引擎：发文调度 / 状态机 / 阅读执行.

全部纯函数或依赖注入（llm_fn / db），不直接联网，便于测试。
编排入口：run_publish_pipeline()（每日发文）、pick_random_state()（状态决策）、
execute_reading()（阅读 Prompt 执行）。
LLM 生成统一走 dsh（dsh --profile xiaoman），凭据由 dsh 管理。
"""

import json as _json
import random
import shutil
from datetime import datetime, timedelta

from agent import config, db as agent_db, dsh_runner
from agent.core import persona


def dsh_task_llm(task):
    """默认 LLM 实现：dsh headless 执行任务 → 最终回复文本。"""
    status, out = dsh_runner.run_task(task)
    if status != "success":
        raise dsh_runner.DshRunnerError(f"dsh {status}: {out}")
    return out


def should_publish(today, published_on=None, hour=None, minute=None):
    """是否到发文时机：当日未发 + 已过目标时刻（PUBLISH_HOUR:MINUTE）。"""
    if published_on == today:
        return {"publish": False, "reason": "already_published"}
    h = hour if hour is not None else config.PUBLISH_HOUR
    m = minute if minute is not None else config.PUBLISH_MINUTE
    if (h, m) < (config.PUBLISH_HOUR, config.PUBLISH_MINUTE):
        return {"publish": False, "reason": "before_time"}
    return {"publish": True, "reason": "due"}


def pick_material(items, min_items=None):
    """素材是否够发文（至少 MIN_TOPIC_ITEMS 条）。返回 {"ready", "items"}。"""
    min_items = min_items or config.MIN_TOPIC_ITEMS
    items = list(items)
    if len(items) < min_items:
        return {"ready": False, "items": []}
    return {"ready": True, "items": items}


def validate_article(text, min_len=50):
    """草稿自检：合规动词（D6）+ 长度。返回 {"ok", "issues"}。"""
    issues = []
    s = persona.sanitize_output(text)
    if not s["ok"]:
        issues.append(f"含禁止买卖指令词: {s['violations']}")
    if len(text.strip()) < min_len:
        issues.append("正文过短")
    return {"ok": not issues, "issues": issues}


def _parse_title(content):
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("标题："):
            return line[len("标题：") :].strip()
    return ""


def compose_article(materials, llm_fn=None, db=None, persona_id=config.PERSONA_ID):
    """组装素材 → dsh 任务（人设由 xiaoman profile 注入）→ 草稿 → 自检 + 免责。

    llm_fn(task: str) -> str（依赖注入；默认 dsh_task_llm）。
    返回 {"title", "content", "ok", "issues"}。
    """
    llm_fn = llm_fn or dsh_task_llm
    db = db or agent_db
    material_lines = [
        f"- [{m.get('source')}] {m.get('title')} ({m.get('url')})" for m in materials
    ]
    material_text = "\n".join(material_lines) or "（今日暂无素材）"
    task = (
        "你是小满，请基于以下今日学习素材，写一篇 300 字左右的财经学习笔记。\n"
        "要求：\n"
        "1. 第一行输出「标题：xxx」；\n"
        "2. 转述素材要点并给出你自己的看法（要有独立见解，可质疑）；\n"
        "3. 区分事实与观点；素材链接以来源形式附在文末；\n"
        "4. 不整篇复制素材原文；\n"
        "5. 结尾附「不构成投资建议」。\n\n"
        f"今日素材：\n{material_text}"
    )
    content = llm_fn(task)
    content = persona.append_disclaimer(content)
    title = _parse_title(content)
    if not title:
        date_part = (
            materials[0]["published_at"][:10]
            if materials and materials[0].get("published_at")
            else ""
        )
        title = f"学习笔记 {date_part}".strip() or "学习笔记"
    body_lines = [
        ln for ln in content.splitlines() if not ln.strip().startswith("标题：")
    ]
    body = "\n".join(body_lines).strip()
    check = validate_article(body)
    return {
        "title": title,
        "content": body,
        "ok": check["ok"],
        "issues": check["issues"],
    }


def run_publish_pipeline(today, now=None, llm_fn=None, db=None):
    """每日发文编排：时机 → 素材 → 草稿 → 入库 → 消费素材 → 标记已发。

    返回 {"published": bool, "reason": str, "article_id": int|None}。
    """
    db = db or agent_db
    published_on = db.meta_get("published_on")
    h, m = now or (config.PUBLISH_HOUR, config.PUBLISH_MINUTE + 1)
    gate = should_publish(today, published_on, hour=h, minute=m)
    if not gate["publish"]:
        return {"published": False, "reason": gate["reason"], "article_id": None}

    materials = db.knowledge_unconsumed(limit=20)
    pick = pick_material(materials)
    if not pick["ready"]:
        return {
            "published": False,
            "reason": "material_insufficient",
            "article_id": None,
        }

    # "写文章" = 一条独立事件：开始 compose 时开记录，结束（含失败）时关闭
    start_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ev_id = db.activity_start("writing", "📝 写文章", start_str, source="auto")

    def _finish_writing(title=None, note=None):
        db.activity_close_open(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        db.activity_set_note(ev_id, note or (f"标题：{title}" if title else ""))

    try:
        art = compose_article(pick["items"], llm_fn=llm_fn, db=db)
    except Exception as e:
        _finish_writing(note=f"写文异常：{e}")
        raise
    if not art["ok"]:
        _finish_writing(title=art.get("title") or "", note=f"未通过校验：{art['issues']}")
        return {
            "published": False,
            "reason": f"validation: {art['issues']}",
            "article_id": None,
        }

    sources = [
        {"title": m["title"], "url": m["url"], "source": m["source"]}
        for m in pick["items"]
    ]
    topics = ["学习笔记"]
    aid = db.article_create(
        art["title"],
        art["content"][:120],
        art["content"],
        topics=topics,
        sources=sources,
    )
    db.opinion_add(topics[0], art["content"], article_id=aid)
    for m in pick["items"]:
        db.knowledge_mark_consumed(m["id"])
    db.meta_set("published_on", today)
    _finish_writing(title=art.get("title") or "", note=f"完成：{art.get('title') or ''}")
    return {"published": True, "reason": "done", "article_id": aid}


# ═══════════════════════════════════════════
# 行为状态机
# ═══════════════════════════════════════════


def load_behaviors():
    """加载行为池 → Python dict。"""
    raw = config.BEHAVIORS_FILE.read_text(encoding="utf-8")
    return _json.loads(raw)


def load_reading_prompt():
    """加载阅读 Prompt 模板。"""
    return config.READING_PROMPT_FILE.read_text(encoding="utf-8")


def pick_random_state(now=None, db=None):
    """硬编码权重随机选状态。

    根据时间修正权重（晚给 sleep/gaming 加权）、未读数量给 reading 加权。

    返回 {"id","label","require_llm","duration_minutes","until_iso"}。
    """
    now = now or datetime.now()
    db = db or agent_db
    pool = load_behaviors()
    behaviors = pool["behaviors"]
    time_mods = pool.get("time_modifiers", {})
    unread_bonus = pool.get("unread_bonus", {})
    cooldown = pool.get("cooldown", {})
    max_repeat = cooldown.get("max_repeat", 2)

    last_state = db.meta_get("xiaoman_current_state") or ""
    # 计数最近连续相同状态
    state_history_raw = db.meta_get("xiaoman_state_history") or "[]"
    try:
        state_history = _json.loads(state_history_raw)
    except Exception:
        state_history = []

    weights = []
    for b in behaviors:
        w = b["weight"]

        mod = time_mods.get(b["id"])
        if mod:
            ah = mod.get("after_hour")
            hr = mod.get("hour_range")
            if ah and now.hour >= ah:
                w += mod.get("weight_bonus", 0)
            if hr and hr[0] <= now.hour <= hr[1]:
                w += mod.get("weight_bonus", 0)

        if b["id"] == unread_bonus.get("target"):
            unread_count = len(db.knowledge_unread(limit=200))
            w += unread_bonus.get("per_article_weight", 0) * unread_count

        if b["id"] == "sleep" and w == 0 and now.hour < 23:
            w = 0

        # 最近 max_repeat 次都是同一状态 → 降权重
        recent_same = sum(1 for s in state_history[-max_repeat:] if s == b["id"])
        if recent_same >= max_repeat:
            w = max(1, w // 3)

        weights.append(max(1, w))

    chosen = random.choices(behaviors, weights=weights, k=1)[0]
    duration = random.randint(chosen["duration_min"], chosen["duration_max"])
    until = now + timedelta(minutes=duration)

    # 更新状态历史（最多保留 10 条）
    state_history.append(chosen["id"])
    if len(state_history) > 10:
        state_history = state_history[-10:]
    db.meta_set("xiaoman_state_history", _json.dumps(state_history, ensure_ascii=False))

    return {
        "id": chosen["id"],
        "label": chosen["label"],
        "require_llm": chosen.get("require_llm", False),
        "duration_minutes": duration,
        "until_iso": until.isoformat(),
        "until_display": until.strftime("%H:%M"),
    }


# 认真/工作态（桌宠 working 语义，其余即"摸鱼"池）
_PRODUCTIVE_IDS = {"reading", "writing", "thinking"}

# 动作事件型状态：不占"常驻状态段"台账，由真实执行（阅读/写文章）时单独开/关事件记录
_EVENT_KINDS = {"reading", "writing"}


def pick_manual_slack(now=None, db=None):
    """用户点"摸鱼"：从非工作/非睡觉的状态里按权重随机选一个。"""
    now = now or datetime.now()
    pool = load_behaviors()
    cand = [
        b for b in pool["behaviors"]
        if b["id"] not in _PRODUCTIVE_IDS and b["id"] != "sleep"
    ]
    weights = [max(1, b["weight"]) for b in cand]
    chosen = random.choices(cand, weights=weights, k=1)[0]
    duration = random.randint(chosen["duration_min"], chosen["duration_max"])
    until = now + timedelta(minutes=duration)
    return {
        "id": chosen["id"],
        "label": chosen["label"],
        "duration_minutes": duration,
        "until_iso": until.isoformat(),
        "until_display": until.strftime("%H:%M"),
    }


def pick_manual_reading(now=None):
    """用户点"阅读"：固定进入阅读态（时长取行为池区间中值，30~60 取 45）。"""
    now = now or datetime.now()
    pool = load_behaviors()
    b = next((x for x in pool["behaviors"] if x["id"] == "reading"), None)
    label = b["label"] if b else "📖 阅读"
    duration = 45
    if b:
        duration = (b.get("duration_min", 30) + b.get("duration_max", 60)) // 2
    until = now + timedelta(minutes=duration)
    return {
        "id": "reading",
        "label": label,
        "duration_minutes": duration,
        "until_iso": until.isoformat(),
        "until_display": until.strftime("%H:%M"),
    }


def switch_state(target, now=None, db=None, source="auto"):
    """统一的状态切换入口（自动状态机与用户手动按钮都走这里）。

    语义（动作事件模型）：
    - "阅读 / 写文章" 属动作事件：切换时只改 meta 当前状态，**不占常驻台账段**，
      真正执行（execute_reading / 发文 compose）时再各自"开一条事件 → 结束后关闭"。
    - 其余常驻状态（摸鱼/发呆/打游戏…）维持状态段台账：切换进来开一条（started_at），
      切走时关掉上一条（ended_at）；tokens 暂无真实通道 → 保持 NULL=未计量。
    - 每次切换把 xiaoman_state_seq +1（阅读执行器据此保证"每进一次阅读只读一次"）。
    - 目标与当前常驻状态相同 → 不重复开记录，只顺延到期时间。

    target: pick_random_state / pick_manual_* 返回的 dict（含 id/label/until_iso）。
    返回 {"changed", "id", "label", "started_at", "until", "event"}。
    """
    now = now or datetime.now()
    db = db or agent_db
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    until_iso = target.get("until_iso") or ""
    try:
        until_dt = datetime.fromisoformat(until_iso) if until_iso else now
    except ValueError:
        until_dt = now
    if not until_iso:
        until_dt = now + timedelta(minutes=target.get("duration_minutes") or 30)

    seq = int(db.meta_get("xiaoman_state_seq") or "0") + 1
    db.meta_set("xiaoman_state_seq", str(seq))

    is_event = target["id"] in _EVENT_KINDS
    changed = True
    if not is_event:
        open_act = db.activity_open()
        if open_act and open_act["kind"] == target["id"]:
            changed = False  # 还在这件事上：不关旧开新，只顺延
        if changed:
            if open_act:
                db.activity_close_open(now_str)
            db.activity_start(target["id"], target["label"], now_str, source=source)

    db.meta_set("xiaoman_current_state", target["id"])
    db.meta_set("xiaoman_state_until", until_dt.strftime("%Y-%m-%d %H:%M:%S"))
    return {
        "changed": changed,
        "id": target["id"],
        "label": target["label"],
        "started_at": now_str,
        "until": until_dt.strftime("%H:%M"),
        "event": is_event,
    }


# Windows CreateProcess 命令行总长上限 32767 字符，dsh headless 只收 positional
# 参数、无 stdin 通道 → 任务文本必须控长，否则 [WinError 206]。
# 阅读上下文（未读清单/记忆）体积随知识库增长不可控，外置为"资料包"临时文件，
# 由 LLM 用读文件工具打开（xiaoman profile 已实测可读仓库内文件）；任务文本
# 只留骨架（~1K）。资料包写失败时降级回内联注入，并按 18K 预算保新弃旧。
_READING_INLINE_BUDGET = 18000
_READING_SUMMARY_MAX = 200
_READING_CTX_DIR = config.DATA_DIR / "tmp" / "reading"
_READING_CTX_KEEP = 5  # 保留最近 N 次资料包，便于回看"她为什么挑这几篇"
_READING_CTX_MAX_AGE_DAYS = 7


def _fmt_unread_md(unread, budget=None):
    """未读清单 Markdown 文本；budget 给定时按字符预算保新弃旧（内联降级用）。"""
    lines, total = [], 0
    for i, item in enumerate(unread or []):
        summary = (item.get("summary") or "(无)")[:_READING_SUMMARY_MAX]
        line = (
            f"{i + 1}. [{item['source']}] {item['title']}\n"
            f"   链接: {item['url']}\n"
            f"   摘要: {summary}"
        )
        if budget is not None and total + len(line) > budget:
            break  # 清单按 fetched_at 倒序，装不下的旧文留待下轮
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines) if lines else "（今天没有未读文章）"


def _fmt_memories_md(past):
    """过往阅读记忆 Markdown 文本。"""
    if not past:
        return "（还没有过往记忆）"
    return "\n".join(
        f"- [{p['id']}] {p['title']} | 观点: {p.get('viewpoint') or ''} | 你的感受: {p.get('memory') or ''}"
        for p in past
    )


def _prune_reading_ctx():
    """清理旧资料包：删 7 天前残留，再只保留最近 _READING_CTX_KEEP 份。"""
    try:
        if not _READING_CTX_DIR.is_dir():
            return
        dirs = sorted(d for d in _READING_CTX_DIR.iterdir() if d.is_dir())
        cutoff = datetime.now() - timedelta(days=_READING_CTX_MAX_AGE_DAYS)
        for d in dirs:
            try:
                expired = datetime.fromtimestamp(d.stat().st_mtime) < cutoff
            except OSError:
                continue
            if expired:
                shutil.rmtree(d, ignore_errors=True)
        for d in dirs[:-_READING_CTX_KEEP]:
            shutil.rmtree(d, ignore_errors=True)
    except OSError:
        pass


def _write_reading_ctx(unread, past_memories):
    """把未读清单 + 过往记忆写成资料包，返回目录 Path；失败返回 None。"""
    try:
        ctx_dir = _READING_CTX_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
        ctx_dir.mkdir(parents=True, exist_ok=True)
        (ctx_dir / "unread.md").write_text(
            _fmt_unread_md(unread), encoding="utf-8")
        (ctx_dir / "memories.md").write_text(
            _fmt_memories_md(past_memories), encoding="utf-8")
        return ctx_dir
    except OSError:
        return None


def execute_reading(db=None, llm_fn=None):
    """执行阅读行为（进入"阅读"时调用一次）。

    加载 reading.md → 未读文章 + 过往记忆外置为资料包文件（任务文本留骨架，
    LLM 用读文件工具打开）→ dsh 调用 → LLM 自己挑选想读的文章、用 web 读全文、
    记录感受、决定发几条动态。资料包写失败时降级为内联注入。

    返回 {"read_count", "posted_count", "error": str|None}。
    """
    db = db or agent_db
    llm_fn = llm_fn or dsh_task_llm

    # 阅读会话 = 一条独立事件：开始时开记录，结束（含失败）时关闭并写备注
    start_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ev_id = db.activity_start("reading", "📖 阅读", start_str, source="auto")

    def _finish_reading(result, err=None):
        db.activity_close_open(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        note = f"读了 {result.get('read_count', 0)} 篇"
        if err:
            note += f"（异常：{err}）"
        elif result.get("_parse_error"):
            note += f"（解析异常：{result['_parse_error']}）"
        db.activity_set_note(ev_id, note)

    template = load_reading_prompt()
    unread = db.knowledge_unread(limit=100)
    past_memories = db.knowledge_with_memory(limit=10)
    _prune_reading_ctx()

    # 上下文外置：未读/记忆写成资料包文件，任务文本只留骨架；
    # 写失败（磁盘异常/路径不可用）降级回内联注入（18K 预算保新弃旧）
    ctx_dir = _write_reading_ctx(unread, past_memories)
    if ctx_dir is not None:
        try:
            shown = ctx_dir.relative_to(config.REPO_ROOT).as_posix()
        except ValueError:
            shown = ctx_dir.as_posix()
        task = template.replace(
            "<!-- UNREAD_ARTICLES -->",
            f"未读清单文件：`{shown}/unread.md`（最新在前）。"
            "请先用读文件工具打开它，浏览全部未读文章后再从中挑选。",
        ).replace(
            "<!-- PAST_MEMORIES -->",
            f"过往记忆文件：`{shown}/memories.md`。请用读文件工具打开它。",
        )
    else:
        task = template.replace(
            "<!-- UNREAD_ARTICLES -->",
            _fmt_unread_md(unread, _READING_INLINE_BUDGET),
        ).replace("<!-- PAST_MEMORIES -->", _fmt_memories_md(past_memories))
    try:
        text = llm_fn(task)
    except Exception as e:
        _finish_reading({"read_count": 0}, err=str(e))
        raise
    result = _parse_reading_output(text)

    # 写入记忆：按 url 匹配
    for art in result.get("articles", []):
        url = (art.get("url") or "").strip()
        if not url:
            continue
        matched = next(
            (k for k in db.knowledge_all(limit=500) if k["url"] == url), None
        )
        if matched:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            db.knowledge_set_memory(
                matched["id"],
                viewpoint=art.get("viewpoint"),
                emotion=art.get("emotion"),
                memory=art.get("memory"),
                read_at=now_str,
            )

    # 写入动态
    posted = 0
    for post in result.get("posts", []):
        content = (post.get("content") or "").strip()
        if not content:
            continue
        content = persona.append_disclaimer(content)
        if not validate_article(content, min_len=10)["ok"]:
            continue
        db.article_create(
            datetime.now().strftime("%Y-%m-%d"),
            content[:120],
            content,
            topics=["动态"],
            sources=[],
            kind="post",
        )
        posted += 1

    err = result.get("_parse_error")
    _finish_reading(result)
    return {
        "read_count": result.get("read_count", 0),
        "posted_count": posted,
        "error": err,
    }


def _extract_outer_json(raw, wanted=None):
    """从文本里提取可完整解码的 JSON 对象（容忍模型输出前后夹带的废话）。

    raw_decode 会从任一 '{' 起解码"第一个完整值"——嵌套对象自身也能解出，
    所以不能直接取第一个：优先选含 wanted 键之一的对象；没有则退回解码成功里
    最外层（位置最靠前的那个）。
    """
    if not raw:
        return None
    dec = _json.JSONDecoder()
    wanted = wanted or ()
    best_pos, best_obj = None, None
    idx = raw.rfind("{")
    while idx != -1:
        try:
            obj, _ = dec.raw_decode(raw[idx:])
        except Exception:
            obj = None
        if isinstance(obj, dict):
            if wanted and any(k in obj for k in wanted):
                return obj
            if best_pos is None:
                best_pos, best_obj = idx, obj
        idx = raw.rfind("{", 0, idx)
    return best_obj


def _parse_reading_output(text):
    """解析阅读输出 JSON（取含 read_count/articles/posts 的最外层完整对象）。"""
    if not text:
        return {"read_count": 0, "articles": [], "posts": [], "_parse_error": "empty"}

    obj = _extract_outer_json(text.strip(), wanted=("read_count", "articles", "posts"))
    if obj is None:
        return {
            "read_count": 0,
            "articles": [],
            "posts": [],
            "_parse_error": "no_json_block",
        }

    return {
        "read_count": int(obj.get("read_count") or 0),
        "articles": obj.get("articles") or [],
        "posts": obj.get("posts") or [],
        "_parse_error": None,
    }
