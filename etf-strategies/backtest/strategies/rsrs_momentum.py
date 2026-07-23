"""S15 趋势过滤+动量增强：先趋势筛选（剔除下行趋势ETF），再动量打分选优。

原理：纯动量策略在市场风格切换时容易买到"强弩之末"的假突破。
加入两道趋势过滤提升信号质量：
1. 长期趋势过滤：ETF必须在其200日MA之上（处于上升趋势），否则排除
2. 短期趋势确认：20日价格斜率必须为正，否则排除
只有通过双过滤的ETF才进入动量打分环节。

动量打分：25日对数价格OLS回归 → 年化收益 × R² → 选top_n等权持有。
过滤后无标的 → 考虑二级候选（黄金/债券）→ 仍无则切货币。

调仓频率：周度（取每周最后交易日信号），减少噪音交易。

来源：JoinQuant @蚂蚁量化 "趋势筛选后相关性最小ETF轮动"
      原始指标：Sortino 1.445, 年化 26.73%, 最大回撤 -17.36% (2017-2024)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from .base import Strategy


class TrendFilterMomentum(Strategy):
    """S15 趋势过滤+动量增强"""

    name = "S15_趋势过滤动量增强"

    def __init__(self, ma_long=200, ma_short=20,
                 mom_lookback=25, top_n=2,
                 etf_pool=None, defensive_pool=None, cash="511880"):
        self.ma_long = ma_long                # 长期趋势过滤MA
        self.ma_short = ma_short              # 短期趋势确认MA
        self.mom_lookback = mom_lookback       # 动量打分回看
        self.top_n = top_n
        self.cash = cash
        if etf_pool is None:
            etf_pool = [
                "513100",  # 纳指100
                "159915",  # 创业板
                "510180",  # 上证180
                "518880",  # 黄金
                "510300",  # 沪深300
                "512480",  # 半导体
            ]
        self.etf_pool = etf_pool
        if defensive_pool is None:
            defensive_pool = ["518880", "511260"]  # 黄金、国债
        self.defensive_pool = defensive_pool
        self.assets = list(dict.fromkeys(etf_pool + defensive_pool + [cash]))

    def _momentum_score(self, closes):
        """年化收益 × R² 打分。"""
        if len(closes) < self.mom_lookback:
            return 0.0
        y = np.log(closes[-self.mom_lookback:])
        x = np.arange(len(y))
        slope, intercept = np.polyfit(x, y, 1)
        ann_ret = np.exp(slope * 250) - 1
        y_pred = slope * x + intercept
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = (len(y) - 1) * np.var(y, ddof=1) if len(y) > 1 else 1e-12
        r_sq = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
        return ann_ret * max(r_sq, 0)

    def _trend_filter(self, closes):
        """趋势双过滤：必须同时通过长期MA和短期斜率检测。
        返回 (passed, short_slope_sign)。
        """
        if len(closes) < max(self.ma_long, self.ma_short):
            return False, 0

        # 长期过滤：价格 > MA_long
        ma_l = np.mean(closes[-self.ma_long:]) if len(closes) >= self.ma_long else np.mean(closes)
        price_now = closes[-1]
        long_pass = price_now > ma_l

        # 短期过滤：20日斜率 > 0
        if len(closes) >= self.ma_short:
            y = np.log(closes[-self.ma_short:])
            x = np.arange(len(y))
            slope, _ = np.polyfit(x, y, 1)
            short_pass = slope > 0
            short_sign = 1 if slope > 0 else -1
        else:
            short_pass = True
            short_sign = 0

        return long_pass and short_pass, short_sign

    def generate(self, prices, live=False):
        """Generate target weights for each trading day.

        Args:
            prices: DataFrame of close prices (index=date, columns=assets)
            live: If True, skip weekly resample and return raw daily weights.
                  Used for live signal generation (current filtering state).
        """
        n_days = len(prices)
        weights = pd.DataFrame(0.0, index=prices.index, columns=self.assets)

        warmup = max(self.ma_long, self.mom_lookback, 250)
        n_pool = len(self.etf_pool)
        if warmup > 0 and n_pool > 0:
            for etf in self.etf_pool:
                if etf in weights.columns:
                    weights.loc[weights.index[:warmup], etf] = 1.0 / n_pool

        # 逐日计算
        for i in range(warmup, n_days):
            # ── 1) 趋势过滤：筛选通过双过滤的ETF ──
            qualified = []
            for etf in self.etf_pool:
                if etf not in prices.columns:
                    continue
                closes = prices[etf].iloc[:i+1].values
                passed, _ = self._trend_filter(closes)
                if passed:
                    qualified.append(etf)

            # ── 2) 如果通过过滤的ETF不够，考虑防御池 ──
            if len(qualified) < self.top_n:
                for etf in self.defensive_pool:
                    if etf not in prices.columns or etf in qualified:
                        continue
                    closes = prices[etf].iloc[:i+1].values
                    passed, _ = self._trend_filter(closes)
                    if passed and etf not in qualified:
                        qualified.append(etf)

            # ── 3) 动量打分 ──
            if qualified:
                scores = {}
                for etf in qualified:
                    closes = prices[etf].iloc[:i+1].values
                    scores[etf] = self._momentum_score(closes)

                ranked = sorted(scores, key=scores.get, reverse=True)
                best_score = scores.get(ranked[0], -999)

                if best_score > 0:
                    n_select = min(self.top_n, len(ranked))
                    w = 1.0 / n_select
                    for etf in ranked[:n_select]:
                        if etf in weights.columns:
                            idx = weights.columns.get_loc(etf)
                            weights.iloc[i, idx] = w
                else:
                    # 动量全为负 → 切货币
                    if self.cash in weights.columns:
                        weights.iloc[i, weights.columns.get_loc(self.cash)] = 1.0
            else:
                # 全不过滤 → 切货币
                if self.cash in weights.columns:
                    weights.iloc[i, weights.columns.get_loc(self.cash)] = 1.0

        # ── 4) 周度调仓 ──
        if not live:
            weekly = weights.resample("W").last()
            weights = weekly.reindex(prices.index, method="ffill").bfill().fillna(0.0)
        return weights
