#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""xhs_scroll.py — 模拟人类"刷小红书"的最小工具（Playwright + 系统 Chrome）。

思路（v1，个人研究用途）：
  1. login   —— 打开真实 Chrome，你在页面里扫码/手机号登录一次，登录态存本地 data/session.json；
  2. scroll  —— 用保存的登录态打开 /explore，像人一样慢慢往下滚，期间**抓页面自己发出的
                homefeed 接口响应**（签名由页面 JS 完成，我们只收结果），把笔记结构化落盘 JSONL；
  3. search  —— 到搜索页输入关键词，同样抓 search 接口响应，落盘候选；
  4. note    —— 打开单篇笔记，抓详情/评论接口响应，导出 markdown/JSON。

用法示例：
  python xhs_scroll.py login
  python xhs_scroll.py scroll --max-cards 20 --out data/feed.jsonl
  python xhs_scroll.py search "基金定投" --max-cards 10 --out data/search.jsonl
  python xhs_scroll.py note https://www.xiaohongshu.com/explore/<id> --with-comments --out data/note.md

注意：仅供你自己账号的个人阅读/研究；限速、低频、勿商用分发、勿批量对抗风控；
小红书 DOM/接口会变，字段取不到时以 JSON/DOM 兜底为准。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import sys
import time
import urllib.parse
from pathlib import Path

try:
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover
    sys.exit("需要 playwright：先执行 .venv\\Scripts\\python -m pip install -r requirements.txt")

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
SESSION = DATA / "session.json"
CACHE = DATA / "cache"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
FEED_API = "/api/sns/web/v1/homefeed"
SEARCH_API = "/api/sns/web/v1/search/notes"
FEED_NOTE_API = "/api/sns/web/v1/feed"
COMMENT_API = "/api/sns/web/v2/comment/page"
NOTE_ID_RE = re.compile(r"/explore/([0-9a-f]{24})")
NOTE_ID2_RE = re.compile(r"/(?:item|discovery|search_result)/[0-9a-f]{24}", re.I)


