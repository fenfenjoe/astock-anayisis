"""browser_cookies.py — 小满专属浏览器档案：本机浏览器 Cookie 读取与登录引导。

方案（2026-10，用户确认）：
- 小满维护一个**独立持久浏览器档案**（`agent/data/browser_profile/`），用
  `channel="chrome"` 复用本机 Chrome，与该用户日常浏览器完全隔离（互不干扰登录态）。
- `read_platform_cookie(platform_id)`：以持久档案启动浏览器，读取该平台域名下的
  Cookie，拼成 `k1=v1; k2=v2` 串返回；档案里没有该平台的 Cookie → 返回 None。
- `open_login_window(platform)`：打开 **headed** 浏览器窗口（同一持久档案）导航到
  平台首页/登录页，供用户登录。登录后 Cookie 会写入档案，下次 refresh 即可读到。
- 平台 → 域名映射集中在此（weibo.com / xiaohongshu.com / zhihu.com / xueqiu.com /
  joinquant.com）。

为什么从浏览器内部读（而不是解密 Chrome cookie 库）：
- Chrome 127+ 的 app-bound 加密（v20）让外部进程无法解密 cookie 库；浏览器运行中
  数据库还被独占锁。从浏览器内部（CDP）读 cookie 是唯一稳定、跨版本的方案。
- Playwright `channel="chrome"` 复用本机已装 Chrome，无需额外下载浏览器内核。

健壮性：
- playwright 未安装 / 启动失败 / 档案无该平台 cookie → 返回 None（上层回退待办）。
- 全程不接触用户日常浏览器档案，隐私隔离。
"""

import threading
import time

# 平台 → 域名列表（cookie 过滤用；含根域与 www 子域）
PLATFORM_DOMAINS = {
    "weibo": ["weibo.com", "weibo.cn", "m.weibo.cn"],
    "xhs": ["xiaohongshu.com", "www.xiaohongshu.com"],
    "zhihu": ["zhihu.com", "www.zhihu.com"],
    "xueqiu": ["xueqiu.com", "www.xueqiu.com"],
    "joinquant": ["joinquant.com", "www.joinquant.com"],
}

# 固定调试端口：headed 登录窗口常驻时，read 通过该端口连接读取（避免档案被占锁）
_DEBUG_PORT = 9223

# 登录窗口单例管理：共享档案 + 固定调试端口只允许同时开一个 headed 窗口。
# 打开新窗口前先通知旧窗口关闭（否则 Chrome 单实例会把新窗口卡在 about:blank）。
_ACTIVE = {"lock": threading.Lock(), "stop": None, "done": None, "thread": None}


def _profile_dir():
    """小满专属浏览器档案目录（agent/data/browser_profile/）。"""
    from agent import config

    return str(config.DATA_DIR / "browser_profile")


def platform_domains(platform_id) -> list[str]:
    """平台 → 域名列表；未知平台返回空列表。"""
    return PLATFORM_DOMAINS.get(platform_id, [])


def _cookie_string(cookies) -> str | None:
    """把 Playwright cookie 列表拼成 `k1=v1; k2=v2` 串。无有效 cookie → None。"""
    pairs = []
    for c in cookies or []:
        name = (c.get("name") or "").strip()
        value = (c.get("value") or "").strip()
        if name and value:
            pairs.append(f"{name}={value}")
    return "; ".join(pairs) if pairs else None


def _filter_by_domain(cookies, domains) -> list:
    """按平台域名过滤 cookie（domain 双向后缀匹配：根域/子域都算）。

    为什么不用 Playwright `context.cookies(urls)` 传裸域名：
    Playwright 驱动会对每个 url 执行 `new URL(s)`，裸域名（无 scheme）会抛
    `Invalid URL`，导致整次读取失败（BUG-1，2026-10 修复）。改为取全量 cookie
    后在 Python 侧按域名过滤，更稳、不依赖驱动 URL 解析。
    """
    out = []
    for c in cookies or []:
        cd = (c.get("domain") or "").lstrip(".")
        if not cd:
            continue
        for dom in domains:
            if cd == dom or cd.endswith("." + dom) or dom.endswith("." + cd):
                out.append(c)
                break
    return out


