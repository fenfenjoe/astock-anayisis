"""S7 目标波动率：动态调整仓位使组合波动率稳定在目标值。

原理：计算股票资产实现波动率（滚动窗口），仓位 = 目标波动率 / 实现波动率，
上限 1.0（不加杠杆）。波动大时降仓避险，波动小时满仓博收益。
月末调仓，未持股部分持货币ETF。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from .base import Strategy


class TargetVol(Strategy):
    """S7 目标波动率：动态仓位，实现波动率 ↑ → 仓位 ↓，月末调仓。"""

    name = "S7_目标波动率"

    def __init__(self, stock="510300", cash="511880", target_vol=0.15, window=20):
        self.stock = stock
        self.cash = cash
        self.target_vol = target_vol    # 年化目标波动率（默认15%）
        self.window = window            # 实现波动率估计窗口
        self.assets = [stock, cash]

    def generate(self, prices):
        # 计算实现波动率（年化）
        rets = prices[self.stock].pct_change().fillna(0.0)
        realized_vol = rets.rolling(self.window).std() * np.sqrt(252)

        # 仓位 = 目标波动率 / 实现波动率，上限1.0（不加杠杆），下限0.0
        stock_w = (self.target_vol / realized_vol.replace(0, np.nan)).clip(0.0, 1.0)
        stock_w = stock_w.fillna(0.0)  # warmup 期波动率不可计算 → 持现金

        weights = pd.DataFrame(0.0, index=prices.index, columns=self.assets)
        weights[self.stock] = stock_w.values
        weights[self.cash] = 1.0 - stock_w.values

        # 月末调仓：取每月最后交易日信号，向前填充
        monthly = weights.resample("ME").last()
        weights = monthly.reindex(prices.index, method="ffill").bfill().fillna(0.0)
        return weights
