"""agent 爱逛的地方「刷新」测试 — browser_cookies + reachability.refresh_platform + API。

覆盖（2026-10 新增，用户确认方案）：
- browser_cookies：平台域名映射、cookie 串拼接、playwright 缺失/启动失败回退 None
- reachability.refresh_platform：云库 Cookie → 本机浏览器 → 待办 三级级联
  - rss/none 平台：与 probe 一致（RSSHub 多实例 / 固定不可达）
  - cookie 平台：云库 Cookie 有效 → 可达；失效 → 读浏览器 Cookie → 有效落库+可达；
    浏览器也无/无效 → 生成待办（新文案）
- API：POST /api/agent/reachability/refresh、POST /api/agent/browser/open-login

无网络：requests 探测 monkeypatch；playwright 用 fake 对象；db 用 tmp_path 本地。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from agent import api as agent_api
from agent import config, db as agent_db
from agent.core import browser_cookies, notices, reachability
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _tmp_db(tmp_path, monkeypatch):
    agent_db.init_db(tmp_path / "agent.db")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "agent.db")
    yield
    agent_db.init_db(None)


def _json_resp(ok):
    """requests.get 假响应：ok=True → 200+application/json；ok=False → 200+text/html。

    带 json()（聚宽 is_login 探测解析 body：ok=True → isLogin=1）。"""

    class R:
        status_code = 200
        headers = {"Content-Type": "application/json; charset=UTF-8" if ok else "text/html; charset=UTF-8"}

        def json(self):
            return {"data": {"isLogin": 1 if ok else 0}, "status": "0", "code": "00000"}

    return R()


# ═══════════════════════════════════════════
# browser_cookies
# ═══════════════════════════════════════════


class TestBrowserCookies:
    @pytest.fixture(autouse=True)
    def _reset_active_windows(self):
        """每个用例后关闭并等待登录窗口线程结束（避免线程在解释器退出时崩溃）。"""
        yield
        with browser_cookies._ACTIVE["lock"]:
            t = browser_cookies._ACTIVE["thread"]
            stop = browser_cookies._ACTIVE["stop"]
            browser_cookies._ACTIVE["stop"] = None
            browser_cookies._ACTIVE["done"] = None
            browser_cookies._ACTIVE["thread"] = None
        if stop is not None:
            stop.set()
        if t is not None and t.is_alive():
            t.join(timeout=10)

    def test_platform_domains(self):
        assert "weibo.com" in browser_cookies.platform_domains("weibo")
        assert "xiaohongshu.com" in browser_cookies.platform_domains("xhs")
        assert "zhihu.com" in browser_cookies.platform_domains("zhihu")
        assert "xueqiu.com" in browser_cookies.platform_domains("xueqiu")
        assert "joinquant.com" in browser_cookies.platform_domains("joinquant")
        assert browser_cookies.platform_domains("cls") == []

    def test_cookie_string_basic(self):
        s = browser_cookies._cookie_string(
            [{"name": "SUB", "value": "abc"}, {"name": "XSRF", "value": "xyz"}]
        )
        assert s == "SUB=abc; XSRF=xyz"

    def test_cookie_string_skips_empty(self):
        s = browser_cookies._cookie_string(
            [{"name": "SUB", "value": "abc"}, {"name": "x", "value": ""}, {"name": "", "value": "v"}]
        )
        assert s == "SUB=abc"

    def test_cookie_string_none_when_empty(self):
        assert browser_cookies._cookie_string([]) is None
        assert browser_cookies._cookie_string(None) is None

    def test_filter_by_domain_root_and_www(self):
        """BUG-1 修复：域名过滤同时命中根域与 www 子域 cookie。"""
        cookies = [
            {"name": "PHPSESSID", "value": "s", "domain": ".joinquant.com"},
            {"name": "token", "value": "t", "domain": "www.joinquant.com"},
            {"name": "uid", "value": "u", "domain": ".joinquant.com"},
            {"name": "OTHER", "value": "x", "domain": ".example.com"},
            {"name": "no_domain", "value": "y", "domain": ""},
        ]
        got = browser_cookies._filter_by_domain(cookies, ["joinquant.com", "www.joinquant.com"])
        names = {c["name"] for c in got}
        assert names == {"PHPSESSID", "token", "uid"}

    def test_read_platform_cookie_headless_cookies_no_bare_domains(self, monkeypatch):
        """BUG-1 修复：read_platform_cookie 不再把裸域名传给 Playwright
        cookies()（驱动 new URL() 会抛 Invalid URL），改为取全量后按域名过滤。"""
        captured = {}

        class FakeCtx:
            def cookies(self, *a):
                captured["args"] = a
                return [
                    {"name": "token", "value": "t", "domain": ".joinquant.com"},
                    {"name": "uid", "value": "u", "domain": "www.joinquant.com"},
                    {"name": "OTHER", "value": "x", "domain": ".example.com"},
                ]

            def close(self):
                pass

        class FakeP:
            def stop(self):
                pass

        monkeypatch.setattr(browser_cookies, "_launch_persistent", lambda headless: (FakeP(), FakeCtx()))
        s = browser_cookies.read_platform_cookie("joinquant")
        assert captured["args"] == ()  # 不传域名参数
        assert s == "token=t; uid=u"

    def test_read_returns_none_when_playwright_missing(self, monkeypatch):
        """playwright 未安装 → 返回 None（上层回退待办，不崩）。"""
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "playwright.sync_api":
                raise ImportError("No module named 'playwright'")
            return real_import(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert browser_cookies.read_platform_cookie("weibo") is None

    def test_read_returns_none_when_launch_fails(self, monkeypatch):
        """启动失败（如 Chrome 不可用）→ None，不抛异常。"""
        # 函数内部是局部 import playwright.sync_api，patch 模块属性无效；
        # 直接 mock _launch_persistent 返回 (None, None)（等价于启动失败），
        # 并让 CDP 连接段快速失败（无服务在 9223 监听 → 连接拒绝）。
        monkeypatch.setattr(browser_cookies, "_launch_persistent", lambda headless: (None, None))
        assert browser_cookies.read_platform_cookie("weibo") is None

    def test_open_login_window_returns_ok(self, monkeypatch):
        """open_login_window：平台有 URL → 返回 ok（窗口由守护线程打开）。"""
        # mock 掉浏览器启动，避免测试里弹出真实 Chrome 窗口
        monkeypatch.setattr(browser_cookies, "_launch_persistent", lambda headless: (None, None))
        weibo = next(p for p in config.SOCIAL_PLATFORMS if p["id"] == "weibo")
        r = browser_cookies.open_login_window(weibo)
        assert r["ok"] is True
        assert r["url"] == weibo["url"]
        assert "小满" in r["message"]

    def test_open_login_window_missing_url(self, monkeypatch):
        r = browser_cookies.open_login_window({})
        assert r["ok"] is False

    def test_open_login_window_serializes_second_window(self, monkeypatch):
        """BUG-2 修复：打开第二个登录窗口时先通知第一个窗口关闭，
        避免共享档案 + 固定调试端口导致第二个窗口卡在 about:blank。"""
        monkeypatch.setattr(browser_cookies, "_launch_persistent", lambda headless: (None, None))
        weibo = next(p for p in config.SOCIAL_PLATFORMS if p["id"] == "weibo")
        zhihu = next(p for p in config.SOCIAL_PLATFORMS if p["id"] == "zhihu")

        r1 = browser_cookies.open_login_window(weibo)
        assert r1["ok"] is True
        with browser_cookies._ACTIVE["lock"]:
            stop1 = browser_cookies._ACTIVE["stop"]
            done1 = browser_cookies._ACTIVE["done"]
        assert stop1 is not None and done1 is not None
        assert stop1.is_set() is False

        r2 = browser_cookies.open_login_window(zhihu)
        assert r2["ok"] is True
        # 第二个窗口打开时，第一个窗口收到关闭通知
        assert stop1.is_set() is True


# ═══════════════════════════════════════════
# reachability.refresh_platform：云库 Cookie → 本机浏览器 → 待办
# ═══════════════════════════════════════════


class TestRefreshPlatform:
    def test_refresh_none_platform_fixed_unreachable(self):
        x = next(p for p in config.SOCIAL_PLATFORMS if p["id"] == "x")
        r = reachability.refresh_platform(x)
        assert r["reachable"] is False
        assert "未实施" in r["reason"]
        assert r["todo_created"] is False

    def test_refresh_rss_ok(self, monkeypatch):
        monkeypatch.setattr(
            reachability.knowledge, "fetch_feed",
            lambda feed, instance=None, timeout=None: [{"title": "条目"}],
        )
        cls = next(p for p in config.SOCIAL_PLATFORMS if p["id"] == "cls")
        r = reachability.refresh_platform(cls)
        assert r["reachable"] is True
        assert "RSSHub" in r["reason"]
        assert r["todo_created"] is False

    def test_refresh_rss_unreachable(self, monkeypatch):
        monkeypatch.setattr(
            reachability.knowledge, "fetch_feed",
            lambda feed, instance=None, timeout=None: [],
        )
        cls = next(p for p in config.SOCIAL_PLATFORMS if p["id"] == "cls")
        r = reachability.refresh_platform(cls)
        assert r["reachable"] is False
        assert "RSSHub" in r["reason"]

    def test_refresh_cloud_cookie_valid(self, monkeypatch):
        """云库 Cookie 有效 → 可达，不碰浏览器。"""
        agent_db.platform_cookie_set("weibo", "SUB=good")
        browser_called = []

        def fake_read(pid):
            browser_called.append(pid)
            return "SUB=browser"

        monkeypatch.setattr("requests.get", lambda *a, **k: _json_resp(True))
        monkeypatch.setattr(browser_cookies, "read_platform_cookie", fake_read)
        weibo = next(p for p in config.SOCIAL_PLATFORMS if p["id"] == "weibo")
        r = reachability.refresh_platform(weibo)
        assert r["reachable"] is True
        assert browser_called == []  # 云库有效 → 不读浏览器
        assert agent_db.platform_cookie_get("weibo") == "SUB=good"

    def test_refresh_cloud_cookie_expired_browser_valid_saves(self, monkeypatch):
        """云库 Cookie 失效 → 浏览器有有效 Cookie → 落库 + 可达。"""
        agent_db.platform_cookie_set("weibo", "SUB=expired")

        def fake_probe_cookie(pid, cookie):
            # 云库 Cookie（SUB=expired）失效；浏览器 Cookie（SUB=browser）有效
            return cookie == "SUB=browser"

        monkeypatch.setattr(reachability, "_probe_cookie", fake_probe_cookie)
        monkeypatch.setattr(browser_cookies, "read_platform_cookie", lambda pid: "SUB=browser")
        weibo = next(p for p in config.SOCIAL_PLATFORMS if p["id"] == "weibo")
        r = reachability.refresh_platform(weibo)
        assert r["reachable"] is True
        assert "本机浏览器" in r["reason"]
        # 浏览器 Cookie 已落库
        assert agent_db.platform_cookie_get("weibo") == "SUB=browser"
        assert r["todo_created"] is False

    def test_refresh_no_cloud_cookie_browser_valid_saves(self, monkeypatch):
        """云库无 Cookie → 浏览器有有效 Cookie → 落库 + 可达。"""
        monkeypatch.setattr("requests.get", lambda *a, **k: _json_resp(True))
        monkeypatch.setattr(
            browser_cookies, "read_platform_cookie", lambda pid: "z_c0=browser"
        )
        zhihu = next(p for p in config.SOCIAL_PLATFORMS if p["id"] == "zhihu")
        r = reachability.refresh_platform(zhihu)
        assert r["reachable"] is True
        assert agent_db.platform_cookie_get("zhihu") == "z_c0=browser"

    def test_refresh_cloud_expired_browser_invalid_creates_todo(self, monkeypatch):
        """云库失效 + 浏览器 Cookie 也无效 → 待办（新文案）。"""
        agent_db.platform_cookie_set("weibo", "SUB=expired")

        def fake_probe_cookie(pid, cookie):
            return False  # 云库与浏览器 Cookie 探测都不通过

        def fake_read(pid):
            return "SUB=browser"

        monkeypatch.setattr(reachability, "_probe_cookie", fake_probe_cookie)
        monkeypatch.setattr(browser_cookies, "read_platform_cookie", fake_read)
        weibo = next(p for p in config.SOCIAL_PLATFORMS if p["id"] == "weibo")
        r = reachability.refresh_platform(weibo)
        assert r["reachable"] is False
        assert r["todo_created"] is True
        todos = [
            n for n in agent_db.notice_list(kind="todo", status="open", limit=50)
            if n.get("todo_type") == "cookie_provide"
            and (n.get("todo_data") or {}).get("platform_id") == "weibo"
        ]
        assert todos
        assert "爱逛的地方" in todos[0]["content"]
        assert "刷新" in todos[0]["content"]

    def test_refresh_no_cookie_anywhere_creates_todo(self, monkeypatch):
        """云库无 Cookie + 浏览器无 Cookie → 待办。"""
        monkeypatch.setattr("requests.get", lambda *a, **k: _json_resp(False))
        monkeypatch.setattr(browser_cookies, "read_platform_cookie", lambda pid: None)
        xhs = next(p for p in config.SOCIAL_PLATFORMS if p["id"] == "xhs")
        r = reachability.refresh_platform(xhs)
        assert r["reachable"] is False
        assert r["todo_created"] is True
        todos = [
            n for n in agent_db.notice_list(kind="todo", status="open", limit=50)
            if n.get("todo_type") == "cookie_provide"
            and (n.get("todo_data") or {}).get("platform_id") == "xhs"
        ]
        assert todos
        assert "爱逛的地方" in todos[0]["content"]

    def test_refresh_reachability_all(self, monkeypatch):
        """全量刷新：遍历全部平台并写缓存。"""
        monkeypatch.setattr(
            reachability.knowledge, "fetch_feed",
            lambda feed, instance=None, timeout=None: [{"title": "条目"}],
        )
        monkeypatch.setattr("requests.get", lambda *a, **k: _json_resp(True))
        monkeypatch.setattr(
            browser_cookies, "read_platform_cookie",
            lambda pid: {"weibo": "SUB=b", "xhs": "a1=b", "zhihu": "z_c0=b",
                         "xueqiu": "xq_a=b", "joinquant": "token=b; uid=c"}.get(pid),
        )
        results = reachability.refresh_reachability()
        by_id = {r["platform_id"]: r for r in results}
        # 财联社/华尔街见闻 RSS 可达
        assert by_id["cls"]["reachable"] is True
        assert by_id["wallstreetcn"]["reachable"] is True
        # 微博/小红书/知乎/雪球/聚宽 浏览器 Cookie 有效 → 可达
        for pid in ("weibo", "xhs", "zhihu", "xueqiu", "joinquant"):
            assert by_id[pid]["reachable"] is True, pid
        # X 固定不可达
        assert by_id["x"]["reachable"] is False


# ═══════════════════════════════════════════
# API
# ═══════════════════════════════════════════


@pytest.fixture()
def client(tmp_path, monkeypatch):
    agent_db.init_db(tmp_path / "agent.db")
    monkeypatch.setattr(agent_api, "API_KEY", "")
    yield TestClient(agent_api.app)
    agent_db.init_db(None)


class TestRefreshApi:
    def test_reachability_refresh(self, client, monkeypatch):
        monkeypatch.setattr(
            reachability.knowledge, "fetch_feed",
            lambda feed, instance=None, timeout=None: [{"title": "条目"}],
        )
        monkeypatch.setattr("requests.get", lambda *a, **k: _json_resp(True))
        monkeypatch.setattr(
            browser_cookies, "read_platform_cookie",
            lambda pid: {"weibo": "SUB=b", "xhs": "a1=b", "zhihu": "z_c0=b",
                         "xueqiu": "xq_a=b", "joinquant": "token=b; uid=c"}.get(pid),
        )
        r = client.post("/api/agent/reachability/refresh")
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True
        assert d["total"] == len(config.SOCIAL_PLATFORMS)
        assert d["reachable_count"] >= 7  # cls/wallstreetcn/weibo/xhs/zhihu/xueqiu/joinquant

    def test_reachability_refresh_offline_reachable_state_persisted(self, client, monkeypatch):
        """刷新后 reachability 缓存已更新（前端 profile 读取新状态）。"""
        monkeypatch.setattr(
            reachability.knowledge, "fetch_feed",
            lambda feed, instance=None, timeout=None: [{"title": "条目"}],
        )
        r = client.post("/api/agent/reachability/refresh").json()
        assert agent_db.reachability_get("cls")["reachable"] is True

    def test_browser_open_login_unknown_platform(self, client):
        r = client.post("/api/agent/browser/open-login", json={"platform_id": "nope"})
        assert r.status_code == 400

    def test_browser_open_login_ok(self, client, monkeypatch):
        monkeypatch.setattr(
            browser_cookies, "open_login_window",
            lambda p: {"ok": True, "message": f"已打开小满的浏览器窗口：{p['name']}", "url": p["url"]},
        )
        r = client.post("/api/agent/browser/open-login", json={"platform_id": "xhs"})
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is True
        assert "小红书" in d["message"]


class TestDashboardProxyRefresh:
    """dashboard/api_agent.py 代理层契约：转发 + 降级。"""

    @pytest.fixture()
    def proxy_client(self, monkeypatch):
        from dashboard import api_agent as proxy_mod
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(proxy_mod.router)
        app.dependency_overrides[proxy_mod.get_current_user] = lambda: {
            "username": "tester", "role": "admin",
        }
        yield proxy_mod, TestClient(app)
        app.dependency_overrides.clear()

    def test_proxy_refresh(self, proxy_client, monkeypatch):
        proxy_mod, c = proxy_client
        monkeypatch.setattr(
            proxy_mod, "_proxy_post",
            lambda path, body=None: {"ok": True, "results": [], "reachable_count": 0, "total": 0},
        )
        d = c.post("/api/agent/reachability/refresh").json()
        assert d["ok"] is True

    def test_proxy_refresh_offline(self, proxy_client, monkeypatch):
        proxy_mod, c = proxy_client
        monkeypatch.setattr(proxy_mod, "_proxy_post", lambda path, body=None: None)
        d = c.post("/api/agent/reachability/refresh").json()
        assert d["ok"] is False
        assert "不可达" in d["error"]

    def test_proxy_open_login_ok(self, proxy_client, monkeypatch):
        proxy_mod, c = proxy_client
        seen = {}

        def _fake_post(path, body=None):
            seen["path"] = path
            seen["body"] = body
            return {"ok": True, "message": "ok", "url": "https://x.com"}

        monkeypatch.setattr(proxy_mod, "_proxy_post", _fake_post)
        d = c.post("/api/agent/browser/open-login", json={"platform_id": "xhs"}).json()
        assert seen["path"] == "/browser/open-login"
        assert seen["body"] == {"platform_id": "xhs"}
        assert d["ok"] is True

    def test_proxy_open_login_offline(self, proxy_client, monkeypatch):
        proxy_mod, c = proxy_client
        monkeypatch.setattr(proxy_mod, "_proxy_post", lambda path, body=None: None)
        d = c.post("/api/agent/browser/open-login", json={"platform_id": "xhs"}).json()
        assert d["ok"] is False
