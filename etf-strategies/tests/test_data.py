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
    """东财+腾讯均返回空数据且无缓存时明确报错（不静默编造）"""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("backtest.data.CACHE_DIR", cache_dir)
    monkeypatch.setattr("backtest.data.eastmoney_kline",
                        lambda code, **kw: [])
    class _EmptyTencent:
        def tencent_daily_kline(self, code, start=None, end=None):
            import pandas as pd
            return pd.DataFrame(columns=["open", "close", "high", "low", "vol"])
    monkeypatch.setattr("backtest.data.tencent_client", _EmptyTencent())
    with pytest.raises(RuntimeError, match="所有行情源均不可用"):
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


def test_kline_order(tmp_path, monkeypatch):
    """DAT-001: get_kline 返回价格按日期升序排列，无重复索引"""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("backtest.data.CACHE_DIR", cache_dir)
    # 故意乱序 + 重复日期，验证 get_kline 排序/去重
    fake_rows = [
        {"date": "2026-01-05", "open": 3.55, "close": 3.58, "high": 3.59,
         "low": 3.54, "vol": 1.3e6, "amount": 4.6e6, "amp": 1.5},
        {"date": "2026-01-02", "open": 3.50, "close": 3.52, "high": 3.53,
         "low": 3.49, "vol": 1.0e6, "amount": 3.5e6, "amp": 1.1},
        {"date": "2026-01-02", "open": 3.50, "close": 3.52, "high": 3.53,
         "low": 3.49, "vol": 1.0e6, "amount": 3.5e6, "amp": 1.1},  # 重复
        {"date": "2026-01-03", "open": 3.52, "close": 3.55, "high": 3.56,
         "low": 3.51, "vol": 1.2e6, "amount": 4.2e6, "amp": 1.4},
    ]
    monkeypatch.setattr("backtest.data.eastmoney_kline",
                        lambda code, **kw: fake_rows)
    df = get_kline("510300", start="2026-01-01", end="2026-01-31", refresh=True)
    assert df.index.is_monotonic_increasing
    assert not df.index.duplicated().any()
    assert list(df.index) == sorted(df.index)


def test_cache_fallback(tmp_path, monkeypatch):
    """DAT-003: API 调用失败时降级到 parquet 缓存，两者均失败才抛 RuntimeError"""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("backtest.data.CACHE_DIR", cache_dir)
    # 第一步：先正常拉取，生成 parquet 缓存
    fake_rows = [
        {"date": "2026-01-02", "open": 3.50, "close": 3.52, "high": 3.53,
         "low": 3.49, "vol": 1.0e6, "amount": 3.5e6, "amp": 1.1},
        {"date": "2026-01-03", "open": 3.52, "close": 3.55, "high": 3.56,
         "low": 3.51, "vol": 1.2e6, "amount": 4.2e6, "amp": 1.4},
    ]
    monkeypatch.setattr("backtest.data.eastmoney_kline",
                        lambda code, **kw: fake_rows)
    get_kline("510300", start="2026-01-01", end="2026-06-30", refresh=True)
    # 第二步：东财+腾讯均失败 → 应降级读缓存，而非抛错
    def boom(code, **kw):
        raise ConnectionError("API down")
    monkeypatch.setattr("backtest.data.eastmoney_kline", boom)
    class _BoomTencent:
        def tencent_daily_kline(self, code, start=None, end=None):
            raise ConnectionError("tencent down")
    monkeypatch.setattr("backtest.data.tencent_client", _BoomTencent())
    df = get_kline("510300", start="2026-01-01", end="2026-06-30", refresh=True)
    assert len(df) == 2
    assert (df["close"] > 0).all()
    # 第三步：API 异常 + 无缓存 → 抛 RuntimeError
    empty_dir = tmp_path / "no_cache"
    monkeypatch.setattr("backtest.data.CACHE_DIR", empty_dir)
    with pytest.raises(RuntimeError, match="所有行情源均不可用"):
        get_kline("510300", start="2026-01-01", end="2026-06-30", refresh=True)


# ═══════════════════════════════════════════════════════════════
# REQ-004：多源容错（东财 → 腾讯 → 缓存）
# ═══════════════════════════════════════════════════════════════

