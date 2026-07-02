"""列出项目中所有已维护的ETF策略。用法: python list_strategies.py"""
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
]


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
    # 去掉开头的 S{N} 前缀如果有的话
    return first_line


def list_strategies(markdown=True):
    """列出所有策略。markdown=True 输出表格格式。"""
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
        print("| 编号 | 策略名称 | 资产池 | 默认参数 | 说明 |")
        print("|------|---------|--------|---------|------|")
        for r in rows:
            print(f"| {r['id']} | {r['class']} | {r['assets']} | {r['params']} | {r['description']} |")
    else:
        for r in rows:
            print(f"{r['id']:30s} {r['class']:25s}  assets={r['assets']}")
            if r["description"]:
                print(f"  {' ':*^30s}  {r['description']}")
            print()

    print(f"\n共 {len(rows)} 个策略")


if __name__ == "__main__":
    list_strategies()
