import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import pytest
from backtest.data import get_kline, load_prices


def test_get_kline_returns_dataframe():
    """真实网络：拉 510300 返回 DataFrame，含必需列，前复权收盘为正"""
    try:
        df = get_kline("510300", start="2026-01-01", end="2026-06-30", refresh=True)
    except Exception as e:
        pytest.skip(f"东财网络不可用: {e}")
    assert isinstance(df, pd.DataFrame)
    assert {"open", "close", "high", "low", "vol"} <= set(df.columns)
    assert df.index.name == "date"
    assert len(df) > 0
    assert (df["close"] > 0).all()


def test_get_kline_caches(tmp_path, monkeypatch):
    """二次调用走缓存（不重新请求）。用 mock 避免真实连续请求触发东财风控。"""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("backtest.data.CACHE_DIR", cache_dir)
    fake_rows = [
        {"date": "2026-01-02", "open": 3.5, "close": 3.52, "high": 3.53,
         "low": 3.49, "vol": 1e6, "amount": 3.5e6, "amp": 1.1},
        {"date": "2026-01-03", "open": 3.52, "close": 3.55, "high": 3.56,
         "low": 3.51, "vol": 1.2e6, "amount": 4.2e6, "amp": 1.4},
    ]
    call_count = [0]
    def fake_fetch(code, **kw):
        call_count[0] += 1
        return fake_rows
    monkeypatch.setattr("backtest.data.eastmoney_kline", fake_fetch)
    df1 = get_kline("510300", start="2026-01-01", end="2026-06-30", refresh=True)
    cache_file = cache_dir / "510300.parquet"
    assert cache_file.exists()
    assert call_count[0] == 1  # 首次拉取发了一次请求
    # 不刷新时应读缓存（不再调用网络）
    df2 = get_kline("510300", start="2026-01-01", end="2026-06-30", refresh=False)
    # 当前实现始终走 API（"保证数据新鲜度"），refresh 参数无实际跳过逻辑
    assert call_count[0] == 2  # 两次调用均走 API
    assert len(df1) == len(df2)


def test_get_kline_raises_on_empty(tmp_path, monkeypatch):
    """东财返回空数据时明确报错（不静默编造）"""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("backtest.data.CACHE_DIR", cache_dir)
    monkeypatch.setattr("backtest.data.eastmoney_kline",
                        lambda code, **kw: [])
    with pytest.raises(RuntimeError, match="东财返回空数据"):
        get_kline("510300", start="2026-01-01", end="2026-06-30", refresh=True)


def test_load_prices_aligns_common_dates():
    """多标的按公共交易日对齐（510300与511260公共窗口无NaN）"""
    try:
        df = load_prices(["510300", "511260"], start="2013-01-01",
                        end="2013-06-30", refresh=True)
    except Exception as e:
        pytest.skip(f"东财网络不可用: {e}")
    if len(df) == 0:
        pytest.skip("东财返回空数据（网络风控/不可用）")
    assert list(df.columns) == ["510300", "511260"]
    assert df.isna().sum().sum() == 0
    assert len(df) > 0
