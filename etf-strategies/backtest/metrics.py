"""回测指标计算。"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd


def compute_metrics(result, benchmark=None, freq=252):
    """计算收益/风险指标。benchmark 可选 BacktestResult 用于超额。"""
    nav = result.nav
    rets = result.returns
    n = len(rets)
    years = n / freq
    # 年化收益
    ann_ret = nav.iloc[-1] ** (1 / years) - 1 if years > 0 else 0.0
    # 年化波动
    ann_vol = rets.std() * np.sqrt(freq) if n > 1 else 0.0
    # 夏普（无风险利率=0）
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
    # 最大回撤
    cummax = nav.cummax()
    drawdown = nav / cummax - 1
    max_dd = drawdown.min()
    # Calmar
    calmar = ann_ret / abs(max_dd) if max_dd < 0 else 0.0
    # 胜率（日收益>0 占比，忽略0）
    nonzero = (rets != 0).sum()
    win_rate = (rets > 0).sum() / nonzero if nonzero > 0 else 0.0
    m = {
        "annual_return": ann_ret,
        "annual_vol": ann_vol,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "calmar": calmar,
        "win_rate": win_rate,
        "turnover": result.turnover,
    }
    if benchmark is not None:
        b_years = len(benchmark.returns) / freq
        b_ann = benchmark.nav.iloc[-1] ** (1 / b_years) - 1 if b_years > 0 else 0.0
        m["excess_return"] = ann_ret - b_ann
    return m
