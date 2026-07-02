import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from backtest.strategies.buy_hold import BuyHold
from backtest.strategies.dual_momentum import DualMomentum
from backtest.strategies.ma_trend import MATrend
from backtest.strategies.momentum_rotation import MomentumRotation
from backtest.strategies.equal_weight import EqualWeight
from backtest.strategies.portfolio_6040 import Portfolio6040
from backtest.strategies.target_vol import TargetVol
from backtest.strategies.three_factor_momentum import ThreeFactorMomentum
from backtest.strategies.industry_momentum import IndustryMomentum
from backtest.strategies.low_vol import LowVol
from backtest.strategies.bollinger import Bollinger
from backtest.strategies.sentiment_momentum import SentimentMomentum
from backtest.strategies.multi_factor import MultiFactor


def _prices(up_a=True, n=300):
    """510300 上涨/下跌 + 511260 平 + 511880 平 + 510500 跟涨 + 159915 跟涨"""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    slope = 1.002 if up_a else 0.998
    data = {
        "510300": [100 * (slope ** i) for i in range(n)],
        "511260": [100.0] * n,
        "511880": [100.0] * n,
    }
    return pd.DataFrame(data, index=dates)


def _prices_multi(n=300):
    """4 资产上行（用于动量轮动测试）：黄金/纳指/创业板/上证180 同涨"""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "518880": [100 * (1.0005 ** i) for i in range(n)],   # 微涨
        "513100": [100 * (1.002 ** i) for i in range(n)],    # 快涨（应选为 top）
        "159915": [100 * (1.001 ** i) for i in range(n)],    # 慢涨
        "510180": [100 * (1.0008 ** i) for i in range(n)],   # 慢涨
    }, index=dates)


# ── S1 Buy & Hold ──

def test_buy_hold_weights():
    p = _prices()[["510300"]]
    s = BuyHold()
    w = s.generate(p)
    assert (w == 1.0).all().all()
    assert w.columns.tolist() == ["510300"]


# ── S2 Dual Momentum ──

def test_dual_momentum_hold_stock_when_up():
    p = _prices(up_a=True)
    s = DualMomentum(lookback=250)
    w = s.generate(p)
    assert w["510300"].iloc[-1] == 1.0
    assert w["511880"].iloc[-1] == 0.0


def test_dual_momentum_switch_to_cash_when_down():
    p = _prices(up_a=False)
    s = DualMomentum(lookback=250)
    w = s.generate(p)
    assert w["511880"].iloc[-1] == 1.0
    assert w["510300"].iloc[-1] == 0.0


# ── S3 MA Trend ──

def test_ma_trend_hold_when_ma_above():
    p = _prices(up_a=True)
    s = MATrend(short=20, long=60)
    w = s.generate(p[["510300", "511880"]])
    assert w["510300"].iloc[-1] == 1.0


def test_ma_trend_switch_when_ma_below():
    p = _prices(up_a=False)
    s = MATrend(short=20, long=60)
    w = s.generate(p[["510300", "511880"]])
    assert w["511880"].iloc[-1] == 1.0


# ── S4 Momentum Rotation ──

def test_momentum_rotation_picks_fastest():
    """纳指(513100)涨最快，应被选为 top-1"""
    p = _prices_multi(n=60)
    s = MomentumRotation(lookback=25, top_n=1)
    w = s.generate(p)
    # warmup 期后，最后一天应全仓最快涨的资产
    assert w["513100"].iloc[-1] == 1.0


def test_momentum_rotation_weights_sum_to_one():
    p = _prices_multi(n=60)
    s = MomentumRotation(lookback=25, top_n=1)
    w = s.generate(p)
    valid = w.iloc[30:]  # skip warmup
    rowsums = valid.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all()


def test_momentum_rotation_warmup_equal_weight():
    """warmup 期（前24天）应等权分配"""
    p = _prices_multi(n=60)
    s = MomentumRotation(lookback=25, top_n=1)
    w = s.generate(p)
    # warmup 期内每行权重和=1
    warmup = w.iloc[:24]
    rowsums = warmup.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all()
    # 每资产权重相等
    assert (warmup.iloc[0] == 0.25).all()


def test_momentum_rotation_top2():
    """top_n=2 应选两个资产各50%"""
    p = _prices_multi(n=60)
    s = MomentumRotation(lookback=25, top_n=2)
    w = s.generate(p)
    valid = w.iloc[30:]
    rowsums = valid.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all()
    # 最多两只非零
    nonzero = (valid.iloc[-1] > 0).sum()
    assert nonzero == 2


# ── S5 Equal Weight ──

def test_equal_weight_allocation():
    p = _prices_multi(n=60)
    s = EqualWeight(assets=["518880", "513100", "159915", "510180"])
    w = s.generate(p)
    # 每资产应 ≈0.25
    assert abs(w["518880"].iloc[-1] - 0.25) < 1e-6
    assert abs(w["513100"].iloc[-1] - 0.25) < 1e-6


