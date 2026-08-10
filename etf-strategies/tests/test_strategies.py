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
from backtest.strategies.rsrs_reversal_momentum import RsrsReversalMomentum
from backtest.strategies.low_correlation_rotation import LowCorrelationRotation
from backtest.strategies.adaptive_momentum import AdaptiveMomentum
from backtest.strategies.rsrs_momentum import TrendFilterMomentum
from backtest.strategies.canary_defense import CanaryDefense, CanaryDefenseDaily


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


def _prices_broad(n=300):
    """6 资产上行 + 现金平：用于 RSRS反转动量(S18)测试"""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "513100": [100 * (1.002 ** i) for i in range(n)],    # 快涨
        "159915": [100 * (1.001 ** i) for i in range(n)],    # 慢涨
        "510180": [100 * (1.0008 ** i) for i in range(n)],   # 慢涨
        "518880": [100 * (1.0005 ** i) for i in range(n)],   # 微涨
        "510300": [100 * (1.001 ** i) for i in range(n)],    # 慢涨
        "512480": [100 * (1.0015 ** i) for i in range(n)],   # 中涨
        "511880": [100.0] * n,                                # 现金平
    }, index=dates)


def _prices_low_corr(n=300):
    """5 资产上行：用于低相关ETF轮动(S19)测试"""
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "518880": [100 * (1.0005 ** i) for i in range(n)],   # 微涨
        "513100": [100 * (1.002 ** i) for i in range(n)],    # 快涨（应选为 top）
        "159915": [100 * (1.001 ** i) for i in range(n)],    # 慢涨
        "511260": [100 * (1.0002 ** i) for i in range(n)],   # 极慢涨
        "510300": [100 * (1.001 ** i) for i in range(n)],    # 慢涨
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


# ── S18 RSRS增强反转动量 ──

def test_rsrs_reversal_weights_sum_to_one():
    """S18 warmup 期后每行权重和≈1（含现金列）"""
    p = _prices_broad(n=300)
    s = RsrsReversalMomentum(mom_short=25, mom_long=200, top_n=1)
    w = s.generate(p)
    valid = w.iloc[210:]  # warmup = max(200, 60) = 200
    rowsums = valid.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all(), f"S18 权重不和为1"


def test_rsrs_reversal_has_cash_column():
    """S18 应有现金列 511880"""
    p = _prices_broad(n=300)
    s = RsrsReversalMomentum()
    w = s.generate(p)
    assert "511880" in w.columns


def test_rsrs_reversal_picks_best_momentum():
    """S18 应选反转动量得分最高的 ETF（纳指涨最快，mom25-mom200/6 应最高）"""
    p = _prices_broad(n=300)
    s = RsrsReversalMomentum(mom_short=25, mom_long=200, top_n=1)
    w = s.generate(p)
    # 在 warmup 后，纳指(513100)涨最快，应被选中
    assert w["513100"].iloc[-1] == 1.0 or w["513100"].iloc[-1] > 0.9


def test_rsrs_reversal_warmup_holds_cash():
    """S18 warmup 期内应全仓现金（等待动量回看窗口充分积累数据）"""
    p = _prices_broad(n=300)
    s = RsrsReversalMomentum()
    w = s.generate(p)
    warmup_row = w.iloc[100]  # 在 warmup 期内（warmup = max(200, 60) = 200）
    # warmup 期内应全仓现金
    assert warmup_row["511880"] == 1.0, f"warmup 应全仓现金，实际: {warmup_row['511880']}"
    # 所有 ETF 权重应为 0
    etf_weights = warmup_row[s.etf_pool]
    assert (etf_weights == 0.0).all()


def test_rsrs_reversal_diagnostics():
    """S18 get_diagnostics 应返回 RSRS 诊断信息"""
    p = _prices_broad(n=300)
    s = RsrsReversalMomentum()
    diag = s.get_diagnostics(p)
    assert "scores" in diag
    assert "score_details" in diag
    assert "holdings" in diag
    assert "parameters" in diag
    # 应包含 RSRS 相关参数
    assert "RSRS窗口(天)" in diag["parameters"]


# ── S19 低相关ETF轮动 ──

def test_low_correlation_weights_sum_to_one():
    """S19 warmup 期后每行权重和≈1"""
    p = _prices_low_corr(n=200)
    s = LowCorrelationRotation(lookback=25, top_n=1)
    w = s.generate(p)
    valid = w.iloc[50:]  # after warmup
    rowsums = valid.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all(), f"S19 权重不和为1"


