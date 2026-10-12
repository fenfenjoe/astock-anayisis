"""reachability.py — 爱逛的地方可达性判定（方案 v1.10 §9.4 + 2026-09 合并改版）。

分类（SOCIAL_PLATFORMS 的 kind 字段）：
- rss（财联社/华尔街见闻）：复用 knowledge.fetch_feed 轻量探测（多实例 fallback），
  任一实例能拉到条目 → 可达（小满通过 RSS 阅读 = 能逛）
- cookie（微博/小红书/知乎/雪球/聚宽）：带 Cookie 的轻量 HTTP 探测（不拉起 Playwright 浏览器），
  能拿到正常响应 → 可达；无 Cookie / 401/403 / 超时 → 不可达
  （聚宽走 /user/index/isLogin 登录态判定：isLogin=1 可达，0=需登录）
- none（X）：固定不可达（未实施访问逻辑，仅展示图标）

缓存：判定结果写 agent_db.reachability_set（云库/本地），前端读缓存渲染。
首次启动由 dashboard 侧调用 ensure_reachability() 全量判定一次；
小满真实访问（playwright_collector）成功后由访问侧回写自校准。
"""

import time

from agent import config, db as agent_db
from agent.core import knowledge


# 带 Cookie 探测的 HTTP 超时（秒）
_PROBE_TIMEOUT = 8


def _probe_rsshub(platform_id):
    """RSSHub 源探测：按实例优先序逐个尝试，任一实例拉到条目即认为可达。

    与日常拉取 fetch_and_store 的 fallback 逻辑保持一致（之前只试
    RSSHUB_INSTANCES[0]，第一个实例不可达就误判整源不可达）。
    """
    feed = next((f for f in config.RSS_FEEDS if f["id"] == platform_id), None)
    if not feed:
        return False
    for inst in config.RSSHUB_INSTANCES:
        items = knowledge.fetch_feed(feed, inst, timeout=_PROBE_TIMEOUT)
        if items:
            return True
    return False