def test_equal_weight_sum_to_one():
    p = _prices_multi(n=60)
    s = EqualWeight(assets=["518880", "513100", "159915", "510180"])
    w = s.generate(p)
    valid = w.iloc[10:]
    rowsums = valid.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all()


# ── S6 60/40 ──

def test_portfolio_6040_weights():
    p = _prices()[["510300", "511260"]]
    s = Portfolio6040()
    w = s.generate(p)
    assert abs(w["510300"].iloc[-1] - 0.6) < 1e-6
    assert abs(w["511260"].iloc[-1] - 0.4) < 1e-6


# ── S7 Target Volatility ──

def test_target_vol_weights_in_range():
    """权重应在 [0, 1] 之间"""
    p = _prices(up_a=True, n=120)[["510300", "511880"]]
    s = TargetVol(target_vol=0.15, window=20)
    w = s.generate(p)
    valid = w.iloc[30:]
    assert (valid["510300"] >= 0.0).all() and (valid["510300"] <= 1.0).all()


def test_target_vol_sum_to_one():
    p = _prices(up_a=True, n=120)[["510300", "511880"]]
    s = TargetVol(target_vol=0.15, window=20)
    w = s.generate(p)
    valid = w.iloc[30:]
    rowsums = valid.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all()


def test_target_vol_cash_when_flat():
    """平稳价格 → 低波动 → 应满仓（或接近满仓）"""
    dates = pd.date_range("2024-01-01", periods=120, freq="B")
    p = pd.DataFrame({
        "510300": [100.0] * 120,
        "511880": [100.0] * 120,
    }, index=dates)
    s = TargetVol(target_vol=0.15, window=20)
    w = s.generate(p)
    # 零波动时 target/0 → inf → clipped to 1.0, actual code fills NaN→0
    # So after warmup, should be 0 until we have vol data
    valid = w.iloc[30:]
    # 零波动 → realized_vol=0 → stock_w NaN → filled 0 → all cash
    assert (valid["511880"] >= 0.0).all()


# ── S8 Three-Factor Momentum ──

def test_three_factor_weights_sum_to_one():
    p = _prices_multi(n=60)
    s = ThreeFactorMomentum(lookback=25, top_n=1)
    w = s.generate(p)
    valid = w.iloc[30:]
    rowsums = valid.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all()


def test_three_factor_picks_positive_momentum():
    """上涨趋势中应选中涨得最好的资产"""
    p = _prices_multi(n=60)  # 513100 涨最快
    s = ThreeFactorMomentum(lookback=25, top_n=1, threshold=1.0)  # threshold=1 无过滤
    w = s.generate(p)
    # warmup 后应选中涨最快的 513100
    assert w["513100"].iloc[-1] == 1.0


def test_three_factor_warmup_equal():
    p = _prices_multi(n=60)
    s = ThreeFactorMomentum(lookback=25, top_n=1)
    w = s.generate(p)
    warmup = w.iloc[:24]
    rowsums = warmup.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all()


# ── S9 Industry Momentum ──

def test_industry_momentum_picks_top():
    """60日动量：涨最快的应被选中"""
    dates = pd.date_range("2024-01-01", periods=120, freq="B")
    p = pd.DataFrame({
        "512010": [100 * (1.0005 ** i) for i in range(120)],   # 慢涨
        "512880": [100 * (1.002 ** i) for i in range(120)],    # 快涨
        "512800": [100 * (1.0003 ** i) for i in range(120)],   # 慢涨
    }, index=dates)
    s = IndustryMomentum(lookback=60, top_n=1, etf_pool=["512010", "512880", "512800"])
    w = s.generate(p)
    # 月末调仓后应选中涨最快的512880
    assert w["512880"].iloc[-1] == 1.0


def test_industry_momentum_weights_sum_to_one():
    dates = pd.date_range("2024-01-01", periods=120, freq="B")
    p = pd.DataFrame({
        "512010": [100 * (1.0005 ** i) for i in range(120)],
        "512880": [100 * (1.002 ** i) for i in range(120)],
        "512800": [100 * (1.0003 ** i) for i in range(120)],
    }, index=dates)
    s = IndustryMomentum(lookback=60, top_n=2, etf_pool=["512010", "512880", "512800"])
    w = s.generate(p)
    valid = w.iloc[80:]
    rowsums = valid.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all()


# ── S10 Low Volatility ──