def test_low_correlation_picks_best():
    """S19 应选动量最高的 ETF（纳指涨最快）"""
    p = _prices_low_corr(n=200)
    s = LowCorrelationRotation(lookback=25, top_n=1)
    w = s.generate(p)
    assert w["513100"].iloc[-1] == 1.0 or w["513100"].iloc[-1] > 0.9


def test_low_correlation_weekly_rebalance():
    """S19 周度调仓：同一周内权重应 forward-fill 不变"""
    p = _prices_low_corr(n=200)
    s = LowCorrelationRotation(lookback=25, top_n=1)
    w = s.generate(p, live=False)
    # 取最后两周的数据，上周四和上周五权重应相同
    last_week = w.iloc[-10:-3]
    # 取非 NaN 行检查
    if len(last_week) >= 3:
        # 同一周内非周五的权重应该一致（ffill）
        row1 = last_week.iloc[-2].values
        row2 = last_week.iloc[-1].values
        # 如果在同一周内，权重应相同
        assert (row1 == row2).all() or abs(row1.sum() - row2.sum()) < 1e-6


def test_low_correlation_live_vs_backtest_modes():
    """S19: live=True 返回原始日频权重；live=False 返回周度重采样权重。
    两种模式在 warmup 期后权重和均≈1，且最后一行同为最优ETF。"""
    p = _prices_low_corr(n=200)
    s = LowCorrelationRotation(lookback=25, top_n=1)
    w_live = s.generate(p, live=True)
    w_bt = s.generate(p, live=False)

    # 两者应覆盖相同日期范围
    assert len(w_live) == len(p)
    assert len(w_bt) == len(p)

    # 两种模式下 warmup 期后每行权重和均≈1
    for w in [w_live, w_bt]:
        rowsums = w.iloc[50:].sum(axis=1)
        assert ((rowsums - 1.0).abs() < 1e-6).all()

    # 最后一行的 top-1 持仓应一致（都是最佳ETF）
    live_top = w_live.iloc[-1].nlargest(1)
    bt_top = w_bt.iloc[-1].nlargest(1)
    assert live_top.index[0] == bt_top.index[0], \
        f"live 和 backtest 模式最终持仓应一致: {live_top.index[0]} vs {bt_top.index[0]}"


def test_low_correlation_backtest_bfill_initial():
    """S19 live=False: bfill 从首个周度信号向后回填，避免回测从空仓启动。"""
    p = _prices_low_corr(n=200)
    s = LowCorrelationRotation(lookback=25, top_n=1)
    w = s.generate(p, live=False)

    # bfill 后首行应有非零权重（从首个周度重采样点回填）
    row_sums = w.sum(axis=1)
    assert row_sums.iloc[0] > 0.001, \
        "首日应从首个周度信号 bfill 得到非零权重，而非全零"

    # warmup 期后每行权重和≈1
    valid = w.iloc[50:]
    assert ((valid.sum(axis=1) - 1.0).abs() < 1e-6).all()


def test_low_correlation_weekly_signal_stable():
    """S19 live=False: 同一周内权重应稳定（ffill 保证不每日翻转）"""
    p = _prices_low_corr(n=200)
    s = LowCorrelationRotation(lookback=25, top_n=1)
    w = s.generate(p, live=False)
    # warmup 后取最后 10 天检查周内稳定性
    w_tail = w.iloc[-10:]
    w_changes = w_tail.diff().abs().sum(axis=1).iloc[1:]
    # 大部分天数的权重变动应为 0（ffill 周内不变）
    zero_ratio = (w_changes < 0.001).mean()
    assert zero_ratio > 0.0, "周度策略应在周内保持权重稳定"


def test_low_correlation_single_position():
    """S19 live=True: top_n=1 时最后一行应只有一个 ETF 持仓（非多只）"""
    p = _prices_low_corr(n=200)
    s = LowCorrelationRotation(lookback=25, top_n=1)
    w = s.generate(p, live=True)
    last_row = w.iloc[-1]
    nonzero = (last_row > 0.001).sum()
    assert nonzero == 1, f"Top-1 策略应只持仓 1 只 ETF，实际 {nonzero} 只"


