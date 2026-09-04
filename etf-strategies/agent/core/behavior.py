"""behavior.py — 行为引擎：发文调度 / 状态机 / 阅读执行.

全部纯函数或依赖注入（llm_fn / db），不直接联网，便于测试。
编排入口：run_publish_pipeline()（每日发文）、pick_random_state()（状态决策）、
execute_reading()（阅读 Prompt 执行）。
LLM 生成统一走 dsh（dsh --profile xiaoman），凭据由 dsh 管理。
"""

import json as _json
import random
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

    art = compose_article(pick["items"], llm_fn=llm_fn, db=db)
    if not art["ok"]:
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


def execute_reading(db=None, llm_fn=None):
    """执行阅读行为（进入"阅读"时调用一次）。

    加载 reading.md → 注入未读文章 + 过往记忆 → dsh 调用 →
    LLM 自己挑选想读的文章、用 web 读全文、记录感受、决定发几条动态。

    返回 {"read_count", "posted_count", "error": str|None}。
    """
    db = db or agent_db
    llm_fn = llm_fn or dsh_task_llm

    template = load_reading_prompt()
    unread = db.knowledge_unread(limit=100)
    past_memories = db.knowledge_with_memory(limit=10)

    unread_text = ""
    if unread:
        unread_lines = []
        for i, item in enumerate(unread):
            unread_lines.append(
                f"{i + 1}. [{item['source']}] {item['title']}\n"
                f"   链接: {item['url']}\n"
                f"   摘要: {item.get('summary') or '(无)'}"
            )
        unread_text = "\n".join(unread_lines)
    else:
        unread_text = "（今天没有未读文章）"

    past_text = ""
    if past_memories:
        past_text = "\n".join(
            f"- [{p['id']}] {p['title']} | 观点: {p.get('viewpoint') or ''} | 你的感受: {p.get('memory') or ''}"
            for p in past_memories
        )
    else:
        past_text = "（还没有过往记忆）"

    task = template.replace("<!-- UNREAD_ARTICLES -->", unread_text).replace(
        "<!-- PAST_MEMORIES -->", past_text
    )
    text = llm_fn(task)
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
    return {
        "read_count": result.get("read_count", 0),
        "posted_count": posted,
        "error": err,
    }


def _parse_reading_output(text):
    """解析阅读输出 JSON（取最后一个完整的 {...} 块）。

    容错：禁止 JSON {} 内的内容可能包含换行和嵌套对象，递归取最外层。
    """
    if not text:
        return {"read_count": 0, "articles": [], "posts": [], "_parse_error": "empty"}

    raw = text.strip()
    # 从最后一个 { 到最后一个 } 之间提取
    start = raw.rfind("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        return {
            "read_count": 0,
            "articles": [],
            "posts": [],
            "_parse_error": "no_json_block",
        }

    raw = raw[start : end + 1]
    try:
        obj = _json.loads(raw)
    except Exception as e:
        return {
            "read_count": 0,
            "articles": [],
            "posts": [],
            "_parse_error": f"json_parse: {e}",
        }

    return {
        "read_count": int(obj.get("read_count") or 0),
        "articles": obj.get("articles") or [],
        "posts": obj.get("posts") or [],
        "_parse_error": None,
    }