def _launch_persistent(headless: bool):
    """启动持久档案浏览器上下文。失败 → None（调用方回退）。"""
    from playwright.sync_api import sync_playwright

    p = sync_playwright().start()
    try:
        ctx = p.chromium.launch_persistent_context(
            _profile_dir(),
            channel="chrome",
            headless=headless,
            args=[f"--remote-debugging-port={_DEBUG_PORT}"],
            viewport={"width": 1280, "height": 860},
        )
        return p, ctx
    except Exception:
        try:
            p.stop()
        except Exception:
            pass
        return None, None


def read_platform_cookie(platform_id) -> str | None:
    """读取小满浏览器档案中某平台的 Cookie 串。无/失败 → None。

    优先连接常驻 headed 窗口（调试端口），避免档案被占锁；否则 headless 短启读取。
    取全量 cookie 后在 Python 侧按平台域名过滤（避免裸域名触发驱动 URL 解析异常）。
    """
    domains = platform_domains(platform_id)
    if not domains:
        return None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    # 1) 常驻窗口在跑 → 直接连接读取（不重启、不占锁冲突）
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{_DEBUG_PORT}")
            if browser.contexts:
                cookies = _filter_by_domain(browser.contexts[0].cookies(), domains)
                s = _cookie_string(cookies)
                if s:
                    return s
    except Exception:
        pass

    # 2) headless 短启读取（档案未被占用时）
    p, ctx = _launch_persistent(headless=True)
    if not ctx:
        return None
    try:
        cookies = _filter_by_domain(ctx.cookies(), domains)
        return _cookie_string(cookies)
    except Exception:
        return None
    finally:
        try:
            ctx.close()
        except Exception:
            pass
        try:
            p.stop()
        except Exception:
            pass


def _run_login_window(url, stop_evt, done_evt, prev_done):
    """守护线程：打开 headed 登录窗口。

    - prev_done：上一个窗口的 done 事件。非空则先等它完全关闭（释放共享档案 +
      固定调试端口），避免 Chrome 单实例把新窗口卡在 about:blank（BUG-2）。
    - stop_evt：收到 set 后提前关闭本窗口（新窗口替换 / 主动通知）。
    - 保持窗口最多 5 分钟；用户手动关闭窗口或收到替换通知 → 提前结束。
    """
    if prev_done is not None:
        prev_done.wait(30)
    try:
        p, ctx = _launch_persistent(headless=False)
        if not ctx:
            return
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                page.goto(url, timeout=60000, wait_until="domcontentloaded")
            except Exception:
                pass  # 导航失败也保持窗口（用户可手动操作/重试）
            deadline = time.time() + 300
            while time.time() < deadline:
                if stop_evt.is_set():
                    break
                try:
                    if page.is_closed():
                        break
                except Exception:
                    break
                time.sleep(1)
        finally:
            try:
                ctx.close()
            except Exception:
                pass
            try:
                p.stop()
            except Exception:
                pass
    except Exception:
        pass
    finally:
        if done_evt is not None:
            done_evt.set()


def open_login_window(platform) -> dict:
    """打开 headed 小满浏览器窗口导航到平台首页，供用户登录。

    单窗口串行：若已有登录窗口在开（共享档案 + 固定调试端口），先通知其关闭，
    新窗口等旧窗口完全释放后再启动，避免第二个窗口卡在 about:blank。
    返回 {"ok": bool, "message": str, "url": str}。
    """
    url = (platform or {}).get("url") or ""
    name = (platform or {}).get("name") or "该平台"
    if not url:
        return {"ok": False, "message": "平台缺少 URL，无法打开"}

    with _ACTIVE["lock"]:
        old_stop = _ACTIVE["stop"]
        old_done = _ACTIVE["done"]
        stop_evt = threading.Event()
        done_evt = threading.Event()
        _ACTIVE["stop"] = stop_evt
        _ACTIVE["done"] = done_evt
    if old_stop is not None:
        old_stop.set()  # 让旧窗口线程尽快关闭，释放档案/端口

    t = threading.Thread(
        target=_run_login_window,
        args=(url, stop_evt, done_evt, old_done),
        daemon=True,
        name="xm-login-window",
    )
    with _ACTIVE["lock"]:
        _ACTIVE["thread"] = t
    t.start()
    return {
        "ok": True,
        "message": f"已打开小满的浏览器窗口：{name}（请登录后关窗，Cookie 会自动保存）",
        "url": url,
    }
