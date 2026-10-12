"""S20 四基轮动+RSRS择时：60% 动量轮动仓 + 40% RSRS择时仓（双仓并行）。

来源：聚宽 @泽安投资 "稳定而简单的四基轮动策略，找了好久的" (post/61282)
      原策略克隆自 @mackintosh "ETF轮动+择时策略" (post/61155)
      backtestId=fedc660c127485408a499e7801c558d5（原始回测见聚宽平台）

原理：
1. 双仓并行结构：
   - 轮动仓（60%）：4只ETF池（黄金/纳指/创业板/上证180）用20日简单动量
     (last/first-1) 选最高分持有，每3天调仓
   - 择时仓（40%）：沪深300(510300) 用15日RSRS（log high vs log low OLS斜率）
     判定趋势：RSRS>1.0 全仓择时，RSRS<0.8 半仓，否则维持
2. 调仓节奏：每3个交易日调仓一次（调仓日更新权重，中间持有）
3. 风控：动量全负或数据不足 → 轮动仓切货币ETF(511880)避险

本地化适配（JoinQuant → 本框架）：
- attribute_history(etf,30,'1d',['close']) → prices[etf].iloc[-30:]
- attribute_history(TIMING_ETF,25,'1d',['high','low','close']) → 缓存 parquet 的 high/low
- order_target_value(etf, value) → 目标权重（60%/40% 双仓）
- run_daily(daily_trade) + 每3天调仓 → generate() 内用调仓日索引
- context.portfolio.total_value → 归一化权重（和≈1）
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path

import pandas as pd
import numpy as np

from .base import Strategy

# 缓存目录（与 data.py / S18 一致）
_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache"


class EtfTimingRotation(Strategy):
    """S20 四基轮动+RSRS择时（60%动量轮动 + 40%RSRS择时）"""

    name = "S20_四基轮动RSRS择时"

    def __init__(self, rotation_weight=0.6, timing_weight=0.4,
                 momentum_period=20, rsrs_period=15, rebalance_days=3,
                 rsrs_buy=1.0, rsrs_trim=0.8,
                 etf_pool=None, timing_etf="510300", cash="511880"):
        self.rotation_weight = rotation_weight     # 轮动仓权重
        self.timing_weight = timing_weight         # 择时仓权重
        self.momentum_period = momentum_period     # 动量回看天数
        self.rsrs_period = rsrs_period             # RSRS 窗口
        self.rebalance_days = rebalance_days       # 调仓间隔（交易日）
        self.rsrs_buy = rsrs_buy                   # RSRS 买入阈值
        self.rsrs_trim = rsrs_trim                 # RSRS 减仓阈值
        self.timing_etf = timing_etf               # 择时标的
        self.cash = cash
        if etf_pool is None:
            etf_pool = [
                "518880",  # 黄金ETF
                "513100",  # 纳指100
                "159915",  # 创业板100
                "510180",  # 上证180
            ]
        self.etf_pool = etf_pool
        self.assets = list(dict.fromkeys(etf_pool + [timing_etf, cash]))

    # ── 辅助 ──

    def _momentum(self, closes):
        """20日简单动量：(last/first - 1) * 100。数据不足 → 0。"""
        if len(closes) < self.momentum_period:
            return 0.0
        recent = closes[-self.momentum_period:]
        return float((recent[-1] / recent[0] - 1) * 100)

    def _rsrs_slope(self, highs, lows):
        """15日 RSRS：log(high) vs log(low) OLS 斜率。数据不足/异常 → 1.0（默认持有）。"""
        if len(highs) < self.rsrs_period or len(lows) < self.rsrs_period:
            return 1.0
        try:
            h = np.log(highs[-self.rsrs_period:])
            l = np.log(lows[-self.rsrs_period:])
            mask = np.isfinite(h) & np.isfinite(l)
            if mask.sum() < self.rsrs_period // 2:
                return 1.0
            slope = np.polyfit(l[mask], h[mask], 1)[0]
            return float(slope) if not np.isnan(slope) else 1.0
        except Exception:
            return 1.0

    def _load_ohlc(self, code, dates):
        """从缓存 parquet 读取某 ETF 的 high/low，对齐到 dates。返回 (highs, lows)。"""
        cache_file = _CACHE_DIR / f"{code}.parquet"
        if not cache_file.exists():
            return pd.Series(dtype=float), pd.Series(dtype=float)
        try:
            df = pd.read_parquet(cache_file)
        except Exception:
            return pd.Series(dtype=float), pd.Series(dtype=float)
        common = df.index.intersection(dates)
        if len(common) == 0:
            return pd.Series(dtype=float), pd.Series(dtype=float)
        df = df.loc[common]
        return df["high"], df["low"]

    # ── 核心 ──

    def generate(self, prices):
        """每日计算双仓权重：每 rebalance_days 调仓，中间持有。

        轮动仓 = rotation_weight × top1动量ETF（动量≤0 → 现金）
        择时仓 = timing_weight × RSRS信号（>buy 全仓 / <trim 半仓 / 否则维持）
        """
        n_days = len(prices)
        weights = pd.DataFrame(0.0, index=prices.index, columns=self.assets)

        # 择时标的 high/low（缓存 parquet）
        timing_highs, timing_lows = self._load_ohlc(self.timing_etf, prices.index)
        # 缓存缺失 → 择时仓按 0 处理（数据不足保守避险）
        has_timing_data = (len(timing_highs) > 0) and (len(timing_lows) > 0)

        # warmup：前 momentum_period 天轮动仓现金（动量窗口不足）
        warmup = max(self.momentum_period, self.rsrs_period)
        if warmup > 0 and self.cash in weights.columns:
            weights.loc[weights.index[:warmup], self.cash] = 1.0

        last_rebalance = -10**9
        for i in range(warmup, n_days):
            # ── 调仓节奏：每 rebalance_days 个交易日调仓 ──
            if i - last_rebalance >= self.rebalance_days:
                last_rebalance = i

                # ── 轮动仓：20日动量选 top1 ──
                best_etf, best_score = None, -999.0
                for etf in self.etf_pool:
                    if etf not in prices.columns:
                        continue
                    closes = prices[etf].iloc[: i + 1].values
                    score = self._momentum(closes)
                    if score > best_score:
                        best_score = score
                        best_etf = etf

                rotation_row = {}
                if best_etf and best_score > 0:
                    rotation_row[best_etf] = self.rotation_weight
                else:
                    # 动量全负/不足 → 轮动仓现金
                    rotation_row[self.cash] = self.rotation_weight

                # ── 择时仓：RSRS 信号 ──
                timing_row = {}
                if has_timing_data and self.timing_etf in weights.columns:
                    # 用截至当日的数据（含当日，引擎 shift(1) 保证无前视）
                    h = timing_highs.loc[: prices.index[i]].values
                    l = timing_lows.loc[: prices.index[i]].values
                    rsrs = self._rsrs_slope(h, l)
                    if rsrs > self.rsrs_buy:
                        timing_row[self.timing_etf] = self.timing_weight
                    elif rsrs < self.rsrs_trim:
                        # 减半仓（其余留现金）
                        timing_row[self.timing_etf] = self.timing_weight * 0.5
                        timing_row[self.cash] = timing_row.get(self.cash, 0) + self.timing_weight * 0.5
                    else:
                        # 中间区：维持当前（首次进中间区则半仓）
                        timing_row[self.timing_etf] = self.timing_weight * 0.5
                        timing_row[self.cash] = timing_row.get(self.cash, 0) + self.timing_weight * 0.5

                # 合并双仓 → 写入当日权重
                for col, w in rotation_row.items():
                    if col in weights.columns:
                        weights.iloc[i, weights.columns.get_loc(col)] += w
                for col, w in timing_row.items():
                    if col in weights.columns:
                        weights.iloc[i, weights.columns.get_loc(col)] += w
            else:
                # 调仓间隔内的中间天：结转上次调仓的权重（持有不变）
                if i > 0:
                    weights.iloc[i] = weights.iloc[i - 1]

        return weights

    def get_diagnostics(self, prices):
        """返回最新一期各ETF动量、RSRS信号、双仓权重。"""
        w = self.generate(prices)
        latest = w.iloc[-1]
        holdings = {str(c): round(float(latest.get(c, 0)), 4)
                    for c in self.assets if latest.get(c, 0) > 0.001}

        n_days = len(prices)
        i = n_days - 1
        latest_date = str(prices.index[i].date())

        # 各ETF动量
        momentum = {}
        for etf in self.etf_pool:
            if etf in prices.columns:
                closes = prices[etf].iloc[: i + 1].values
                momentum[etf] = round(self._momentum(closes), 4)

        # RSRS 信号
        timing_highs, timing_lows = self._load_ohlc(self.timing_etf, prices.index)
        rsrs = None
        if len(timing_highs) > 0:
            h = timing_highs.loc[: prices.index[i]].values
            l = timing_lows.loc[: prices.index[i]].values
            rsrs = round(self._rsrs_slope(h, l), 4)

        return {
            "strategy_id": self.__class__.__name__,
            "latest_date": latest_date,
            "parameters": {
                "轮动仓权重": self.rotation_weight,
                "择时仓权重": self.timing_weight,
                "动量回看(天)": self.momentum_period,
                "RSRS窗口(天)": self.rsrs_period,
                "调仓间隔(天)": self.rebalance_days,
            },
            "scores": momentum,
            "score_details": {
                "momentum_20d": momentum,
                "rsrs_signal": rsrs,
                "rsrs_buy_threshold": self.rsrs_buy,
                "rsrs_trim_threshold": self.rsrs_trim,
            },
            "holdings": holdings,
        }
