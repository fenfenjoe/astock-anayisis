"""S11 布林带均值回归：价格触及下轨买入，回归中轨/触及上轨卖出。

原理：假设价格围绕均值波动，极端偏离会回归。价格跌破布林带下轨（均值-2σ）
时超卖→买入，回升至中轨或触及上轨（均值+2σ）时超买→卖出/减仓。
剩余仓位持有货币ETF。

来源：经典技术分析 + 聚宽社区布林带策略

周度评估（减少噪音交易），动态仓位。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from .base import Strategy


class Bollinger(Strategy):
    """S11 布林带均值回归：下轨买入，上轨卖出，周度评估。"""

    name = "S11_布林带均值回归"

    def __init__(self, etf="510300", cash="511880",
                 ma_period=20, sigma=2.0):
        self.etf = etf
        self.cash = cash
        self.ma_period = ma_period    # 布林带中轨周期
        self.sigma = sigma            # 标准差倍数
        self.assets = [etf, cash]

    def generate(self, prices):
        n_days = len(prices)
        close = prices[self.etf]

        # 布林带
        mid = close.rolling(self.ma_period, min_periods=1).mean()
        std = close.rolling(self.ma_period, min_periods=1).std()
        upper = mid + self.sigma * std
        lower = mid - self.sigma * std

        weights = pd.DataFrame(0.0, index=prices.index, columns=self.assets)

        # 信号：价格在下轨附近 → 买入；在上轨附近 → 卖出
        # 使用价格相对布林带的位置： (price - lower) / (upper - lower)
        band_width = upper - lower
        position_in_band = (close - lower) / band_width.replace(0, np.nan)
        position_in_band = position_in_band.fillna(0.5)  # 默认中轨

        # 仓位映射：下轨=满仓(1.0)，上轨=空仓(0.0)，线性插值
        # 更保守的做法：<0.2→满仓，>0.8→空仓，中间线性
        stock_weight = 1.0 - position_in_band.clip(0.0, 1.0)
        # 下轨附近加重，上轨附近减仓
        stock_weight = (1.0 - position_in_band).clip(0.0, 1.0)

        weights[self.etf] = stock_weight.values
        weights[self.cash] = 1.0 - stock_weight.values

        # 每周调仓：取每周最后交易日信号
        weekly = weights.resample("W").last()
        weights = weekly.reindex(prices.index, method="ffill").bfill().fillna(0.0)

        # warmup期（前ma_period天）：半仓
        weights.iloc[:self.ma_period] = [0.5, 0.5]

        return weights
