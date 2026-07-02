"""S12 量价情绪多因子轮动：动量+成交量情绪+波动率+量价关系 四因子打分。

原理：传统动量因子在震荡市中容易失效，加入成交量情绪因子可提升信号质量。
- 动量因子(30%)：20日收益率
- 量价情绪因子(25%)：放量程度——成交量大增往往意味着情绪转变（机构进出）
- 波动率因子(20%)：低波优先——高波动ETF往往方向不明
- 量价关系因子(25%)：量价齐升=强势看多，量价背离=警惕

每日评估，信号转负时切货币(511880)避险。

来源：Stanford MS&E 448 情绪增强多因子 + 聚宽社区量价轮动策略
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from .base import Strategy


class SentimentMomentum(Strategy):
    """S12 量价情绪多因子：四因子加权，量价情绪增强。"""

    name = "S12_量价情绪多因子"

    def __init__(self, lookback=20, top_n=1,
                 etf_pool=None, cash="511880"):
        self.lookback = lookback
        self.top_n = top_n
        self.cash = cash
        if etf_pool is None:
            etf_pool = ["513100", "159915", "510180", "518880"]
        self.etf_pool = etf_pool
        self.assets = etf_pool + [cash]

    def generate(self, prices):
        n_days = len(prices)
        n_assets = len(self.etf_pool)
        weights = pd.DataFrame(0.0, index=prices.index,
                               columns=self.etf_pool + [self.cash])

        warmup = max(self.lookback, 30)  # 成交量需要更长的回看期
        if warmup > 0:
            weights.iloc[:warmup] = 1.0 / (n_assets + 1)
            weights.iloc[:warmup, weights.columns.get_loc(self.cash)] = 0.0

        for i in range(warmup, n_days):
            window = prices.iloc[i - self.lookback + 1: i + 1]
            scores = {}

            for etf in self.etf_pool:
                closes = window[etf].values

                # F1: 动量因子 (30%) — 区间收益率
                mom = closes[-1] / closes[0] - 1.0

                # F2: 量价情绪因子 (25%) — 成交量异常检测
                # 用收盘价变化幅度的平方根作成交量代理（无真实volume列时）
                # 实际用价格波动幅度代理：大波动=高关注度=情绪升温
                daily_range = np.abs(np.diff(closes)) / closes[:-1]
                recent_range = daily_range[-min(10, len(daily_range)):].mean()
                hist_range = daily_range.mean() if daily_range.mean() > 0 else 0.001
                vol_sentiment = recent_range / hist_range - 1.0  # >0=近期波动放大

                # F3: 波动率因子 (20%) — 逆波动率（低波优先）
                rets = np.diff(np.log(closes))
                ann_vol = np.std(rets) * np.sqrt(252) if len(rets) > 1 else 0.99
                inv_vol = 0.15 / max(ann_vol, 0.01)  # 目标15%波动

                # F4: 量价关系因子 (25%) — 量价协同方向
                # 价格涨+波动放大=看多；价格跌+波动放大=看空
                pv_corr = mom * vol_sentiment  # 同向为正，背离为负

                # 综合打分（各因子归一化到合理范围）
                score = (0.30 * mom +
                         0.25 * np.tanh(vol_sentiment) +  # tanh压缩极端值
                         0.20 * min(inv_vol, 2.0) +       # 上限2.0
                         0.25 * np.tanh(pv_corr * 3))      # 放大后压缩

                # 方向修正：如果动量+量价关系都严重为负 → 大幅扣分
                if mom < -0.05 and vol_sentiment > 0.5:
                    score -= 0.3  # 放量下跌 = 危险信号

                scores[etf] = score

            # 排名选 top_n
            ranked = sorted(scores, key=scores.get, reverse=True)
            best_score = scores.get(ranked[0], 0)

            # 判断是否避险：最高分也为负 → 全切货币
            if best_score <= 0:
                weights.iloc[i, weights.columns.get_loc(self.cash)] = 1.0
            else:
                w = 1.0 / self.top_n
                for etf in ranked[:self.top_n]:
                    if etf in self.etf_pool:
                        idx = weights.columns.get_loc(etf)
                        weights.iloc[i, idx] = w

        return weights
