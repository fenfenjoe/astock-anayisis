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


class WeiboHTMLBlocked(Exception):
    """微博移动接口返回 HTML（登录态失效/被反爬）而非 JSON，无法解析热榜。

    专门异常：让 collect_platform 捕获后给出可读错误（"微博接口被反爬/需重新登录"），
    而不是 resp.json() 抛出的晦涩 JSONDecodeError（"Expecting value: line 1 column 1"）。
    """


def _weibo_hot_items(cookie, limit):
    """微博热搜：m.weibo.cn 移动热榜 JSON 接口。返回 [{title, url, summary}]。

    2026-09-16 反爬变更：m.weibo.cn 对无登录态/被风控的请求返回 HTTP 200 +
    text/html 登录/验证页（不再是 JSON）→ 检查 Content-Type，非 JSON 抛
    WeiboHTMLBlocked（上层 collect_platform 捕获后回写 reachability=false，
    不再抛晦涩的 JSONDecodeError "Expecting value"）。
    """
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
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "json" not in ctype:
        raise WeiboHTMLBlocked(
            f"微博接口返回 {ctype or '未知 Content-Type'}（登录态失效/被反爬，非 JSON）"
        )
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


def _joinquant_hot_items(cookie, limit):
    """聚宽社区文章：/community/post/listV2（无需登录，匿名可用，实测 2026-10）。

    聚宽社区列表 API 与微博/小红书不同——**匿名即可访问**（不带 Cookie 也返回
    完整 JSON），Cookie 仅影响收藏/点赞等个性化字段。因此：
    - 有 Cookie 时带上（提升个别帖子的可见性/内容完整度）
    - 无 Cookie 也能采集（列表页内容公开）

    返回 [{title, url, summary}]，每项：
    - title: 帖子标题
    - url:   详情页 https://www.joinquant.com/view/community/detail/{postId}
    - summary: 标签 + 浏览量/回复 + 正文摘要（Markdown 截断）

    采集参数：
    - cate=0：全部类别（文章/问答/公告/精华）
    - type=isNew：最新排序（isHot=最热）。BROWSE_COLLECT_LIMIT 条以内取第一页。
    """
    import requests

    url = "https://www.joinquant.com/community/post/listV2"
    params = {"limit": limit, "page": 1, "cate": 0, "type": "isNew"}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0",
        "Referer": "https://www.joinquant.com/view/community/list?listType=1",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/plain, */*",
    }
    if cookie:
        headers["Cookie"] = cookie
    resp = requests.get(url, params=params, headers=headers, timeout=config.BROWSE_COLLECT_TIMEOUT_SECONDS)
    resp.raise_for_status()
    data = resp.json()
    if (data.get("code") or "") != "00000":
        return []  # 系统异常/被拦 → 不阻塞状态机
    items = []
    for it in (data.get("data") or {}).get("list") or []:
        title = (it.get("title") or "").strip()
        post_id = it.get("postId") or ""
        if not title or not post_id:
            continue
        tags = ",".join(t.get("name", "") for t in (it.get("tagInfo") or []) if t.get("name"))
        content = (it.get("content") or "").strip()
        # 摘要：标签 + 热度 + 正文前 120 字（Markdown，去掉换行）
        excerpt = " ".join(content.split())[:120]
        summary_bits = []
        if tags:
            summary_bits.append(f"[{tags}]")
        summary_bits.append(f"浏览{it.get('viewCount') or 0}/回复{it.get('replyCount') or 0}")
        if excerpt:
            summary_bits.append(excerpt)
        items.append(
            {
                "title": title[:80],
                "url": f"https://www.joinquant.com/view/community/detail/{post_id}",
                "summary": " ".join(summary_bits)[:200],
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
    # 聚宽社区 API 匿名可用（listV2 无需登录）→ 无 Cookie 也放行采集；
    # 其他平台仍要求 Cookie（登录态采集）。
    if not cookie and platform_id != "joinquant":
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
        elif platform_id == "joinquant":
            items = _joinquant_hot_items(cookie, limit)
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
        # Cookie 失效/反爬类失败 → 生成"失效"待办，让用户重新提供 Cookie
        # （2026-09-16 修复：之前只有无 Cookie 才生成待办，失效不触发 → 用户无从得知）
        _notify_cookie_expired(platform_id, e, db=db)
        return {
            "platform_id": platform_id,
            "ok": False,
            "collected": 0,
            "error": f"采集失败: {e}",
        }


def _notify_cookie_expired(platform_id, exc, db=None):
    """Cookie 失效/反爬类采集异常 → 生成"失效"待办（幂等去重，已有 open 待办则跳过）。

    判断依据：WeiboHTMLBlocked（微博接口返回 HTML 登录页）或异常信息含
    "登录态失效/反爬/Cookie 失效" 等关键词；其他异常（网络抖动等）不打扰用户。
    """
    msg = str(exc)
    is_auth_failure = isinstance(exc, WeiboHTMLBlocked) or any(
        kw in msg for kw in ("登录态失效", "反爬", "Cookie 失效", "Cookie已失效", "Cookie 无效")
    )
    if not is_auth_failure:
        return None
    try:
        from agent.core import notices

        return notices.create_cookie_todo(platform_id, reason="失效", db=db)
    except Exception:
        return None  # 待办生成失败不阻塞采集流程
