"""S9 行业动量轮动：在行业ETF池中按动量打分，选最强K只持有。

原理：行业轮动是A股结构性行情的核心特征。"强者恒强"的动量效应在
3-12个月中期最为显著。本策略在多个行业ETF中按过去N日收益率排名，
选Top-K等权持有，月度调仓。

来源：行业轮动经典框架 + 聚宽社区行业动量策略
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from .base import Strategy


class IndustryMomentum(Strategy):
    """S9 行业动量轮动：多行业ETF动量排名，选Top-K，月度调仓。"""

    name = "S9_行业动量轮动"

    def __init__(self, lookback=60, top_n=3,
                 etf_pool=None):
        self.lookback = lookback      # 动量回看天数（60日≈3个月）
        self.top_n = top_n            # 持有最强行业数
        if etf_pool is None:
            # 主流行业ETF，覆盖医药/金融/军工/消费/科技/周期
            etf_pool = [
                "512010",  # 医药ETF
                "512880",  # 证券ETF
                "512800",  # 银行ETF
                "512660",  # 军工ETF
                "510300",  # 沪深300ETF（宽基兜底）
            ]
        self.etf_pool = etf_pool
        self.assets = etf_pool

    def generate(self, prices):
        n_days = len(prices)
        n_assets = len(self.etf_pool)
        weights = pd.DataFrame(0.0, index=prices.index, columns=self.etf_pool)

        warmup = self.lookback - 1
        if warmup > 0:
            weights.iloc[:warmup] = 1.0 / n_assets  # warmup期等权

        for i in range(warmup, n_days):
            # 计算过去lookback天的收益率作为动量得分
            window_start = max(0, i - self.lookback + 1)
            momentum_scores = {}
            for etf in self.etf_pool:
                start_price = prices[etf].iloc[window_start]
                end_price = prices[etf].iloc[i]
                if start_price > 0:
                    mom = end_price / start_price - 1.0
                else:
                    mom = 0.0
                momentum_scores[etf] = mom

            # 按动量降序排列，选top_n
            ranked = sorted(momentum_scores, key=momentum_scores.get, reverse=True)
            w = 1.0 / self.top_n
            for etf in ranked[:self.top_n]:
                idx = self.etf_pool.index(etf)
                weights.iloc[i, idx] = w

        # 月末调仓：取每月最后交易日信号，向前填充
        monthly = weights.resample("ME").last()
        weights = monthly.reindex(prices.index, method="ffill").bfill().fillna(0.0)
        return weights