def _probe_cookie(platform_id, cookie):
    """Cookie 源轻量 HTTP 探测：带 Cookie 请求平台热榜/首页，正常响应 → 可达。

    端点（决策 43：实施时定）：
    - 微博：m.weibo.cn 移动热榜 JSON 接口（.m.weibo.cn 域名 + cookie 能拿到 JSON；
      2026-09-16 反爬变更：失效/被风控返回 200+HTML → 要求 JSON Content-Type 判可达）
    - 小红书：www.xiaohongshu.com 首页（200 即可达，无需解析内容）
    - 知乎：api/v4/me（有效 Cookie → 200 JSON；无/失效 → 401）
    - 雪球：hot listV2 JSON（有效 Cookie → Content-Type application/json；
      无/失效 → WAF renderData text/html 页）
    - 聚宽：/user/index/isLogin（登录态 JSON：data.isLogin==1 → 可达；
      未登录/失效 → isLogin==0；2026-10 新增，探针实测匿名返回 isLogin=0）
    401/403/超时/异常/非预期类型 → 不可达。
    """
    import requests

    endpoints = {
        "weibo": (
            "https://m.weibo.cn/api/container/getIndex?containerid=106003type%3D25"
            "&filter_type%3Drealtimehot&title%3D%E5%BE%AE%E5%8D%9A%E7%83%AD%E6%90%9C",
            {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)"},
            "json_content_type",
        ),
        "xhs": (
            "https://www.xiaohongshu.com/explore",
            {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            "status200",
        ),
        "zhihu": (
            "https://www.zhihu.com/api/v4/me",
            {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            "status200",
        ),
        "xueqiu": (
            "https://xueqiu.com/statuses/hot/listV2.json?since_id=-1&max_id=-1&size=15",
            {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            "json_content_type",
        ),
        "joinquant": (
            "https://www.joinquant.com/user/index/isLogin",
            {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            "is_login",
        ),
    }
    if platform_id not in endpoints:
        return False
    url, headers, mode = endpoints[platform_id]
    headers = dict(headers)
    headers["Cookie"] = cookie
    try:
        resp = requests.get(url, headers=headers, timeout=_PROBE_TIMEOUT)
        if resp.status_code != 200:
            return False
        if mode == "json_content_type":
            return "json" in (resp.headers.get("Content-Type") or "").lower()
        if mode == "is_login":
            # 聚宽：登录态 JSON（data.isLogin==1 可达；0/缺省 → 未登录不可达）
            try:
                return resp.json().get("data", {}).get("isLogin") == 1
            except (ValueError, AttributeError):
                return False
        return True
    except requests.RequestException:
        return False


def probe_platform(platform):
    """判定单个平台可达性。platform 来自 config.SOCIAL_PLATFORMS。

    分类（platform["kind"]）：
    - rss（财联社/华尔街见闻）：RSSHub 路由能拉到条目 → 可达
    - cookie（微博/小红书/知乎/雪球/聚宽）：有 Cookie 且轻量探测通过 → 可达
    - none（X）：未实施访问逻辑，固定不可达（仅展示置灰）

    返回 (reachable: bool, reason: str)。
    """
    pid = platform["id"]
    kind = platform.get("kind") or ("cookie" if platform.get("needs_cookie") else "none")
    if kind == "none":
        return False, "未实施访问逻辑"
    if kind == "cookie":
        cookie = agent_db.platform_cookie_get(pid)
        if not cookie:
            keys = platform.get("cookie_keys") or []
            hint = f"（需要 key: {', '.join(keys)}）" if keys else ""
            return False, f"需要用户提供 Cookie{hint}"
        ok = _probe_cookie(pid, cookie)
        return ok, ("Cookie 探测通过" if ok else "Cookie 失效或探测失败")
    # rss 源（默认）
    ok = _probe_rsshub(pid)
    return ok, ("RSSHub 路由可达" if ok else "RSSHub 路由不可达")


def ensure_reachability(db=None):
    """首次启动全量判定：对全部 SOCIAL_PLATFORMS 探测并写缓存（幂等）。"""
    db = db or agent_db
    for platform in config.SOCIAL_PLATFORMS:
        try:
            reachable, reason = probe_platform(platform)
        except Exception as e:  # 探测异常保守置不可达
            reachable, reason = False, f"探测异常: {e}"
        db.reachability_set(platform["id"], reachable, reason)
    return get_reachability(db)


def refresh_platform(platform, db=None):
    """「爱逛的地方」刷新：对单个平台重新判定可达性（云库 Cookie → 浏览器 → 待办）。

    分类（platform["kind"]）：
    - rss（财联社/华尔街见闻）：与 probe 一致，RSSHub 多实例探测
    - cookie（微博/小红书/知乎/雪球）：
      1) 云库 Cookie 探测通过 → 可达
      2) 云库 Cookie 缺失/失效 → 查小满专属浏览器档案（本机浏览器）：
         有 Cookie 且探测通过 → 落库（platform_cookie_set）+ 可达
         无 / 探测不过 → 生成待办（新文案：请在本机登录xxx平台并在爱逛的地方刷新）
    - none（X）：固定不可达

    返回 {"platform_id", "reachable", "reason", "todo_created": bool}。
    """
    db = db or agent_db
    pid = platform["id"]
    kind = platform.get("kind") or ("cookie" if platform.get("needs_cookie") else "none")

    if kind == "none":
        db.reachability_set(pid, False, "未实施访问逻辑")
        return {"platform_id": pid, "reachable": False, "reason": "未实施访问逻辑", "todo_created": False}

    if kind == "cookie":
        cloud_cookie = db.platform_cookie_get(pid)
        if cloud_cookie and _probe_cookie(pid, cloud_cookie):
            db.reachability_set(pid, True, "Cookie 探测通过")
            return {"platform_id": pid, "reachable": True, "reason": "Cookie 探测通过", "todo_created": False}

        # 云库 Cookie 缺失/失效 → 查本机浏览器（小满专属档案）
        try:
            from agent.core import browser_cookies

            browser_cookie = browser_cookies.read_platform_cookie(pid)
        except Exception:
            browser_cookie = None

        if browser_cookie and _probe_cookie(pid, browser_cookie):
            db.platform_cookie_set(pid, browser_cookie)  # 本机浏览器 Cookie 有效 → 落库使用
            db.reachability_set(pid, True, "使用本机浏览器 Cookie")
            return {"platform_id": pid, "reachable": True, "reason": "使用本机浏览器 Cookie", "todo_created": False}

        # 浏览器 Cookie 也没有/无效 → 待办（新文案，小满语气）
        reason = "云库 Cookie 失效且本机浏览器无有效 Cookie" if cloud_cookie else "无 Cookie 且本机浏览器无 Cookie"
        db.reachability_set(pid, False, reason)
        try:
            from agent.core import notices

            nid = notices.create_cookie_todo(pid, reason="失效" if cloud_cookie else "无", db=db)
        except Exception:
            nid = None
        return {"platform_id": pid, "reachable": False, "reason": reason, "todo_created": nid is not None}

    # rss 源（默认）
    ok = _probe_rsshub(pid)
    reason = "RSSHub 路由可达" if ok else "RSSHub 路由不可达"
    db.reachability_set(pid, ok, reason)
    return {"platform_id": pid, "reachable": ok, "reason": reason, "todo_created": False}


def refresh_reachability(db=None):
    """「爱逛的地方」刷新：全量重判定全部平台。返回每平台结果列表。"""
    db = db or agent_db
    results = []
    for platform in config.SOCIAL_PLATFORMS:
        try:
            results.append(refresh_platform(platform, db=db))
        except Exception as e:  # 单平台异常不中断其余
            db.reachability_set(platform["id"], False, f"刷新异常: {e}")
            results.append(
                {
                    "platform_id": platform["id"],
                    "reachable": False,
                    "reason": f"刷新异常: {e}",
                    "todo_created": False,
                }
            )
    return results


def get_reachability(db=None):
    """读取全部平台可访问性缓存 → {platform_id: {reachable, checked_at, reason}}。"""
    db = db or agent_db
    cache = db.reachability_all()
    # 无缓存的平台：返回保守默认（未判定 → 不可达）
    for p in config.SOCIAL_PLATFORMS:
        cache.setdefault(
            p["id"], {"reachable": False, "checked_at": None, "reason": "未判定"}
        )
    return cache


def update_after_access(platform_id, ok, reason=None, db=None):
    """小满真实访问平台后回写缓存（访问成功→true，失败/超时/Cookie 失效→false）。"""
    db = db or agent_db
    db.reachability_set(
        platform_id, ok, reason or ("真实访问成功" if ok else "真实访问失败")
    )
