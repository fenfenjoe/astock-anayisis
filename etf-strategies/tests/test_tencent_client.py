"""腾讯财经客户端测试（backtest/tencent_client.py）。

数据来源：腾讯财经 HTTP API（qt.gtimg.cn / ifzq.gtimg.cn），免费不封IP。
测试策略：mock urllib.request.urlopen 返回样例响应，不依赖真实网络。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import json
import pytest
from unittest.mock import patch, MagicMock


# ═══════════════════════════════════════════════════════════════
# Fixtures：腾讯 API 样例响应
# ═══════════════════════════════════════════════════════════════

# qt.gtimg.cn 实时报价（GBK 编码，~ 分隔 88 字段）
SAMPLE_QUOTE_GBK = (
    'v_sh510300="1~沪深300ETF~510300~4.385~4.389~4.369~12767331~5728748~7038583~'
    '4.385~13539~4.384~1919~4.383~1969~4.382~1495~4.381~1022~4.386~1725~4.387~614~'
    '4.388~6906~4.389~17257~4.390~4708~~20261009161500~-0.004~-0.09~4.400~4.309~'
    '4.385/12767331/5564821743~12767331~556482~5.23~~~4.400~4.309~2.07~1069.60~'
    '1069.60~0.00~4.828~3.950~1.87~-11266~4.359~~~~556482.1743~90.5503~2065~A~ETF'
    '";\n'
)

# ifzq.gtimg.cn fqkline/get 日K（qfqday: [date, open, close, high, low, volume]）
SAMPLE_DAILY_JSON = {
    "code": 0, "msg": "", "data": {
        "sh510300": {
            "qfqday": [
                ["2026-10-08", "4.418", "4.389", "4.459", "4.358", "7508725.000"],
                ["2026-10-09", "4.369", "4.385", "4.400", "4.309", "12767331.000"],
            ],
            "qt": {"sh510300": ["1", "沪深300ETF"]},
        }
    }
}

# ifzq.gtimg.cn mkline 分钟K（m5: [datetime, open, close, high, low, volume, {}, amount]）
SAMPLE_MKLINE_JSON = {
    "code": 0, "msg": "", "data": {
        "sh510300": {
            "m5": [
                ["202610091345", "4.386", "4.385", "4.388", "4.385", "216047.000", {}, "8.978"],
                ["202610091350", "4.389", "4.388", "4.390", "4.387", "198552.000", {}, "7.511"],
            ],
            "qt": {"sh510300": ["1", "沪深300ETF"]},
        }
    }
}


def _mock_open(byte_payload: bytes, status=200):
    """构造 mock 的 urlopen 返回值（BytesIO + read()）。"""
    m = MagicMock()
    m.read.return_value = byte_payload
    m.status = status
    m.__enter__.return_value = m
    m.__exit__.return_value = False
    return m


# ═══════════════════════════════════════════════════════════════
# tencent_quote：批量实时报价解析
# ═══════════════════════════════════════════════════════════════

def test_quote_parses_gbk_fields():
    """qt.gtimg.cn GBK 响应 → 结构化 dict（现价/昨收/开高低/涨跌幅/PE/PB）"""
    from backtest import tencent_client
    with patch("urllib.request.urlopen", return_value=_mock_open(SAMPLE_QUOTE_GBK.encode("gbk"))):
        result = tencent_client.tencent_quote(["510300"])
    assert "510300" in result
    q = result["510300"]
    assert q["name"] == "沪深300ETF"
    assert q["price"] == pytest.approx(4.385)
    assert q["last_close"] == pytest.approx(4.389)
    assert q["open"] == pytest.approx(4.369)
    assert q["high"] == pytest.approx(4.400)
    assert q["low"] == pytest.approx(4.309)
    assert q["change_pct"] == pytest.approx(-0.09)
    assert q["vol_ratio"] == pytest.approx(1.87)    # 样例索引49
    assert q["mcap_yi"] == pytest.approx(1069.60)   # 样例索引44
    assert q["pe_ttm"] == 0.0                        # 样例索引39为空 → 0
    assert q["pb"] == 0.0                            # 样例索引46=0.00


def test_quote_batch_codes():
    """批量查询多个代码：URL 应包含全部代码"""
    from backtest import tencent_client
    captured = {}
    def fake_urlopen(req, timeout=10):
        captured["url"] = req.full_url
        return _mock_open(SAMPLE_QUOTE_GBK.encode("gbk"))
    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        tencent_client.tencent_quote(["510300", "159915"])
    assert "510300" in captured["url"]
    assert "159915" in captured["url"]


def test_quote_handles_empty_line():
    """空行/格式异常行应安全跳过，不抛异常"""
    from backtest import tencent_client
    bad_payload = 'v_sh510300="bad";\n;\n'.encode("gbk")
    with patch("urllib.request.urlopen", return_value=_mock_open(bad_payload)):
        result = tencent_client.tencent_quote(["510300"])
    assert "510300" not in result  # 解析失败不产出该 code


# ═══════════════════════════════════════════════════════════════
# tencent_daily_kline：日K（前复权）解析
# ═══════════════════════════════════════════════════════════════

def test_daily_kline_parses_qfqday():
    """fqkline/get qfqday → DataFrame（date/open/close/high/low/vol，升序）"""
    import pandas as pd
    from backtest import tencent_client
    payload = json.dumps(SAMPLE_DAILY_JSON).encode("utf-8")
    with patch("urllib.request.urlopen", return_value=_mock_open(payload)):
        df = tencent_client.tencent_daily_kline("510300", start="2026-10-08", end="2026-10-09")
    assert isinstance(df, pd.DataFrame)
    assert {"open", "close", "high", "low", "vol"} <= set(df.columns)
    assert df.index.name == "date"
    assert len(df) == 2
    # 腾讯 qfqday 字段序: [date, open, close, high, low, volume] —— open!=close 验证不串列
    assert df["open"].iloc[-1] == pytest.approx(4.369)
    assert df["close"].iloc[-1] == pytest.approx(4.385)
    assert df["high"].iloc[-1] == pytest.approx(4.400)
    assert df["low"].iloc[-1] == pytest.approx(4.309)
    assert df.index.is_monotonic_increasing


def test_daily_kline_returns_empty_on_missing_data():
    """data 缺失/空 → 返回空 DataFrame（不抛异常）"""
    from backtest import tencent_client
    payload = json.dumps({"code": 0, "msg": "", "data": {"sh510300": {}}}).encode("utf-8")
    with patch("urllib.request.urlopen", return_value=_mock_open(payload)):
        df = tencent_client.tencent_daily_kline("510300")
    assert len(df) == 0


# ═══════════════════════════════════════════════════════════════
# tencent_mkline：分钟K解析
# ═══════════════════════════════════════════════════════════════

def test_mkline_parses_minute_bars():
    """mkline m5 → DataFrame（datetime 索引，open/close/high/low/vol）"""
    import pandas as pd
    from backtest import tencent_client
    payload = json.dumps(SAMPLE_MKLINE_JSON).encode("utf-8")
    with patch("urllib.request.urlopen", return_value=_mock_open(payload)):
        df = tencent_client.tencent_mkline("510300", freq="m5")
    assert isinstance(df, pd.DataFrame)
    assert {"open", "close", "high", "low", "vol"} <= set(df.columns)
    assert len(df) == 2
    # 腾讯分钟字段序: [datetime, open, close, high, low, volume]
    assert df["close"].iloc[-1] == pytest.approx(4.388)
    assert df["open"].iloc[-1] == pytest.approx(4.389)
    assert df["high"].iloc[-1] == pytest.approx(4.390)
    # 索引含日期时间（可解析）
    assert pd.to_datetime(df.index[-1]) is not None


def test_mkline_rejects_invalid_freq():
    """非法 freq 参数应报 ValueError（m1/m5/m15/m30/m60 白名单）"""
    from backtest import tencent_client
    with pytest.raises(ValueError, match="freq"):
        tencent_client.tencent_mkline("510300", freq="m7")
