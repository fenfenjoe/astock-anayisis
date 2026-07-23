"""S14 动态波动率调整动量轮动：波动率自适应回看窗口 + 动量打分。

原理：传统动量策略使用固定回看期（如25日），但在不同波动率环境下最优回看期不同。
高波动期 → 短回看期（快速响应趋势转变），低波动期 → 长回看期（过滤噪音）。
通过短期/长期波动率比值动态调整 momentum lookback：
    lookback = lb_min + (lb_max - lb_min) * (1 - min(ratio_cap, vol_ratio))
其中 vol_ratio = short_vol(10日) / long_vol(60日)

动量打分：自适应回看期的年化收益 × R²，选 top_n 等权持有。
无合适标的（最高分为负）时切货币避险。

来源：JoinQuant @0xtao "动量ETF轮动之基于历史波动率动态调整历史回溯期"
      原始指标：Sharpe 2.27, 年化 43.47%, 最大回撤 -23.31% (2019-2025)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from .base import Strategy


class AdaptiveMomentum(Strategy):
    """S14 动态波动率调整动量轮动"""

    name = "S14_动态波动率调整动量"

    def __init__(self, lb_min=15, lb_max=120, vol_short=10, vol_long=60,
                 ratio_cap=2.0, top_n=2,
                 etf_pool=None, cash="511880"):
        self.lb_min = lb_min                # 最短回看期
        self.lb_max = lb_max                # 最长回看期
        self.vol_short = vol_short          # 短期波动窗口
        self.vol_long = vol_long            # 长期波动窗口
        self.ratio_cap = ratio_cap          # 波动率比值上限
        self.top_n = top_n
        self.cash = cash
        if etf_pool is None:
            etf_pool = ["513100", "159915", "510180", "518880"]
        self.etf_pool = etf_pool
        self.assets = etf_pool + [cash]

    def _momentum_score(self, closes, lookback):
        """年化收益 × R² 打分（使用动态回看期）。"""
        n = min(lookback, len(closes))
        if n < 5:
            return 0.0
        y = np.log(closes[-n:])
        x = np.arange(len(y))
        slope, intercept = np.polyfit(x, y, 1)
        ann_ret = np.exp(slope * 250) - 1
        y_pred = slope * x + intercept
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = (len(y) - 1) * np.var(y, ddof=1) if len(y) > 1 else 1e-12
        r_sq = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
        return ann_ret * max(r_sq, 0)

    def generate(self, prices):
        n_days = len(prices)
        weights = pd.DataFrame(0.0, index=prices.index, columns=self.assets)

        warmup = max(self.lb_max, self.vol_long, 120)
        n_pool = len(self.etf_pool)
        if warmup > 0 and n_pool > 0:
            w_eq = 1.0 / n_pool
            for etf in self.etf_pool:
                if etf in weights.columns:
                    weights.iloc[:warmup] = weights.iloc[:warmup].copy()
                    weights.loc[weights.index[:warmup], etf] = w_eq

        # 逐日计算
        for i in range(warmup, n_days):
            # ── 1) 计算每只ETF的动态回看期（基于波动率比值） ──
            lookbacks = {}
            for etf in self.etf_pool:
                if etf not in prices.columns:
                    continue
                closes = prices[etf].iloc[max(0, i-self.vol_long):i+1].values
                if len(closes) < self.vol_long:
                    lookbacks[etf] = self.lb_max  # 默认最长
                    continue

                rets = np.diff(np.log(closes))
                if len(rets) < self.vol_short:
                    lookbacks[etf] = self.lb_max
                    continue

                short_vol = np.std(rets[-self.vol_short:]) * np.sqrt(252)
                long_vol = np.std(rets) * np.sqrt(252)
                if long_vol < 0.001:
                    long_vol = 0.001

                vol_ratio = short_vol / long_vol
                capped_ratio = min(self.ratio_cap, vol_ratio)
                lb = int(self.lb_min + (self.lb_max - self.lb_min) * (1 - capped_ratio / self.ratio_cap))
                lookbacks[etf] = max(self.lb_min, min(self.lb_max, lb))

            # ── 2) 打分排名 ──
            scores = {}
            for etf in self.etf_pool:
                if etf not in prices.columns:
                    continue
                closes = prices[etf].iloc[:i+1].values
                lb = lookbacks.get(etf, self.lb_max)
                scores[etf] = self._momentum_score(closes, lb)

            if not scores:
                if self.cash in weights.columns:
                    weights.iloc[i, weights.columns.get_loc(self.cash)] = 1.0
                continue

            ranked = sorted(scores, key=scores.get, reverse=True)
            best_score = scores.get(ranked[0], -999)

            # ── 3) 无合适标的 → 货币避险 ──
            if best_score <= 0:
                if self.cash in weights.columns:
                    weights.iloc[i, weights.columns.get_loc(self.cash)] = 1.0
            else:
                w = 1.0 / min(self.top_n, len(ranked))
                for etf in ranked[:self.top_n]:
                    if etf in weights.columns:
                        idx = weights.columns.get_loc(etf)
                        weights.iloc[i, idx] = w

        return weights
