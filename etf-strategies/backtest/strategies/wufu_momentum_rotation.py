"""S21 五福动量轮动（聚宽「五福闹新春」核心逻辑本地化）。

来源：聚宽社区「五福闹新春」策略（@烟花三月ETF，v2.0→v5.2 迭代）+ v7 优化
     克隆帖: https://www.joinquant.com/post/81357（蔷薇天下拆解文）
     克隆算法: algorithmId=89677cfaf5741fc425205f2e1bf79a88（用户聚宽研究环境）
     平台回测: backtestId=8d11496f72dd9f31d9a69fab33a5b989（聚宽分钟级）

核心逻辑（忠实还原）：
1. 候选池：固定精选池（全球17 + 大A~100）双轨合并；大A走弱期→仅用全球池
2. 打分：25日【加权线性回归】(权重 linspace(1,2)^2) log(price)~time
        → 年化斜率收益 exp(slope×250)-1 × R² = 动量得分
3. 过滤：动量∈[0,5] / R²>0.4 / 5日成交量比<1.8 / 近3日无单日跌>3% / 价>MA10
4. 选择：top-10 中取得分≥第2名×0.9 的候选（走弱期×1.0），结合持仓保留 → top-2 等权
5. 防御：无候选通过 → 货币ETF(511880)
6. 走弱期：沪深300/小盘/创业板/A500 四指数 ≥3个低于MA10（2日确认）→ 全球池

本地化适配（JoinQuant → 本框架）：
- attribute_history → prices 滚动窗口（引擎 shift(1) 保证无前视）
- get_price/成交量比 → 本地无成交量数据，volume 过滤降级为不拦截（数据缺失时保守放行）
- run_daily(13:10 调仓) → 每日调仓（本地日频）
- context.portfolio 持仓保留 → 简化：候选池按分数重选（引擎日频调仓近似）
- 分钟级 ATR/趋势择时/止损 → 本地日频框架不移植（记录于文档）
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from .base import Strategy


class WufuMomentumRotation(Strategy):
    """S21 五福动量轮动：加权回归动量得分（年化斜率×R²）+ 多层过滤 + top2 持有。"""

    name = "S21_五福动量轮动"

    # 聚宽 global_etf_pool → 本地6位代码（去掉 .XSHG/.XSHE 后缀）
    GLOBAL_POOL = [
        "518880", "501018", "161226", "159985", "159980",
        "513310", "159518", "159509", "513100", "513520",
        "513500", "159502", "513400", "513030", "513290",
        "520830", "159529",
    ]
    # 聚宽 china_etf_pool → 本地6位代码
    CHINA_POOL = [
        "513090", "513120", "513180", "513330", "513750",
        "159892", "513190", "159605", "513630", "159323",
        "510900", "513920", "513970", "511380", "512050",
        "510500", "159915", "510300", "512100", "159949",
        "588080", "159967", "588220", "563300", "510760",
        "588200", "515880", "159981", "512880", "513350",
        "159326", "159516", "159206", "512480", "159363",
        "159870", "512400", "159755", "588170", "159992",
        "159995", "512890", "515220", "159566", "159819",
        "512800", "512690", "515050", "562500", "512170",
        "517520", "159869", "512070", "159611", "562800",
        "515120", "512010", "510880", "515790", "515980",
        "512660", "159928", "512710", "560860", "515030",
        "159766", "159218", "159852", "516160", "516150",
        "159227", "159583", "588790", "159865", "512980",
        "159851", "561360", "561980", "562590", "512200",
        "159732", "159667", "516510", "159840", "159998",
        "159825", "512670", "159883", "515210", "515400",
        "159256", "561330", "515170", "159638", "516520",
        "513360", "516190",
    ]
    # 走弱期判断指数（本地无指数数据 → 用代表性 ETF 近似）
    WEAK_INDEX_PROXIES = {
        "000300": "510300",   # 沪深300 → 510300 ETF
        "399101": "512100",   # 中证1000(小盘) → 512100 ETF
        "399006": "159915",   # 创业板指 → 159915 ETF
        "000510": "510500",   # 中证A500 → 510500 ETF（近似）
    }

    def __init__(self, lookback=25, holdings_num=2, r2_threshold=0.4,
                 ma_lookback=10, volume_lookback=5, volume_threshold=1.8,
                 loss=0.97, min_score=0.0, max_score=5.0,
                 score_threshold_ratio=0.9, weak_ma_lookback=10,
                 weak_confirm_days=2, max_weak_days=20,
                 defensive="511880", global_pool=None, china_pool=None,
                 enable_volume_filter=False):
        self.lookback = lookback
        self.holdings_num = holdings_num
        self.r2_threshold = r2_threshold
        self.ma_lookback = ma_lookback
        self.volume_lookback = volume_lookback
        self.volume_threshold = volume_threshold
        self.loss = loss
        self.min_score = min_score
        self.max_score = max_score
        self.score_threshold_ratio = score_threshold_ratio
        self.weak_ma_lookback = weak_ma_lookback
        self.weak_confirm_days = weak_confirm_days
        self.max_weak_days = max_weak_days
        self.defensive = defensive
        self.global_pool = global_pool or list(self.GLOBAL_POOL)
        self.china_pool = china_pool or list(self.CHINA_POOL)
        # 成交量过滤：本地框架无成交量数据，默认关闭（不拦截）
        self.enable_volume_filter = enable_volume_filter
        # 全部资产 = 双池 + 防御
        self.assets = list(dict.fromkeys(self.global_pool + self.china_pool + [defensive]))

    # ── 核心打分：加权线性回归动量得分 ──

    def _momentum_score(self, closes):
        """25日加权线性回归 log(price)~time（权重 linspace(1,2)^2）。
        返回 (momentum_score, annualized_returns, r_squared)。数据不足 → (None,None,None)。"""
        if len(closes) < self.lookback + 1:
            return None, None, None
        recent = closes[- (self.lookback + 1):]
        try:
            y = np.log(recent)
        except Exception:
            return None, None, None
        if not np.all(np.isfinite(y)):
            return None, None, None
        x = np.arange(len(y))
        w = np.linspace(1, 2, len(y))
        W = w ** 2
        W_sum = W.sum()
        x_bar = (W * x).sum() / W_sum
        y_bar = (W * y).sum() / W_sum
        dx = x - x_bar
        dy = y - y_bar
        var_x = (W * dx ** 2).sum()
        if var_x == 0:
            return 0.0, 0.0, 0.0
        slope = (W * dx * dy).sum() / var_x
        intercept = y_bar - slope * x_bar
        annualized = float(np.exp(slope * 250) - 1)
        y_pred = slope * x + intercept
        ss_res = (w * (y - y_pred) ** 2).sum()
        ss_tot = (w * (y - y.mean()) ** 2).sum()
        r_sq = float(1 - ss_res / ss_tot) if ss_tot > 1e-12 else 0.0
        score = annualized * r_sq
        return score, annualized, r_sq

    # ── 过滤 ──

    def _passes_filters(self, closes, score, r_sq):
        """动量∈[min,max] / R²>阈值 / 近3日无单日跌>loss / 价>MA。返回 (passed, 详情)。"""
        details = {}
        # 动量区间
        details["mom"] = self.min_score <= score <= self.max_score
        # R²
        details["r2"] = r_sq > self.r2_threshold
        # 近3日防连跌
        details["loss"] = True
        if len(closes) >= 4:
            ratios = [closes[-1] / closes[-2], closes[-2] / closes[-3], closes[-3] / closes[-4]]
            if min(ratios) < self.loss:
                details["loss"] = False
        # MA
        details["ma"] = False
        if len(closes) >= self.ma_lookback:
            ma = closes[-self.ma_lookback:].mean()
            details["ma"] = closes[-1] > ma
        return all(details.values()), details

    # ── 走弱期判断（用代表性 ETF 代理指数）──

    def _is_weak_period(self, prices, i):
        """4个指数代理(ETF) ≥3个低于MA → 走弱期（含2日确认）。返回 (is_weak, below_count)。"""
        below = 0
        total = 0
        for idx_name, proxy_etf in self.WEAK_INDEX_PROXIES.items():
            if proxy_etf not in prices.columns:
                continue
            closes = prices[proxy_etf].iloc[: i + 1].values
            if len(closes) < self.weak_ma_lookback + 1:
                continue
            total += 1
            if closes[-1] < closes[-self.weak_ma_lookback:].mean():
                below += 1
        if total == 0:
            return False, 0
        return (below >= 3), below

    # ── 主流程 ──

    def generate(self, prices):
        """每日：打分→过滤→选择 top2 等权（走弱期用全球池），无候选→防御ETF。"""
        n_days = len(prices)
        weights = pd.DataFrame(0.0, index=prices.index, columns=self.assets)

        # warmup：动量窗口不足 → 防御ETF
        warmup = max(self.lookback + 1, self.ma_lookback + 1)
        if warmup > 0 and self.defensive in weights.columns:
            weights.loc[weights.index[:warmup], self.defensive] = 1.0

        # 走弱期状态（含确认计数）
        weak_state = False
        weak_confirm = 0
        weak_days = 0

        for i in range(warmup, n_days):
            # ── 走弱期检测（含2日确认 / 最大持续天数强制退出）──
            is_weak_now, below_cnt = self._is_weak_period(prices, i)
            if weak_state:
                weak_days += 1
                if weak_days >= self.max_weak_days:
                    weak_state = False
                    weak_days = 0
                    weak_confirm = 0
                elif not is_weak_now:
                    weak_confirm += 1
                    if weak_confirm >= self.weak_confirm_days:
                        weak_state = False
                        weak_days = 0
                        weak_confirm = 0
                else:
                    weak_confirm = 0
            else:
                if is_weak_now:
                    weak_confirm += 1
                    if weak_confirm >= self.weak_confirm_days:
                        weak_state = True
                        weak_days = 0
                        weak_confirm = 0
                else:
                    weak_confirm = 0

            # ── 候选池：走弱期→全球池；正常期→双池 ──
            pool = self.global_pool if weak_state else (self.global_pool + self.china_pool)

            # ── 打分 + 过滤 ──
            ranked = []
            for etf in pool:
                if etf not in prices.columns:
                    continue
                closes = prices[etf].iloc[: i + 1].values
                score, ann_ret, r_sq = self._momentum_score(closes)
                if score is None:
                    continue
                passed, det = self._passes_filters(closes, score, r_sq)
                if passed:
                    ranked.append({
                        "etf": etf, "score": score,
                        "ann_return": ann_ret, "r_squared": r_sq,
                    })
            ranked.sort(key=lambda m: m["score"], reverse=True)
            top10 = ranked[:10]

            # ── 选择：top-10 取 ≥ 第holdings_num名×ratio ──
            candidates = []
            if len(top10) >= self.holdings_num:
                ref_score = top10[self.holdings_num - 1]["score"]
                ratio = 1.0 if weak_state else self.score_threshold_ratio
                threshold = ref_score * ratio
                candidates = [m for m in top10 if m["score"] >= threshold]
            else:
                candidates = top10

            # ── 防御：无候选 → 货币ETF ──
            row = {}
            if candidates:
                final = candidates[:self.holdings_num]
                w_each = 1.0 / len(final)
                for m in final:
                    row[m["etf"]] = w_each
            else:
                row[self.defensive] = 1.0

            for col, w in row.items():
                if col in weights.columns:
                    weights.iloc[i, weights.columns.get_loc(col)] = w

        return weights

    def get_diagnostics(self, prices):
        """最新一期：各池ETF动量分解、走弱期状态、持仓。"""
        w = self.generate(prices)
        latest = w.iloc[-1]
        holdings = {str(c): round(float(latest.get(c, 0)), 4)
                    for c in self.assets if latest.get(c, 0) > 0.001}
        i = len(prices) - 1
        latest_date = str(prices.index[i].date())
        is_weak, below = self._is_weak_period(prices, i)

        # 打分明细（合并池，取前8）
        scores, details = {}, {}
        pool = self.global_pool + self.china_pool
        for etf in pool[:60]:
            if etf not in prices.columns:
                continue
            closes = prices[etf].iloc[: i + 1].values
            score, ann_ret, r_sq = self._momentum_score(closes)
            if score is None:
                continue
            scores[etf] = round(float(score), 6)
            details[etf] = {
                "ann_return": round(float(ann_ret), 6),
                "r_squared": round(float(r_sq), 4),
                "score": round(float(score), 6),
            }

        return {
            "strategy_id": self.__class__.__name__,
            "latest_date": latest_date,
            "parameters": {
                "动量回看(天)": self.lookback,
                "持仓数量": self.holdings_num,
                "R²阈值": self.r2_threshold,
                "MA回看(天)": self.ma_lookback,
                "防连跌阈值": self.loss,
                "走弱期确认(天)": self.weak_confirm_days,
                "大A走弱": is_weak,
            },
            "scores": scores,
            "score_details": {"wufu_momentum": details},
            "holdings": holdings,
        }
