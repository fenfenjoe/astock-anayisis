"""S8 三因子动量轮动：乖离动量 + 斜率动量 + 效率动量 综合打分。

来源：猫哥AI量化（知乎）+ 掘金社区 ETF智能导航
原理：三个互补动量因子加权打分，辅以调仓阈值（challenger 需超出 leader 50%
才切换），显著降低换手率。跨市场ETF池（A股+海外+黄金）捕捉大类资产动量。

因子说明：
  F1 斜率动量 — log-price OLS回归：年化收益 × R²（趋势强度 × 质量）
  F2 乖离动量 — 价格相对MA的偏离趋势，捕捉短期超买超卖中的方向性
  F3 效率动量 — 方向/波动率比率，衡量趋势"效率"，避免高波动假趋势

每日调仓，阈值过滤减少冗余切换。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from .base import Strategy


class ThreeFactorMomentum(Strategy):
    """S8 三因子动量轮动：三因子加权打分 + 调仓阈值，每日评估。"""

    name = "S8_三因子动量轮动"

    def __init__(self, lookback=25, top_n=1, threshold=1.5,
                 etf_pool=None,
                 w_slope=0.4, w_bias=0.3, w_efficiency=0.3):
        self.lookback = lookback
        self.top_n = top_n
        self.threshold = threshold  # 挑战者需超出 leader 的倍数才切换
        self.w_slope = w_slope
        self.w_bias = w_bias
        self.w_efficiency = w_efficiency
        if etf_pool is None:
            etf_pool = ["513100", "159915", "510180", "518880"]
            # 纳指100 / 创业板 / 上证180 / 黄金ETF
        self.etf_pool = etf_pool
        self.assets = etf_pool

    # ── F1: 斜率动量因子 ──
    def _slope_factor(self, closes):
        """log-price OLS: 年化收益 × R²，归一化到 [0,1]"""
        y = np.log(closes)
        x = np.arange(len(y))
        slope, intercept = np.polyfit(x, y, 1)
        ann_ret = np.exp(slope * 250) - 1
        y_pred = slope * x + intercept
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = (len(y) - 1) * np.var(y, ddof=1)
        r_sq = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
        return ann_ret * r_sq

    # ── F2: 乖离动量因子 ──
    def _bias_factor(self, closes, ma_period=10):
        """价格相对MA的偏离趋势斜率。偏离持续扩大=趋势强化。"""
        ma = pd.Series(closes).rolling(ma_period, min_periods=1).mean().values
        bias = closes / ma  # >1 价格在均线上方
        # 对乖离率序列做线性回归，斜率为趋势方向
        bias_recent = bias[-min(len(bias), self.lookback):]
        x = np.arange(len(bias_recent))
        if len(bias_recent) < 3:
            return 0.0
        slope, _ = np.polyfit(x, bias_recent, 1)
        return slope * 100  # 放大到可读量级

    # ── F3: 效率动量因子 ──
    def _efficiency_factor(self, prices_df):
        """方向 / 波动率 = 趋势效率。高分=方向明确且路径平滑。"""
        period = min(self.lookback, len(prices_df))
        window = prices_df.iloc[-period:]
        # 用 pivot price = (O+H+L+C)/4 减少噪声
        if all(c in window.columns for c in ["open", "high", "low", "close"]):
            pivot = (window["open"] + window["high"] +
                     window["low"] + window["close"]) / 4.0
        else:
            pivot = window["close"] if "close" in window.columns else window.iloc[:, 0]

        pivot = pivot.values
        direction = abs(np.log(pivot[-1]) - np.log(pivot[0]))
        log_changes = np.abs(np.diff(np.log(pivot)))
        volatility = log_changes.sum()
        efficiency_ratio = direction / volatility if volatility > 1e-12 else 0.0
        momentum = np.log(pivot[-1] / pivot[0])  # 正=涨，负=跌
        return momentum * efficiency_ratio * 100  # 放大

    def generate(self, prices):
        n_days = len(prices)
        n_assets = len(self.etf_pool)
        weights = pd.DataFrame(0.0, index=prices.index, columns=self.etf_pool)

        warmup = self.lookback - 1
        if warmup > 0:
            weights.iloc[:warmup] = 1.0 / n_assets

        # 需要完整OHLC用于效率因子，尝试用收盘价近似
        has_ohlc = all(c in prices.columns for c in ["open", "high", "low", "close"])
        # prices 只是收盘价 DataFrame（列=资产），没有 OHLC。用收盘价近似
        # 构建简易OHLC: 用close代替所有字段
        ohlc = {}
        for etf in self.etf_pool:
            ohlc[etf] = pd.DataFrame({
                "open": prices[etf],
                "high": prices[etf],
                "low": prices[etf],
                "close": prices[etf],
            }, index=prices.index)

        current_holding = None  # 追踪当前持仓，用于阈值判断

        for i in range(warmup, n_days):
            scores = {}
            for etf in self.etf_pool:
                closes = prices[etf].iloc[i - self.lookback + 1: i + 1].values
                ohlc_window = ohlc[etf].iloc[i - self.lookback + 1: i + 1]

                f1 = self._slope_factor(closes)
                f2 = self._bias_factor(closes)
                f3 = self._efficiency_factor(ohlc_window)

                # Min-Max 归一化到 [-1, 1] 区间不方便（全局未知），
                # 采用原始值加权，依赖因子本身量级
                # 实际上三个因子原始量级不同，这里用简单的标准化
                score = (self.w_slope * f1 +
                         self.w_bias * f2 +
                         self.w_efficiency * f3)
                scores[etf] = score

            ranked = sorted(scores, key=scores.get, reverse=True)

            # 阈值过滤：只有挑战者得分超出当前持有者 threshold 倍才切换
            if current_holding is not None and ranked[0] != current_holding:
                leader_score = scores.get(ranked[0], 0)
                holder_score = scores.get(current_holding, 0)
                # 如果当前持仓不在 pool（不应发生），强制切换
                if current_holding in self.etf_pool:
                    if holder_score > 0 and leader_score / holder_score < self.threshold:
                        ranked[0] = current_holding  # 维持原持仓

            top = ranked[:self.top_n]
            current_holding = top[0]
            w = 1.0 / len(top)
            for etf in top:
                idx = self.etf_pool.index(etf)
                weights.iloc[i, idx] = w

        return weights
