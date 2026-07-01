"""一年回测HTML报告生成器。

用法:
  from html_report import generate_report
  generate_report("S4", strat_instance)
  → 生成 report/S4_多资产动量轮动-20260701143022.html
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import io, base64
from pathlib import Path
from datetime import date, timedelta, datetime
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.collections import LineCollection

from backtest.data import get_kline
from backtest.engine import backtest
from backtest.metrics import compute_metrics
from daily_signal import get_etf_name
from strategy_kb import get_kb

plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

REPORT_DIR = Path(__file__).resolve().parent / "report"


def load_one_year_prices(assets):
    """拉取近一年+warmup的收盘价数据。返回 (完整prices, 用于回测)。"""
    end = date.today()
    start = end - timedelta(days=400)  # 多取一些做 warmup
    series = {}
    for code in assets:
        df = get_kline(code, start=start.strftime("%Y-%m-%d"),
                       end=end.strftime("%Y-%m-%d"), refresh=False)
        series[code] = df["close"]
    return pd.DataFrame(series).dropna()


def _fig_to_b64(fig):
    """matplotlib figure → base64 PNG。"""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    buf.seek(0)
    b64 = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return b64


def plot_price_chart(prices_1y, weights_1y, strat_name, assets):
    """画收盘价折线图：持仓期间=红色，非持仓=灰色。标题显示代码+名称。"""
    n_assets = len(assets)
    cols = min(2, n_assets)
    rows = (n_assets + 1) // 2
    fig, axes = plt.subplots(rows, cols, figsize=(14, 4 * rows))
    if n_assets == 1:
        axes = [axes]
    else:
        axes = axes.flatten() if hasattr(axes, "flatten") else [axes]

    dates = mdates.date2num(prices_1y.index.to_pydatetime())

    for idx, etf in enumerate(assets):
        if etf not in prices_1y.columns:
            continue
        ax = axes[idx]
        y = prices_1y[etf].values
        w_series = weights_1y[etf].values if etf in weights_1y.columns else np.zeros(len(y))
        held = (w_series > 0.001)

        # 线段着色
        points = np.array([dates, y]).T.reshape(-1, 1, 2)
        segments = np.concatenate([points[:-1], points[1:]], axis=1)
        colors = ['#e74c3c' if held[i] else '#bdc3c7' for i in range(len(held) - 1)]

        lc = LineCollection(segments, colors=colors, linewidth=1.5)
        ax.add_collection(lc)
        ax.set_xlim(dates.min() - 1, dates.max() + 1)
        y_range = y.max() - y.min()
        margin = y_range * 0.05 if y_range > 0 else y.max() * 0.05
        ax.set_ylim(y.min() - margin, y.max() + margin)

        months = mdates.MonthLocator(interval=2)
        ax.xaxis.set_major_locator(months)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

        name = get_etf_name(etf)
        ax.set_title(f"{etf} {name}", fontsize=11)
        ax.set_ylabel("收盘价")
        ax.grid(True, alpha=0.3)

    for idx in range(n_assets, len(axes)):
        axes[idx].set_visible(False)

    fig.suptitle(f"{strat_name} — 近一年收盘价走势（红色=持仓期间）",
                 fontsize=14, fontweight='bold')
    fig.text(0.5, 0.01, f"红线=持仓期 | 灰线=非持仓期 | {len(prices_1y)}个交易日",
             ha='center', fontsize=9, style='italic')
    plt.tight_layout()
    plt.subplots_adjust(top=0.92, hspace=0.35, wspace=0.25)
    return _fig_to_b64(fig)


def generate_report(strat_id, strat_instance):
    """生成策略的一年回测HTML报告。"""
    sid = strat_id.upper()
    kb = get_kb(sid)
    strat = strat_instance
    strat_name = kb["name"] if kb else sid

    # ── 1) 拉数据 & 回测 ──
    prices_full = load_one_year_prices(strat.assets)
    if len(prices_full) < 20:
        raise RuntimeError(f"数据不足（仅{len(prices_full)}个交易日），无法生成报告")

    weights_full = strat.generate(prices_full)

    # 截取最近一年（约252个交易日）用于展示
    one_year_ago = prices_full.index[-1] - pd.Timedelta(days=365)
    mask = prices_full.index >= one_year_ago
    if mask.sum() < 20:
        # 如果一年数据不够，取最近200个交易日
        n_take = min(200, len(prices_full))
        prices_1y = prices_full.iloc[-n_take:]
        weights_1y = weights_full.iloc[-n_take:]
    else:
        prices_1y = prices_full.loc[mask]
        weights_1y = weights_full.loc[mask]

    res = backtest(prices_1y, weights_1y)
    m = compute_metrics(res)
    window_start = prices_1y.index[0].date()
    window_end = prices_1y.index[-1].date()
    n_days = len(prices_1y)

    # ── 2) 真实一年收益率（非年化，而是区间实际收益） ──
    total_return_1y = res.nav.iloc[-1] / res.nav.iloc[0] - 1 if len(res.nav) > 1 else 0.0

    # ── 3) 调仓历史 ──
    w_changes = weights_1y.diff().abs().sum(axis=1)
    trade_dates = w_changes[w_changes > 0.01].index
    trade_rows = []

    # 首日建仓：检查第一天是否有仓位（从空仓→持仓）
    first_day = weights_1y.index[0]
    w_first = weights_1y.loc[first_day]
    if w_first.sum() > 0.01:
        open_actions = []
        for etf in strat.assets:
            if w_first[etf] > 0.005:
                open_actions.append(f"建仓 {etf} {get_etf_name(etf)} {w_first[etf]:.1%}")
        if open_actions:
            holding_str = ", ".join(
                f"{e} {get_etf_name(e)} {w_first[e]:.0%}"
                for e in strat.assets if w_first[e] > 0.01
            ) or "空仓"
            trade_rows.append({
                "date": first_day.date(),
                "actions": " | ".join(open_actions),
                "holding": holding_str,
            })

    # 后续调仓
    for t in trade_dates:
        if t == first_day:
            continue  # 跳过首日，已作为建仓处理
        w_today = weights_1y.loc[t]
        prev_idx = weights_1y.index.get_loc(t) - 1
        w_prev = weights_1y.iloc[prev_idx] if prev_idx >= 0 else pd.Series(0, index=w_today.index)
        actions = []
        for etf in strat.assets:
            diff = w_today.get(etf, 0) - w_prev.get(etf, 0)
            if diff > 0.005:
                actions.append(f"买入 {etf} {get_etf_name(etf)} {diff:.1%}")
            elif diff < -0.005:
                actions.append(f"卖出 {etf} {get_etf_name(etf)} {abs(diff):.1%}")
        if actions:
            holding_str = ", ".join(
                f"{e} {get_etf_name(e)} {w_today[e]:.0%}"
                for e in strat.assets if w_today[e] > 0.01
            ) or "空仓"
            trade_rows.append({
                "date": t.date(),
                "actions": " | ".join(actions),
                "holding": holding_str,
            })

    # ── 4) 图表 ──
    chart_b64 = plot_price_chart(prices_1y, weights_1y, strat_name, strat.assets)

    # ── 5) 策略简介（优化版） ──
    intro_html = ""
    if kb:
        strengths = kb.get("strengths", "")
        weaknesses = kb.get("weaknesses", "")
        factors = kb.get("factors", "")
        stock_sel = kb.get("stock_selection", "").replace("\n", "<br>")
        timing = kb.get("market_timing", "").replace("\n", "<br>")
        intro_html = f"""
          <div class="kb-grid">
            <div class="kb-box">
              <div class="kb-box-title">🎯 择股逻辑</div>
              <div class="kb-box-content">{stock_sel}</div>
            </div>
            <div class="kb-box">
              <div class="kb-box-title">⏱️ 择时方法</div>
              <div class="kb-box-content">{timing}</div>
            </div>
            <div class="kb-box">
              <div class="kb-box-title">📐 核心因子</div>
              <div class="kb-box-content">{factors}</div>
            </div>
          </div>
          <div class="kb-grid" style="margin-top:16px">
            <div class="kb-box pros">
              <div class="kb-box-title">✅ 优势</div>
              <div class="kb-box-content">{strengths}</div>
            </div>
            <div class="kb-box cons">
              <div class="kb-box-title">⚠️ 风险与局限</div>
              <div class="kb-box-content">{weaknesses}</div>
            </div>
          </div>"""

    # ── 6) 调仓历史表格 ──
    trade_table = ""
    for r in trade_rows[:50]:
        trade_table += f"<tr><td>{r['date']}</td><td>{r['actions']}</td><td>{r['holding']}</td></tr>"

    # ── 7) 组装 HTML ──
    now = datetime.now().strftime("%Y%m%d%H%M%S")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{sid}_{strat_name}-{now}.html"
    filepath = REPORT_DIR / filename

    ret_class = "positive" if total_return_1y > 0 else "negative"

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{sid} {strat_name} — 一年回测报告</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif; background: #f5f6fa; color: #2c3e50; }}
.header {{ background: linear-gradient(135deg, #2c3e50, #3498db); color: white; padding: 36px 40px; text-align: center; }}
.header h1 {{ font-size: 26px; margin-bottom: 6px; }}
.header .meta {{ opacity: 0.85; font-size: 13px; }}
.container {{ max-width: 1100px; margin: 0 auto; padding: 28px 20px; }}
.card {{ background: white; border-radius: 12px; padding: 28px; margin-bottom: 22px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); }}
.card h2 {{ font-size: 19px; margin-bottom: 14px; padding-bottom: 8px; border-bottom: 2px solid #3498db; }}
.metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 14px; }}
.metric {{ background: #f8f9fa; border-radius: 8px; padding: 16px 14px; text-align: center; }}
.metric .value {{ font-size: 26px; font-weight: bold; color: #2c3e50; }}
.metric .value.positive {{ color: #27ae60; }}
.metric .value.negative {{ color: #e74c3c; }}
.metric .label {{ font-size: 11px; color: #7f8c8d; margin-top: 2px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{ background: #3498db; color: white; padding: 10px 12px; text-align: left; font-weight: 600; }}
td {{ padding: 8px 12px; border-bottom: 1px solid #ecf0f1; }}
tr:hover {{ background: #f0f7ff; }}
.chart {{ text-align: center; }}
.chart img {{ max-width: 100%; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
.kb-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; }}
.kb-box {{ background: #f8f9fa; border-radius: 8px; padding: 16px; border-left: 4px solid #3498db; }}
.kb-box.pros {{ border-left-color: #27ae60; }}
.kb-box.cons {{ border-left-color: #e74c3c; }}
.kb-box-title {{ font-size: 15px; font-weight: bold; margin-bottom: 6px; color: #2c3e50; }}
.kb-box-content {{ font-size: 13px; line-height: 1.7; color: #555; }}
.summary-tag {{ display: inline-block; background: #3498db; color: white; border-radius: 4px; padding: 2px 8px; font-size: 12px; margin-right: 4px; }}
.footer {{ text-align: center; color: #95a5a6; font-size: 11px; padding: 18px; }}
</style>
</head>
<body>
<div class="header">
  <h1>{sid} {strat_name}</h1>
  <div class="meta">一年回测报告 · 数据窗口: {window_start} ~ {window_end} · 生成时间: {now}</div>
</div>
<div class="container">

  <!-- 1. 回测指标 -->
  <div class="card">
    <h2>📊 回测指标（近一年）</h2>
    <div class="metrics">
      <div class="metric"><div class="value {ret_class}">{total_return_1y:+.2%}</div><div class="label">一年实际收益率</div></div>
      <div class="metric"><div class="value {'positive' if m['annual_return']>0 else 'negative'}">{m['annual_return']:.2%}</div><div class="label">年化收益率</div></div>
      <div class="metric"><div class="value">{m['annual_vol']:.2%}</div><div class="label">年化波动率</div></div>
      <div class="metric"><div class="value">{m['sharpe']:.2f}</div><div class="label">夏普比率</div></div>
      <div class="metric"><div class="value negative">{m['max_drawdown']:.2%}</div><div class="label">最大回撤</div></div>
      <div class="metric"><div class="value">{m['win_rate']:.1%}</div><div class="label">日胜率</div></div>
      <div class="metric"><div class="value">{m['turnover']:.1f}</div><div class="label">年化换手率</div></div>
      <div class="metric"><div class="value">{n_days}</div><div class="label">交易日数</div></div>
    </div>
  </div>

  <!-- 2. 收盘价走势图 -->
  <div class="card">
    <h2>📉 收盘价走势图</h2>
    <div class="chart"><img src="data:image/png;base64,{chart_b64}" alt="价格走势图"></div>
  </div>

  <!-- 3. 调仓历史 -->
  <div class="card">
    <h2>📋 调仓历史（权重变动 &gt;1%）</h2>
    <table>
      <tr><th>日期</th><th>操作</th><th>调仓后持仓</th></tr>
      {trade_table if trade_table else '<tr><td colspan="3" style="text-align:center;color:#95a5a6">回测期内无调仓操作</td></tr>'}
    </table>
    <p style="margin-top:12px;color:#7f8c8d;font-size:12px">仅展示权重变动&gt;1%的调仓，最多50条。交易成本：佣金万2.5+滑点万1（单边约0.035%）。</p>
  </div>

  <!-- 4. 策略简介 -->
  <div class="card">
    <h2>📖 策略详解</h2>
    <p style="font-size:14px;line-height:1.8;color:#555;margin-bottom:14px">{kb.get('intro', '') if kb else ''}</p>
    {intro_html}
  </div>

</div>
<div class="footer">AStock ETF 策略回测系统 · 自动生成 · 回测结果不代表未来表现</div>
</body>
</html>"""

    filepath.write_text(html, encoding="utf-8")
    return filepath
