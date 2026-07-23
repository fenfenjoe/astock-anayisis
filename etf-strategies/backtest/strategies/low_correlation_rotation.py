"""S19 低相关ETF轮动：五类跨资产低相关ETF动量轮动，低相关池=天然风控。

来源：知乎专栏 "RSRS动量ETF轮动" (zhuanlan.zhihu.com/p/24155902542)
      实测指标：Sharpe 2.69, 最大回撤 ~10% (2024-2025 实盘1年+)

原理：
1. ETF 池设计是核心创新——五类资产天然低相关：
   - 黄金（518880）：避险资产，股市下跌时往往上涨
   - 纳指100（513100）：海外科技成长，与A股低相关
   - 创业板（159915）：A股成长/中小盘
   - 国债（511260）：利率债，与股市负相关或低相关
   - 沪深300（510300）：A股大盘价值
   组合在一起形成天然对冲——某一类资产下跌时另一类往往在上涨。

2. 动量打分：25日对数价格 OLS 回归 → 年化收益 × R²（标准公式）
3. 选 Top-1 满仓持有，周度调仓（减少噪音交易和换手成本）
4. 无显式止损——低相关池本身就是风控机制

调仓频率：周度（每周最后交易日信号），减少噪音交易。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from .base import Strategy


class LowCorrelationRotation(Strategy):
    """S19 低相关ETF轮动：五类跨资产低相关ETF动量轮动"""

    name = "S19_低相关ETF轮动"

    def __init__(self, lookback=25, top_n=1,
                 gold="518880", nasdaq="513100", chinext="159915",
                 treasury="511260", csi300="510300"):
        self.lookback = lookback
        self.top_n = top_n
        self.gold = gold          # 黄金ETF（避险资产）
        self.nasdaq = nasdaq      # 纳指100（海外成长）
        self.chinext = chinext    # 创业板（A股成长）
        self.treasury = treasury  # 国债ETF（利率债）
        self.csi300 = csi300      # 沪深300（A股大盘）
        self.etf_pool = [gold, nasdaq, chinext, treasury, csi300]
        self.assets = self.etf_pool

    def _momentum_score(self, closes):
        """年化收益 × R² 打分（与 S4/S15 同款公式）。"""
        if len(closes) < self.lookback:
            return 0.0
        y = np.log(closes[-self.lookback:])
        x = np.arange(len(y))
        slope, intercept = np.polyfit(x, y, 1)
        ann_ret = np.exp(slope * 250) - 1
        y_pred = slope * x + intercept
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = (len(y) - 1) * np.var(y, ddof=1) if len(y) > 1 else 1e-12
        r_sq = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
        return ann_ret * max(r_sq, 0.0)

    def generate(self, prices, live=False):
        """每日计算动量打分，选 top_n 等权持有。周度调仓。

        Args:
            prices: DataFrame of close prices (index=date, columns=assets)
            live: If True, return raw daily weights for live signal use
                  (daily_signal.py detects day-to-day rotations).
                  If False (backtest), apply weekly resample + ffill + bfill
                  to match the strategy's weekly rebalance frequency.
        """
        n_days = len(prices)
        n_assets = len(self.etf_pool)
        weights = pd.DataFrame(0.0, index=prices.index, columns=self.etf_pool)

        # warmup: 前 (lookback-1) 天等权持有
        warmup = self.lookback - 1
        if warmup > 0 and n_assets > 0:
            weights.iloc[:warmup] = 1.0 / n_assets

        # 每日滚动计算动量打分
        for i in range(warmup, n_days):
            scores = {}
            for etf in self.etf_pool:
                if etf not in prices.columns:
                    continue
                closes = prices[etf].iloc[:i+1].values
                scores[etf] = self._momentum_score(closes)

            if not scores:
                continue

            # 按分数降序，选 top_n 等权
            ranked = sorted(scores, key=scores.get, reverse=True)
            n_select = min(self.top_n, len(ranked))
            w = 1.0 / n_select
            for etf in ranked[:n_select]:
                idx = self.etf_pool.index(etf)
                weights.iloc[i, idx] = w

        # ── 周度调仓 ──
        if not live:
            # Backtest mode: apply weekly resampling.
            # ffill: propagate Friday's signal to the following week.
            # bfill: backfill the first weekly signal to earlier dates
            #        (before the first weekly resample point) so the
            #        backtest does not start 100% uninvested.
            weekly = weights.resample("W").last()
            weights = weekly.reindex(prices.index, method="ffill").bfill().fillna(0.0)
        # Live mode: return raw daily weights so callers (daily_signal.py)
        # can detect day-to-day signal rotation.
        return weights

    def get_diagnostics(self, prices):
        """返回最新的各ETF动量分解：年化收益、R²、综合得分。"""
        w = self.generate(prices)
        latest = w.iloc[-1]
        holdings = {str(c): round(float(latest.get(c, 0)), 4)
                    for c in self.assets if latest.get(c, 0) > 0.001}

        n_days = len(prices)
        i = n_days - 1

        score_details = {}
        scores = {}
        for etf in self.etf_pool:
            if etf not in prices.columns:
                continue
            closes = prices[etf].iloc[:i+1].values
            y = np.log(closes[-self.lookback:])
            x = np.arange(len(y))
            slope, intercept = np.polyfit(x, y, 1)
            ann_ret = np.exp(slope * 250) - 1
            y_pred = slope * x + intercept
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = (len(y) - 1) * np.var(y, ddof=1) if len(y) > 1 else 1e-12
            r_sq = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
            score = ann_ret * max(r_sq, 0.0)
            scores[etf] = round(float(score), 6)
            score_details[etf] = {
                "ann_return": round(float(ann_ret), 6),
                "r_squared": round(float(r_sq), 4),
                "score": round(float(score), 6),
            }

        return {
            "strategy_id": self.__class__.__name__,
            "latest_date": str(w.index[-1].date()),
            "parameters": {
                "回看窗口(天)": self.lookback,
                "持仓数量(top_n)": self.top_n,
                "调仓频率": "周度",
                "ETF池": self.etf_pool,
            },
            "scores": scores,
            "score_details": score_details,
            "holdings": holdings,
        }
