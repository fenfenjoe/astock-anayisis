"""持仓/资产 领域逻辑 — 持仓.md 解析与回写 + 实时估值计算.

与 my_doc/每日复盘/harness/config/持仓.md 双向同步：
- read_holdings_md()  从文件解析持仓（文件 → DB）
- write_holdings_md() 把 DB 持仓回写文件（DB → 文件，保持 prompt 期望的表格格式）
- read_trades_md()    从 每日调仓.md 解析调仓记录
- compute_valuation() 用现有 K 线基建重算实时市值（复用 sync_kline + kline_get_dataframe）
"""
import re
import json
import os
from pathlib import Path
from datetime import date, timedelta

# 仓库根：etf-strategies/dashboard/portfolio.py → 向上三级（本地）；
# Docker 里用 DASHBOARD_REPO_ROOT 环境变量覆盖为挂载点（与 scheduler.py 一致）。
_env_repo_root = os.environ.get("DASHBOARD_REPO_ROOT")
REPO_ROOT = (Path(_env_repo_root).resolve() if _env_repo_root
             else Path(__file__).resolve().parent.parent.parent)

HOLDINGS_MD = REPO_ROOT / "my_doc" / "每日复盘" / "harness" / "config" / "持仓.md"
TRADES_MD = REPO_ROOT / "my_doc" / "每日复盘" / "每日调仓.md"


# ═══════════════════════════════════════════════════════════════
# 持仓.md 解析 / 回写
# ═══════════════════════════════════════════════════════════════

def _norm_num(s: str) -> str:
    """去千分位逗号/全角逗号，便于数字比较与转换。"""
    return (s or "").replace(",", "").replace("，", "").strip()


def parse_holdings_md(text: str) -> list[dict]:
    """解析持仓.md 表格 → [{code, name, shares, cost_price}]。

    表格格式（与 prompt 1.3b/1.3c 的解析规则一致）：
    | 股票名称 | 代码 | 持仓数量（份） | 成本价（元） |
    | 航空航天ETF | 159227 | 2,000 | 2.222 |
    """
    holdings = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")[1:-1]]
        if len(parts) < 4:
            continue
        name, code = parts[0], parts[1]
        # 代码必须是 6 位数字（表头/分隔行会被过滤）
        if not code.isdigit() or len(code) != 6:
            continue
        try:
            shares = float(_norm_num(parts[2]))
            cost = float(_norm_num(parts[3])) if parts[3] else None
        except ValueError:
            continue
        holdings.append({"code": code, "name": name, "shares": shares, "cost_price": cost})
    return holdings


def read_holdings_md() -> list[dict] | None:
    """从 持仓.md 读取持仓；文件不存在返回 None。"""
    if not HOLDINGS_MD.exists():
        return None
    return parse_holdings_md(HOLDINGS_MD.read_text(encoding="utf-8"))


def holdings_md_mtime() -> float | None:
    if HOLDINGS_MD.exists():
        return HOLDINGS_MD.stat().st_mtime
    return None


def _fmt_shares(v) -> str:
    """数量格式化：整数带千分位（2,000 / 15,800），小数保留原值。"""
    try:
        f = float(_norm_num(str(v)))
        if f == int(f):
            return f"{int(f):,}"
        return str(f)
    except (TypeError, ValueError):
        return _norm_num(str(v))


def _fmt_price(v) -> str:
    """价格格式化：去掉多余尾零（2.222 / 0.648 / 1.845）。"""
    s = _norm_num(str(v))
    if not s:
        return ""
    try:
        return str(float(s))  # Python 最短 repr
    except ValueError:
        return s


def write_holdings_md(rows: list[dict]) -> bool:
    """把持仓写回 持仓.md（保持 prompt 期望的表格格式）。返回是否成功。"""
    HOLDINGS_MD.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 当前持仓",
        "",
        "> 本文件由每日复盘自动同步自 每日调仓.md，反映最新持仓状态。",
        "> 最后更新: 自动同步（Dashboard 持仓/资产 页面维护）",
        "",
        "| 股票名称 | 代码 | 持仓数量（份） | 成本价（元） |",
        "| -------- | ------ | -------------- | ------------ |",
    ]
    for r in rows:
        code = str(r.get("code", "")).strip()
        if not code:
            continue
        name = r.get("name") or code
        shares = _fmt_shares(r.get("shares", ""))
        cost = _fmt_price(r.get("cost_price")) if r.get("cost_price") is not None else ""
        lines.append(f"| {name} | {code} | {shares} | {cost} |")
    HOLDINGS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True


# ═══════════════════════════════════════════════════════════════
# 每日调仓.md 解析
# ═══════════════════════════════════════════════════════════════

