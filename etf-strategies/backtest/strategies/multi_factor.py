"""S13 多因子综合打分：动量+低波+趋势质量+成交量趋势 四因子加权选Top-K。

原理：单因子策略存在周期性失效风险。综合多个互补因子可平滑收益曲线、
降低单一因子失效的冲击。四个因子覆盖不同维度：
- 动量(40%)：捕捉趋势持续性
- 低波动(25%)：低波异象——低波动资产长期风险调整收益更优
- 趋势质量(20%)：log-price回归R²——筛掉假趋势（大波动无方向的震荡）
- 成交量趋势(15%)：成交活跃度变化——放量上涨比缩量上涨更可靠

月末调仓，无合适标的时切货币避险。

来源：聚宽"ETF加权轮动策略" + Stanford多因子回归框架
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from .base import Strategy


class MultiFactor(Strategy):
    """S13 多因子综合打分：四因子加权，月末调仓。"""

    name = "S13_多因子综合打分"

    def __init__(self, lookback=60, top_n=3,
                 etf_pool=None, cash="511880"):
        self.lookback = lookback      # 主回看期（动量+趋势质量）
        self.top_n = top_n
        self.cash = cash
        if etf_pool is None:
            etf_pool = [
                "512010",  # 医药ETF
                "512880",  # 证券ETF
                "512800",  # 银行ETF
                "512660",  # 军工ETF
                "510300",  # 沪深300ETF
            ]
        self.etf_pool = etf_pool
        self.assets = etf_pool + [cash]

    def generate(self, prices):
        n_days = len(prices)
        n_assets = len(self.etf_pool)
        weights = pd.DataFrame(0.0, index=prices.index,
                               columns=self.etf_pool + [self.cash])

        warmup = self.lookback
        if warmup > 0:
            weights.iloc[:warmup, :n_assets] = 1.0 / n_assets
            weights.iloc[:warmup, weights.columns.get_loc(self.cash)] = 0.0

        for i in range(warmup, n_days):
            window = prices.iloc[i - self.lookback + 1: i + 1]
            scores = {}

            for etf in self.etf_pool:
                closes = window[etf].values

                # F1: 动量因子 (40%) — 区间收益率
                mom = closes[-1] / closes[0] - 1.0

                # F2: 低波动因子 (25%) — 年化波动率倒数
                rets = np.diff(np.log(closes))
                ann_vol = np.std(rets) * np.sqrt(252) if len(rets) > 1 else 999.0
                if ann_vol < 0.001:
                    ann_vol = 0.001
                vol_score = 0.15 / ann_vol  # 以15%目标波动为基准
                vol_score = min(vol_score, 2.0)  # 截断极端值

                # F3: 趋势质量因子 (20%) — log-price OLS的R²
                y = np.log(closes)
                x = np.arange(len(y))
                slope, intercept = np.polyfit(x, y, 1)
                y_pred = slope * x + intercept
                ss_res = np.sum((y - y_pred) ** 2)
                ss_tot = (len(y) - 1) * np.var(y, ddof=1)
                r_sq = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0

                # F4: 成交量趋势因子 (15%) — 用价格波动幅度变化代理
                # 近期日均波动 / 历史日均波动 — 1.0
                half = len(closes) // 2
                if half > 0:
                    recent_vol = np.std(np.diff(closes[-half:]))
                    hist_vol = np.std(np.diff(closes))
                    if hist_vol > 1e-12:
                        vol_trend = recent_vol / hist_vol - 1.0
                    else:
                        vol_trend = 0.0
                else:
                    vol_trend = 0.0

                # 综合打分
                score = (0.40 * mom +
                         0.25 * vol_score +
                         0.20 * r_sq * max(mom, 0) +  # 趋势质量只在正动量时有意义
                         0.15 * vol_trend)

                scores[etf] = score

            ranked = sorted(scores, key=scores.get, reverse=True)
            best_score = scores.get(ranked[0], -999)

            # 无合适标的时切货币
            if best_score <= 0:
                weights.iloc[i, weights.columns.get_loc(self.cash)] = 1.0
            else:
                w = 1.0 / self.top_n
                for etf in ranked[:self.top_n]:
                    if etf in self.etf_pool:
                        idx = weights.columns.get_loc(etf)
                        weights.iloc[i, idx] = w

        # 月末调仓
        monthly = weights.resample("ME").last()
        weights = monthly.reindex(prices.index, method="ffill").bfill().fillna(0.0)
        return weights
