import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pytest
from backtest.em_client import em_get, EM_SESSION, EM_MIN_INTERVAL, eastmoney_kline


def test_em_min_interval_is_positive():
    """限流间隔>=1秒（防封铁律）"""
    assert EM_MIN_INTERVAL >= 1.0


def test_eastmoney_kline_parses():
    """eastmoney_kline 解析为 dict 列表，含 date/open/close。
    真实网络：失败则 skip 而非误报（东财住宅IP偶发风控）。"""
    try:
        rows = eastmoney_kline("510300", start="20260101", end="20260630")
    except Exception as e:
        pytest.skip(f"东财网络不可用: {e}")
    assert len(rows) > 0
    assert "date" in rows[0] and "close" in rows[0]
    assert isinstance(rows[0]["close"], float)
    assert rows[0]["close"] > 0


def test_eastmoney_kline_parses_mocked(monkeypatch):
    """mock 响应验证解析逻辑（不依赖网络，快）"""
    fake = {
        "data": {
            "klines": [
                "2024-01-02,3.500,3.520,3.530,3.490,1000000,3510000.0,1.14",
                "2024-01-03,3.520,3.510,3.540,3.500,1200000,4220000.0,1.13",
            ]
        }
    }

    class FakeResp:
        status_code = 200
        def json(self):
            return fake

    monkeypatch.setattr("backtest.em_client.em_get",
                        lambda url, **kw: FakeResp())
    rows = eastmoney_kline("510300", start="20240101", end="20240131")
    assert len(rows) == 2
    assert rows[0]["date"] == "2024-01-02"
    assert rows[0]["open"] == 3.5
    assert rows[0]["close"] == 3.52
    assert rows[0]["high"] == 3.53
    assert rows[0]["amp"] == 1.14
