import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from backtest.engine import backtest, BacktestResult
from backtest.cost import Cost


def test_buy_hold_matches_price_relative_return(synth_prices):
    """买入持有：净值 = 价格相对收益（无成本）。10价格点→9次1%收益"""
    prices = synth_prices[["510300"]]
    weights = pd.DataFrame({"510300": 1.0}, index=prices.index)
    result = backtest(prices, weights, cost=Cost(slippage=0, commission_rate=0))
    expected = 1.01 ** 9  # 首日ret=0，后9日各1%
    assert abs(result.nav.iloc[-1] - expected) < 1e-6


def test_signal_lag_prevents_lookahead(synth_prices):
    """信号滞后生效：第3日才买入，净值应低于全程持有"""
    prices = synth_prices[["510300"]]
    weights = pd.DataFrame({"510300": 0.0}, index=prices.index)
    weights.iloc[3:] = 1.0
    result = backtest(prices, weights, cost=Cost(slippage=0, commission_rate=0))
    full = backtest(prices, pd.DataFrame({"510300": 1.0}, index=prices.index),
                    cost=Cost(slippage=0, commission_rate=0))
    assert result.nav.iloc[-1] < full.nav.iloc[-1]


def test_rebalance_arithmetic(flat_prices):
    """再平衡算术：价格不变时仅首日建仓扣成本，之后无换手"""
    weights = pd.DataFrame({"510300": 0.6, "511260": 0.4}, index=flat_prices.index)
    result = backtest(flat_prices, weights, cost=Cost())
    # 首日建仓：权重和1.0 × 单边成本0.00035
    expected = 1 - 1.0 * Cost().one_way()
    assert abs(result.nav.iloc[-1] - expected) < 1e-8


def test_cost_deducted(synth_prices):
    """有成本时净值低于无成本"""
    prices = synth_prices[["510300"]]
    weights = pd.DataFrame({"510300": 1.0}, index=prices.index)
    no_cost = backtest(prices, weights, cost=Cost(slippage=0, commission_rate=0))
    with_cost = backtest(prices, weights, cost=Cost(slippage=1e-4, commission_rate=2.5e-4))
    assert with_cost.nav.iloc[-1] < no_cost.nav.iloc[-1]


def test_returns_result_object(synth_prices):
    """返回 BacktestResult，首日净值=1"""
    prices = synth_prices[["510300"]]
    weights = pd.DataFrame({"510300": 1.0}, index=prices.index)
    result = backtest(prices, weights, cost=Cost(slippage=0, commission_rate=0))
    assert isinstance(result, BacktestResult)
    assert len(result.nav) == len(prices)
    assert abs(result.nav.iloc[0] - 1.0) < 1e-10


def test_nav_positive(synth_prices):
    """ENG-002: NAV 起始值为 1.0 且永不为负"""
    prices = synth_prices[["510300"]]
    weights = pd.DataFrame({"510300": 1.0}, index=prices.index)
    result = backtest(prices, weights, cost=Cost(slippage=0, commission_rate=0))
    assert abs(result.nav.iloc[0] - 1.0) < 1e-10
    assert (result.nav > 0).all()
    # 全仓下跌也应为正（价格恒正，最多趋近0但不会为负）
    down = pd.DataFrame({"A": [100 * (0.99 ** i) for i in range(10)]},
                        index=prices.index)
    w = pd.DataFrame({"A": 1.0}, index=down.index)
    r2 = backtest(down, w, cost=Cost(slippage=0, commission_rate=0))
    assert (r2.nav > 0).all()
