"""S18 RSRS增强+反转因子动量轮动：RSRS Beta z-score过滤 + 25d/200d反转动量打分。

来源：聚宽 @hayy "ETF核心资产轮动-添油加醋" (post/23696793bd901970f0d2b375a2d92440)
      原始指标：年化 35.29%, Sortino 1.971, 最大回撤 -22.86% (2015-2023, 8年, 398克隆)

原理：
1. 动量打分：对数价格 OLS 回归 → 年化收益 × R²（与 S4 同款公式）
2. 反转因子：综合得分 = 25日动量 - (200日动量 / 6)，惩罚"强弩之末"的长期趋势，
   避免在趋势末端追高买入
3. RSRS 过滤：计算 log(high) vs log(low) 的 OLS 斜率（RSRS Beta），当 Beta 的
   z-score < -2.0 时表示市场支撑/阻力结构弱化，排除该 ETF
4. 得分差过滤：最高最低分差过小（< score_range_min）时说明所有 ETF 趋势相似，
   无明确领先者，不调仓切现金

综合得分 = 25日动量 - (200日动量 / 6)
选 Top-1，每日调仓。无合格标的时切现金(511880)。

RSRS 数据通过读取缓存 parquet 文件获取 high/low 列，无需额外 API 调用。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from pathlib import Path
from .base import Strategy

# 缓存目录（与 data.py 一致）
_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache"


class RsrsReversalMomentum(Strategy):
    """S18 RSRS增强+反转因子动量轮动"""

    name = "S18_RSRS增强反转动量"

    def __init__(self, mom_short=25, mom_long=200, reversal_scale=6.0,
                 rsrs_window=20, rsrs_zscore_window=60, rsrs_zscore_threshold=-2.0,
                 score_range_min=0.02, top_n=1,
                 etf_pool=None, cash="511880"):
        self.mom_short = mom_short                # 短期动量回看天数
        self.mom_long = mom_long                  # 长期动量回看天数（反转因子）
        self.reversal_scale = reversal_scale       # 反转因子缩放系数
        self.rsrs_window = rsrs_window             # RSRS Beta 计算窗口
        self.rsrs_zscore_window = rsrs_zscore_window  # z-score 滚动窗口
        self.rsrs_zscore_threshold = rsrs_zscore_threshold  # z-score 排除阈值
        self.score_range_min = score_range_min     # 得分差最小阈值
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
        self.assets = list(dict.fromkeys(etf_pool + [cash]))

    # ── 辅助方法 ──

    def _momentum_score(self, closes, lookback):
        """年化收益 × R² 打分（与 S4/S15 同款公式）。"""
        if len(closes) < lookback:
            return 0.0
        y = np.log(closes[-lookback:])
        x = np.arange(len(y))
        slope, intercept = np.polyfit(x, y, 1)
        ann_ret = np.exp(slope * 250) - 1
        y_pred = slope * x + intercept
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = (len(y) - 1) * np.var(y, ddof=1) if len(y) > 1 else 1e-12
        r_sq = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
        return ann_ret * max(r_sq, 0.0)

    def _rsrs_beta(self, highs, lows):
        """RSRS Beta: OLS slope of log(high) vs log(low)。"""
        if len(highs) < self.rsrs_window:
            return 0.0
        log_high = np.log(highs[-self.rsrs_window:])
        log_low = np.log(lows[-self.rsrs_window:])
        # 确保没有 inf/nan
        mask = np.isfinite(log_high) & np.isfinite(log_low)
        if mask.sum() < self.rsrs_window // 2:
            return 0.0
        slope, _ = np.polyfit(log_low[mask], log_high[mask], 1)
        return float(slope)

    def _load_ohlc(self, codes, dates):
        """从缓存 parquet 读取 high/low 数据，对齐到给定日期索引。"""
        highs = {}
        lows = {}
        for code in codes:
            cache_file = _CACHE_DIR / f"{code}.parquet"
            if not cache_file.exists():
                continue
            try:
                df = pd.read_parquet(cache_file)
            except Exception:
                # 缓存文件损坏 → 跳过该 ETF 的 RSRS 数据，优雅降级
                continue
            # 对齐日期
            common = df.index.intersection(dates)
            if len(common) == 0:
                continue
            df = df.loc[common]
            if "high" in df.columns and "low" in df.columns:
                highs[code] = df["high"]
                lows[code] = df["low"]
        return pd.DataFrame(highs), pd.DataFrame(lows)

    # ── 核心方法 ──

    def _precompute_rsrs(self, highs_df, lows_df):
        """预计算 RSRS Beta 和 z-score 序列（避免 O(n²) 三重循环）。

        Returns:
            rsrs_z: DataFrame (日期×ETF) — RSRS Beta z-score
            rsrs_beta: DataFrame (日期×ETF) — 原始 RSRS Beta 值
        """
        pool = [e for e in self.etf_pool
                if e in highs_df.columns and e in lows_df.columns]
        if not pool:
            return pd.DataFrame(index=highs_df.index), pd.DataFrame(index=highs_df.index)

        n = len(highs_df)
        betas = pd.DataFrame(index=highs_df.index, columns=pool, dtype=float)
        zscores = pd.DataFrame(index=highs_df.index, columns=pool, dtype=float)

        for etf in pool:
            h = highs_df[etf].values
            l = lows_df[etf].values

            # 预计算 RSRS Beta（滑动窗口 OLS）
            for i in range(self.rsrs_window - 1, n):
                log_h = np.log(h[i - self.rsrs_window + 1: i + 1])
                log_l = np.log(l[i - self.rsrs_window + 1: i + 1])
                mask = np.isfinite(log_h) & np.isfinite(log_l)
                if mask.sum() >= self.rsrs_window // 2:
                    slope, _ = np.polyfit(log_l[mask], log_h[mask], 1)
                    betas.iloc[i, betas.columns.get_loc(etf)] = float(slope)

            # 预计算滚动 z-score
            beta_vals = betas[etf].values
            for i in range(self.rsrs_zscore_window, n):
                window = beta_vals[i - self.rsrs_zscore_window + 1: i + 1]
                # 排除 NaN（初始化/数据不足）
                valid = window[~np.isnan(window)]
                if len(valid) < self.rsrs_zscore_window // 2:
                    continue
                mean_b = np.mean(valid)
                std_b = np.std(valid, ddof=1)
                if std_b > 1e-12 and not np.isnan(beta_vals[i]):
                    zscores.iloc[i, zscores.columns.get_loc(etf)] = (
                        (beta_vals[i] - mean_b) / std_b
                    )

        return zscores, betas

    def generate(self, prices):
        """每日计算 RSRS 过滤 + 反转动量打分，选 top_n 等权持有。"""
        n_days = len(prices)
        weights = pd.DataFrame(0.0, index=prices.index, columns=self.assets)

        # 加载 high/low 数据并预计算 RSRS
        trade_etfs = [e for e in self.etf_pool if e in prices.columns]
        highs_df, lows_df = self._load_ohlc(trade_etfs, prices.index)
        rsrs_z, _ = self._precompute_rsrs(highs_df, lows_df)
        # 对齐 RSRS z-score 到 prices 的日期索引
        rsrs_z = rsrs_z.reindex(prices.index)

        # warmup: 前 max(mom_long, rsrs_zscore_window) 天全仓现金（默认 200 天）
        # 等待动量回看窗口充分积累数据后再启动轮动
        warmup = max(self.mom_long, self.rsrs_zscore_window)
        if warmup > 0 and self.cash in weights.columns:
            weights.loc[weights.index[:warmup], self.cash] = 1.0

        # 逐日计算（仅做查找，不做重复计算）
        for i in range(warmup, n_days):
            # ── 1) RSRS过滤：排除市场结构弱化的ETF ──
            rsrs_pass = set()
            for etf in self.etf_pool:
                if etf not in prices.columns:
                    continue
                # 无 RSRS 数据则通过
                if etf not in rsrs_z.columns:
                    rsrs_pass.add(etf)
                    continue
                z = rsrs_z[etf].iloc[i]
                if pd.isna(z) or z >= self.rsrs_zscore_threshold:
                    rsrs_pass.add(etf)

            # ── 2) 反转动量打分 ──
            candidates = list(rsrs_pass)
            if not candidates:
                if self.cash in weights.columns:
                    weights.iloc[i, weights.columns.get_loc(self.cash)] = 1.0
                continue

            scores = {}
            for etf in candidates:
                closes = prices[etf].iloc[:i+1].values
                mom25 = self._momentum_score(closes, self.mom_short)
                mom200 = self._momentum_score(closes, self.mom_long)
                composite = mom25 - (mom200 / self.reversal_scale)
                scores[etf] = composite

            # ── 3) 得分差过滤：分差太小则不调仓 ──
            if len(scores) >= 2:
                score_range = max(scores.values()) - min(scores.values())
                if score_range < self.score_range_min:
                    if self.cash in weights.columns:
                        weights.iloc[i, weights.columns.get_loc(self.cash)] = 1.0
                    continue

            # ── 4) 选 top_n ──
            ranked = sorted(scores, key=scores.get, reverse=True)
            best_score = scores.get(ranked[0], -999)

            if best_score > 0:
                n_select = min(self.top_n, len(ranked))
                w = 1.0 / n_select
                for etf in ranked[:n_select]:
                    if etf in weights.columns:
                        weights.iloc[i, weights.columns.get_loc(etf)] = w
            else:
                # 动量全为负 → 切现金
                if self.cash in weights.columns:
                    weights.iloc[i, weights.columns.get_loc(self.cash)] = 1.0

        return weights

    def get_diagnostics(self, prices):
        """返回最新的 RSRS Beta、z-score、25d/200d 动量分解及持仓。

        score_details 兼容前端标准格式（ann_return + r_squared + score），
        同时提供 S18 特有的 25d/200d 反转动量分解 + RSRS 诊断信息。
        RSRS z-score 直接复用 _precompute_rsrs 的滚动窗口 z-score，
        与 generate() 信号一致，避免"诊断与信号不同步"。
        """
        w = self.generate(prices)
        latest = w.iloc[-1]
        holdings = {str(c): round(float(latest.get(c, 0)), 4)
                    for c in self.assets if latest.get(c, 0) > 0.001}

        # 加载 high/low 并预计算 RSRS z-score（与 generate 内部一致）
        etfs_with_price = [e for e in self.etf_pool if e in prices.columns]
        highs_df, lows_df = self._load_ohlc(etfs_with_price, prices.index)
        rsrs_z, rsrs_beta_df = self._precompute_rsrs(highs_df, lows_df)
        # 对齐到 prices 的日期索引（reindex 确保 iloc 不越界）
        rsrs_z = rsrs_z.reindex(prices.index)
        rsrs_beta_df = rsrs_beta_df.reindex(prices.index)

        n_days = len(prices)
        i = n_days - 1
        latest_date = prices.index[i]

        score_details = {}
        scores = {}
        for etf in self.etf_pool:
            if etf not in prices.columns:
                continue
            closes = prices[etf].iloc[:i+1].values

            # ── 25d 动量分解（用于前端标准格式） ──
            ann_ret_25, r_sq_25 = self._momentum_decompose(closes, self.mom_short)
            # ── 200d 动量 ──
            mom200 = self._momentum_score(closes, self.mom_long)
            # ── composite = 25d动量 - (200d动量 / reversal_scale) ──
            mom25 = ann_ret_25 * max(r_sq_25, 0.0)
            composite = mom25 - (mom200 / self.reversal_scale)
            scores[etf] = round(float(composite), 6)

            # ── RSRS 诊断（复用预计算的滚动 z-score，与 generate 信号一致） ──
            rsrs_info = {
                "rsrs_beta": 0.0,
                "rsrs_zscore": 0.0,
                "rsrs_pass": True,
            }
            if etf in rsrs_z.columns and etf in rsrs_beta_df.columns:
                z = rsrs_z[etf].iloc[i]
                b = rsrs_beta_df[etf].iloc[i]
                if not pd.isna(z) or not pd.isna(b):
                    rsrs_info = {
                        "rsrs_beta": round(float(b) if not pd.isna(b) else 0.0, 4),
                        "rsrs_zscore": round(float(z) if not pd.isna(z) else 0.0, 4),
                        "rsrs_pass": bool(pd.isna(z) or z >= self.rsrs_zscore_threshold),
                    }

            # ── 兼容前端标准格式（ann_return + r_squared + score）──
            # score = composite（实际用于排名的分数）
            score_details[etf] = {
                "ann_return": round(float(ann_ret_25), 6),
                "r_squared": round(float(r_sq_25), 6),
                "score": round(float(composite), 6),
                # S18 特有字段
                "mom_25d": round(float(mom25), 6),
                "mom_200d": round(float(mom200), 6),
                "composite": round(float(composite), 6),
                "rsrs": rsrs_info,
            }

        return {
            "strategy_id": self.__class__.__name__,
            "latest_date": str(w.index[-1].date()),
            "parameters": {
                "短期动量(天)": self.mom_short,
                "长期动量(天)": self.mom_long,
                "反转缩放系数": self.reversal_scale,
                "RSRS窗口(天)": self.rsrs_window,
                "RSRS z-score窗口(天)": self.rsrs_zscore_window,
                "RSRS z-score阈值": self.rsrs_zscore_threshold,
                "得分差最小阈值": self.score_range_min,
                "持仓数量(top_n)": self.top_n,
            },
            "scores": scores,
            "score_details": score_details,
            "holdings": holdings,
        }

    def _momentum_decompose(self, closes, lookback):
        """与 _momentum_score 相同的 Log-OLS，但返回 (ann_ret, r_sq) 分解值。
        用于 get_diagnostics 提供前端标准格式的 ann_return + r_squared 字段。"""
        if len(closes) < lookback:
            return 0.0, 0.0
        y = np.log(closes[-lookback:])
        x = np.arange(len(y))
        slope, intercept = np.polyfit(x, y, 1)
        ann_ret = np.exp(slope * 250) - 1
        y_pred = slope * x + intercept
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = (len(y) - 1) * np.var(y, ddof=1) if len(y) > 1 else 1e-12
        r_sq = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
        return float(ann_ret), float(r_sq)
