import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from backtest.engine import BacktestResult
from backtest.reporting import render_markdown_report, plot_equity_curves, plot_drawdowns


def _result():
    """合成 BacktestResult：10 个交易日，NAV 从 1.0 起步"""
    idx = pd.date_range("2024-01-01", periods=10, freq="B")
    nav = pd.Series([1.0, 1.01, 1.02, 1.015, 1.03, 1.04, 1.035, 1.05, 1.06, 1.07],
                    index=idx)
    rets = nav.pct_change().fillna(0.0)
    weights = pd.DataFrame({"A": 1.0}, index=idx)
    return BacktestResult(nav=nav, returns=rets, weights=weights, turnover=1.2)


def _metrics():
    return {
        "S1_买入持有": {
            "annual_return": 0.08, "annual_vol": 0.15, "sharpe": 0.53,
            "max_drawdown": -0.05, "calmar": 1.6, "win_rate": 0.55,
            "turnover": 0.1,
        }
    }


def test_render_markdown_report_contains_metric_table(tmp_path):
    """render_markdown_report 输出含指标表头与策略行（数据结构正确）"""
    r = _result()
    path = tmp_path / "report.md"
    render_markdown_report({"S1_买入持有": r}, _metrics(), str(path),
                           "2024-01-01", "2024-01-10")
    text = path.read_text(encoding="utf-8")
    assert "# A股 ETF 策略回测报告" in text
    assert "| 策略 | 年化收益 | 年化波动 | 夏普 | 最大回撤 | Calmar | 胜率 | 年化换手 |" in text
    assert "| S1_买入持有 |" in text
    assert "## 策略说明" in text


def test_render_markdown_report_benchmark_excess(tmp_path):
    """metrics 含 excess_return 时输出超额收益表，基准行显示 —"""
    r = _result()
    metrics = _metrics()
    metrics["S2_双动量"] = dict(metrics["S1_买入持有"], excess_return=0.02)
    path = tmp_path / "report.md"
    render_markdown_report({"S1_买入持有": r, "S2_双动量": r}, metrics, str(path),
                           "2024-01-01", "2024-01-10")
    text = path.read_text(encoding="utf-8")
    assert "相对基准超额年化" in text
    assert "| S1_买入持有（基准） | — |" in text
    assert "| S2_双动量 | 2.00% |" in text


def test_plot_equity_curves_saves_png(tmp_path):
    """plot_equity_curves 生成非空 PNG 文件"""
    r = _result()
    path = tmp_path / "equity_curves.png"
    plot_equity_curves({"S1_买入持有": r}, str(path))
    assert path.exists()
    assert path.stat().st_size > 0


def test_plot_drawdowns_saves_png(tmp_path):
    """plot_drawdowns 生成非空 PNG 文件"""
    r = _result()
    path = tmp_path / "drawdowns.png"
    plot_drawdowns({"S1_买入持有": r}, str(path))
    assert path.exists()
    assert path.stat().st_size > 0