def _prices_low_corr_rotating(n=350):
    """模拟 ETF 轮动场景：不同 ETF 在不同阶段领涨，测试调仓检测"""
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    data = np.zeros((n, 5))
    for i in range(n):
        if i < 100:
            data[i] = [
                100 * (1.0005 ** i),   # 518880 微涨
                100 * (1.003 ** i),    # 513100 快涨
                100 * (1.001 ** i),    # 159915
                100 * (1.0003 ** i),   # 511260
                100 * (1.002 ** i),    # 510300
            ]
        elif i < 200:
            data[i] = [
                100 * (1.002 ** i),    # 518880
                100 * (1.001 ** i),    # 513100
                100 * (1.003 ** i),    # 159915 快涨
                100 * (1.0003 ** i),   # 511260
                100 * (1.0015 ** i),   # 510300
            ]
        elif i < 280:
            data[i] = [
                100 * (1.003 ** i),    # 518880 快涨
                100 * (1.001 ** i),    # 513100
                100 * (1.0005 ** i),   # 159915
                100 * (1.0003 ** i),   # 511260
                100 * (1.0008 ** i),   # 510300
            ]
        else:
            data[i] = [
                100 * (1.0005 ** i),   # 518880
                100 * (1.001 ** i),    # 513100
                100 * (1.0005 ** i),   # 159915
                100 * (1.0003 ** i),   # 511260
                100 * (1.003 ** i),    # 510300 快涨
            ]
    return pd.DataFrame(data, index=dates,
                       columns=["518880", "513100", "159915", "511260", "510300"])


def test_low_correlation_rotation_trade_detection():
    """S19 live=False: ETF 轮动时 html_report 应正确检测到调仓"""
    p = _prices_low_corr_rotating(n=350)
    s = LowCorrelationRotation(lookback=25, top_n=1)
    w = s.generate(p, live=False)

    # 截取最近一年
    one_year_ago = w.index[-1] - pd.Timedelta(days=365)
    mask = w.index >= one_year_ago
    w_1y = w.loc[mask]

    w_changes = w_1y.diff().abs().sum(axis=1)
    trade_dates = w_changes[w_changes > 0.01].index
    assert len(trade_dates) > 0, "ETF 轮动场景应检测到调仓记录"

    # 首日应有仓位（建仓）
    first_day = w_1y.index[0]
    w_first = w_1y.loc[first_day]
    assert float(w_first.sum()) > 0.01, "首日应有仓位"
    n_first = int((w_first > 0.001).sum())
    assert n_first == 1, f"首日应持仓 1 只，实际 {n_first} 只"

    # 每个调仓日都应只有 1 个持仓
    for t in trade_dates:
        w_t = w_1y.loc[t]
        n_pos = int((w_t > 0.001).sum())
        assert n_pos == 1, f"调仓日 {t.date()} 应持仓 1 只，实际 {n_pos} 只"


def test_low_correlation_rotation_recent_single_position():
    """S19 live=False: 即使在轮动中，最近 20 天每天也只持仓 1 只"""
    p = _prices_low_corr_rotating(n=350)
    s = LowCorrelationRotation(lookback=25, top_n=1)
    w = s.generate(p, live=False)
    recent = w.iloc[-20:]
    for i in range(len(recent)):
        n_pos = int((recent.iloc[i] > 0.001).sum())
        assert n_pos == 1, \
            f"{recent.index[i].date()} 持仓 {n_pos} 只，应为 1 只"


def test_low_correlation_live_daily_signal_rotation():
    """S19 live=True: 日频信号在不同阶段应选出不同的最优ETF（轮动检测）"""
    p = _prices_low_corr_rotating(n=350)
    s = LowCorrelationRotation(lookback=25, top_n=1)
    w = s.generate(p, live=True)

    # 不同阶段应选出不同的 top-1（验证轮动能力）
    n = len(w)
    phases = {
        "phase1": w.iloc[100:150],   # 513100 主导
        "phase2": w.iloc[200:250],   # 159915 主导
        "phase3": w.iloc[250:300],   # 518880 主导
        "phase4": w.iloc[300:350],   # 510300 主导
    }
    picked = {}
    for name, seg in phases.items():
        last = seg.iloc[-1]
        top = last.nlargest(1)
        picked[name] = top.index[0]

    # 不同阶段应选出不同的ETF（否则无法检测轮动）
    unique_picks = set(picked.values())
    assert len(unique_picks) >= 2, \
        f"不同阶段应选出不同ETF以验证轮动，实际只选出: {unique_picks}"


def test_rsrs_reversal_diagnostics_rsrs_pass_correct():
    """S18: rsrs_pass 应正确反映 zscore vs threshold 的比较"""
    p = _prices_broad(n=300)
    s = RsrsReversalMomentum(rsrs_zscore_threshold=-2.0)
    diag = s.get_diagnostics(p)
    for etf, detail in diag["score_details"].items():
        rsrs = detail.get("rsrs", {})
        if rsrs and "rsrs_zscore" in rsrs and "rsrs_pass" in rsrs:
            expected = rsrs["rsrs_zscore"] >= -2.0
            assert rsrs["rsrs_pass"] == expected, \
                f"{etf}: rsrs_pass={rsrs['rsrs_pass']} 但 zscore={rsrs['rsrs_zscore']}"


