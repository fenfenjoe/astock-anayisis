"""playwright_collector.py — 社交平台 Playwright 登录态采集（方案 v1.10 §9.4）。

微博 / 小红书 / 知乎 / 雪球：用户提供 Cookie（存云库 platform_cookies），本模块以登录态
访问热点页采集文章标题/链接/摘要 → 入 agent_knowledge（source=weibo/xhs/zhihu/xueqiu）。

设计约束（用户确认）：
- 随状态机"逛微博/逛小红书/逛知乎/逛雪球"状态触发（不独立定时采集），同轮串行（不并发）
- 跑在小满进程内但独立子进程；采集超时/资源回收
- 采集失败不阻塞状态机：失败时回写 reachability=false 并提示
- 入库去重：① url UNIQUE（db.knowledge_upsert 精确去重）→ ② 标题相似度去重 0.85
  （db.title_similar，difflib 字符级，不引 embedding）
- 真实访问成功后回写 reachability=true（自校准）
"""

import time

from agent import config, db as agent_db
from agent.core import reachability


def _weibo_hot_items(cookie, limit):
    """微博热搜：m.weibo.cn 移动热榜 JSON 接口。返回 [{title, url, summary}]。"""
    import requests

    url = (
        "https://m.weibo.cn/api/container/getIndex?containerid=106003type%3D25"
        "&filter_type%3Drealtimehot&title%3D%E5%BE%AE%E5%8D%9A%E7%83%AD%E6%90%9C"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
        "Cookie": cookie,
    }
    resp = requests.get(url, headers=headers, timeout=config.BROWSE_COLLECT_TIMEOUT_SECONDS)
    resp.raise_for_status()
    data = resp.json()
    cards = (data.get("data") or {}).get("cards") or []
    items = []
    for card in cards:
        for mblog in (card.get("card_group") or []):
            if not isinstance(mblog, dict):
                continue
            title = (mblog.get("desc") or mblog.get("title") or "").strip()
            mid = mblog.get("id") or ""
            if not title or not mid:
                continue
            items.append(
                {
                    "title": title,
                    "url": f"https://m.weibo.cn/status/{mid}",
                    "summary": title,
                }
            )
            if len(items) >= limit:
                return items
    return items


def _xhs_hot_items(cookie, limit):
    """小红书热点：explore 页。返回 [{title, url, summary}]。

    小红书无公开轻量热点 JSON（反爬较强）；用带 Cookie 的 explore 页抓取，
    解析标题卡片（尽力而为，抓不到返回 []，不阻塞状态机）。
    """
    import re

    import requests

    url = "https://www.xiaohongshu.com/explore"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie": cookie,
    }
    resp = requests.get(url, headers=headers, timeout=config.BROWSE_COLLECT_TIMEOUT_SECONDS)
    resp.raise_for_status()
    html = resp.text
    # 尽力解析：提取 note id + 标题（XHS 把数据塞在 window.__INITIAL_STATE__）
    titles = re.findall(r'"title":"([^"]{4,40})"', html)
    note_ids = re.findall(r'"noteId":"([a-f0-9]{24})"', html) or re.findall(
        r"/explore/([a-f0-9]{24})", html
    )
    items = []
    for i, t in enumerate(titles):
        if not t:
            continue
        nid = note_ids[i] if i < len(note_ids) else ""
        items.append(
            {
                "title": t.replace("\\u002F", "/").replace("\\n", ""),
                "url": f"https://www.xiaohongshu.com/explore/{nid}" if nid else url,
                "summary": t,
            }
        )
        if len(items) >= limit:
            break
    return items


def _zhihu_hot_items(cookie, limit):
    """知乎热榜：api/v3/feed/topstory/hot-lists/total（有效 Cookie → 200 JSON）。

    返回 [{title, url, summary}]；失效/反爬 → []（不阻塞状态机）。
    """
    import requests

    url = "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=50"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie": cookie,
    }
    resp = requests.get(url, headers=headers, timeout=config.BROWSE_COLLECT_TIMEOUT_SECONDS)
    resp.raise_for_status()
    data = resp.json()
    items = []
    for it in (data.get("data") or []):
        target = it.get("target") or {}
        title = (target.get("title") or "").strip()
        qid = target.get("id") or ""
        if not title or not qid:
            continue
        items.append(
            {
                "title": title,
                "url": f"https://www.zhihu.com/question/{qid}",
                "summary": title,
            }
        )
        if len(items) >= limit:
            break
    return items


