"""notices.py — 提示/待办（REQ-002）生成器 + 回复回调 dispatch。

提示（notice）：小满主动告知，无需用户回复，无回调。
待办（todo）：需要用户回复；回复后按 todo_type dispatch 执行对应逻辑。

内置生成器：
- create_cookie_todo(platform_id)：Cookie 类平台（微博/小红书/知乎/雪球）无 Cookie 时
  生成"请提供 Cookie"待办（去重：已有 open 同平台待办则不重复生成）

内置回调：
- cookie_provide：用户回复 Cookie 串 → 落库 platform_cookies + 重探测可达性回写

纯函数/依赖注入（db 参数），便于测试；不直接联网。
"""

import json

from agent import db as agent_db
from agent.core import reachability


def create_cookie_todo(platform_id, reason="无", db=None):
    """内置生成器：平台 Cookie 缺失/失效 → 生成"请提供 Cookie"待办（幂等去重）。

    reason: '无'（从未提供 Cookie）/ '失效'（Cookie 探测失败，需重新提供）。
    已有同平台 open 状态待办（无论 reason）→ 不重复生成（返回 None）。
    有 Cookie 且 reason='无' → 跳过（调用方未判失效，向后兼容）。
    返回新待办 id 或 None。
    """
    db = db or agent_db
    platform = _platform(platform_id, db)
    if not platform or platform.get("kind") != "cookie":
        return None
    cookie = db.platform_cookie_get(platform_id)
    if reason == "无" and cookie:
        return None  # 已有 Cookie 且未判失效，无需待办
    existing = db.notice_list(kind="todo", status="open", limit=100)
    for n in existing:
        if n.get("todo_type") == "cookie_provide" and (
            (n.get("todo_data") or {}).get("platform_id") == platform_id
        ):
            return None  # 已有未处理的同平台待办（含失效待办，幂等）
    keys = platform.get("cookie_keys") or []
    name = platform["name"]
    key_hint = f"（关键 key：{', '.join(keys)}）" if keys else ""
    # 新文案（2026-10，用户确认）：引导用户在本机登录平台后，回到「爱逛的地方」刷新
    # 由小满自动从浏览器档案取 Cookie —— 取代旧的"复制完整 Cookie 串回复给我"流程。
    if reason == "失效":
        content = (
            f"「{name}」不可访问啦～ 检测到 Cookie 可能过期了。麻烦你在本机浏览器登录一下 "
            f"{name}，然后回到「爱逛的地方」点一下刷新，我就能自动去取 Cookie 继续逛啦！"
            f"{key_hint}"
        )
    else:
        content = (
            f"「{name}」暂时逛不了啦～ 请在本机浏览器登录一下 {name}，然后回到「爱逛的地方」"
            f"点一下刷新，我就能自动去取 Cookie 啦！{key_hint}"
        )
    return db.notice_create(
        "todo",
        f"请在本机登录{name}后刷新",
        content,
        todo_type="cookie_provide",
        todo_data={"platform_id": platform_id},
        source="agent",
    )


def create_review_done_notice(summary, db=None):
    """内置生成器：复盘完成提示（来源=evening_review）。

    summary: 一句话总结（如"今日复盘完成，3 条信号已结算"）。
    返回新提示 id。
    """
    db = db or agent_db
    return db.notice_create(
        "notice",
        "复盘完成",
        summary or "今日复盘完成",
        source="evening_review",
    )


def ensure_cookie_todos(db=None):
    """启动时批量生成：所有 Cookie 类平台 无 Cookie 或 Cookie 失效（reachability 缓存判不可达）→ 生成待办。

    与 ensure_reachability 搭配：agent 常驻进程启动时**先**跑 ensure_reachability()
    （写 reachability 缓存），本函数随后读缓存识别失效平台（有 Cookie 但不可达 →
    失效待办），避免额外网络探测（2026-09-16 修复：之前只覆盖"无 Cookie"，
    Cookie 失效不会触发待办，用户无从得知登录态过期）。
    返回本次新生成待办 id 列表。
    """
    db = db or agent_db
    from agent import config

    created = []
    for p in config.SOCIAL_PLATFORMS:
        if p.get("kind") != "cookie":
            continue
        cookie = db.platform_cookie_get(p["id"])
        if cookie:
            # 有 Cookie：读 reachability 缓存判断是否失效
            cache = db.reachability_get(p["id"])
            if not cache or cache.get("reachable") is not False:
                continue  # 未判定（保守不打扰）或可达 → 不生成待办
            nid = create_cookie_todo(p["id"], reason="失效", db=db)
        else:
            nid = create_cookie_todo(p["id"], reason="无", db=db)
        if nid is not None:
            created.append(nid)
    return created


def dispatch_todo_reply(notice, reply, db=None):
    """待办回复回调 dispatch：按 todo_type 执行对应逻辑。

    notice: agent_notices 行（dict）。reply: 用户回复文本。
    返回 {"ok": bool, "message": str}。
    """
    db = db or agent_db
    todo_type = notice.get("todo_type")
    handlers = {
        "cookie_provide": _handle_cookie_provide,
    }
    handler = handlers.get(todo_type)
    if not handler:
        return {"ok": False, "message": f"未知待办类型: {todo_type}"}
    return handler(notice, reply, db)


def _handle_cookie_provide(notice, reply, db):
    """Cookie 提供：用户回复完整 Cookie 串 → 落库 + 重探测可达性。

    回复内容即 Cookie 串（去除首尾空白与常见引号包装）。
    """
    cookie = (reply or "").strip().strip('"').strip("'")
    if not cookie or len(cookie) < 4:
        return {"ok": False, "message": "回复内容太短，看起来不像 Cookie 串"}
    # todo_data 可能是 dict（本地 _row_dict 解析后）或 JSON 字符串（云端未解析）→ 归一化
    data = notice.get("todo_data") or {}
    if isinstance(data, str):
        try:
            data = json.loads(data) or {}
        except (json.JSONDecodeError, TypeError):
            data = {}
    platform_id = data.get("platform_id") if isinstance(data, dict) else None
    if not platform_id:
        return {"ok": False, "message": "待办缺少平台信息"}
    db.platform_cookie_set(platform_id, cookie)
    # 真实重探测：写回可达性缓存
    platform = _platform(platform_id, db)
    ok, reason = False, "平台不存在"
    if platform:
        try:
            ok, reason = reachability.probe_platform(platform)
        except Exception as e:  # 探测异常保守置不可达
            ok, reason = False, f"探测异常: {e}"
        db.reachability_set(platform_id, ok, reason)
    status = "可达啦" if ok else f"仍不可达（{reason}）"
    return {"ok": True, "message": f"已收到 Cookie 并重新探测：{platform_id} {status}"}


def _platform(platform_id, db):
    from agent import config

    return next(
        (p for p in config.SOCIAL_PLATFORMS if p["id"] == platform_id), None
    )