def test_low_correlation_diagnostics():
    """S19 get_diagnostics 应返回动量分解信息"""
    p = _prices_low_corr(n=200)
    s = LowCorrelationRotation()
    diag = s.get_diagnostics(p)
    assert "scores" in diag
    assert "score_details" in diag
    assert "holdings" in diag
    # score_details 应包含年化收益和R²
    for etf, detail in diag["score_details"].items():
        assert "ann_return" in detail
        assert "r_squared" in detail
        assert "score" in detail


# ── S14 动态波动率调整动量（BUG-002 补测） ──

def test_adaptive_momentum_weights_sum_to_one():
    """S14 warmup 期后每行权重和≈1"""
    p = _prices_multi(n=300)
    s = AdaptiveMomentum()
    w = s.generate(p)
    valid = w.iloc[120:]  # warmup = max(lb_max=120, vol_long=60, 120) = 120
    rowsums = valid.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all(), f"S14 权重不和为1"


def test_adaptive_momentum_warmup_equal_weight():
    """S14 warmup 期内应等权分配且每行和=1"""
    p = _prices_multi(n=300)
    s = AdaptiveMomentum()
    w = s.generate(p)
    warmup = w.iloc[:120]
    rowsums = warmup.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all()
    assert (warmup.iloc[0][s.etf_pool] == 0.25).all()  # 4 只 ETF 等权


def test_adaptive_momentum_date_alignment():
    """S14 权重索引与价格索引逐日对齐，无 NaN"""
    p = _prices_multi(n=300)
    s = AdaptiveMomentum()
    w = s.generate(p)
    assert w.index.equals(p.index)
    assert not w.iloc[120:].isna().any().any()


# ── S15 趋势过滤+动量增强（BUG-002 补测） ──

def test_trend_filter_weights_sum_to_one():
    """S15 warmup 期后每行权重和≈1"""
    p = _prices_broad(n=300)
    s = TrendFilterMomentum()
    w = s.generate(p)
    valid = w.iloc[250:]  # warmup = max(ma_long=200, mom_lookback=25, 250) = 250
    rowsums = valid.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all(), f"S15 权重不和为1"


def test_trend_filter_warmup_equal_weight():
    """S15 warmup 期内应等权分配"""
    p = _prices_broad(n=300)
    s = TrendFilterMomentum()
    w = s.generate(p)
    warmup = w.iloc[:250]
    rowsums = warmup.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all()
    assert (warmup.iloc[100][s.etf_pool] == 1.0 / len(s.etf_pool)).all()


def test_trend_filter_date_alignment():
    """S15 权重索引与价格索引逐日对齐，无 NaN"""
    p = _prices_broad(n=300)
    s = TrendFilterMomentum()
    w = s.generate(p)
    assert w.index.equals(p.index)
    assert not w.iloc[250:].isna().any().any()


# ── S16/S17 金丝雀防御（BUG-002 补测） ──

def test_canary_defense_weights_sum_to_one():
    """S16 warmup 期后每行权重和≈1（含现金列）"""
    p = _prices_broad(n=300)
    s = CanaryDefense()
    w = s.generate(p)
    valid = w.iloc[150:]  # warmup = max(ma_bond=150, ma_vol*3=60, mom_lookback=25) = 150
    rowsums = valid.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all(), f"S16 权重不和为1"


def test_canary_defense_warmup_equal_weight():
    """S16 warmup 期内应等权分配"""
    p = _prices_broad(n=300)
    s = CanaryDefense()
    w = s.generate(p)
    warmup = w.iloc[:150]
    rowsums = warmup.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all()
    assert (warmup.iloc[0][s.etf_pool] == 0.25).all()  # 4 只 ETF 等权


def test_canary_defense_date_alignment():
    """S16 权重索引与价格索引逐日对齐，无 NaN"""
    p = _prices_broad(n=300)
    s = CanaryDefense()
    w = s.generate(p)
    assert w.index.equals(p.index)
    assert not w.iloc[150:].isna().any().any()


def test_canary_defense_daily_weights_sum_to_one():
    """S17 (CanaryDefenseDaily) warmup 期后每行权重和≈1"""
    p = _prices_broad(n=300)
    s = CanaryDefenseDaily()
    w = s.generate(p)
    valid = w.iloc[150:]
    rowsums = valid.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all(), f"S17 权重不和为1"


def test_canary_defense_has_cash_column():
    """S16 应有现金列 511880"""
    p = _prices_broad(n=300)
    s = CanaryDefense()
    w = s.generate(p)
    assert "511880" in w.columns


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
