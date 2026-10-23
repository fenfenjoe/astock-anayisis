"""持仓/资产 领域逻辑 — 持仓.md 解析与回写 + 实时估值计算 + 交易账本.

与 my_doc/每日复盘/持仓.md 双向同步：
- read_holdings_md()  从文件解析持仓（文件 → DB）
- write_holdings_md() 把 DB 持仓回写文件（DB → 文件，保持 prompt 期望的表格格式）
- read_trades_md()    从 每日调仓.md 解析调仓记录
- append_trade()      界面录入交易 → 追加调仓记录 + 自动重算持仓/可用金额（写两个 md 文件）
- undo_last_trade()   撤销最近一笔界面录入（快照回滚）
- compute_valuation() 用现有 K 线基建重算实时市值（复用 sync_kline + kline_get_dataframe）

数据一致性（重要）：
- 唯一权威数据源 = my_doc/每日复盘/每日调仓.md（§0 可用金额 + §1 当前持仓 + §2 调仓记录）；
  my_doc/每日复盘/持仓.md 是其同步快照。
- append_trade() 同时更新两个文件，口径与每日复盘任务 4.5 完全一致；
- T+1 校验：A股/场内权益 ETF 当日买入份额当日不可卖出（跨境 513/159、债券 511 等 T+0 除外）。
"""
import hashlib
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

HOLDINGS_MD = REPO_ROOT / "my_doc" / "每日复盘" / "持仓.md"
TRADES_MD = REPO_ROOT / "my_doc" / "每日复盘" / "每日调仓.md"

# 界面录入的撤销快照目录（写前快照，undo 回滚，不依赖历史可重放）
# 2026-10-15 解耦：随 .dsh 迁至用户目录 ~/.dsh/trade-entry/undo
SNAPSHOT_DIR = (
    Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or Path.home())
    / ".dsh" / "trade-entry" / "undo"
)

# ── 本地文件读写（2026-09-07 移除 TOS：云权威库已迁移 Supabase，持仓/调仓以本地 md 为工作副本）──
# key 参数仅为兼容历史签名保留（曾用于 TOS 对象 key），现本地实现不使用。
HOLDINGS_KEY = "holdings/持仓.md"
TRADES_KEY = "holdings/每日调仓.md"
UNDO_PREFIX = "holdings/undo/"


def _md_text(key: str, local: Path) -> str | None:
    """读本地文件；不存在返回 None。key 参数保留以兼容调用方签名。"""
    return local.read_text(encoding="utf-8") if local.exists() else None


def _md_exists(key: str, local: Path) -> bool:
    return local.exists()


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
    """从 持仓.md 读取持仓；不存在返回 None（云端优先）。"""
    text = _md_text(HOLDINGS_KEY, HOLDINGS_MD)
    return parse_holdings_md(text) if text else None


# 可用金额行（每日复盘建仓份额计算依赖，2026-08 引入）
# 持仓.md 头部格式：`可用金额: 25701 元`（每日调仓.md 为 `## 0. 可用金额` 节）
_AVAILABLE_CASH_RE = re.compile(r"可用金额\s*[:：]\s*([\d,]+)\s*元?")


def parse_available_cash_md(text: str) -> float | None:
    """从 持仓.md 提取可用金额（'可用金额: 25701 元'）→ float；缺失返回 None。"""
    m = _AVAILABLE_CASH_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def read_available_cash_md() -> float | None:
    """从 持仓.md 读取可用金额；不存在/无该行返回 None（云端优先）。"""
    text = _md_text(HOLDINGS_KEY, HOLDINGS_MD)
    return parse_available_cash_md(text) if text else None


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
    daily_text = _md_text(TRADES_KEY, TRADES_MD)
    return parse_trades_md(daily_text) if daily_text else None


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


# ═══════════════════════════════════════════════════════════════
# 交易账本（界面录入 → 每日调仓.md + 持仓.md）
# ═══════════════════════════════════════════════════════════════

