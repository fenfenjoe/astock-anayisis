"""向量化回测引擎。策略产目标权重，引擎统一处理信号滞后/成本/净值。"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from dataclasses import dataclass
from backtest.cost import Cost


@dataclass
class BacktestResult:
    nav: pd.Series          # 净值序列（初始=1）
    returns: pd.Series      # 日收益序列
    weights: pd.DataFrame   # 实际持仓权重（已滞后）
    turnover: float         # 年化换手率


def backtest(prices, target_weights, cost=None, initial_capital=1e6):
    """
    prices: 日期×资产 收盘价（前复权）
    target_weights: 日期×资产 目标权重（0~1，每行和≈1）
    信号滞后1日：t日收盘算信号，t+1日收盘执行（w_{t-1} 对齐 r_t）。
    """
    if cost is None:
        cost = Cost()
    common = prices.index.intersection(target_weights.index)
    prices = prices.loc[common]
    target_weights = target_weights.loc[common]
    # 信号滞后1日：昨日收盘设定的权重决定今日持仓
    held_weights = target_weights.shift(1).fillna(0.0)
    # 日收益
    daily_ret = prices.pct_change().fillna(0.0)
    # 权重变动产生的成本（单边成本率 × 权重变动绝对值）
    weight_change = held_weights.diff().abs().fillna(held_weights.abs().iloc[0] if len(held_weights) else 0)
    cost_rate = cost.one_way()
    daily_cost = (weight_change * cost_rate).sum(axis=1)
    # 组合日收益
    portfolio_ret = (held_weights * daily_ret).sum(axis=1) - daily_cost
    nav = (1 + portfolio_ret).cumprod()
    # 首日净值设为1（首日若有建仓成本已扣，但 cumprod 首日=1+ret，强制归1）
    nav.iloc[0] = 1.0
    # 年化换手率
    total_turnover = weight_change.sum().sum()
    years = len(prices) / 252
    ann_turnover = total_turnover / years if years > 0 else 0.0
    return BacktestResult(nav=nav, returns=portfolio_ret, weights=held_weights,
                           turnover=ann_turnover)
