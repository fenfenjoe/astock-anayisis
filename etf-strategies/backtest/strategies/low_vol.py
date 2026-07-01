"""S10 低波动因子：在候选ETF池中选历史波动率最低的品种持有。

原理：低波动异象（Low Volatility Anomaly）——长期来看，低波动资产的风险调整后
收益不输高波动资产，甚至在震荡/下行市中表现更优。本策略按过去N日年化波动率
排序，选波动率最低的K只等权持有，每月调仓。

来源：经典因子投资文献 + BigQuant低波策略社区
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from .base import Strategy


class LowVol(Strategy):
    """S10 低波动因子：按历史波动率排序，选最低K只，月度调仓。"""

    name = "S10_低波动因子"

    def __init__(self, window=60, top_n=3,
                 etf_pool=None):
        self.window = window          # 波动率计算窗口
        self.top_n = top_n            # 持有最低波动品种数
        if etf_pool is None:
            # 跨资产类别ETF池：低波策略需大差异品种才能体现分散效果
            etf_pool = [
                "510300",  # 沪深300ETF
                "511260",  # 国债ETF
                "518880",  # 黄金ETF
                "510500",  # 中证500ETF
                "159915",  # 创业板ETF
                "512800",  # 银行ETF
            ]
        self.etf_pool = etf_pool
        self.assets = etf_pool

    def generate(self, prices):
        n_days = len(prices)
        n_assets = len(self.etf_pool)
        weights = pd.DataFrame(0.0, index=prices.index, columns=self.etf_pool)

        warmup = self.window
        if warmup > 0:
            weights.iloc[:warmup] = 1.0 / n_assets

        for i in range(warmup, n_days):
            # 计算过去window天的年化波动率
            window_prices = prices.iloc[i - self.window + 1: i + 1]
            daily_rets = window_prices.pct_change().dropna()
            vol_scores = {}
            for etf in self.etf_pool:
                if etf in daily_rets.columns and len(daily_rets) > 1:
                    ann_vol = daily_rets[etf].std() * np.sqrt(252)
                else:
                    ann_vol = 999.0  # 数据不足 → 不选
                vol_scores[etf] = ann_vol

            # 按波动率升序排列（低波优先），选top_n
            ranked = sorted(vol_scores, key=vol_scores.get)
            w = 1.0 / self.top_n
            for etf in ranked[:self.top_n]:
                idx = self.etf_pool.index(etf)
                weights.iloc[i, idx] = w

        # 月末调仓
        monthly = weights.resample("ME").last()
        weights = monthly.reindex(prices.index, method="ffill").bfill().fillna(0.0)
        return weights
