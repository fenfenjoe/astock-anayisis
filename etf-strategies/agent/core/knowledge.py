"""knowledge.py — 知识源接入：RSS 拉取/解析/去重入库/素材检索.

数据纪律：RSS 素材仅作为「大V观点 / 时事」学习素材（D4 主通道）；
涉 A 股行情/财务等真实数据仍一律走 `a-stock-data`，本模块不碰行情。
"""

import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

import requests

from agent import config, db as agent_db


def feed_url(feed, instance=None):
    """拼接 RSSHub 源 URL。instance 缺省用配置优先实例。"""
    instance = instance or config.RSSHUB_INSTANCES[0]
    return f"{instance.rstrip('/')}{feed['path']}"


def parse_rss(xml_text):
    """解析 RSS 2.0 → [{title, url, summary, published_at}]。

    容错：空/坏 XML 返回 []；缺字段返回空串，不抛异常。
    """
    if not xml_text or not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items = []
    for item in root.iter("item"):

        def _text(tag):
            el = item.find(tag)
            return (el.text or "").strip() if el is not None and el.text else ""

        items.append(
            {
                "title": _text("title"),
                "url": _text("link"),
                "summary": _text("description"),
                "published_at": _format_pub(_text("pubDate")),
            }
        )
    return items


def _format_pub(pub):
    """RFC822 pubDate → 'YYYY-MM-DD HH:MM'；解析失败保留原串。"""
    if not pub:
        return ""
    try:
        return parsedate_to_datetime(pub).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return pub


def fetch_feed(feed, instance=None, timeout=15):
    """拉取一个源的 RSS 并解析；网络/解析失败返回 []（容错，不中断轮询）。"""
    url = feed_url(feed, instance)
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return parse_rss(resp.text)
    except requests.RequestException:
        return []


def sync_feed(source_id, items, db=None):
    """把解析出的 items 入库（按 url 去重）。返回 {"added", "dup"}。"""
    db = db or agent_db
    added = dup = 0
    for it in items:
        if not it.get("url"):
            continue
        ok = db.knowledge_upsert(
            source_id, it["title"], it["url"], it["summary"], None, it["published_at"]
        )
        if ok:
            added += 1
        else:
            dup += 1
    return {"added": added, "dup": dup}


def fetch_and_store(db=None, instances=None):
    """拉取全部订阅源并入库存档（lifecycle tick 调用）。

    返回 {"feeds": n, "added": total, "errors": [feed_id...]}；
    单源失败不中断其余。
    """
    db = db or agent_db
    instances = instances or config.RSSHUB_INSTANCES
    total_added, errors = 0, []
    for feed in config.RSS_FEEDS:
        items = []
        for inst in instances:  # 实例按优先序尝试，成功即停
            items = fetch_feed(feed, inst)
            if items:
                break
        if not items:
            errors.append(feed["id"])
            continue
        total_added += sync_feed(feed["id"], items, db)["added"]
    return {"feeds": len(config.RSS_FEEDS), "added": total_added, "errors": errors}


# ═══════════════════════════════════════════
# 自定义站点源采集（①素材源增强）
# ═══════════════════════════════════════════


def _gather_task(sites):
    """构造"小满逛站找文章"的 directive。"""
    site_lines = "\n".join(f"- {s['name']}: {s['url']}" for s in sites)
    return (
        "你是小满。请浏览以下财经网站/栏目，从中挑选 2~3 篇最近值得学习的文章。\n"
        "对每篇文章用 web 工具查看内容，然后只输出一个 JSON 数组，不要输出其他任何文字：\n"
        '[{"title": "文章标题", "url": "文章链接", "summary": "50字以内摘要", "source": "站点名"}, ...]\n\n'
        f"站点：\n{site_lines}"
    )


def parse_gather_output(text):
    """解析采集 directive 输出 → [{title, url, summary, source}]。

    容错：支持 ```json 围栏 / 纯 JSON；解析失败返回 []；缺 url 的条目丢弃。
    """
    if not text or not text.strip():
        return []
    raw = text.strip()
    # 提取 ```json ... ``` 围栏块
    if "```" in raw:
        import re

        m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", raw, re.S)
        raw = m.group(1) if m else raw
    else:
        # 取第一个 [ 到最后一个 ]
        start, end = raw.find("["), raw.rfind("]")
        if start != -1 and end > start:
            raw = raw[start : end + 1]
    try:
        import json as _json

        rows = _json.loads(raw)
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    items = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        url = (r.get("url") or "").strip()
        title = (r.get("title") or "").strip()
        if not url or not title:
            continue
        items.append(
            {
                "title": title,
                "url": url,
                "summary": (r.get("summary") or "").strip(),
                "source": (r.get("source") or "自定义").strip(),
            }
        )
    return items


