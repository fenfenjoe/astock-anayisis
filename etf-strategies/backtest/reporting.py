"""报告输出：matplotlib 可视化 + markdown 表格。"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# matplotlib 中文支持（Windows）
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False


def plot_equity_curves(results, path):
    """权益曲线对比。results: {name: BacktestResult}"""
    plt.figure(figsize=(12, 6))
    for name, r in results.items():
        plt.plot(r.nav.index, r.nav.values, label=name, linewidth=1.5)
    plt.title("ETF 策略净值曲线 (NAV=1 起始)")
    plt.xlabel("日期"); plt.ylabel("净值"); plt.legend(); plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=120); plt.close()


def plot_drawdowns(results, path):
    """回撤曲线。"""
    plt.figure(figsize=(12, 4))
    for name, r in results.items():
        dd = r.nav / r.nav.cummax() - 1
        plt.fill_between(dd.index, dd.values, 0, label=name, alpha=0.4)
    plt.title("策略回撤")
    plt.xlabel("日期"); plt.ylabel("回撤"); plt.legend(); plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=120); plt.close()


def render_markdown_report(results, metrics, path, data_start, data_end):
    """生成 markdown 回测报告。"""
    lines = []
    lines.append("# A股 ETF 策略回测报告\n")
    lines.append(f"> 数据时点：{data_end}（盘后）")
    lines.append(f"> 回测窗口：{data_start} ~ {data_end}（公共交易日对齐）")
    lines.append(f"> 数据来源：东财 push2his 前复权日K（`fqt=1`），经 `em_get` 限流防封；本地 parquet 缓存")
    lines.append(f"> 初始资金：1,000,000 | 成本：佣金万2.5+滑点万1（单边0.035%），ETF免印花税\n")
    lines.append("## 指标对比表（实测）\n")
    lines.append("| 策略 | 年化收益 | 年化波动 | 夏普 | 最大回撤 | Calmar | 胜率 | 年化换手 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for name, m in metrics.items():
        lines.append(
            f"| {name} | {m['annual_return']:.2%} | {m['annual_vol']:.2%} | "
            f"{m['sharpe']:.2f} | {m['max_drawdown']:.2%} | {m['calmar']:.2f} | "
            f"{m['win_rate']:.2%} | {m['turnover']:.1f} |"
        )
    if any("excess_return" in m for m in metrics.values()):
        lines.append("\n| 策略 | 相对基准超额年化 |")
        lines.append("|---|---|")
        bench_name = "S1_买入持有"
        for name, m in metrics.items():
            if name == bench_name:
                lines.append(f"| {name}（基准） | — |")
            elif "excess_return" in m:
                lines.append(f"| {name} | {m['excess_return']:.2%} |")
    lines.append("\n## 净值曲线\n![equity](equity_curves.png)\n")
    lines.append("## 回撤曲线\n![drawdown](drawdowns.png)\n")
    lines.append("## 策略说明\n")
    lines.append("- **S1 买入持有**：恒满仓沪深300ETF（510300），不调仓。作基准。")
    lines.append("- **S2 双动量**：沪深300过去250日收益>0且>国债→持股；为正且<=国债→持债；为负→持货币（511880）。月末调仓。")
    lines.append("- **S3 均线趋势**：20日线上穿60日线→持股；下穿→持货币。月末调仓。")
    lines.append("- **S4 多资产动量轮动**：黄金(518880)/纳指(513100)/创业板(159915)/上证180(510180)四资产，25日log-price OLS回归，年化收益×R²打分，选最高分持有。每日调仓。")
    lines.append("- **S5 等权组合**：沪深300/中证500/创业板/国债四资产等权重，季末再平衡。")
    lines.append("- **S6 60-40**：60%沪深300+40%国债ETF（511260），季末再平衡。")
    lines.append("- **S7 目标波动率**：实现波动率(20日)↑→降仓至 target/realized（上限100%），目标年化波动15%。月末调仓。")
    lines.append("- **S8 三因子动量轮动**：斜率动量(年化×R²)+乖离动量(MA偏离趋势)+效率动量(方向/波动率)三因子加权打分，阈值过滤（挑战者需超leader 1.5倍才切换），每日评估。")
    lines.append("- **S9 行业动量轮动**：5大行业ETF（医药/证券/银行/军工）+沪深300宽基，按60日动量排名，选Top-3等权持有，月末调仓。")
    lines.append("- **S10 低波动因子**：跨资产ETF池（沪深300/国债/黄金/中证500/创业板/银行）按60日波动率排序，选最低3只等权持有，月末调仓。")
    lines.append("- **S11 布林带均值回归**：20日均线±2σ布林带，价格近下轨→加仓，近上轨→减仓，动态仓位(0~100%)，周度评估。\n")
    lines.append("## 风险提示与口径说明\n")
    lines.append("- 回测好≠实盘好：存在过拟合风险、参数依赖（动量回看250日/均线20-60/月度调仓）。")
    lines.append("- 成本为简化模型（佣金+滑点），未计入冲击成本（流动性差品种实际更高）。")
    lines.append("- 信号滞后1日已处理前视偏差（t日收盘算信号，t+1日收盘执行）；前复权已处理分红除权。")
    lines.append("- S6 简化为日日维持目标权重（未模拟季内漂移），换手率反映调仓频率。")
    lines.append("- 标的均为2012-2013年上市长寿品种，全周期无生存者偏差。")
    lines.append("- 本报告区分'实测值'（上表与图）与'判断'（结论性文字），实测值均来自真实行情。")
    Path(path).write_text("\n".join(lines), encoding="utf-8")
