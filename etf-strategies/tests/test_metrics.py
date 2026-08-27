import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from backtest.engine import BacktestResult
from backtest.metrics import compute_metrics


def _make_result(returns):
    """从收益序列构造 BacktestResult"""
    nav = (1 + pd.Series(returns)).cumprod()
    nav.iloc[0] = 1.0
    weights = pd.DataFrame({"A": 1.0}, index=nav.index)
    return BacktestResult(nav=nav, returns=pd.Series(returns), weights=weights,
                           turnover=1.0)


def test_metrics_basic():
    """252个收益日（首日0，后251日各1%），年化=1.01^251-1"""
    rets = [0.0] + [0.01] * 251
    r = _make_result(rets)
    m = compute_metrics(r)
    # years=252/252=1, nav最终=1.01^251
    assert abs(m["annual_return"] - (1.01 ** 251 - 1)) < 1e-4
    assert m["annual_vol"] > 0
    assert m["sharpe"] > 0
    assert m["max_drawdown"] <= 0
    assert 0 <= m["win_rate"] <= 1


def test_max_drawdown():
    """净值 1 -> 1.2 -> 0.9 -> 1.0，回撤25%"""
    rets = [0.0, 0.2, -0.25, 0.111]
    r = _make_result(rets)
    m = compute_metrics(r)
    assert abs(m["max_drawdown"] - (-0.25)) < 1e-6


def test_win_rate():
    """4个非零收益日，3正1负 → 胜率0.75"""
    rets = [0.0, 0.01, 0.02, -0.01, 0.03]
    r = _make_result(rets)
    m = compute_metrics(r)
    assert abs(m["win_rate"] - 0.75) < 1e-6


def test_excess_return_vs_benchmark():
    """策略超额 = 策略年化 - 基准年化"""
    r = _make_result([0.0] + [0.01] * 251)
    b = _make_result([0.0] + [0.005] * 251)
    m = compute_metrics(r, benchmark=b)
    assert m["excess_return"] > 0


def test_annual_return():
    """MET-001: 年化收益率 = (final_nav)^(252/总交易日数) - 1"""
    rets = [0.0] + [0.01] * 251  # 252 交易日，nav_final = 1.01^251
    r = _make_result(rets)
    m = compute_metrics(r)
    expected = (1.01 ** 251) ** (252 / 252) - 1
    assert abs(m["annual_return"] - expected) < 1e-6


def test_sharpe():
    """MET-002: 夏普 = 年化收益 / 年化波动（日 std × sqrt(252)）"""
    rets = [0.0] + [0.01] * 251
    r = _make_result(rets)
    m = compute_metrics(r)
    ann_vol = pd.Series(rets).std() * np.sqrt(252)
    assert ann_vol > 0
    assert abs(m["sharpe"] - m["annual_return"] / ann_vol) < 1e-6