# T+0 品种前缀：跨境（513/159）、债券（511）、债基（501/502）等，当日买入可当日卖出；
# 其余 A股/场内权益 ETF 按 T+1 处理（当日买入份额当日不可卖出）。
_T0_RE = re.compile(r"^(51[13]|159|501|502)")
# 股票代码前缀：60(沪主板)/68(科创板)/00(深主板)/30(创业板)；其余为 ETF（51/15/16/56/58）
_STOCK_RE = re.compile(r"^(60|68|00|30)")


def is_t0(code: str) -> bool:
    """该代码是否 T+0 品种（当日买入可当日卖出）。"""
    return bool(_T0_RE.match(str(code or "")))


def is_stock(code: str) -> bool:
    """该代码是否股票（非 ETF）：涉及印花税（卖出）与过户费。"""
    return bool(_STOCK_RE.match(str(code or "")))


def _fmt_qty(v) -> str:
    """交易数量/持仓数量：整数带千分位（1,400），小数保留原值。"""
    try:
        f = float(str(v).replace(",", "").replace("，", "").strip())
        if f == int(f):
            return f"{int(f):,}"
        return str(f)
    except (TypeError, ValueError):
        return str(v)


def _fmt_price(v) -> str:
    """价格：去尾零（1.044 / 9.05 / 33.563）。"""
    try:
        return str(float(str(v).replace(",", "").replace("，", "").strip()))
    except (TypeError, ValueError):
        return str(v)


def _norm_num(v) -> float | None:
    """数字字符串 → float；非法返回 None。"""
    try:
        f = float(str(v).replace(",", "").replace("，", "").strip())
        return f if f == f else None  # NaN → None
    except (TypeError, ValueError):
        return None


def parse_daily_ledger_md(text: str) -> dict:
    """解析 每日调仓.md → {cash, positions: [{code,name,shares,cost_price}], trades: [...]}。

    §0 可用金额 / §1 当前持仓 / §2 调仓记录，任一缺失返回空值，不抛异常。
    """
    cash = None
    positions: list[dict] = []
    trades: list[dict] = []
    section = None
    for line in str(text).splitlines():
        stripped = line.strip()
        if stripped.startswith("## 0."):
            section = "cash"
            continue
        if stripped.startswith("## 1."):
            section = "positions"
            continue
        if stripped.startswith("## 2."):
            section = "trades"
            continue
        if section == "cash":
            if cash is None:
                n = _norm_num(stripped)
                if n is not None:
                    cash = n
            continue
        if section == "positions":
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) < 4:
                continue
            name, code = parts[0], parts[1]
            if not code.isdigit() or len(code) != 6:
                continue
            shares = _norm_num(parts[2])
            cost = _norm_num(parts[3]) if parts[3] else None
            if shares is None:
                continue
            positions.append({"code": code, "name": name, "shares": shares, "cost_price": cost})
            continue
        if section == "trades":
            parts = [p.strip() for p in line.split("|")[1:-1]]
            if len(parts) < 6:
                continue
            trade_date = parts[0]
            if not re.match(r"\d{4}-\d{2}-\d{2}", trade_date):
                continue
            name, code = parts[1], parts[2]
            if not code.isdigit() or len(code) != 6:
                continue
            quantity = _norm_num(parts[3])
            price = _norm_num(parts[4])
            if quantity is None or price is None:
                continue
            trades.append({
                "trade_date": trade_date, "name": name, "code": code,
                "quantity": quantity, "price": price,
                "side": parts[5], "remark": parts[6] if len(parts) > 6 else "",
            })
    return {"cash": cash, "positions": positions, "trades": trades}


def read_daily_ledger() -> dict:
    """从云库读账本状态（持仓 + 可用金额 + 调仓记录）。

    2026-10-23 改造：云库为唯一权威（portfolio_holdings / portfolio_meta.available_cash /
    portfolio_trades）；本地 md 仅在云库无持仓时作「旧数据」只读兜底（不写回）。
    """
    positions, cash, trades = [], None, []
    try:
        from dashboard import db as _db
        positions = _db.portfolio_holdings_get_all() or []
        raw_cash = _db.meta_get("available_cash")
        try:
            cash = float(raw_cash) if raw_cash not in (None, "") else None
        except (TypeError, ValueError):
            cash = None
        trades = _db.portfolio_trades_get_all() or []
    except Exception:
        positions, cash, trades = [], None, []

    if not positions:
        # 旧本地账本兜底（只读；迁移由页面保存/录入交易时写回云库）
        daily_text = _md_text(TRADES_KEY, TRADES_MD)
        daily = parse_daily_ledger_md(daily_text) if daily_text else {}
        positions = daily.get("positions") or []
        if not trades:
            trades = daily.get("trades") or []
        if cash is None:
            cash = daily.get("cash")
        if not positions and _md_exists(HOLDINGS_KEY, HOLDINGS_MD):
            positions = read_holdings_md() or []
        if cash is None and _md_exists(HOLDINGS_KEY, HOLDINGS_MD):
            cash = read_available_cash_md()
    return {"cash": cash, "positions": positions, "trades": trades}


