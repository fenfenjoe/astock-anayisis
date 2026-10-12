#!/usr/bin/env python3
"""fetch_joinquant_forum.py — 聚宽社区策略抓取（供 strategy_scan_weekly 使用）。

从聚宽社区（https://www.joinquant.com/view/community/list）抓取策略帖子，
按 ETF/指数相关关键词过滤，输出结构化候选列表（YAML），供策略发现任务评估。

登录态：
- 读取 agent.db（platform_cookies 表）中 joinquant 平台的 Cookie
- 用 /user/index/isLogin 校验登录态；未登录/无 Cookie → 提示用户先到
  Dashboard「角色页 → 认识小满 → 爱逛的地方」登录聚宽（与微博/小红书同流程）
- 列表 API（/community/post/listV2）实测匿名可访问，但为与"小满逛站"登录态
  一致，脚本仍以登录 Cookie 抓取（未登录时回退匿名抓取 + 明确标注登录态缺失）

用法：
    python etf-strategies/automation/scripts/fetch_joinquant_forum.py
    python etf-strategies/automation/scripts/fetch_joinquant_forum.py --pages 3 --limit 20
    python etf-strategies/automation/scripts/fetch_joinquant_forum.py --json   # 输出 JSON 而非 YAML

输出：
- 未登录：exit code 3 + stderr 提示（调用方 prompt 感知并生成"去登录"待办）
- 已登录：YAML 候选列表（title/url/like_count/content 摘要）
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 仓库根（scripts/ 的上级 = etf-strategies/）
SCRIPT_DIR = Path(__file__).resolve().parent
ETF_STRATEGIES_DIR = SCRIPT_DIR.parent.parent  # etf-strategies/
AGENT_DB = ETF_STRATEGIES_DIR / "agent" / "data" / "agent.db"

# 聚宽 API
BASE_URL = "https://www.joinquant.com"
LOGIN_CHECK_URL = BASE_URL + "/user/index/isLogin"
POST_LIST_URL = BASE_URL + "/community/post/listV2"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "X-Requested-With": "XMLHttpRequest",
}

# ETF/指数相关关键词（标题命中即视为候选；content 命中仅作补充提示）
ETF_KEYWORDS = [
    "ETF", "etf", "指数", "轮动", "动量", "宽基", "行业", "网格",
    "定投", "红利", "低波", "趋势", "均线", "SmartBeta", "smartbeta",
    "纳指", "沪深300", "中证500", "创业板", "科创", "债券ETF", "货币ETF",
]

# 与候选池已有策略明显重复/非策略类帖子（标题关键词排除）
SKIP_KEYWORDS = [
    "求助", "提问", "求教", "新人", "报错", "bug", "BUG", "卡死",
    "招聘", "广告", "推广", "课程", "直播", "活动",
]


def _read_joinquant_cookie():
    """读 agent.db platform_cookies 中 joinquant 的 Cookie 串；无/异常 → None。"""
    if not AGENT_DB.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{AGENT_DB}?mode=ro", uri=True, timeout=5)
        try:
            row = conn.execute(
                "SELECT cookie FROM platform_cookies WHERE platform_id=?",
                ("joinquant",),
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return None


def _is_logged_in(cookie):
    """聚宽登录态校验：/user/index/isLogin → data.isLogin==1。"""
    import requests

    try:
        headers = dict(HEADERS)
        if cookie:
            headers["Cookie"] = cookie
        r = requests.get(LOGIN_CHECK_URL, headers=headers, timeout=10)
        if r.status_code != 200:
            return False
        return r.json().get("data", {}).get("isLogin") == 1
    except Exception:
        return False


def _fetch_posts(cookie, pages, limit):
    """抓取社区帖子列表（listV2），翻 pages 页。返回帖子 dict 列表。"""
    import requests

    headers = dict(HEADERS)
    if cookie:
        headers["Cookie"] = cookie
    posts = []
    seen = set()
    for page in range(1, pages + 1):
        try:
            r = requests.get(
                POST_LIST_URL,
                headers=headers,
                params={"limit": limit, "page": page},
                timeout=15,
            )
            if r.status_code != 200:
                break
            data = r.json().get("data") or {}
            lst = data.get("list") or []
            if not lst:
                break
            for p in lst:
                pid = p.get("postId") or p.get("uniqueKey")
                if not pid or pid in seen:
                    continue
                seen.add(pid)
                posts.append(
                    {
                        "title": (p.get("title") or "").strip(),
                        "content": (p.get("content") or "").strip(),
                        "post_id": pid,
                        "unique_key": p.get("uniqueKey") or pid,
                        "like_count": p.get("likeCount") or 0,
                        "type": p.get("type"),
                    }
                )
        except Exception:
            break
    return posts


def _is_etf_related(post):
    """标题命中 ETF 关键词且未命中排除词 → 候选。"""
    title = post["title"]
    if not title:
        return False
    if any(kw.lower() in title.lower() for kw in SKIP_KEYWORDS):
        return False
    return any(kw.lower() in title.lower() for kw in ETF_KEYWORDS)


def _post_url(post):
    """帖子详情 URL（社区详情页）。"""
    key = post.get("unique_key") or post.get("post_id")
    return f"{BASE_URL}/view/community/detail/{key}"


def _to_yaml(posts):
    """把候选帖子转 YAML（策略发现任务第三/四步可直接复用）。"""
    lines = ["joinquant_posts:"]
    if not posts:
        lines.append("  # 未发现 ETF 相关候选")
        return "\n".join(lines)
    for p in posts:
        lines.append(f"  - title: {json.dumps(p['title'], ensure_ascii=False)}")
        lines.append(f"    url: {_post_url(p)}")
        lines.append(f"    like_count: {p['like_count']}")
        lines.append(f"    type: {p['type']}")
        content = (p.get("content") or "").replace("\n", " ")[:120]
        if content:
            lines.append(f"    content_preview: {json.dumps(content, ensure_ascii=False)}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="抓取聚宽社区 ETF 相关策略帖子")
    ap.add_argument("--pages", type=int, default=2, help="翻页数（默认 2）")
    ap.add_argument("--limit", type=int, default=20, help="每页条数（默认 20）")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非 YAML")
    args = ap.parse_args()

    cookie = _read_joinquant_cookie()
    logged_in = _is_logged_in(cookie)

    # 未登录 → 明确提示（exit 3），调用方 prompt 据此生成"去登录"待办
    if not logged_in:
        msg = (
            "聚宽未登录：请先在 Dashboard「角色页 → 认识小满 → 爱逛的地方」"
            "对聚宽点「去登录」，登录后刷新，小满才能带登录态抓取社区策略。"
        )
        print(json.dumps({"logged_in": False, "message": msg}, ensure_ascii=False))
        print(msg, file=sys.stderr)
        return 3

    posts = _fetch_posts(cookie, args.pages, args.limit)
    candidates = [p for p in posts if _is_etf_related(p)]
    # 按点赞数降序（社区热度 proxy）
    candidates.sort(key=lambda p: p["like_count"], reverse=True)

    if args.json:
        print(
            json.dumps(
                {
                    "logged_in": True,
                    "total_fetched": len(posts),
                    "candidates": candidates,
                    "urls": {c["title"]: _post_url(c) for c in candidates},
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"# 聚宽社区 ETF 相关策略（抓取 {len(posts)} 帖，候选 {len(candidates)}）")
        print(_to_yaml(candidates))
    return 0


if __name__ == "__main__":
    sys.exit(main())