def collect_custom_sources(db=None, llm_fn=None):
    """让小满逛自定义站点找文章 → 结构化入库（参与发文素材池）。

    llm_fn(task: str) -> str（默认 dsh_task_llm，即 dsh --profile xiaoman）。
    返回 {"sites": n, "added": total, "errors": [...]}。
    """
    from agent.core import behavior

    db = db or agent_db
    llm_fn = llm_fn or behavior.dsh_task_llm
    sites = [s for s in db.source_list(enabled_only=True) if s["kind"] == "website"]
    if not sites:
        return {"sites": 0, "added": 0, "errors": []}
    task = _gather_task(sites)
    text = llm_fn(task)
    items = parse_gather_output(text)
    added = 0
    for it in items:
        if db.knowledge_upsert(
            it["source"], it["title"], it["url"], it["summary"], None, None
        ):
            added += 1
    return {"sites": len(sites), "added": added, "errors": []}


# ═══════════════════════════════════════════
# 阅读引擎：RSS 摘要 → 全文拉取 → 观点记忆
# ═══════════════════════════════════════════


def read_article(item, llm_fn=None, db=None):
    """小满阅读一篇文章（通过 dsh web fetch 拉全文）并生成记忆。

    流程：
    1. dsh 打开 url 读全文
    2. LLM 提取核心观点 + 情绪 + 个人记忆
    3. 写回 agent_knowledge（viewpoint / emotion / memory / read_at）

    返回 {"kid", "viewpoint", "emotion", "memory", "post_worthy": bool}
    """
    from agent.core import behavior

    db = db or agent_db
    llm_fn = llm_fn or behavior.dsh_task_llm

    existing = next(
        (k for k in db.knowledge_all(limit=500) if k["url"] == item["url"]), None
    )
    past_memories = db.knowledge_with_memory(limit=10)
    past_lines = ""
    if past_memories:
        past_lines = "小满过去的阅读记忆（可联想、对比，避免重复感受）：\n" + "\n".join(
            f"- [{p['id']}] {p['title']} | 观点: {p.get('viewpoint') or ''} | 记忆: {p.get('memory') or ''}"
            for p in past_memories
        )

    task = (
        "你是小满。请先用 web 工具打开这篇链接，阅读全文内容。\n"
        f"链接：{item['url']}\n"
        f"标题：{item['title']}\n"
        f"已有摘要：{item.get('summary') or ''}\n\n" + past_lines + "\n"
        "读完文章后，只输出一个严格的 JSON 对象，不要输出其他任何文字：\n"
        "{\n"
        '  "viewpoint": "这篇文章的核心观点（一句话，30字以内）",\n'
        '  "emotion": "excited|angry|curious|calm|skeptical（选一个最符合你读完后的情绪）",\n'
        '  "memory": "你的个人感受、联想或吐槽（50字以内，加入你过往阅读记忆的对比联想）",\n'
        '  "post_worthy": true/false\n'
        "}\n\n"
        "post_worthy 判定标准：观点很有参考价值 或 内容让你情绪被调动（"
        "emotion=excited/angry/skeptical），就设为 true；否则 false。"
    )
    text = llm_fn(task)
    result = _parse_read_output(text)
    if not result:
        return {
            "kid": (existing or {}).get("id"),
            "viewpoint": None,
            "emotion": None,
            "memory": None,
            "post_worthy": False,
        }

    kid = existing["id"] if existing else None
    if kid:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.knowledge_set_memory(
            kid,
            viewpoint=result.get("viewpoint"),
            emotion=result.get("emotion"),
            memory=result.get("memory"),
            read_at=now,
        )
    return {
        "kid": kid,
        "viewpoint": result.get("viewpoint"),
        "emotion": result.get("emotion"),
        "memory": result.get("memory"),
        "post_worthy": result.get("post_worthy", False),
    }


def _parse_read_output(text):
    """解析阅读记忆输出 → {viewpoint, emotion, memory, post_worthy}。"""
    if not text or not text.strip():
        return None
    raw = text.strip()
    if "```" in raw:
        import re

        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
        raw = m.group(1) if m else raw
    else:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            raw = raw[start : end + 1]
    try:
        import json as _json

        obj = _json.loads(raw)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    valid_emotions = {"excited", "angry", "curious", "calm", "skeptical"}
    emotion = obj.get("emotion", "")
    if emotion not in valid_emotions:
        emotion = "calm"
    return {
        "viewpoint": (obj.get("viewpoint") or "").strip(),
        "emotion": emotion,
        "memory": (obj.get("memory") or "").strip(),
        "post_worthy": bool(obj.get("post_worthy", False)),
    }
