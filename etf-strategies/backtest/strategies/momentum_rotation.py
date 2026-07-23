"""S4 多资产动量轮动：对数价格 OLS 回归，年化收益×R² 打分轮动。

来源：JoinQuant 聚宽社区（https://www.joinquant.com/post/26142）
原理：对每只ETF过去N天收盘价的对数做线性回归，以年化斜率收益×判定系数(R²)
作为动量质量分数。R²越高说明趋势越"干净"（少震荡），选分数最高的持有。
跨资产类别（黄金/海外/成长/价值）轮动，捕捉大类资产动量。

每日调仓 — 于9:30运行确保即时捕捉动量变化。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from .base import Strategy


class MomentumRotation(Strategy):
    """S4 多资产动量轮动：log-price 回归打分，年化收益×R²，选最高分持有。"""

    name = "S4_多资产动量轮动"

    def __init__(self, lookback=25, top_n=1,
                 gold="518880", nasdaq="513100", chinext="159915", sse180="510180"):
        self.lookback = lookback
        self.top_n = top_n
        self.gold = gold          # 黄金ETF（大宗商品）
        self.nasdaq = nasdaq      # 纳指100（海外资产）
        self.chinext = chinext    # 创业板100（成长股/科技股/中小盘）
        self.sse180 = sse180      # 上证180（价值股/蓝筹股/中大盘）
        self.etf_pool = [gold, nasdaq, chinext, sse180]
        self.assets = self.etf_pool

    def generate(self, prices):
        """每日计算回归打分，选 top_n 等权持有。warmup 期等权分配。"""
        n_days = len(prices)
        n_assets = len(self.etf_pool)
        weights = pd.DataFrame(0.0, index=prices.index, columns=self.etf_pool)

        # warmup: 前 (lookback-1) 天数据不足，等权持有
        warmup = self.lookback - 1
        if warmup > 0:
            weights.iloc[:warmup] = 1.0 / n_assets

        # 每日滚动计算 log-price OLS 回归打分
        for i in range(warmup, n_days):
            # 取最近 lookback 天（含当日），引擎 shift(1) 保证无前视
            window = prices.iloc[i - self.lookback + 1: i + 1]
            scores = {}
            for etf in self.etf_pool:
                closes = window[etf].values
                y = np.log(closes)
                x = np.arange(len(y))
                # OLS: y = slope * x + intercept
                slope, intercept = np.polyfit(x, y, 1)
                # 年化收益 = exp(日斜率 × 250) - 1
                annualized_return = np.exp(slope * 250) - 1
                # 判定系数 R² = 1 - SS_res / SS_tot
                y_pred = slope * x + intercept
                ss_res = np.sum((y - y_pred) ** 2)
                ss_tot = (len(y) - 1) * np.var(y, ddof=1)
                r_squared = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
                # 分数 = 年化收益 × R²（趋势强度 × 趋势质量）
                scores[etf] = annualized_return * r_squared

            # 按分数降序，选 top_n 等权
            ranked = sorted(scores, key=scores.get, reverse=True)
            w = 1.0 / self.top_n
            for etf in ranked[:self.top_n]:
                idx = self.etf_pool.index(etf)
                weights.iloc[i, idx] = w

        # 每日调仓 — 不做 resample，引擎 shift(1) 处理滞后
        return weights

    def get_diagnostics(self, prices):
        """返回最新的各ETF动量分解：年化收益、R²、综合得分。"""
        import numpy as np
        w = self.generate(prices)
        latest = w.iloc[-1]
        holdings = {str(c): round(float(latest.get(c, 0)), 4)
                    for c in self.assets if latest.get(c, 0) > 0.001}

        # 计算最新一期的各ETF动量分解
        n_days = len(prices)
        i = n_days - 1  # 最新一天
        window = prices.iloc[i - self.lookback + 1: i + 1]

        score_details = {}
        scores = {}
        for etf in self.etf_pool:
            closes = window[etf].values
            y = np.log(closes)
            x = np.arange(len(y))
            slope, intercept = np.polyfit(x, y, 1)
            ann_ret = np.exp(slope * 250) - 1
            y_pred = slope * x + intercept
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = (len(y) - 1) * np.var(y, ddof=1) if len(y) > 1 else 1e-12
            r_sq = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
            score = ann_ret * r_sq
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
            },
            "scores": scores,
            "score_details": score_details,  # 新增：年化收益+R²+得分明细
            "holdings": holdings,
        }
