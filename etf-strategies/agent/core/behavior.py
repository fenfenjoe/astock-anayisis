"""behavior.py — 行为引擎：发文调度 / 素材选择 / 草稿管线.

全部纯函数或依赖注入（llm_fn / db），不直接联网，便于测试。
编排入口：run_publish_pipeline()（每日发文）、run_post_pipeline()（动态）。
LLM 生成统一走 dsh（Agent 2 = dsh --profile xiaoman），凭据由 dsh 管理。
"""
from datetime import datetime

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
            return line[len("标题："):].strip()
    return ""


def compose_article(materials, llm_fn=None, db=None,
                    persona_id=config.PERSONA_ID):
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
        date_part = materials[0]["published_at"][:10] if materials and \
            materials[0].get("published_at") else ""
        title = f"学习笔记 {date_part}".strip() or "学习笔记"
    body_lines = [ln for ln in content.splitlines()
                  if not ln.strip().startswith("标题：")]
    body = "\n".join(body_lines).strip()
    check = validate_article(body)
    return {"title": title, "content": body, "ok": check["ok"],
            "issues": check["issues"]}


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
        return {"published": False, "reason": "material_insufficient",
                "article_id": None}

    art = compose_article(pick["items"], llm_fn=llm_fn, db=db)
    if not art["ok"]:
        return {"published": False,
                "reason": f"validation: {art['issues']}",
                "article_id": None}

    sources = [
        {"title": m["title"], "url": m["url"], "source": m["source"]}
        for m in pick["items"]
    ]
    topics = ["学习笔记"]
    aid = db.article_create(art["title"], art["content"][:120], art["content"],
                            topics=topics, sources=sources)
    # 观点入库：正文主观点归档，供后续发言自洽检索（方案 §2.2）
    db.opinion_add(topics[0], art["content"], article_id=aid)
    for m in pick["items"]:
        db.knowledge_mark_consumed(m["id"])
    db.meta_set("published_on", today)
    return {"published": True, "reason": "done", "article_id": aid}


def run_post_pipeline(now=None, llm_fn=None, db=None,
                      interval_minutes=None, active_hours=None):
    """发动态（微博式短文本）：节流 + 活跃时段 + dsh directive。

    now: datetime（注入便于测试）；interval_minutes: 距上一条动态的最短间隔；
    active_hours: (start, end) 仅在该时段发动态。
    返回 {"posted": bool, "reason": str, "post_id": int|None}。
    """
    now = now or datetime.now()
    db = db or agent_db
    llm_fn = llm_fn or dsh_task_llm
    interval_minutes = interval_minutes or config.POST_INTERVAL_MINUTES
    start_h, end_h = active_hours or config.POST_ACTIVE_HOURS
    if not (start_h <= now.hour < end_h):
        return {"posted": False, "reason": "not_active_hours", "post_id": None}

    last = db.meta_get("last_post_at")
    if last:
        try:
            prev = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
            if (now - prev).total_seconds() < interval_minutes * 60:
                return {"posted": False, "reason": "too_soon", "post_id": None}
        except ValueError:
            pass

    materials = db.knowledge_unconsumed(limit=3)
    material_lines = "\n".join(
        f"- {m['title']}" for m in materials) or "（今天还没学到新东西）"
    task = (
        "你是小满。用 50~150 字发一条动态（像微博/朋友圈）：今天的学习心得或心情，"
        "口语化、有个人风格，可引用今天看到的内容，结尾附「不构成投资建议」。\n"
        f"今天的素材：\n{material_lines}"
    )
    content = llm_fn(task)
    content = persona.append_disclaimer(content)
    check = validate_article(content, min_len=10)
    if not check["ok"]:
        return {"posted": False,
                "reason": f"validation: {check['issues']}",
                "post_id": None}
    pid = db.article_create(now.strftime("%Y-%m-%d"), content[:120], content,
                            topics=["动态"], sources=[], kind="post")
    db.meta_set("last_post_at", now.strftime("%Y-%m-%d %H:%M:%S"))
    return {"posted": True, "reason": "done", "post_id": pid}