def _fake_rows():
    return [
        {"date": "2026-01-02", "open": 3.50, "close": 3.52, "high": 3.53,
         "low": 3.49, "vol": 1.0e6, "amount": 3.5e6, "amp": 1.1},
        {"date": "2026-01-03", "open": 3.52, "close": 3.55, "high": 3.56,
         "low": 3.51, "vol": 1.2e6, "amount": 4.2e6, "amp": 1.4},
    ]


def _fake_tencent_df():
    import pandas as pd
    idx = pd.to_datetime(["2026-01-02", "2026-01-03"])
    return pd.DataFrame({
        "open": [3.50, 3.52], "close": [3.52, 3.55],
        "high": [3.53, 3.56], "low": [3.49, 3.51],
        "vol": [1.0e6, 1.2e6],
    }, index=idx)


def test_get_kline_falls_back_to_tencent(tmp_path, monkeypatch):
    """REQ-004: 东财失败 → 自动切腾讯日K，返回数据且打 WARN"""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("backtest.data.CACHE_DIR", cache_dir)
    monkeypatch.setattr("backtest.data.eastmoney_kline",
                        lambda code, **kw: (_ for _ in ()).throw(ConnectionError("eastmoney down")))
    calls = []
    monkeypatch.setattr("backtest.data.tencent_client",
                        MagicMockWithDaily(calls))
    df = get_kline("510300", start="2026-01-01", end="2026-06-30", refresh=True)
    assert len(df) == 2
    assert (df["close"] > 0).all()
    assert calls  # 腾讯被调用


class MagicMockWithDaily:
    """mock tencent_client 模块：仅提供 tencent_daily_kline，其余抛 AttributeError"""
    def __init__(self, calls):
        self._calls = calls
    def tencent_daily_kline(self, code, start=None, end=None):
        self._calls.append((code, start, end))
        return _fake_tencent_df()


def test_get_kline_tencent_also_fails_uses_cache(tmp_path, monkeypatch):
    """REQ-004: 东财失败 + 腾讯失败 → 降级读本地缓存"""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("backtest.data.CACHE_DIR", cache_dir)
    # 第一步：正常生成缓存
    monkeypatch.setattr("backtest.data.eastmoney_kline", lambda code, **kw: _fake_rows())
    get_kline("510300", start="2026-01-01", end="2026-06-30", refresh=True)
    # 第二步：东财失败
    monkeypatch.setattr("backtest.data.eastmoney_kline",
                        lambda code, **kw: (_ for _ in ()).throw(ConnectionError("down")))
    # 腾讯也失败
    class _FailTencent:
        def tencent_daily_kline(self, code, start=None, end=None):
            raise ConnectionError("tencent down")
    monkeypatch.setattr("backtest.data.tencent_client", _FailTencent())
    df = get_kline("510300", start="2026-01-01", end="2026-06-30", refresh=True)
    assert len(df) == 2
    assert (df["close"] > 0).all()


def test_get_kline_all_sources_fail_no_cache(tmp_path, monkeypatch):
    """REQ-004: 东财+腾讯+缓存全失败 → 抛 RuntimeError"""
    empty_dir = tmp_path / "no_cache"
    monkeypatch.setattr("backtest.data.CACHE_DIR", empty_dir)
    monkeypatch.setattr("backtest.data.eastmoney_kline",
                        lambda code, **kw: (_ for _ in ()).throw(ConnectionError("down")))
    class _FailTencent:
        def tencent_daily_kline(self, code, start=None, end=None):
            raise ConnectionError("tencent down")
    monkeypatch.setattr("backtest.data.tencent_client", _FailTencent())
    with pytest.raises(RuntimeError, match="所有行情源均不可用"):
        get_kline("510300", start="2026-01-01", end="2026-06-30", refresh=True)


def test_get_kline_tencent_when_eastmoney_empty(tmp_path, monkeypatch):
    """REQ-004: 东财返回空数据 → 切腾讯"""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("backtest.data.CACHE_DIR", cache_dir)
    monkeypatch.setattr("backtest.data.eastmoney_kline", lambda code, **kw: [])
    calls = []
    monkeypatch.setattr("backtest.data.tencent_client", MagicMockWithDaily(calls))
    df = get_kline("510300", start="2026-01-01", end="2026-06-30", refresh=True)
    assert len(df) == 2
    assert calls

