"""S16 金丝雀防御+动量进攻：领先指标预警 + 动量ETF轮动。

原理："煤矿金丝雀"概念——用对风险敏感的领先资产（金丝雀）提前预警市场转向。
当金丝雀资产走弱时，即使动量信号仍然看多，也要降低风险敞口。

双层架构：
1. 金丝雀哨兵层：监控3类预警信号
   - 债券金丝雀：国债ETF是否在MA之上（债市领先股市3-6个月）
   - 波动率金丝雀：近期波动率是否异常放大
   - 动量宽度金丝雀：ETF池中正动量标的占比是否下降
2. 动量打分选股层：log-price OLS 回归 → 年化收益 × R² 打分（与S4同款）

防御等级（金丝雀触发数量）：
- 0只触发 → 进攻模式：100%动量ETF
- 1只触发 → 警戒模式：70%动量ETF + 30%货币
- 2只触发 → 防御模式：40%动量ETF + 60%货币
- 3只触发 → 避险模式：100%货币

月末调仓，降低交易成本。

来源：Meb Faber "金丝雀资产配置" + Ashwin Carvalho 风险预警框架
      改良适配A股ETF（用国债/黄金/波动率替代美股版金丝雀）
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from .base import Strategy


class CanaryDefense(Strategy):
    """S16 金丝雀防御+动量进攻 — 月度调仓版"""

    name = "S16_金丝雀防御动量"

    def __init__(self, mom_lookback=25, ma_bond=150, ma_vol=20,
                 top_n=2,
                 etf_pool=None, bond_etf="511260", gold_etf="518880",
                 cash="511880", rebalance="monthly"):
        self.mom_lookback = mom_lookback       # 动量打分回看
        self.ma_bond = ma_bond                  # 债券MA周期（金丝雀1）
        self.ma_vol = ma_vol                    # 波动率异常检测周期
        self.top_n = top_n
        self.bond_etf = bond_etf                # 债券金丝雀
        self.gold_etf = gold_etf                # 黄金（防御资产）
        self.cash = cash
        self.rebalance = rebalance              # "monthly" 或 "daily"
        if etf_pool is None:
            etf_pool = [
                "513100",  # 纳指100
                "159915",  # 创业板
                "510180",  # 上证180
                "510300",  # 沪深300
            ]
        self.etf_pool = etf_pool
        self.assets = list(dict.fromkeys(etf_pool + [bond_etf, gold_etf, cash]))

    def _momentum_score(self, closes):
        """年化收益 × R² 打分（log-price OLS 回归）。"""
        if len(closes) < self.mom_lookback:
            return 0.0
        y = np.log(closes[-self.mom_lookback:])
        x = np.arange(len(y))
        slope, intercept = np.polyfit(x, y, 1)
        # 年化收益 = exp(日斜率 × 250) - 1
        ann_ret = np.exp(slope * 250) - 1
        # 判定系数 R² = 1 - SS_res / SS_tot（趋势质量）
        y_pred = slope * x + intercept
        ss_res = np.sum((y - y_pred) ** 2)
        ss_tot = (len(y) - 1) * np.var(y, ddof=1) if len(y) > 1 else 1e-12
        r_sq = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
        return ann_ret * max(r_sq, 0)

    def _canary_bond(self, bond_closes):
        """金丝雀1 — 债券趋势：国债是否在MA之上。返回 True=金丝雀叫了（预警）。"""
        if len(bond_closes) < self.ma_bond:
            return False
        ma = np.mean(bond_closes[-self.ma_bond:])
        return bond_closes[-1] < ma  # 债券跌破MA → 预警

    def _canary_volatility(self, prices, etf_pool):
        """金丝雀2 — 波动率异常：近期波动率是否显著放大。返回 True=预警。"""
        signals = 0
        count = 0
        for etf in etf_pool:
            if etf not in prices.columns:
                continue
            closes = prices[etf].iloc[-self.ma_vol*3:].values if len(prices) > self.ma_vol*3 else prices[etf].values
            if len(closes) < self.ma_vol * 2:
                continue
            rets = np.diff(np.log(closes))
            recent_vol = np.std(rets[-self.ma_vol:]) * np.sqrt(252)
            hist_vol = np.std(rets[:-self.ma_vol]) * np.sqrt(252) if len(rets) > self.ma_vol else recent_vol
            if hist_vol > 0.001 and recent_vol / hist_vol > 1.5:
                signals += 1
            count += 1
        # 超过半数ETF波动率异常 → 预警
        return signals > count / 2 if count > 0 else False

    def _canary_breadth(self, prices, etf_pool):
        """金丝雀3 — 动量宽度：正动量ETF占比是否下降。返回 True=预警。"""
        positive = 0
        count = 0
        for etf in etf_pool:
            if etf not in prices.columns:
                continue
            closes = prices[etf].values
            if len(closes) < self.mom_lookback:
                continue
            mom = self._momentum_score(closes[-self.mom_lookback:])
            if mom > 0:
                positive += 1
            count += 1
        if count == 0:
            return False
        # 正动量占比 < 40% → 预警
        return positive / count < 0.4

    def generate(self, prices, live=False):
        """Generate target weights for each trading day.

        Args:
            prices: DataFrame of close prices (index=date, columns=assets)
            live: If True, skip monthly resample and return raw daily weights.
                  Used for live signal generation (current canary state).
        """
        n_days = len(prices)
        weights = pd.DataFrame(0.0, index=prices.index, columns=self.assets)

        warmup = max(self.ma_bond, self.ma_vol * 3, self.mom_lookback)
        n_pool = len(self.etf_pool)
        if warmup > 0 and n_pool > 0:
            for etf in self.etf_pool:
                if etf in weights.columns:
                    weights.loc[weights.index[:warmup], etf] = 1.0 / n_pool

        # 逐日计算
        for i in range(warmup, n_days):
            # ── 1) 金丝雀预警检测 ──
            warnings = 0

            # 金丝雀1：债券趋势
            if self.bond_etf in prices.columns:
                bond_closes = prices[self.bond_etf].iloc[:i+1].values
                if self._canary_bond(bond_closes):
                    warnings += 1

            # 金丝雀2：波动率异常
            # 取到当前日期的切片
            slice_prices = prices.iloc[:i+1]
            if self._canary_volatility(slice_prices, self.etf_pool):
                warnings += 1

            # 金丝雀3：动量宽度
            if self._canary_breadth(slice_prices, self.etf_pool):
                warnings += 1

            # ── 2) 根据防御等级确定风险预算 ──
            if warnings == 0:
                risk_budget = 1.0    # 进攻
            elif warnings == 1:
                risk_budget = 0.7    # 警戒
            elif warnings == 2:
                risk_budget = 0.4    # 防御
            else:
                risk_budget = 0.0    # 避险

            # ── 3) 动量打分选股 ──
            if risk_budget > 0:
                scores = {}
                for etf in self.etf_pool:
                    if etf not in prices.columns:
                        continue
                    closes = prices[etf].iloc[:i+1].values
                    scores[etf] = self._momentum_score(closes)

                if scores:
                    ranked = sorted(scores, key=scores.get, reverse=True)
                    n_select = min(self.top_n, len(ranked))
                    w_each = risk_budget / n_select
                    for etf in ranked[:n_select]:
                        if etf in weights.columns:
                            idx = weights.columns.get_loc(etf)
                            weights.iloc[i, idx] = w_each

            # ── 4) 剩余仓位 → 货币 ──
            equity_sum = weights.iloc[i, [weights.columns.get_loc(e)
                             for e in self.etf_pool if e in weights.columns]].sum()
            remaining = 1.0 - equity_sum
            if remaining > 0 and self.cash in weights.columns:
                weights.iloc[i, weights.columns.get_loc(self.cash)] = remaining

        # ── 5) 调仓频率处理 ──
        if self.rebalance == "monthly":
            if not live:
                monthly = weights.resample("ME").last()
                weights = monthly.reindex(prices.index, method="ffill").bfill().fillna(0.0)
            else:
                # Live mode: monthly-resampled history + raw last day.
                # This ensures prev_w (上期权重) matches the backtest's month-end
                # forward-filled position, while today_w reflects the current canary
                # assessment and momentum scores.
                if len(weights) > 1:
                    hist = weights.iloc[:-1]
                    monthly = hist.resample("ME").last()
                    hist_monthly = monthly.reindex(hist.index, method="ffill").bfill().fillna(0.0)
                    weights = pd.concat([hist_monthly, weights.iloc[[-1]]])
        # daily: return raw daily weights as-is (no resample)
        return weights

    def get_diagnostics(self, prices):
        """Return canary defense internal state for the most recent trading day."""
        import numpy as np
        i = len(prices) - 1

        # ── Canary 1: Bond trend ──
        bond_triggered = False
        bond_current = None
        bond_ma = None
        if self.bond_etf in prices.columns:
            bond_closes = prices[self.bond_etf].iloc[:i+1].values
            bond_triggered = self._canary_bond(bond_closes)
            if len(bond_closes) >= self.ma_bond:
                bond_current = round(float(bond_closes[-1]), 4)
                bond_ma = round(float(np.mean(bond_closes[-self.ma_bond:])), 4)

        # ── Canary 2: Volatility ──
        vol_triggered = False
        vol_details = []
        if i >= self.ma_vol * 3:
            vol_triggered = self._canary_volatility(prices.iloc[:i+1], self.etf_pool)
            # Collect per-ETF volatility ratios for display
            # IMPORTANT: must use same data window as _canary_volatility()
            # (last ma_vol*3 points) so displayed ratios match the trigger decision
            for etf in self.etf_pool:
                if etf not in prices.columns:
                    continue
                slice_prices = prices.iloc[:i+1]
                closes = slice_prices[etf].iloc[-self.ma_vol*3:].values if len(slice_prices) > self.ma_vol*3 else slice_prices[etf].values
                if len(closes) < self.ma_vol * 2:
                    continue
                rets = np.diff(np.log(closes))
                recent_vol = float(np.std(rets[-self.ma_vol:]) * np.sqrt(252))
                hist_vol = float(np.std(rets[:-self.ma_vol]) * np.sqrt(252)) if len(rets) > self.ma_vol else recent_vol
                raw_ratio = recent_vol / hist_vol if hist_vol > 0.001 else 1.0
                ratio = round(raw_ratio, 2)
                vol_details.append({
                    "etf": etf,
                    "short_vol": round(recent_vol, 4),
                    "long_vol": round(hist_vol, 4),
                    "ratio": ratio,
                    "triggered": raw_ratio > 1.5,
                })

        # ── Canary 3: Breadth ──
        breadth_triggered = False
        breadth_positive = 0
        breadth_total = 0
        if i >= self.mom_lookback:
            breadth_triggered = self._canary_breadth(prices.iloc[:i+1], self.etf_pool)
            for etf in self.etf_pool:
                if etf not in prices.columns:
                    continue
                closes = prices[etf].iloc[:i+1].values
                if len(closes) < self.mom_lookback:
                    continue
                mom = self._momentum_score(closes[-self.mom_lookback:])
                if mom > 0:
                    breadth_positive += 1
                breadth_total += 1

        warnings = sum([bond_triggered, vol_triggered, breadth_triggered])
        risk_map = {0: 1.0, 1: 0.7, 2: 0.4, 3: 0.0}
        risk_budget = risk_map.get(warnings, 0.0)

        # ── Momentum scores + breakdown ──
        scores = {}
        score_details = {}
        for etf in self.etf_pool:
            if etf in prices.columns:
                closes = prices[etf].iloc[:i+1].values
                if len(closes) < self.mom_lookback:
                    scores[etf] = 0.0
                    continue
                # log-OLS 回归分解（与 _momentum_score 同款公式）
                y = np.log(closes[-self.mom_lookback:])
                x = np.arange(len(y))
                slope, intercept = np.polyfit(x, y, 1)
                ann_ret = np.exp(slope * 250) - 1
                y_pred = slope * x + intercept
                ss_res = np.sum((y - y_pred) ** 2)
                ss_tot = (len(y) - 1) * np.var(y, ddof=1) if len(y) > 1 else 1e-12
                r_sq = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
                score = ann_ret * max(r_sq, 0)
                scores[etf] = round(float(score), 4)
                score_details[etf] = {
                    "ann_return": round(float(ann_ret), 6),
                    "r_squared": round(float(r_sq), 4),
                    "score": round(float(score), 6),
                }

        w = self.generate(prices, live=True)
        holdings = {str(c): round(float(w.iloc[-1].get(c, 0)), 4)
                    for c in self.assets if w.iloc[-1].get(c, 0) > 0.001}

        # ── Build parameters with current values + thresholds ──
        params = {}

        # 金丝雀1: 债券趋势
        if bond_current is not None and bond_ma is not None:
            params["金丝雀1_债券趋势"] = (
                f"{'🔴触发' if bond_triggered else '🟢正常'} | "
                f"当前价={bond_current} vs MA({self.ma_bond})={bond_ma} | "
                f"阈值: 价格<MA即触发"
            )
        else:
            params["金丝雀1_债券趋势"] = f"{'🔴触发' if bond_triggered else '🟢正常'} | 数据不足"

        # 金丝雀2: 波动率异常
        if vol_details:
            triggered_count = sum(1 for v in vol_details if v["triggered"])
            params["金丝雀2_波动率异常"] = (
                f"{'🔴触发' if vol_triggered else '🟢正常'} | "
                f"触发ETF: {triggered_count}/{len(vol_details)} | "
                f"阈值: 短/长波动率比>1.5 且超半数ETF触发"
            )
            for vd in vol_details:
                params[f"  └ {vd['etf']} 波动率"] = (
                    f"短(20日)={vd['short_vol']:.2%} 长(60日)={vd['long_vol']:.2%} "
                    f"比值={vd['ratio']} {'🔴' if vd['triggered'] else '🟢'}"
                )
        else:
            params["金丝雀2_波动率异常"] = f"{'🔴触发' if vol_triggered else '🟢正常'} | 数据不足"

        # 金丝雀3: 动量宽度
        if breadth_total > 0:
            breadth_pct = round(breadth_positive / breadth_total * 100, 1)
            params["金丝雀3_动量宽度"] = (
                f"{'🔴触发' if breadth_triggered else '🟢正常'} | "
                f"正动量: {breadth_positive}/{breadth_total} ({breadth_pct}%) | "
                f"阈值: 正动量占比<40%即触发"
            )
        else:
            params["金丝雀3_动量宽度"] = f"{'🔴触发' if breadth_triggered else '🟢正常'} | 数据不足"

        params["预警总数"] = f"{warnings}/3"
        params["风险预算"] = f"{risk_budget*100:.0f}%"
        params["仓位状态"] = "进攻" if warnings == 0 else ("警戒" if warnings == 1 else ("防御" if warnings == 2 else "避险"))

        sid = self.name.split("_")[0] if "_" in self.name else "S16"
        return {
            "strategy_id": sid,
            "latest_date": str(prices.index[-1].date()),
            "parameters": params,
            "scores": scores,
            "score_details": score_details,
            "holdings": holdings,
        }


class CanaryDefenseDaily(CanaryDefense):
    """S17 金丝雀防御+动量进攻 — 每日调仓版。

    与 S16 逻辑完全一致，唯一区别是调仓频率从月度改为每日。
    每日执行金丝雀预警评估 + 动量打分 + 仓位调整，反应更快但交易成本更高。
    """

    name = "S17_金丝雀防御动量_日频"

    def __init__(self, **kwargs):
        kwargs.setdefault("rebalance", "daily")
        super().__init__(**kwargs)
