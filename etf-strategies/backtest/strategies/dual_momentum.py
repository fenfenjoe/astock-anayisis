import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
from .base import Strategy


class DualMomentum(Strategy):
    """S2 双动量：绝对动量+相对动量。
    股票动量为负 → 切货币（避险）；为正且>债券 → 持股；为正且<=债券 → 持债。
    warmup 期（无动量信号）默认持货币避险。月末调仓。"""
    name = "S2_双动量"

    def __init__(self, lookback=250, stock="510300", bond="511260", cash="511880"):
        self.lookback = lookback
        self.stock, self.bond, self.cash = stock, bond, cash
        self.assets = [stock, bond, cash]

    def generate(self, prices):
        stock_mom = prices[self.stock].pct_change(self.lookback)
        bond_mom = prices[self.bond].pct_change(self.lookback)
        # 默认全现金（warmup 期也持货币避险）
        weights = pd.DataFrame(0.0, index=prices.index, columns=self.assets)
        weights[self.cash] = 1.0
        # 有信号时覆盖（向量化，三选一互斥）
        mask_stock = (stock_mom > 0) & (stock_mom > bond_mom)
        mask_bond = (stock_mom > 0) & (stock_mom <= bond_mom)
        weights.loc[mask_stock, [self.stock, self.bond, self.cash]] = [1.0, 0.0, 0.0]
        weights.loc[mask_bond, [self.stock, self.bond, self.cash]] = [0.0, 1.0, 0.0]
        # 月末调仓：取每月最后交易日信号，向前填充
        monthly = weights.resample("ME").last()
        weights = monthly.reindex(prices.index, method="ffill")
        # warmup 段（首个月末之前）bfill 用首个有效信号（货币避险）
        weights = weights.bfill().fillna(0.0)
        return weights
