"""列出项目中所有已维护的ETF策略。用法: python list_strategies.py

输出终端美观表格（rich 库），也支持 --plain 纯文本模式。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import inspect
from backtest.strategies.base import Strategy
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
from backtest.strategies.sentiment_momentum import SentimentMomentum
from backtest.strategies.multi_factor import MultiFactor
from backtest.strategies.adaptive_momentum import AdaptiveMomentum
from backtest.strategies.rsrs_momentum import TrendFilterMomentum
from backtest.strategies.canary_defense import CanaryDefense, CanaryDefenseDaily
from backtest.strategies.rsrs_reversal_momentum import RsrsReversalMomentum
from backtest.strategies.low_correlation_rotation import LowCorrelationRotation

# 策略注册表 — 新增策略在这里加一行即可
STRATEGIES = [
    BuyHold,
    DualMomentum,
    MATrend,
    MomentumRotation,
    EqualWeight,
    Portfolio6040,
    TargetVol,
    ThreeFactorMomentum,
    IndustryMomentum,
    LowVol,
    Bollinger,
    SentimentMomentum,
    MultiFactor,
    AdaptiveMomentum,
    TrendFilterMomentum,
    CanaryDefense,
    CanaryDefenseDaily,
    RsrsReversalMomentum,
    LowCorrelationRotation,
]

# 策略类别 → 颜色映射（rich 支持的颜色名）
CATEGORY_COLORS = {
    "被动": "cyan",
    "动量": "bright_green",
    "趋势": "green",
    "因子": "bright_yellow",
    "资产配置": "blue",
    "风险控制": "magenta",
    "多因子": "bright_magenta",
    "行业轮动": "yellow",
    "均值回归": "bright_cyan",
}

# 策略 → 类别映射（从策略KB中提取）
STRAT_CATEGORY = {
    "S1_买入持有":         "被动投资 / 基准",
    "S2_双动量":            "动量 / 避险",
    "S3_均线趋势":          "趋势跟踪",
    "S4_多资产动量轮动":     "动量轮动",
    "S5_等权组合":          "因子 / 等权",
    "S6_60-40股债平衡":     "资产配置",
    "S7_目标波动率":        "风险控制",
    "S8_三因子动量轮动":     "多因子动量",
    "S9_行业动量轮动":      "行业轮动",
    "S10_低波动因子":       "多因子 / 低波动",
    "S11_布林带均值回归":   "均值回归",
    "S12_量价情绪多因子":   "多因子 / 情绪",
    "S13_多因子综合打分":   "多因子",
    "S14_动态波动率调整动量": "动量 / 自适应",
    "S15_趋势过滤动量增强":   "动量 / 趋势过滤",
    "S16_金丝雀防御动量":         "动量 / 风险预警",
    "S17_金丝雀防御动量_日频":     "动量 / 风险预警",
    "S18_RSRS增强反转动量":        "动量 / 反转",
    "S19_低相关ETF轮动":           "动量 / 低相关",
}

# 已回测的标杆指标（来自最近一期全量回测）
STRAT_BENCHMARKS = {
    "S1_买入持有":         {"年化": "8.19%",  "夏普": "0.30", "回撤": "-52.97%"},
    "S2_双动量":            {"年化": "5.60%",  "夏普": "0.39", "回撤": "-24.58%"},
    "S3_均线趋势":          {"年化": "6.99%",  "夏普": "0.35", "回撤": "-51.17%"},
    "S4_多资产动量轮动":     {"年化": "33.62%", "夏普": "1.21", "回撤": "-28.51%"},
    "S5_等权组合":          {"年化": "7.70%",  "夏普": "0.44", "回撤": "-35.91%"},
    "S6_60-40股债平衡":     {"年化": "5.71%",  "夏普": "0.45", "回撤": "-22.00%"},
    "S7_目标波动率":        {"年化": "9.55%",  "夏普": "0.57", "回撤": "-40.90%"},
    "S8_三因子动量轮动":     {"年化": "34.82%", "夏普": "1.27", "回撤": "-28.51%"},
    "S9_行业动量轮动":      {"年化": "2.95%",  "夏普": "0.14", "回撤": "-46.03%"},
    "S10_低波动因子":       {"年化": "11.79%", "夏普": "1.39", "回撤": "-9.68%"},
    "S11_布林带均值回归":   {"年化": "10.78%", "夏普": "0.47", "回撤": "-43.62%"},
    "S12_量价情绪多因子":   {"年化": "—",     "夏普": "—",   "回撤": "—"},
    "S13_多因子综合打分":   {"年化": "—",     "夏普": "—",   "回撤": "—"},
    "S14_动态波动率调整动量": {"年化": "—",     "夏普": "—",   "回撤": "—"},
    "S15_趋势过滤动量增强":   {"年化": "—",     "夏普": "—",   "回撤": "—"},
    "S16_金丝雀防御动量":         {"年化": "—",     "夏普": "—",   "回撤": "—"},
    "S17_金丝雀防御动量_日频":     {"年化": "—",     "夏普": "—",   "回撤": "—"},
    "S18_RSRS增强反转动量":        {"年化": "34.75%", "夏普": "1.16", "回撤": "-25.50%"},
    "S19_低相关ETF轮动":           {"年化": "21.84%", "夏普": "0.87", "回撤": "-32.01%"},
}


def _default_assets(cls):
    """尝试用默认参数实例化，返回 assets 列表。"""
    try:
        sig = inspect.signature(cls.__init__)
        kwargs = {}
        for name, param in list(sig.parameters.items())[1:]:  # skip self
            if param.default is not inspect.Parameter.empty:
                kwargs[name] = param.default
        inst = cls(**kwargs)
        return inst.assets, kwargs
    except Exception:
        return [], {}


def _parse_doc(cls):
    """提取 docstring 第一行作为简短描述。"""
    doc = (cls.__doc__ or "").strip()
    if not doc:
        return ""
    first_line = doc.split("\n")[0].strip()
    return first_line


def _rich_table(rows):
    """使用 rich 输出美观的终端表格。"""
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text
    from rich import box

    # 显式设置宽度防止列被折叠（非交互终端可能检测为窄屏）
    console = Console(width=160)

    table = Table(
        title="🏦 AStock ETF 量化策略列表",
        title_style="bold bright_cyan",
        box=box.ROUNDED,
        border_style="bright_black",
        highlight=True,
        show_header=True,
        header_style="bold white on grey23",
    )

    table.add_column("编号", width=6, style="bold cyan", no_wrap=True)
    table.add_column("策略名称", width=18, style="bold white")
    table.add_column("类别", width=12, style="bright_black")
    table.add_column("资产池", width=36, style="bright_white")
    table.add_column("年化", width=7, justify="right")
    table.add_column("夏普", width=6, justify="right")
    table.add_column("回撤", width=8, justify="right")
    table.add_column("说明", width=38, style="italic")

    for r in rows:
        sid = r["id"]
        bm = STRAT_BENCHMARKS.get(sid, {})
        cat = STRAT_CATEGORY.get(sid, "—")

        # 年化收益率着色
        ann = bm.get("年化", "—")
        if ann != "—":
            try:
                v = float(ann.replace("%", ""))
                ann_style = "bright_green" if v >= 20 else ("green" if v >= 10 else "white")
            except ValueError:
                ann_style = "white"
        else:
            ann_style = "bright_black"

        # 夏普着色
        sharpe = bm.get("夏普", "—")
        if sharpe != "—":
            try:
                v = float(sharpe)
                sharpe_style = "bright_green" if v >= 1.0 else ("yellow" if v >= 0.5 else "red")
            except ValueError:
                sharpe_style = "white"
        else:
            sharpe_style = "bright_black"

        # 回撤着色
        dd = bm.get("回撤", "—")
        if dd != "—":
            try:
                v = float(dd.replace("%", ""))
                dd_style = "bright_green" if abs(v) <= 15 else ("yellow" if abs(v) <= 30 else "red")
            except ValueError:
                dd_style = "white"
        else:
            dd_style = "bright_black"

        # 类别颜色标签
        cat_color = "bright_black"
        for keyword, color in CATEGORY_COLORS.items():
            if keyword in cat:
                cat_color = color
                break

        table.add_row(
            Text(sid, style="bold cyan"),
            Text(r["class"], style="bold white"),
            Text(cat, style=cat_color),
            r["assets"],
            Text(ann, style=ann_style),
            Text(sharpe, style=sharpe_style),
            Text(dd, style=dd_style),
            r["description"],
        )

    console.print()
    console.print(table)
    console.print(f"  📊 共 {len(rows)} 个策略  |  "
                  f"[bright_green]●[/] 年化≥20% 夏普≥1.0  "
                  f"[yellow]●[/] 中等  "
                  f"[red]●[/] 偏低  "
                  f"[bright_black]— 待回测[/]")
    console.print()


def _plain_table(rows):
    """纯文本表格（无 rich 依赖）。"""
    header = f"{'编号':6s} {'策略名称':18s} {'类别':14s} {'年化':>7s} {'夏普':>6s} {'回撤':>8s}  {'说明'}"
    sep = "─" * len(header)
    print(sep)
    print(header)
    print(sep)
    for r in rows:
        sid = r["id"]
        bm = STRAT_BENCHMARKS.get(sid, {})
        cat = STRAT_CATEGORY.get(sid, "—")
        ann = bm.get("年化", "—")
        sharpe = bm.get("夏普", "—")
        dd = bm.get("回撤", "—")
        print(f"{sid:6s} {r['class']:18s} {cat:14s} {ann:>7s} {sharpe:>6s} {dd:>8s}  {r['description']}")
    print(sep)
    print(f"共 {len(rows)} 个策略")


def list_strategies(markdown=True):
    """列出所有策略。

    Args:
        markdown: True=rich终端美观表格, False=纯文本(--plain)
    """
    rows = []
    for cls in STRATEGIES:
        assets, params = _default_assets(cls)
        desc = _parse_doc(cls)
        rows.append({
            "id": cls.name,
            "class": cls.__name__,
            "description": desc,
            "assets": ", ".join(assets) if assets else "—",
            "params": ", ".join(f"{k}={v}" for k, v in params.items()) if params else "—",
        })

    if markdown:
        _rich_table(rows)
    else:
        _plain_table(rows)


if __name__ == "__main__":
    list_strategies()