def out() -> None:
    """控制台 UTF-8（避免 GBK 打印中文报错）。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def jdump(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def jload(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def note_link(note_id: str) -> str:
    return f"https://www.xiaohongshu.com/explore/{note_id}"


def _clean_interact(info: dict | None) -> dict:
    info = info or {}
    return {
        "liked_count": info.get("liked_count"),
        "collected_count": info.get("collected_count"),
        "comment_count": info.get("comment_count"),
        "share_count": info.get("share_count"),
    }


def _item_to_card(item: dict) -> dict:
    """把 homefeed/search/feed 接口里的 note item 展平成一张卡片。

    web 首页 feed（2026 实测）结构：note_id 在 item 顶层；正文信息在 note_card，
    标题字段叫 display_title（video/normal 都是），desc 不在 feed 卡片里；
    xsec_token 在 item 顶层（打开详情页需要带）。
    """
    nc = item.get("note_card") or {}
    nid = item.get("id") or nc.get("note_id") or ""
    user = nc.get("user") or item.get("user") or {}
    tags = []
    for t in nc.get("tag_list") or []:
        n = t.get("name") or t.get("tagName")
        if n:
            tags.append(n)
    card = {
        "note_id": nid,
        "title": ((nc.get("display_title") or nc.get("title") or "") or "").strip(),
        "desc": (nc.get("desc") or "").strip(),
        "type": nc.get("type") or item.get("model_type") or item.get("note_type") or "",
        "link": note_link(nid) if nid else "",
        "xsec_token": item.get("xsec_token") or nc.get("xsec_token") or "",
        "cover": nc.get("cover") or {},
        "author": {
            "user_id": user.get("user_id") or "",
            "nickname": user.get("nickname") or user.get("nick_name") or "",
        },
        "interact": _clean_interact(nc.get("interact_info")),
        "tags": tags,
        "last_update_time": nc.get("last_update_time"),
    }
    return card


async def _launch(playwright, headed: bool, session_ok: bool):
    kw = {"channel": "chrome"}
    try:
        browser = await playwright.chromium.launch(**kw, headless=not headed)
    except Exception:
        # 备用：系统 Edge
        browser = await playwright.chromium.launch(channel="msedge", headless=not headed)
    kwargs = {"user_agent": UA, "viewport": {"width": 1280, "height": 900},
              "locale": "zh-CN", "timezone_id": "Asia/Shanghai"}
    if session_ok and SESSION.exists():
        kwargs["storage_state"] = str(SESSION)
    ctx = await browser.new_context(**kwargs)
    page = await ctx.new_page()
    return browser, ctx, page


def _captured(responses: list):
    def on_response(resp):
        url = resp.url
        if FEED_API in url or SEARCH_API in url or FEED_NOTE_API in url or COMMENT_API in url:
            asyncio.get_event_loop().create_task(_safe_json(resp, responses))
    return on_response


async def _safe_json(resp, responses):
    try:
        body = await resp.json()
    except Exception:
        return
    responses.append({"url": resp.url, "body": body})


def _pick_best(responses: list, needle: str, key: str = "items"):
    """从抓到的响应里挑出"看起来最完整"的那次（按数量）。"""
    best, best_n = None, -1
    for r in responses:
        if needle not in r["url"]:
            continue
        items = r["body"].get("data", {}).get(key) or []
        n = len(items) if isinstance(items, list) else 0
        if n > best_n:
            best, best_n = r["body"], n
    return best


async def _logged_in(page) -> bool:
    """粗略判断是否处于登录态：登录弹层消失 + 页面出现笔记卡或已登录菜单。"""
    try:
        await page.wait_for_timeout(2500)
        title = (await page.title()) or ""
        body = await page.evaluate("document.body ? document.body.innerText.slice(0,600) : ''")
        has_login_modal = ("登录后推荐" in body) or ("扫码登录" in body) or ("验证码" in body)
        has_avatar = await page.locator("div.user-info, span.user, img.avatar").count() > 0
        return not has_login_modal or has_avatar
    except Exception:
        return False


async def cmd_login(force: bool) -> int:
    if SESSION.exists() and not force:
        print(f"已有登录态 {SESSION}，如需重登加 --force")
        return 0
    DATA.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser, ctx, page = await _launch(p, headed=True, session_ok=False)
        await page.goto("https://www.xiaohongshu.com/", timeout=60000, wait_until="domcontentloaded")
        print("请在打开的 Chrome 里登录小红书（扫码或手机号）。检测到登录后会自动保存，无需按回车……")
        deadline = time.time() + 240  # 最多等 4 分钟
        while time.time() < deadline:
            if await _logged_in(page):
                break
            await page.wait_for_timeout(3000)
        state = await ctx.storage_state()
        jdump(state, SESSION)
        print(f"登录态已保存：{SESSION}")
        await browser.close()
    return 0


async def cmd_scroll(max_cards: int, max_scrolls: int, tag: str) -> list:
    if not SESSION.exists():
        sys.exit("还没有登录态，先执行: python xhs_scroll.py login")
    cards: dict[str, dict] = {}
    async with async_playwright() as p:
        browser, ctx, page = await _launch(p, headed=False, session_ok=True)
        responses: list = []
        page.on("response", _captured(responses))
        await page.goto("https://www.xiaohongshu.com/explore", timeout=60000,
                        wait_until="domcontentloaded")
        await page.wait_for_timeout(4000)
        for i in range(max_scrolls):
            await page.mouse.wheel(0, random.randint(500, 1400))
            await page.wait_for_timeout(random.randint(1800, 4200))
            best = _pick_best(responses, FEED_API)
            if best:
                for item in (best.get("data", {}).get("items") or []):
                    card = _item_to_card(item)
                    if card["note_id"]:
                        cards[card["note_id"]] = card
            print(f"[scroll {i+1}/{max_scrolls}] 已收集 {len(cards)} 张卡片", flush=True)
            if len(cards) >= max_cards:
                break
        await browser.close()
    result = list(cards.values())
    print(f"scroll 结束：共 {len(result)} 张卡片")
    return result


async def cmd_search(keyword: str, max_cards: int, max_scrolls: int) -> list:
    if not SESSION.exists():
        sys.exit("还没有登录态，先执行: python xhs_scroll.py login")
    cards: dict[str, dict] = {}
    async with async_playwright() as p:
        browser, ctx, page = await _launch(p, headed=False, session_ok=True)
        responses: list = []
        page.on("response", _captured(responses))
        url = "https://www.xiaohongshu.com/search_result?keyword=" + urllib.parse.quote(keyword)
        await page.goto(url, timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)
        for i in range(max_scrolls):
            await page.mouse.wheel(0, random.randint(400, 1000))
            await page.wait_for_timeout(random.randint(1800, 4200))
            best = _pick_best(responses, SEARCH_API, key="items")
            if best:
                for item in (best.get("data", {}).get("items") or []):
                    card = _item_to_card(item)
                    if card["note_id"]:
                        cards[card["note_id"]] = card
            print(f"[search {i+1}/{max_scrolls}] 已收集 {len(cards)} 条", flush=True)
            if len(cards) >= max_cards:
                break
        await browser.close()
    result = list(cards.values())
    print(f"search 结束：共 {len(result)} 条")
    return result


async def cmd_note(note_id_or_url: str, with_comments: bool, xsec_token: str | None = None) -> dict:
    if not SESSION.exists():
        sys.exit("还没有登录态，先执行: python xhs_scroll.py login")
    m = NOTE_ID_RE.search(note_id_or_url) or NOTE_ID2_RE.search(note_id_or_url)
    nid = m.group(1) if m else note_id_or_url
    url = note_link(nid)
    if xsec_token:
        url += f"?xsec_token={xsec_token}&xsec_source=pc_feed"
    async with async_playwright() as p:
        browser, ctx, page = await _launch(p, headed=False, session_ok=True)
        responses: list = []
        page.on("response", _captured(responses))
        await page.goto(url, timeout=60000, wait_until="domcontentloaded")
        # 详情接口可能要等图片/交互触发，多等 + 轻滚一下
        await page.wait_for_timeout(5000)
        await page.mouse.wheel(0, 600)
        await page.wait_for_timeout(3000)
        best = _pick_best([r for r in responses if "source_note_id=" in r["url"] or FEED_NOTE_API in r["url"]],
                          FEED_NOTE_API, key="items")
        note_data = None
        if best:
            for item in (best.get("data", {}).get("items") or []):
                if str(item.get("id", "")) == nid or (item.get("note_card") or {}).get("note_id") == nid:
                    note_data = _item_to_card(item)
                    break
            if note_data is None and best.get("data", {}).get("items"):
                note_data = _item_to_card(best["data"]["items"][0])
        # DOM 兜底：从页面正文元素抽标题/正文/作者/标签（接口字段缺失时用）
        dom = None
        try:
            dom = await page.evaluate(
                """() => {
                  const q = s => { const e = document.querySelector(s); return e ? e.innerText.trim() : ''; };
                  return {
                    title: q('#detail-title') || q('.note-content .title') || q('h1.title') || '',
                    desc: q('#detail-desc') || q('.note-scroller .desc') || q('.note-text') || '',
                    author: q('.user-nickname') || q('.author-wrapper .name') || q('.author .name') || '',
                    tags: q('.tag-items') || q('.tag') || ''
                  };
                }""")
        except Exception:
            dom = None
        if note_data is None:
            body = await page.evaluate("document.body ? document.body.innerText : ''")
            note_data = {"note_id": nid, "link": note_link(nid), "page_text": body[:4000]}
        if dom:
            if not (note_data.get("title") or "").strip():
                note_data["title"] = dom.get("title", "")
            if not (note_data.get("desc") or "").strip():
                note_data["desc"] = dom.get("desc", "")
            if not (note_data.get("author") or {}).get("nickname"):
                note_data.setdefault("author", {})["nickname"] = dom.get("author", "")
            if not note_data.get("tags"):
                note_data["tags"] = [t.strip() for t in dom.get("tags", "").split("#") if t.strip()]
        comments = []
        if with_comments:
            cbest = _pick_best([r for r in responses if COMMENT_API in r["url"]], COMMENT_API, key="comments")
            if cbest:
                for c in (cbest.get("data", {}).get("comments") or []):
                    comments.append({
                        "nickname": (c.get("user_info") or {}).get("nickname", ""),
                        "content": c.get("content", ""),
                        "like_count": c.get("like_count"),
                    })
            note_data["comments"] = comments[:50]
        await browser.close()
    return note_data


def _save(lines: list, out_path: str | None, kind: str) -> Path | None:
    if not out_path:
        return None
    p = Path(out_path).resolve()  # 相对路径按当前工作目录解析
    p.parent.mkdir(parents=True, exist_ok=True)
    if kind == "jsonl":
        with p.open("w", encoding="utf-8") as f:
            for ln in lines:
                f.write(json.dumps(ln, ensure_ascii=False) + "\n")
    else:  # markdown
        head = lines[0] if lines else {}
        text = [f"# {head.get('title') or head.get('note_id', '')}", "",
                f"- 链接：{head.get('link','')}",
                f"- 作者：{head.get('author',{}).get('nickname','')}",
                f"- 互动：{head.get('interact',{})}",
                f"- 标签：{' '.join(head.get('tags',[]))}", "",
                head.get("desc") or head.get("page_text", ""), ""]
        for c in head.get("comments", []):
            text.append(f"> {c.get('nickname','')}：{c.get('content','')}")
        p.write_text("\n".join(text), encoding="utf-8")
    print(f"已写出 {len(lines)} 条 → {p}")
    return p


def main() -> int:
    out()
    parser = argparse.ArgumentParser(description="模拟人类刷小红书（个人研究用途，低频限速）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("login", help="打开真实 Chrome 登录一次并保存登录态")
    pl.add_argument("--force", action="store_true", help="忽略已有登录态强制重登")

    ps = sub.add_parser("scroll", help="滚动刷发现页并把笔记卡片写 JSONL")
    ps.add_argument("--max-cards", type=int, default=30)
    ps.add_argument("--max-scrolls", type=int, default=15)
    ps.add_argument("--out", default=None)

    pk = sub.add_parser("search", help="搜索关键词并把结果写 JSONL")
    pk.add_argument("keyword")
    pk.add_argument("--max-cards", type=int, default=20)
    pk.add_argument("--max-scrolls", type=int, default=8)
    pk.add_argument("--out", default=None)

    pn = sub.add_parser("note", help="抓取单篇笔记（可含评论；详情页可能需要 feed/search 里的 xsec_token）")
    pn.add_argument("note", help="笔记 URL 或 24 位 note_id")
    pn.add_argument("--with-comments", action="store_true")
    pn.add_argument("--xsec-token", default=None, help="可选：打开详情页带的 xsec_token（从 JSONL 卡片里拿）")
    pn.add_argument("--out", default=None)

    args = parser.parse_args()
    if args.cmd == "login":
        return asyncio.run(cmd_login(args.force))
    if args.cmd == "scroll":
        cards = asyncio.run(cmd_scroll(args.max_cards, args.max_scrolls, ""))
        _save(cards, args.out, "jsonl")
        return 0
    if args.cmd == "search":
        cards = asyncio.run(cmd_search(args.keyword, args.max_cards, args.max_scrolls))
        _save(cards, args.out, "jsonl")
        return 0
    if args.cmd == "note":
        data = asyncio.run(cmd_note(args.note, args.with_comments, args.xsec_token))
        _save([data], args.out, "md")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