def _xueqiu_hot_items(cookie, limit):
    """雪球热帖：statuses/hot/listV2.json（有效 Cookie → 200 application/json）。

    返回 [{title, url, summary}]；失效/WAF 页 → []（不阻塞状态机）。
    """
    import requests

    url = "https://xueqiu.com/statuses/hot/listV2.json?since_id=-1&max_id=-1&size=15"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cookie": cookie,
        "Referer": "https://xueqiu.com/",
    }
    resp = requests.get(url, headers=headers, timeout=config.BROWSE_COLLECT_TIMEOUT_SECONDS)
    resp.raise_for_status()
    if "json" not in (resp.headers.get("Content-Type") or "").lower():
        return []  # WAF renderData 页（未登录/被拦）
    data = resp.json()
    items = []
    for it in (data.get("items") or []):
        title = (it.get("title") or it.get("description") or "").strip()
        sid = it.get("id") or ""
        if not title or not sid:
            continue
        items.append(
            {
                "title": title[:80],
                "url": f"https://xueqiu.com/{sid}",
                "summary": (it.get("text") or "")[:120] or title,
            }
        )
        if len(items) >= limit:
            break
    return items


def _store_items(platform_id, items, db=None):
    """入库（url 精确去重 + 标题相似度去重）。返回 {"added", "dup"}。

    顺序：先 title_similar 比对既有库（标题相似 → dup，跳过）→ 再 knowledge_upsert
    （url UNIQUE 精确去重）。标题比对发生在插入前，避免命中刚插入的自身。
    """
    db = db or agent_db
    added = dup = 0
    for it in items:
        # ② 标题相似度去重（0.85，difflib）——与既有库标题高度相似则跳过
        if db.title_similar(it["title"]):
            dup += 1
            continue
        # ① url 精确去重（knowledge_upsert 内部 UNIQUE）
        ok = db.knowledge_upsert(
            platform_id, it["title"], it["url"], it.get("summary"), None, None
        )
        if not ok:
            dup += 1
            continue
        added += 1
    return {"added": added, "dup": dup}


def collect_platform(platform_id, db=None):
    """采集单个平台热点并入库。返回 {platform_id, collected, added, dup, ok, error}。

    Cookie 缺失/失效/探测失败 → 回写 reachability=false；成功 → true（自校准）。
    """
    db = db or agent_db
    platform = next(
        (p for p in config.SOCIAL_PLATFORMS if p["id"] == platform_id), None
    )
    if not platform:
        return {"platform_id": platform_id, "ok": False, "error": "未知平台"}
    if not platform.get("playable"):
        return {
            "platform_id": platform_id,
            "ok": False,
            "error": "未实施访问逻辑",
        }

    cookie = db.platform_cookie_get(platform_id)
    if not cookie:
        reachability.update_after_access(platform_id, False, "无 Cookie，无法采集", db=db)
        return {
            "platform_id": platform_id,
            "ok": False,
            "error": "需要用户提供 Cookie",
        }

    limit = config.BROWSE_COLLECT_LIMIT
    t0 = time.time()
    try:
        if platform_id == "weibo":
            items = _weibo_hot_items(cookie, limit)
        elif platform_id == "xhs":
            items = _xhs_hot_items(cookie, limit)
        elif platform_id == "zhihu":
            items = _zhihu_hot_items(cookie, limit)
        elif platform_id == "xueqiu":
            items = _xueqiu_hot_items(cookie, limit)
        else:
            items = []
        if not items:
            reachability.update_after_access(platform_id, False, "采集无内容", db=db)
            return {
                "platform_id": platform_id,
                "ok": False,
                "collected": 0,
                "error": "采集无内容（可能 Cookie 失效或反爬）",
            }
        stats = _store_items(platform_id, items, db=db)
        reachability.update_after_access(platform_id, True, "采集成功", db=db)
        return {
            "platform_id": platform_id,
            "ok": True,
            "collected": len(items),
            "added": stats["added"],
            "dup": stats["dup"],
            "elapsed": round(time.time() - t0, 1),
        }
    except Exception as e:
        reachability.update_after_access(platform_id, False, f"采集失败: {e}", db=db)
        return {
            "platform_id": platform_id,
            "ok": False,
            "collected": 0,
            "error": f"采集失败: {e}",
        }