def validate_trade(state: dict, trade: dict) -> tuple[bool, str]:
    """校验一笔交易（不修改状态）。返回 (ok, error)。"""
    trade_date = str(trade.get("trade_date") or "").strip()
    name = str(trade.get("name") or "").strip()
    code = str(trade.get("code") or "").strip()
    side = str(trade.get("side") or "").strip()
    quantity = _norm_num(trade.get("quantity"))
    price = _norm_num(trade.get("price"))
    fee = _norm_num(trade.get("fee")) or 0.0

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", trade_date):
        return False, f"日期格式应为 YYYY-MM-DD，收到 {trade_date!r}"
    if not (code.isdigit() and len(code) == 6):
        return False, f"股票代码应为 6 位数字，收到 {code!r}"
    if not name:
        return False, "股票名称不能为空"
    if side not in ("买入", "卖出"):
        return False, f"操作方向必须为 买入/卖出，收到 {side!r}"
    if quantity is None or quantity <= 0 or int(quantity) != quantity:
        return False, f"交易数量必须为正整数，收到 {trade.get('quantity')!r}"
    if price is None or price <= 0:
        return False, f"交易价格必须为正数，收到 {trade.get('price')!r}"
    if fee < 0:
        return False, f"手续费不能为负数，收到 {fee!r}"
    amount = quantity * price
    if fee >= amount:
        return False, f"手续费 {fee:.2f} 元 ≥ 成交金额 {amount:.2f} 元，请检查"

    quantity = int(quantity)
    pos = next((p for p in state["positions"] if p["code"] == code), None)
    if side == "卖出":
        if pos is None:
            return False, f"卖出失败：当前无 {name}({code}) 持仓"
        if pos["name"] != name:
            return False, f"卖出失败：代码 {code} 的名称应为 {pos['name']!r}，与 {name!r} 不一致"
        if quantity > pos["shares"]:
            return False, (f"卖出失败：{name}({code}) 仅持有 {_fmt_qty(pos['shares'])} 份，"
                           f"无法卖出 {_fmt_qty(quantity)} 份")
        if not is_t0(code):
            # T+1：当日买入的份额当日不可卖出
            today_buys = sum(int(t["quantity"]) for t in state["trades"]
                             if t["code"] == code and t["trade_date"] == trade_date
                             and t["side"] == "买入")
            sellable = int(pos["shares"]) - today_buys
            if quantity > sellable:
                return False, (f"卖出失败：{name}({code}) 当日买入 {_fmt_qty(today_buys)} 份，"
                               f"按 T+1 规则当日不可卖出；今日可卖 {_fmt_qty(max(0, sellable))} 份")
    else:
        net_out = amount + fee  # 买入净支出 = 成交金额 + 手续费
        cash = state.get("cash")
        if cash is not None and net_out > cash + 1e-6:
            return False, (f"买入失败：净支出 {net_out:.2f} 元（成交 {amount:.2f} + 手续费 {fee:.2f}）"
                           f"超出可用金额 {cash:.2f} 元")
    return True, ""