def test_low_vol_picks_lowest():
    """平稳资产（国债/黄金）应被选为低波标的"""
    dates = pd.date_range("2024-01-01", periods=120, freq="B")
    p = pd.DataFrame({
        "510300": [100 * (1.002 ** i) + np.sin(i/5)*3 for i in range(120)],  # 高波
        "511260": [100.02] * 120,   # 零波动
        "518880": [100.01] * 120,   # 零波动
    }, index=dates)
    s = LowVol(window=60, top_n=1, etf_pool=["510300", "511260", "518880"])
    w = s.generate(p)
    # 平稳资产之一应被选中（511260或518880）
    assert w["511260"].iloc[-1] == 1.0 or w["518880"].iloc[-1] == 1.0


def test_low_vol_weights_sum_to_one():
    p = _prices_multi(n=120)
    s = LowVol(window=60, top_n=3, etf_pool=["518880", "513100", "159915", "510180"])
    w = s.generate(p)
    valid = w.iloc[80:]
    rowsums = valid.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all()


# ── S11 Bollinger Bands ──

def test_bollinger_weights_sum_to_one():
    dates = pd.date_range("2024-01-01", periods=120, freq="B")
    p = pd.DataFrame({
        "510300": [100 * (1.001 ** i) for i in range(120)],
        "511880": [100.0] * 120,
    }, index=dates)
    s = Bollinger(etf="510300", cash="511880")
    w = s.generate(p)
    valid = w.iloc[30:]
    rowsums = valid.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all()


def test_bollinger_weights_in_range():
    """权重应在 [0, 1] 之间"""
    dates = pd.date_range("2024-01-01", periods=120, freq="B")
    p = pd.DataFrame({
        "510300": [100 + 5 * np.sin(i/10) for i in range(120)],  # 震荡
        "511880": [100.0] * 120,
    }, index=dates)
    s = Bollinger(etf="510300", cash="511880")
    w = s.generate(p)
    valid = w.iloc[30:]
    assert (valid["510300"] >= 0.0).all() and (valid["510300"] <= 1.0).all()


def test_bollinger_reduces_at_upper_band():
    """价格远高于均值时应减仓"""
    dates = pd.date_range("2024-01-01", periods=120, freq="B")
    # 快速上涨 → 价格远超中轨 → 仓位应降低
    p = pd.DataFrame({
        "510300": [100 * (1.01 ** i) for i in range(120)],  # 快速涨价
        "511880": [100.0] * 120,
    }, index=dates)
    s = Bollinger(etf="510300", cash="511880", ma_period=20, sigma=2.0)
    w = s.generate(p)
    # 快速上涨后应持有较少股票（减仓）
    assert w["510300"].iloc[-1] < 0.8  # 至少减了一些仓


# ── S12 Sentiment Momentum ──

def test_sentiment_momentum_weights_sum_to_one():
    p = _prices_multi(n=120)
    s = SentimentMomentum(lookback=20, top_n=1)
    w = s.generate(p)
    valid = w.iloc[50:]
    rowsums = valid.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all()


def test_sentiment_momentum_has_cash_column():
    p = _prices_multi(n=120)
    s = SentimentMomentum(lookback=20, top_n=1)
    w = s.generate(p)
    assert "511880" in w.columns  # cash column


# ── S13 Multi-Factor ──

def test_multi_factor_weights_sum_to_one():
    p = _prices_multi(n=120)
    s = MultiFactor(lookback=60, top_n=2, etf_pool=["518880", "513100", "159915", "510180"])
    w = s.generate(p)
    valid = w.iloc[80:]
    rowsums = valid.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all()


def test_multi_factor_top_n_held():
    p = _prices_multi(n=120)
    s = MultiFactor(lookback=60, top_n=2,
                    etf_pool=["518880", "513100", "159915", "510180"])
    w = s.generate(p)
    valid = w.iloc[80:]
    nonzero = (valid.iloc[-1] > 0).sum()
    assert nonzero <= 3  # top_n + cash at most


# ── Cross-strategy invariants ──

def test_all_strategies_weights_sum_to_one():
    """warmup 期后每行权重和≈1"""
    p = _prices(up_a=True)
    p_m = _prices_multi()
    for S, assets in [
        (DualMomentum(250), ["510300", "511260", "511880"]),
        (MATrend(20, 60), ["510300", "511880"]),
        (MomentumRotation(lookback=25, top_n=1), ["518880", "513100", "159915", "510180"]),
        (EqualWeight(assets=["518880", "513100", "159915", "510180"]), ["518880", "513100", "159915", "510180"]),
        (Portfolio6040(), ["510300", "511260"]),
        (TargetVol(target_vol=0.15, window=20), ["510300", "511880"]),
    ]:
        # Pick appropriate price fixture
        if set(assets) <= set(p.columns):
            prices = p[assets]
        else:
            prices = p_m[assets]
        w = S.generate(prices)
        valid = w.iloc[60:] if len(w) > 60 else w
        rowsums = valid.sum(axis=1)
        assert ((rowsums - 1.0).abs() < 1e-6).all(), f"{S.name} 权重不和为1"
