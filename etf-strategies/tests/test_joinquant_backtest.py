"""joinquant_backtest.py 测试：聚宽研究环境回测 API（路径 B2）。

无网络：所有 HTTP 用 monkeypatch mock；聚焦逻辑正确性：
- Cookie 解析（显式 > db > 浏览器）
- is_login 判定（mock /user/index/isLogin 响应）
- 回测摘要 HTML 解析（mock SPA 外壳）
- create_backtest / get_backtest_status 请求构造
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from automation.scripts import joinquant_backtest as jqb


class TestCookieResolution:
    def test_explicit_wins(self, monkeypatch):
        monkeypatch.setattr(jqb, "read_cookie_from_db", lambda: "db=cookie")
        assert jqb.resolve_cookie(explicit="explicit=cookie") == "explicit=cookie"

    def test_db_fallback(self, monkeypatch):
        monkeypatch.setattr(jqb, "read_cookie_from_db", lambda: "db=cookie")
        assert jqb.resolve_cookie() == "db=cookie"

    def test_browser_fallback(self, monkeypatch):
        monkeypatch.setattr(jqb, "read_cookie_from_db", lambda: None)
        monkeypatch.setattr(jqb, "read_cookie_from_browser", lambda: "browser=cookie")
        assert jqb.resolve_cookie(from_browser=True) == "browser=cookie"

    def test_none_when_all_missing(self, monkeypatch):
        monkeypatch.setattr(jqb, "read_cookie_from_db", lambda: None)
        monkeypatch.setattr(jqb, "read_cookie_from_browser", lambda: None)
        assert jqb.resolve_cookie() is None


class TestIsLoggedIn:
    def test_logged_in(self, monkeypatch):
        class R:
            status_code = 200

            def json(self):
                return {"data": {"isLogin": 1}}

        monkeypatch.setattr("requests.get", lambda *a, **k: R())
        assert jqb.is_logged_in("token=abc") is True

    def test_not_logged_in(self, monkeypatch):
        class R:
            status_code = 200

            def json(self):
                return {"data": {"isLogin": 0}}

        monkeypatch.setattr("requests.get", lambda *a, **k: R())
        assert jqb.is_logged_in("token=abc") is False

    def test_http_error(self, monkeypatch):
        class R:
            status_code = 500

        monkeypatch.setattr("requests.get", lambda *a, **k: R())
        assert jqb.is_logged_in("token=abc") is False

    def test_exception(self, monkeypatch):
        def boom(*a, **k):
            raise ConnectionError

        monkeypatch.setattr("requests.get", boom)
        assert jqb.is_logged_in("token=abc") is False


class TestFetchBacktestSummary:
    def test_parses_hidden_backtest_id(self, monkeypatch):
        html = (
            '<input type="hidden" id="backtest-status" value="done">'
            '<input type="hidden" id="backtestId" value="59e04f26a971249a2a44b091dbfe7c74">'
            "<html><body>页面内容</body></html>"
        )

        class R:
            status_code = 200
            text = html

        monkeypatch.setattr("requests.get", lambda *a, **k: R())
        out = jqb.fetch_backtest_summary("orig_id")
        assert out["request_backtest_id"] == "orig_id"
        assert out["resolved_backtest_id"] == "59e04f26a971249a2a44b091dbfe7c74"

    def test_non_200_returns_none(self, monkeypatch):
        class R:
            status_code = 500

        monkeypatch.setattr("requests.get", lambda *a, **k: R())
        assert jqb.fetch_backtest_summary("x") is None

    def test_exception_returns_none(self, monkeypatch):
        def boom(*a, **k):
            raise ConnectionError

        monkeypatch.setattr("requests.get", boom)
        assert jqb.fetch_backtest_summary("x") is None


class TestCreateBacktest:
    def test_builds_request_and_parses(self, monkeypatch):
        class R:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"data": {"backtestId": "bt123", "tradeDays": []}, "status": "0", "code": "00000"}

        captured = {}

        def fake_post(url, headers=None, data=None, timeout=None):
            captured["url"] = url
            captured["data"] = data
            captured["cookie"] = headers.get("Cookie")
            return R()

        monkeypatch.setattr("requests.post", fake_post)
        out = jqb.create_backtest(
            "algo456", "2020-01-01", "2026-09-30", "token=abc; uid=xyz",
            frequency="day", initial_cash="500000", name="test",
            algorithm_code="# 测试\npass", user_id="u123",
        )
        assert out["backtestId"] == "bt123"
        assert captured["cookie"] == "token=abc; uid=xyz"
        assert captured["url"].endswith("/algorithm/index/build?ajax=1")
        d = captured["data"]
        assert d["algorithm[algorithmId]"] == "algo456"
        assert d["backtest[startTime]"] == "2020-01-01 00:00:00"
        assert d["backtest[endTime]"] == "2026-09-30 23:59:59"
        assert d["backtest[frequency]"] == "day"
        assert d["backtest[baseCapital]"] == "500000"
        assert d["algorithm[code]"] == "# 测试\npass"
        assert d["encrType"] == "plain"

    def test_error_code_raises(self, monkeypatch):
        class R:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"data": None, "code": "20000", "msg": "参数错误", "status": "2"}

        monkeypatch.setattr("requests.post", lambda *a, **k: R())
        with pytest.raises(RuntimeError, match="创建回测失败"):
            jqb.create_backtest("a", "2020-01-01", "2026-09-30", "c=1")


class TestGetBacktestStatus:
    def test_parses_status(self, monkeypatch):
        class R:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"data": {"status": "done", "backtestId": "bt1"}, "code": "00000"}

        monkeypatch.setattr("requests.get", lambda *a, **k: R())
        out = jqb.get_backtest_status("bt1", "token=abc")
        assert out["data"]["status"] == "done"


class TestPollBacktest:
    def test_returns_when_done(self, monkeypatch):
        class R:
            status_code = 200

            def json(self):
                return {"data": {"status": "done"}}

        monkeypatch.setattr(jqb, "get_backtest_status", lambda bid, ck: R().json()["data"])
        out = jqb.poll_backtest("bt1", "c=1", interval=0, timeout=10)
        assert out["status"] == "done"

    def test_times_out(self, monkeypatch):
        import time

        def fake_status(bid, ck):
            return {"status": "running"}

        monkeypatch.setattr(jqb, "get_backtest_status", fake_status)
        monkeypatch.setattr(time, "sleep", lambda s: None)
        with pytest.raises(TimeoutError):
            jqb.poll_backtest("bt1", "c=1", interval=0, timeout=0.01)


class TestDeleteBacktest:
    def test_deletes(self, monkeypatch):
        class R:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"data": [], "status": "0", "code": "00000"}

        captured = {}

        def fake_post(url, headers=None, data=None, timeout=None):
            captured["url"] = url
            captured["data"] = data
            captured["cookie"] = headers.get("Cookie")
            return R()

        monkeypatch.setattr("requests.post", fake_post)
        out = jqb.delete_backtest("bt1", "token=abc")
        assert out["status"] == "0"
        assert captured["url"].endswith("/algorithm/backtest/del")
        assert captured["data"]["backtestId"] == "bt1"
        assert captured["cookie"] == "token=abc"
