"""
datapro_client.py 测试 — 火山专业数据集客户端（备源接入骨架）

覆盖: Key 配置检测 / headers 构造 / 无 Key 优雅降级 / HTTP 直连协议解析
（真实调用需 AGENT_PLAN_KEY，测试用 mock 验证协议正确性）
"""

import sys
from pathlib import Path

import pytest

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

import datapro_client as dp


class TestAvailability:
    def test_no_key_not_available(self, monkeypatch):
        monkeypatch.delenv("AGENT_PLAN_KEY", raising=False)
        assert dp.is_available() is False

    def test_with_key_available(self, monkeypatch):
        monkeypatch.setenv("AGENT_PLAN_KEY", "test-key")
        assert dp.is_available() is True

    def test_empty_key_not_available(self, monkeypatch):
        monkeypatch.setenv("AGENT_PLAN_KEY", "   ")
        assert dp.is_available() is False


class TestHeaders:
    def test_headers_with_key(self, monkeypatch):
        monkeypatch.setenv("AGENT_PLAN_KEY", "k-123")
        h = dp._headers()
        assert h["X-Agent-Plan-Key"] == "k-123"

    def test_headers_without_key(self, monkeypatch):
        monkeypatch.delenv("AGENT_PLAN_KEY", raising=False)
        assert dp._headers() == {}


class TestSearchDegrade:
    def test_search_without_key_returns_none(self, monkeypatch):
        """无 Key → 返回 None（调用方降级到 a-stock-data），不抛错。"""
        monkeypatch.delenv("AGENT_PLAN_KEY", raising=False)
        assert dp.datapro_search("002594 ROE") is None
        assert dp.datapro_search_http("002594 ROE") is None


class TestParseResult:
    def test_parse_items(self):
        class FakeContent:
            text = '{"items": [{"查询代码": "002594.SZ", "table": {"连涨天数": [2]}}]}'
        class FakeResult:
            isError = False
            content = [FakeContent()]
        items = dp._parse_result(FakeResult())
        assert items is not None
        assert items[0]["查询代码"] == "002594.SZ"

    def test_parse_is_error(self):
        class FakeResult:
            isError = True
            content = []
        assert dp._parse_result(FakeResult()) is None

    def test_parse_bad_json(self):
        class FakeContent:
            text = "not json"
        class FakeResult:
            isError = False
            content = [FakeContent()]
        assert dp._parse_result(FakeResult()) is None


class TestHttpDirect:
    def test_http_without_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("AGENT_PLAN_KEY", raising=False)
        assert dp.datapro_search_http("002594") is None

    def test_http_with_key_builds_request(self, monkeypatch):
        """有 Key → 构造 HTTP 请求（mock requests 验证协议）。"""
        monkeypatch.setenv("AGENT_PLAN_KEY", "k-456")
        calls = []

        class FakeResp:
            def __init__(self, payload, session_id=""):
                self._payload = payload
                self.headers = {"mcp-session-id": session_id}

            def json(self):
                return self._payload

        init_resp = FakeResp({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}}, "sess-1")
        call_resp = FakeResp({
            "jsonrpc": "2.0", "id": 2,
            "result": {"content": [{"type": "text", "text": '{"items": [{"查询代码": "600519.SH"}]}'}]},
        })

        def fake_post(url, headers=None, json=None, timeout=None):
            calls.append((url, headers, json))
            if json.get("method") == "initialize":
                return init_resp
            if json.get("method") == "tools/call":
                return call_resp
            return FakeResp({})

        monkeypatch.setattr("requests.post", fake_post)
        items = dp.datapro_search_http("600519 ROE")
        assert items is not None
        assert items[0]["查询代码"] == "600519.SH"
        # 验证认证 header
        init_call = calls[0]
        assert init_call[1]["X-Agent-Plan-Key"] == "k-456"
        # 验证 session id 传递
        assert "mcp-session-id" in calls[1][1]


class TestRealResponseFormat:
    """真实 DataPro 响应格式解析（2026-09-24 实测返回结构）。"""

    def test_parse_financial_items(self):
        """财务查询真实响应：证券代码 + table + field_meta。"""
        real = '''{"items": [{"证券代码": "002594.SZ", "table": {"财务分析/杜邦分析/净资产收益率ROE": [4.8612], "财务分析/盈利能力/净资产收益率ROE(TTM)": [12.265576658662], "盈利预测/盈利预测综合值(CONSENSUS,滚动)/预测净资产收益率(FY1)": [14.2143]}, "field_meta": {"财务分析/杜邦分析/净资产收益率ROE": {"caliber": {"报告期": "最新一期(MRQ)", "单位": "%"}}}}]}'''
        items = dp._parse_result(_mk_result(real))
        assert items is not None
        assert items[0]["证券代码"] == "002594.SZ"
        table = items[0]["table"]
        assert table["财务分析/杜邦分析/净资产收益率ROE"] == [4.8612]
        # field_meta 保留
        assert "field_meta" in items[0]

    def test_parse_kline_items(self):
        """日K真实响应：查询代码 + 行情序列。"""
        real = '''{"items": [{"查询代码": "600519.SH", "table": {"开盘价": [1252.15, 1255.03, null], "收盘价": [1253.8, 1251.24, null], "是否非交易日": [false, false, true]}}]}'''
        items = dp._parse_result(_mk_result(real))
        assert items is not None
        table = items[0]["table"]
        assert len(table["开盘价"]) == 3
        assert table["开盘价"][0] == 1252.15
        assert table["是否非交易日"][2] is True

    def test_parse_status_only_items(self):
        """状态查询（无实时价）：字段少但仍有 items。"""
        real = '''{"items": [{"查询代码": "600519.SH", "table": {"是否停牌": [false], "是否非交易日": [true]}}]}'''
        items = dp._parse_result(_mk_result(real))
        assert items is not None
        assert items[0]["table"]["是否非交易日"] == [True]


def _mk_result(text):
    class FakeContent:
        def __init__(self, t):
            self.text = t
    class FakeResult:
        isError = False
        content = [FakeContent(text)]
    return FakeResult()
