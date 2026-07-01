"""回测入口：拉数据 → 跑全部策略 → 生成报告。"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path
import pandas as pd
from backtest.data import get_kline
from backtest.engine import backtest
from backtest.metrics import compute_metrics
from backtest.strategies.buy_hold import BuyHold
from backtest.strategies.dual_momentum import DualMomentum
from backtest.strategies.ma_trend import MATrend
from backtest.strategies.momentum_rotation import MomentumRotation
from backtest.strategies.equal_weight import EqualWeight
from backtest.strategies.portfolio_6040 import Portfolio6040
from backtest.strategies.target_vol import TargetVol
from backtest.strategies.three_factor_momentum import ThreeFactorMomentum
from backtest.strategies.industry_momentum import IndustryMomentum
from backtest.strategies.low_vol import LowVol
from backtest.strategies.bollinger import Bollinger
from backtest.reporting import plot_equity_curves, plot_drawdowns, render_markdown_report

START, END = "2012-05-28", "2026-07-01"
OUT_DIR = Path(__file__).resolve().parent


def load_prices_for_strategy(assets, start, end, refresh=False):
    """为指定资产列表加载对齐后的收盘价 DataFrame。"""
    series = {}
    for code in assets:
        df = get_kline(code, start=start, end=end, refresh=refresh)
        series[code] = df["close"]
    return pd.DataFrame(series).dropna()


def main():
    print("[1/4] 加载数据...")
    # 策略定义 — 每项 (名称, 实例)
    strategies = [
        ("S1_买入持有",            BuyHold("510300")),
        ("S2_双动量",              DualMomentum(lookback=250)),
        ("S3_均线趋势",             MATrend(short=20, long=60)),
        ("S4_多资产动量轮动",        MomentumRotation(lookback=25, top_n=1)),
        ("S5_等权组合",             EqualWeight()),
        ("S6_60-40股债平衡",        Portfolio6040()),
        ("S7_目标波动率",           TargetVol(target_vol=0.15, window=20)),
        ("S8_三因子动量轮动",        ThreeFactorMomentum(lookback=25, top_n=1, threshold=1.5)),
        ("S9_行业动量轮动",         IndustryMomentum(lookback=60, top_n=3)),
        ("S10_低波动因子",          LowVol(window=60, top_n=3)),
        ("S11_布林带均值回归",       Bollinger(etf="510300", cash="511880", ma_period=20, sigma=2.0)),
    ]

    # 逐策略加载各自资产（资产上市时间不同，各自对齐避免截断）
    print("[2/4] 生成策略信号...")
    results, metrics = {}, {}
    bench = None  # S1 作为全局基准

    for name, strat in strategies:
        p = load_prices_for_strategy(strat.assets, START, END, refresh=False)
        data_start = str(p.index[0].date())
        data_end = str(p.index[-1].date())
        w = strat.generate(p)
        res = backtest(p, w)
        results[name] = res

        # 为该策略构建同窗口基准（同日期范围的买入持有）
        strat_bench = None
        if name != "S1_买入持有":
            # 用该策略窗口内的第一个资产做基准，或直接用 S1 同日截断
            bh_prices = p.iloc[:, :1].copy()  # 取该策略第一个资产
            bh_w = pd.DataFrame(1.0, index=bh_prices.index, columns=bh_prices.columns)
            strat_bench = backtest(bh_prices, bh_w)

        if name == "S1_买入持有":
            bench = res

        m = compute_metrics(res, benchmark=strat_bench)
        metrics[name] = m
        print(f"  {name}: 窗口{data_start}~{data_end} | "
              f"年化{m['annual_return']:.2%} 夏普{m['sharpe']:.2f} "
              f"回撤{m['max_drawdown']:.2%} 换手{m['turnover']:.1f}")

    print("[3/4] 计算相对基准超额...")
    # 补充全局基准超额（S1 用自身作参考线）
    if bench is not None:
        for name, m in metrics.items():
            if "excess_return" not in m:
                b_years = len(bench.returns) / 252
                b_ann = bench.nav.iloc[-1] ** (1 / b_years) - 1 if b_years > 0 else 0.0
                m["excess_return"] = m["annual_return"] - b_ann

    print("[4/4] 生成报告...")
    plot_equity_curves(results, OUT_DIR / "equity_curves.png")
    plot_drawdowns(results, OUT_DIR / "drawdowns.png")
    render_markdown_report(results, metrics, OUT_DIR / "03_ETF策略回测报告.md",
                            data_start="2012-05-28", data_end="2026-07-01")
    print("[done] 报告: 03_ETF策略回测报告.md")


if __name__ == "__main__":
    main()