def apply_trade(state: dict, trade: dict) -> dict:
    """应用一笔交易（纯计算，返回新状态，不写文件）。

    现金口径（净额）：买入扣 成交金额+手续费；卖出回 成交金额-手续费。
    """
    code = str(trade["code"]).strip()
    quantity = int(trade["quantity"])
    price = float(trade["price"])
    side = trade["side"]
    name = str(trade["name"] or "").strip()
    fee = float(trade.get("fee") or 0.0)
    remark = str(trade.get("remark") or "").strip()
    if fee > 0:
        fee_note = f"手续费{fee:.2f}元"
        remark = f"{remark}，{fee_note}" if remark else fee_note

    positions = [dict(p) for p in state.get("positions") or []]
    cash = state.get("cash")
    pos = next((p for p in positions if p["code"] == code), None)

    if side == "买入":
        if pos is None:
            positions.append({"code": code, "name": name, "shares": quantity, "cost_price": price})
        else:
            old_shares = float(pos["shares"])
            old_cost = float(pos["cost_price"] or 0)
            new_shares = old_shares + quantity
            new_cost = round((old_shares * old_cost + quantity * price) / new_shares, 4)
            pos["shares"] = new_shares
            pos["cost_price"] = new_cost
        if cash is not None:
            cash = round(cash - (quantity * price + fee), 2)
    else:
        remaining = float(pos["shares"]) - quantity
        if remaining <= 0:
            positions = [p for p in positions if p["code"] != code]
        else:
            pos["shares"] = remaining
        if cash is not None:
            cash = round(cash + (quantity * price - fee), 2)

    trades = [dict(t) for t in state.get("trades") or []]
    trades.append({
        "trade_date": str(trade["trade_date"]).strip(),
        "name": name, "code": code,
        "quantity": quantity, "price": price, "side": side,
        "remark": remark,
    })
    return {"cash": cash, "positions": positions, "trades": trades}


def _write_ledger_db(state: dict) -> None:
    """把账本状态写入云库（持仓表 + 调仓记录表 + 可用金额）。不写任何本地文件。"""
    from dashboard import db as _db
    _db.portfolio_holdings_replace(state.get("positions") or [])
    _db.portfolio_trades_replace_all(state.get("trades") or [])
    cash = state.get("cash")
    if cash is not None:
        _db.meta_set("available_cash", str(cash))


def write_ledger_state(state: dict) -> None:
    """把状态写入云库（含撤销快照 JSON）。2026-10-23：不再回写任何本地 md。"""
    # 撤销快照：写前保存旧状态（云库当前内容），仅用于 undo
    try:
        old = read_daily_ledger()
        snap_id = f"{int(date.today().strftime('%Y%m%d%H%M%S'))}-{os.urandom(3).hex()}"
        snap_payload = json.dumps({
            "cash": old.get("cash"),
            "positions": old.get("positions") or [],
            "trades": old.get("trades") or [],
            "note": state.get("trades")[-1] if state.get("trades") else None,
        }, ensure_ascii=False)
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        (SNAPSHOT_DIR / f"{snap_id}.json").write_text(snap_payload, encoding="utf-8")
        for oldf in sorted(SNAPSHOT_DIR.glob("*.json"))[:-10]:
            oldf.unlink(missing_ok=True)
    except Exception:
        pass  # 快照失败不阻断主流程（undo 不可用而已）
    try:
        _write_ledger_db(state)
    except Exception as e:  # 云库写入失败 → 视为 OSError（api 层转 500）
        raise OSError(f"写云库账本失败: {e}") from e


def append_trade(trade: dict) -> dict:
    """录入一笔交易：读权威状态 → 校验 → 重算 → 写两个 md 文件。返回新状态。"""
    state = read_daily_ledger()
    ok, err = validate_trade(state, trade)
    if not ok:
        raise ValueError(err)
    new_state = apply_trade(state, trade)
    write_ledger_state(new_state)
    return new_state


def undo_last_trade() -> dict:
    """撤销最近一笔界面录入（把云库状态回滚到快照）。无快照时抛 ValueError。"""
    snaps = sorted(SNAPSHOT_DIR.glob("*.json"))
    if not snaps:
        raise ValueError("没有可撤销的录入")
    latest = snaps[-1]
    snapshot = json.loads(latest.read_text(encoding="utf-8"))
    state = {
        "cash": snapshot.get("cash"),
        "positions": snapshot.get("positions") or [],
        "trades": snapshot.get("trades") or [],
    }
    try:
        _write_ledger_db(state)
    except Exception as e:
        raise OSError(f"回滚云库账本失败: {e}") from e
    latest.unlink(missing_ok=True)
    return state
