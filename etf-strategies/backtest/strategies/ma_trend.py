import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
from .base import Strategy


class MATrend(Strategy):
    """S3 均线趋势：ma20>ma60 持股，否则切货币。月末调仓。"""
    name = "S3_均线趋势"

    def __init__(self, short=20, long=60, stock="510300", cash="511880"):
        self.short, self.long = short, long
        self.stock, self.cash = stock, cash
        self.assets = [stock, cash]

    def generate(self, prices):
        ma_s = prices[self.stock].rolling(self.short).mean()
        ma_l = prices[self.stock].rolling(self.long).mean()
        signal = (ma_s > ma_l).astype(float)  # 1持股 0货币
        weights = pd.DataFrame(0.0, index=prices.index, columns=self.assets)
        weights[self.stock] = signal
        weights[self.cash] = 1 - signal
        # 月末调仓
        monthly = weights.resample("ME").last()
        weights = monthly.reindex(prices.index, method="ffill").fillna(0.0)
        return weights