def parse_trades_md(text: str) -> list[dict]:
    """解析每日调仓.md 的"调仓记录"表 → [{trade_date, name, code, quantity, price, side, remark}]。

    表格格式：
    | 日期 | 股票名称 | 股票代码 | 交易数量 | 交易价格 | 买入/卖出 | 备注 |
    | 2026-07-08 | 180ETF | 510180 | 4,100 | 4.049 | 买入 |
    """
    trades = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")[1:-1]]
        if len(parts) < 6:
            continue
        trade_date = parts[0]
        if not re.match(r"\d{4}-\d{2}-\d{2}", trade_date):
            continue
        name, code = parts[1], parts[2]
        if not code.isdigit() or len(code) != 6:
            continue
        try:
            quantity = float(_norm_num(parts[3]))
            price = float(_norm_num(parts[4]))
        except ValueError:
            continue
        side = parts[5]
        remark = parts[6] if len(parts) > 6 else ""
        trades.append({
            "trade_date": trade_date, "name": name, "code": code,
            "quantity": quantity, "price": price, "side": side, "remark": remark,
        })
    return trades


def read_trades_md() -> list[dict] | None:
    if not TRADES_MD.exists():
        return None
    return parse_trades_md(TRADES_MD.read_text(encoding="utf-8"))


# ═══════════════════════════════════════════════════════════════
# 实时估值计算（复用现有 K 线基建）
# ═══════════════════════════════════════════════════════════════

def _latest_close(code: str, lookback_days: int = 400, refresh: bool = True):
    """返回某 code 的最新收盘价（优先 SQLite，其次 parquet/API 兜底）。

    复用 app.py:_load_prices_from_db 的模式：
    sync_kline()（增量，非最新则静默）→ kline_get_dataframe（SQLite）→ get_kline(refresh=False) 兜底。
    refresh=False 时跳过 sync_kline（只读缓存），用于快速响应路径。
    """
    try:
        from dashboard.db import kline_get_dataframe
        from dashboard.sync import sync_kline
        from backtest.data import get_kline
    except ImportError:
        return None

    end_d = date.today().strftime("%Y-%m-%d")
    start_d = (date.today() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    if refresh:
        try:
            sync_kline(code)
        except Exception:
            pass

    try:
        df = kline_get_dataframe(code, start_d, end_d)
        if df is not None and len(df) >= 1:
            return float(df["close"].iloc[-1])
    except Exception:
        pass

    try:
        kdf = get_kline(code, start=start_d, end=end_d, refresh=False)
        if kdf is not None and len(kdf) >= 1:
            return float(kdf["close"].iloc[-1])
    except Exception:
        pass
    return None


def compute_valuation(holdings: list[dict], available_cash: float = 0.0,
                      refresh_prices: bool = True) -> dict:
    """逐持仓算实时估值，返回 {rows:[...], totals:{...}}。

    row: {code, name, shares, cost_price, close, mkt_value, cost_value, pnl, pnl_pct}
    totals: {mkt_value, cost_value, pnl, pnl_pct, total_assets}
    total_assets = Σ市值 + available_cash
    refresh_prices=False → 只读缓存价（快速响应，不触发网络同步）。
    """
    rows = []
    for h in holdings:
        code = h.get("code")
        shares = float(h.get("shares") or 0)
        cost = float(h.get("cost_price") or 0)
        close = _latest_close(code, refresh=refresh_prices) if code else None
        mkt_value = round(shares * close, 2) if close is not None else None
        cost_value = round(shares * cost, 2) if cost else 0.0
        pnl = round(mkt_value - cost_value, 2) if mkt_value is not None and cost_value else None
        pnl_pct = round((pnl / cost_value) * 100, 2) if pnl is not None and cost_value else None
        rows.append({
            "code": code, "name": h.get("name") or code,
            "shares": shares, "cost_price": cost,
            "close": close, "mkt_value": mkt_value,
            "cost_value": cost_value, "pnl": pnl, "pnl_pct": pnl_pct,
        })

    def _sum(field):
        vals = [r[field] for r in rows if r.get(field) is not None]
        return round(sum(vals), 2) if vals else None

    mkt_total = _sum("mkt_value")
    cost_total = _sum("cost_value")
    pnl_total = _sum("pnl")
    return {
        "rows": rows,
        "totals": {
            "mkt_value": mkt_total,
            "cost_value": cost_total,
            "pnl": pnl_total,
            "pnl_pct": round((pnl_total / cost_total) * 100, 2)
            if pnl_total is not None and cost_total else None,
            "total_assets": round((mkt_total or 0) + available_cash, 2)
            if mkt_total is not None else None,
            "available_cash": available_cash,
        },
        "computed_at": date.today().isoformat(),
    }
