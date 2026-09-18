"""每日复盘集成 API — 持仓/资产/报告/信号/调度 (api_daily).

路由前缀 /api，全部走 JWT 认证（依赖 get_current_user）。
- Phase 0: 持仓/资产 配置 + 实时市值刷新 + 东财实验配置
- Phase 1/2: 每日信号 / 报告 / 调度器 路由（随 scheduler.py 一起加入）

⚠️ 路由冲突陷阱：不得用 /api/signals/daily —— 现有 GET /api/signals/{sid} 会先匹配。
   每日信号一律走独立前缀 /api/daily-signals。
"""

import json
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from dashboard.auth import get_current_user
from dashboard import db
from dashboard import portfolio
from dashboard import eastmoney
from dashboard import scheduler
from dashboard import notify

router = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])


# ───────────────────────────────────────────────────────────────────
# 请求/响应模型
# ───────────────────────────────────────────────────────────────────


class HoldingsRow(BaseModel):
    code: str
    name: str = ""
    shares: float = 0
    cost_price: float | None = None


class HoldingsPayload(BaseModel):
    rows: list[HoldingsRow]
    total_assets: float | None = None
    available_cash: float | None = None


class EastmoneyConfigPayload(BaseModel):
    account: str
    password: str
    note: str = ""


class TradePayload(BaseModel):
    """一笔交易录入（字段与 每日调仓.md §2 调仓记录 表一致）。

    side: 买入 | 卖出；quantity 为正整数；remark 可带「做T」等标记。
    fee: 手续费（元，可选，默认 0）——买入时现金多扣、卖出时现金少收，
    手续费会自动并入备注（"手续费X元"），便于在 每日调仓.md 中留痕。
    """

    trade_date: str = ""
    name: str = ""
    code: str = ""
    quantity: float = 0
    price: float = 0
    side: str = ""
    remark: str = ""
    fee: float = 0


class SignalTriggerPayload(BaseModel):
    """盘中记录信号触发价/触发时间（写云库 signal_tracking.trigger_price/trigger_time）。

    trigger_time 格式 'HH:MM'（可选，缺省由服务端补当前时间）。
    """

    signal_id: str
    trigger_price: float
    trigger_time: str = ""


class SignalEntryPayload(BaseModel):
    """复盘关联"录入交易"记录买入价/买入时间（写云库 entry_price/entry_time）。"""

    signal_id: str
    entry_price: float
    entry_time: str = ""


# 并发保护：价格刷新 / 东财刷新 / 交易录入 各自串行，避免并发写坏估值快照与账本文件
_price_refresh_lock = threading.Lock()
_em_refresh_lock = threading.Lock()
_trade_lock = threading.Lock()


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _meta_num(key: str, default=None):
    """portfolio_meta 里以 TEXT 存的数值 → float。"""
    v = db.meta_get(key)
    if v is None or v == "":
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _build_portfolio_response() -> dict:
    """组装 GET /api/portfolio 的完整响应（持仓 + 估值 + meta + 东财状态）。

    2026-09-08 性能优化：原先逐个 meta_get（云模式 N 次 HTTPS 往返，实测单次
    ~0.08-0.8s，页面 8s+）→ 改 meta_get_all() 一次批量取回全部 portfolio_meta，
    再加 holdings/trades 两次读，整个接口仅 3 次云往返（复用连接后 ~0.3s）。
    """
    meta_all = db.meta_get_all()

    def _m(key, default=None):
        v = meta_all.get(key)
        return v if v is not None else default

    def _m_num(key, default=None):
        v = meta_all.get(key)
        if v is None or v == "":
            return default
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    meta = {
        "total_assets": _m_num("total_assets"),
        "available_cash": _m_num("available_cash"),
        "account_source": _m("account_source", "manual"),
        "last_refresh_at": _m("last_refresh_at"),
    }
    snapshot_raw = _m("valuation_snapshot")
    try:
        snapshot = json.loads(snapshot_raw) if snapshot_raw else None
    except (json.JSONDecodeError, TypeError):
        snapshot = None

    has_creds = _m("eastmoney_has_creds") == "1"
    trades = db.portfolio_trades_get_all()
    return {
        "holdings": db.portfolio_holdings_get_all(),
        "trades": trades[:30],
        "trades_count": len(trades),
        "meta": meta,
        "valuation": snapshot,
        "eastmoney": {
            "has_creds": has_creds,
            "account_suffix": _m("eastmoney_account_suffix"),
            "note": _m("eastmoney_note"),
            "last_error": _m("last_eastmoney_error"),
            "experimental": True,
        },
        "server_time": _now_str(),
    }


def _recompute_valuation_and_store(
    refresh_prices: bool = False, available_cash: float | None = None
):
    """重算估值并持久化 valuation_snapshot（不触发同步时用缓存价）。"""
    holdings = db.portfolio_holdings_get_all()
    if available_cash is None:
        available_cash = _meta_num("available_cash", 0.0)
    val = portfolio.compute_valuation(
        holdings, available_cash=available_cash, refresh_prices=refresh_prices
    )
    db.meta_set("valuation_snapshot", json.dumps(val, ensure_ascii=False))
    db.meta_set("last_refresh_at", _now_str())
    return val


# ═════════════════════════════════════════════════════════════════
# 持仓/资产
# ═════════════════════════════════════════════════════════════════


@router.get("/portfolio")
def get_portfolio():
    """持仓 + 估值快照 + meta（total_assets/cash/account_source/last_refresh_at）。"""
    return _build_portfolio_response()


@router.put("/portfolio/holdings")
def put_portfolio_holdings(payload: HoldingsPayload):
    """替换持仓：写 DB + 回写 持仓.md + 用缓存收盘价重算估值。

    不触发网络同步（refresh_prices=False）以保证保存快速响应；
    用户点「刷新市值」才做真实行情同步。
    """
    rows = []
    for r in payload.rows:
        code = str(r.code or "").strip()
        if not (code.isdigit() and len(code) == 6):
            raise HTTPException(400, f"无效代码: {code!r}（需 6 位数字）")
        rows.append(
            {
                "code": code,
                "name": r.name or code,
                "shares": float(r.shares or 0),
                "cost_price": r.cost_price,
            }
        )
    if not rows:
        raise HTTPException(400, "持仓不能为空")

    db.portfolio_holdings_replace(rows)

    # 回写 持仓.md（保持 prompt 期望的表格格式；可用金额行一并写回/保留）
    try:
        portfolio.write_holdings_md(rows, available_cash=payload.available_cash)
        mtime = portfolio.holdings_md_mtime()
        if mtime is not None:
            db.meta_set("holdings_md_mtime", str(mtime))
    except OSError as e:
        raise HTTPException(500, f"回写 持仓.md 失败: {e}")

    if payload.total_assets is not None:
        db.meta_set("total_assets", str(payload.total_assets))
    if payload.available_cash is not None:
        db.meta_set("available_cash", str(payload.available_cash))

    _recompute_valuation_and_store(refresh_prices=False)
    return _build_portfolio_response()


def _sync_ledger_to_db(state: dict) -> None:
    """把账本状态（来自 每日调仓.md）同步进 DB：持仓表 + 调仓记录表 + 可用金额 + 估值快照。

    append_trade/undo 都会重写 每日调仓.md 与 持仓.md，这里是让 Dashboard 的
    DB 镜像与文件保持一致（portfolio_holdings / portfolio_trades / portfolio_meta）。
    """
    db.portfolio_holdings_replace(state.get("positions") or [])
    db.portfolio_trades_replace_all(state.get("trades") or [])
    cash = state.get("cash")
    if cash is not None:
        db.meta_set("available_cash", str(cash))
    val = _recompute_valuation_and_store(refresh_prices=False, available_cash=cash)
    totals = (val or {}).get("totals") or {}
    if totals.get("total_assets") is not None:
        db.meta_set("total_assets", str(totals["total_assets"]))


@router.post("/portfolio/trades")
def post_portfolio_trade(payload: TradePayload):
    """录入一笔交易（买入/卖出/做T）→ 追加 每日调仓.md §2 + 自动重算持仓/可用金额。

    写 每日调仓.md（§0 金额 + §1 持仓 + §2 记录）与 持仓.md，并同步 DB。
    校验失败（卖出超持仓 / T+1 / 可用金额不足 / 代码-名称不一致）返回 400。
    """
    trade = {
        "trade_date": (payload.trade_date or "").strip(),
        "name": (payload.name or "").strip(),
        "code": (payload.code or "").strip(),
        "quantity": payload.quantity,
        "price": payload.price,
        "side": (payload.side or "").strip(),
        "remark": (payload.remark or "").strip(),
        "fee": float(payload.fee or 0),
    }
    with _trade_lock:
        try:
            state = portfolio.append_trade(trade)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except OSError as e:
            raise HTTPException(500, f"写账本文件失败: {e}")
        _sync_ledger_to_db(state)
    last = state["trades"][-1]
    fee_txt = f"，手续费 {trade['fee']:.2f} 元" if trade["fee"] > 0 else ""
    return {
        **_build_portfolio_response(),
        "message": (
            f"已录入 {last['trade_date']} {last['side']} {last['name']}({last['code']}) "
            f"{portfolio._fmt_qty(last['quantity'])} 份 @ {last['price']}{fee_txt}；"
            f"可用现金已更新为 {portfolio._fmt_qty(state['cash'] or 0)} 元"
        ),
    }


@router.post("/portfolio/trades/undo")
def post_portfolio_trade_undo():
    """撤销最近一笔界面录入（回滚文件快照 + 重新同步 DB）。"""
    with _trade_lock:
        try:
            state = portfolio.undo_last_trade()
        except ValueError as e:
            raise HTTPException(400, str(e))
        except OSError as e:
            raise HTTPException(500, f"回滚账本文件失败: {e}")
        _sync_ledger_to_db(state)
    return {
        **_build_portfolio_response(),
        "message": "已撤销最近一笔录入，持仓与可用金额已回滚",
    }


@router.post("/portfolio/refresh")
def post_portfolio_refresh():
    """后台线程：逐 code sync_kline + 重算实时市值，写估值快照。返回 started，前端轮询 GET。"""
    holdings = db.portfolio_holdings_get_all()
    if not holdings:
        raise HTTPException(400, "持仓为空，先保存持仓")

    def _worker():
        if not _price_refresh_lock.acquire(blocking=False):
            return  # 已有刷新在跑
        try:
            # 逐 code 增量同步（sync_kline 非最新才拉，无网络操作时近 no-op）
            for h in holdings:
                try:
                    portfolio._latest_close(h["code"], refresh=True)
                except Exception:
                    pass
            _recompute_valuation_and_store(refresh_prices=False)
        finally:
            _price_refresh_lock.release()

    threading.Thread(target=_worker, daemon=True).start()
    return {
        "started": True,
        "message": "市值刷新已在后台启动",
        "server_time": _now_str(),
    }


# ═════════════════════════════════════════════════════════════════
# 东财实验功能（可选）
# ═════════════════════════════════════════════════════════════════


@router.get("/portfolio/eastmoney/config")
def get_eastmoney_config():
    """读取东财配置状态 — 永不返回密码，仅 has_creds / 尾号 / note / 错误。"""
    has_creds = db.meta_get("eastmoney_has_creds") == "1"
    return {
        "has_creds": has_creds,
        "account_suffix": db.meta_get("eastmoney_account_suffix"),
        "note": db.meta_get("eastmoney_note"),
        "last_error": db.meta_get("last_eastmoney_error"),
        "experimental": True,
    }


@router.put("/portfolio/eastmoney/config")
def put_eastmoney_config(payload: EastmoneyConfigPayload):
    """保存东财凭据 — Fernet 加密后存 portfolio_meta['eastmoney_config']。

    依赖 cryptography；缺包时拒绝保存而非存明文。
    """
    account = (payload.account or "").strip()
    if not account:
        raise HTTPException(400, "请输入东财账号")
    if not payload.password:
        raise HTTPException(400, "请输入东财密码")

    try:
        token = eastmoney.encrypt_creds(account, payload.password, payload.note)
    except eastmoney.EastmoneyUnavailable as e:
        raise HTTPException(400, str(e))

    db.meta_set("eastmoney_config", token)
    db.meta_set("eastmoney_has_creds", "1")
    db.meta_set(
        "eastmoney_account_suffix", eastmoney.account_suffix({"account": account})
    )
    db.meta_set("eastmoney_note", payload.note)
    db.meta_set("last_eastmoney_error", "")  # 清掉旧错误
    return {"ok": True, "account_suffix": db.meta_get("eastmoney_account_suffix")}


@router.post("/portfolio/eastmoney/refresh")
def post_eastmoney_refresh():
    """后台尝试东财拉取持仓/资产。

    成功 → 替换持仓 + 资产 + account_source='eastmoney' + 回写 持仓.md；
    失败 → 保留手动数据 + 写 last_eastmoney_error（优雅降级，绝不覆盖）。
    """
    if db.meta_get("eastmoney_has_creds") != "1":
        raise HTTPException(400, "尚未配置东财账号")
    try:
        creds = eastmoney.decrypt_creds(db.meta_get("eastmoney_config", ""))
    except eastmoney.EastmoneyUnavailable as e:
        raise HTTPException(400, str(e))

    def _worker():
        if not _em_refresh_lock.acquire(blocking=False):
            return
        try:
            try:
                data = eastmoney.fetch_positions(creds)
            except eastmoney.EastmoneyUnavailable as e:
                db.meta_set(
                    "last_eastmoney_error",
                    f"{datetime.now():%Y-%m-%d %H:%M:%S} 东财拉取失败: {e}",
                )
                return  # 手动数据保持不动

            rows = data.get("holdings") or []
            if not rows:
                db.meta_set(
                    "last_eastmoney_error",
                    f"{datetime.now():%Y-%m-%d %H:%M:%S} 东财返回持仓为空（可能需人工过验证码）",
                )
                return
            db.portfolio_holdings_replace(rows)
            if data.get("total_assets") is not None:
                db.meta_set("total_assets", str(data["total_assets"]))
            if data.get("available_cash") is not None:
                db.meta_set("available_cash", str(data["available_cash"]))
            db.meta_set("account_source", "eastmoney")
            db.meta_set("last_eastmoney_error", "")
            try:
                portfolio.write_holdings_md(rows)
            except OSError:
                pass  # 文件回写失败不阻断数据入库
            _recompute_valuation_and_store(refresh_prices=False)
        finally:
            _em_refresh_lock.release()

    threading.Thread(target=_worker, daemon=True).start()
    return {
        "started": True,
        "message": "东财刷新已在后台启动",
        "server_time": _now_str(),
    }


# ═════════════════════════════════════════════════════════════════
# 每日信号 / 报告（只读展示）
# ═════════════════════════════════════════════════════════════════

# 信号总表列名（与 每日信号.md v3.0 模板列一致 — 14 列，早盘模板 §5.1）
# 2026-08 信号体系升级：移除 升级条件/预期收益日/操作来源/生成依据，新增 预期触发率/目标止损
# 2026-09 v3.0：目标/止损 拆为 交易价/目标价/止损价（买入三列，卖出仅交易价）
_SIGNAL_COLUMNS = [
    "优先级",
    "标的",
    "触发条件",
    "操作类型",
    "状态",
    "方向",
    "紧急度",
    "预期触发率",
    "交易价",
    "目标价",
    "止损价",
    "有效时段",
    "仓位",
    "信号ID",
]


def _parse_signals(markdown: str) -> list[dict]:
    """从 每日信号.md 解析「信号总表」为结构化行。

    规则：定位 '## 信号总表' 段，取其中 markdown 表格；表头驱动映射
    （列名 → 索引），按 _SIGNAL_COLUMNS 逐列取值，列名缺失时按位置兜底
    （兼容旧 14 列格式）。解析失败返回 []（调用方 fallback 到全文渲染，
    绝不硬失败）。
    """
    lines = markdown.splitlines()
    idx = None
    for i, line in enumerate(lines):
        if line.strip().startswith("## 信号总表"):
            idx = i
            break
    if idx is None:
        return []

    rows = []
    header: dict[str, int] | None = None
    for line in lines[idx + 1 :]:
        if line.strip().startswith("## "):
            break  # 下一个段落结束
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        joined = "".join(cells)
        if not joined:
            continue
        if set(joined) <= set("-|: "):
            continue  # 分隔行 |---|---|
        if header is None:
            # 第一个非分隔行 = 表头 → 建立 列名→索引 映射
            header = {name: i for i, name in enumerate(cells) if name}
            continue
        # 表头驱动取值；表头缺列名 → 按 _SIGNAL_COLUMNS 位置兜底（旧格式兼容）
        record = {}
        for col in _SIGNAL_COLUMNS:
            j = header.get(col)
            if j is not None:
                record[col] = cells[j] if j < len(cells) else ""
            else:
                k = _SIGNAL_COLUMNS.index(col)
                record[col] = cells[k] if k < len(cells) else ""
        # 信号ID 缺失则该行跳过（信号行必须含 ID）
        if not record.get("信号ID"):
            continue
        rows.append(record)
    return rows


@router.get("/daily-signals")
def get_daily_signals(date: str | None = None):
    """今日信号：?date=YYYYMMDD（默认今天）。返回 {date, signals}，signals = 8 字段视图。

    2026-09-14 任务4 全云库化：仅返回今日云库信号（8 字段视图），
    去掉 markdown/parsed 兜底与"原文视图"数据（原文不再维护）。
    无信号/非交易日 → signals=[]（空表）。
    """
    today_ymd = datetime.now().strftime("%Y%m%d")
    target_date = date or today_ymd
    cloud_rows = _cloud_signal_rows(target_date)
    return {
        "date": target_date,
        "signals": [_signal_view(r) for r in cloud_rows],
        "source": "cloud",
    }


@router.get("/signal-quality")
def get_signal_quality(period: str = "day", date: str | None = None):
    """信号质量评估：?period=day|week|all（默认 day）。

    复用 harness 的 `lib/signal_quality.py` 8 项指标 + P0 执行率，消费云库 `signal_tracking` 表
    （云库不可用时降级读本地 signal_tracking.json 缓存）。方案 v1.10 §9.3。
    返回 {period, metrics: {...}, p0_execution, signals_included, source}。
    """
    # 1. 取信号集（云库优先 → 本地缓存兜底）
    sigs = _load_tracking_signals()
    if date:
        iso = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
        sigs = [s for s in sigs if s.get("trigger_date") == iso or s.get("signal_date") == iso]

    if period == "day":
        today_iso = datetime.now().strftime("%Y-%m-%d")
        sigs = [s for s in sigs if (s.get("trigger_date") or s.get("signal_date")) == today_iso]
    elif period == "week":
        # 最近 7 个自然日
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        sigs = [s for s in sigs if (s.get("trigger_date") or s.get("signal_date")) >= cutoff]
    # period=all 保留全部

    if not sigs:
        return {
            "period": period, "metrics": None, "p0_execution": None,
            "signals_included": 0, "source": _quality_source(),
        }

    settled = [s for s in sigs if s.get("status") == "settled"]
    metrics = _quality_metrics(sigs, settled)
    p0 = _p0_execution(sigs)
    return {
        "period": period,
        "metrics": metrics,
        "p0_execution": p0,
        "signals_included": len(sigs),
        "settled_included": len(settled),
        "source": _quality_source(),
    }


# ───────────────────────────────────────────────────────────────────
# 每日信号页重做（CHAT.md 任务4 · 2026-09-14）：枚举 / 历史查询 / 触发记录
# ───────────────────────────────────────────────────────────────────


def _signal_enums_dict() -> dict:
    """信号字段枚举（与 docs/signal-enums.md / lib 一致）。

    注意：status 为追踪库/云库的英文内部值（open/triggered/executed/partial_executed/settled/expired），
    与 markdown 显示层的中文状态不同——前端下拉/过滤必须用英文值才能命中云库行。
    """
    return {
        "trade_type": ["buy", "sell"],
        "status": ["open", "triggered", "executed", "partial_executed", "settled", "expired"],
        "direction": ["buy", "sell"],
        "priority": ["P0", "P1", "P2"],
        "urgency": ["high", "low"],
        "source": ["morning_analysis", "intraday_check", "evening_review"],
        "outcome": ["hit", "stopped", "miss"],
    }


@router.get("/signal-enums")
def get_signal_enums():
    """信号字段枚举（供前端下拉框填充）。返回 {trade_type, status, ...}。"""
    return _signal_enums_dict()


def _iso(ymd: str) -> str:
    """'YYYYMMDD' → 'YYYY-MM-DD'（容错：已是 ISO 则原样返回）。"""
    if not ymd:
        return ""
    digits = ymd.replace("-", "").strip()
    if len(digits) != 8 or not digits.isdigit():
        return ymd
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def _signal_query_filters(*, date=None, ticker=None, trade_type=None,
                          status=None, signal_id=None) -> list:
    """按查询条件组装 cloud_db.select 的 filters 列表（只加非空条件）。"""
    filters = []
    if date:
        filters.append(("signal_date", "eq", _iso(date)))
    if ticker:
        filters.append(("ticker", "like", f"*{ticker.strip()}*"))
    if trade_type:
        filters.append(("trade_type", "eq", trade_type.strip()))
    if status:
        filters.append(("status", "eq", status.strip()))
    if signal_id:
        filters.append(("signal_id", "like", f"*{signal_id.strip()}*"))
    return filters


@router.get("/signal-history")
def get_signal_history(
    date: str | None = Query(None),
    ticker: str | None = Query(None),
    trade_type: str | None = Query(None),
    status: str | None = Query(None),
    signal_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """历史信号分页查询：按日期倒序，支持 日期/标的/操作类型/状态/信号ID 过滤。

    全云库化（任务4）：一律读云库 signal_tracking 表；云库不可用返回空列表。
    返回 {items, total, page, page_size}；items 为 8 字段视图（含日期）。
    """
    try:
        import cloud_db
        if not cloud_db.enabled():
            return {"items": [], "total": 0, "page": page, "page_size": page_size}
        filters = _signal_query_filters(
            date=date, ticker=ticker, trade_type=trade_type,
            status=status, signal_id=signal_id,
        )
        # total（不含分页）
        total = len(cloud_db.select("signal_tracking", columns="signal_id", filters=filters))
        offset = (page - 1) * page_size
        rows = cloud_db.select(
            "signal_tracking",
            filters=filters,
            order="signal_date.desc,signal_id.desc",
            limit=page_size,
            offset=offset,
        )
        items = [_signal_view(r) for r in rows]
        return {"items": items, "total": total, "page": page, "page_size": page_size}
    except Exception:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}


@router.get("/signal-triggers")
def get_signal_triggers(
    date: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """信号触发记录：trigger_price/trigger_time 非空的行，按日期倒序。

    返回 {items}；items 列：日期|信号ID|标的|触发条件|触发价|触发时间|买入价|买入时间。
    """
    try:
        import cloud_db
        if not cloud_db.enabled():
            return {"items": []}
        filters = [("trigger_price", "is", "not.null")]
        if date:
            filters.append(("signal_date", "eq", _iso(date)))
        rows = cloud_db.select(
            "signal_tracking",
            filters=filters,
            order="signal_date.desc,signal_id.desc",
            limit=limit,
        )
        return {"items": [_signal_view(r, triggers=True) for r in rows]}
    except Exception:
        return {"items": []}


def _signal_view(r: dict, triggers: bool = False) -> dict:
    """云表行 → 前端展示视图。

    triggers=False：今日/历史信号 8 字段视图（v3.0：交易价/目标价/止损价 三列）；
    triggers=True：触发记录视图（追加触发价/触发时间/买入价/买入时间）。
    """
    target = r.get("target_price") if r.get("target_price") is not None \
        else (f"{r['target_pct']}%" if r.get("target_pct") is not None else "")
    stop = r.get("stop_price") if r.get("stop_price") is not None \
        else (f"{r['stop_pct']}%" if r.get("stop_pct") is not None else "")
    view = {
        "signal_date": r.get("signal_date") or r.get("trigger_date"),
        "priority": r.get("priority"),
        "ticker": r.get("ticker"),
        "name": r.get("name"),
        "trade_type": r.get("trade_type"),
        "position": r.get("position"),
        "valid_window": r.get("valid_window"),
        "status": r.get("status"),
        "trade_price": r.get("trade_price"),
        "target_price": target or None,
        "stop_price": stop or None,
        "signal_id": r.get("signal_id"),
    }
    if triggers:
        view.update({
            "trigger_condition": r.get("trigger_condition"),
            "trigger_price": r.get("trigger_price"),
            "trigger_time": r.get("trigger_time"),
            "entry_price": r.get("entry_price"),
            "entry_time": r.get("entry_time"),
        })
    return view


def _update_signal_field(signal_id: str, fields: dict) -> dict:
    """按 signal_id 更新云库字段（含枚举/数值校验）。成功返回 {ok: True}；失败抛 404/400。

    校验委托 lib/signal_tracking_cloud.cloud_update_fields（校验不合法抛 ValueError）。
    """
    _inject_harness_lib()
    from lib import signal_tracking_cloud as stc
    if not stc.cloud_enabled():
        raise HTTPException(503, "云库不可用")
    try:
        ok = stc.cloud_update_fields(signal_id, fields)
    except ValueError as e:
        raise HTTPException(422, f"字段校验失败: {e}")
    if not ok:
        raise HTTPException(404, f"未找到信号 {signal_id} 或更新失败")
    return {"ok": True, "signal_id": signal_id, **fields}


@router.post("/signal-trigger")
def post_signal_trigger(payload: SignalTriggerPayload):
    """盘中记录信号触发价/触发时间 → 云库 signal_tracking.trigger_price/trigger_time。"""
    trigger_time = payload.trigger_time or datetime.now().strftime("%H:%M")
    return _update_signal_field(payload.signal_id, {
        "trigger_price": payload.trigger_price,
        "trigger_time": trigger_time,
    })


@router.post("/signal-entry")
def post_signal_entry(payload: SignalEntryPayload):
    """复盘关联"录入交易"，记录买入价/买入时间 → 云库 entry_price/entry_time。"""
    entry_time = payload.entry_time or datetime.now().strftime("%H:%M")
    return _update_signal_field(payload.signal_id, {
        "entry_price": payload.entry_price,
        "entry_time": entry_time,
    })


def _load_tracking_signals() -> list[dict]:
    """取信号集：云库 signal_tracking → 本地 signal_tracking.json 兜底。"""
    try:
        import cloud_db
        if cloud_db.enabled():
            rows = cloud_db.select("signal_tracking", order="signal_id")
            if rows:
                out = []
                for r in rows:
                    d = dict(r)
                    if d.get("signal_date") and "trigger_date" not in d:
                        d["trigger_date"] = d["signal_date"]
                    out.append(d)
                return out
    except Exception:
        pass
    # 本地兜底
    local = Path(__file__).resolve().parent.parent.parent / "my_doc" / "每日复盘" / "harness" / "automation" / "config" / "signal_tracking.json"
    try:
        data = json.loads(local.read_text(encoding="utf-8"))
        return data.get("signals", [])
    except (OSError, json.JSONDecodeError):
        return []


def _quality_source() -> str:
    try:
        import cloud_db
        if cloud_db.enabled() and cloud_db.select("signal_tracking", columns="signal_id", limit=1):
            return "cloud"
    except Exception:
        pass
    return "local-cache"


def _quality_metrics(sigs: list[dict], settled: list[dict]) -> dict:
    """复用 harness lib/signal_quality.py 计算 8 项指标（导入失败则内联计算）。"""
    try:
        _inject_harness_lib()
        from lib import signal_quality as sq
        return sq.generate_quality_dashboard(sigs, settled, "")
    except Exception:
        return _inline_quality_metrics(sigs, settled)


def _inline_quality_metrics(sigs, settled):
    """signal_quality.py 不可导入时的内联 8 项指标（口径一致）。"""
    trig_statuses = {"triggered", "executed", "partial_executed", "settled"}
    def trig(s): return s.get("status") in trig_statuses
    pool = sigs
    trigger_rate = round(sum(1 for s in pool if trig(s)) / len(pool) * 100, 1) if pool else 0.0
    hits = [s for s in settled if s.get("outcome") == "hit"]
    target_hit_rate = round(len(hits) / len(settled) * 100, 1) if settled else 0.0
    hit_days = [s.get("holding_days") for s in hits if s.get("holding_days") is not None]
    avg_hit_days = round(sum(hit_days) / len(hit_days), 1) if hit_days else 0.0
    wins = [s.get("pnl", 0.0) for s in settled if (s.get("pnl") or 0) > 0]
    losses = [s.get("pnl", 0.0) for s in settled if (s.get("pnl") or 0) < 0]
    avg_pl = round((sum(wins) / len(wins)) / abs(sum(losses) / len(losses)), 2) if wins and losses else 0.0
    correct = total = 0
    for s in settled:
        if s.get("trade_type") not in ("buy", "sell"): continue
        is_buy = s.get("trade_type") == "buy"
        if (is_buy and (s.get("settle_price") or 0) >= (s.get("entry_price") or 0)) or \
           (not is_buy and (s.get("settle_price") or 0) <= (s.get("entry_price") or 0)):
            correct += 1
        total += 1
    direction_acc = round(correct / total * 100, 1) if total else 0.0
    exp_rows = [s for s in sigs if s.get("expected_trigger_rate") is not None]
    actual_rate = round(sum(1 for r in exp_rows if trig(r)) / len(exp_rows) * 100, 1) if exp_rows else 0.0
    avg_exp = sum(r.get("expected_trigger_rate", 0) for r in exp_rows) / len(exp_rows) if exp_rows else 0.0
    exp_vs_actual = round(actual_rate - avg_exp, 1) if exp_rows else None
    expected_value = round(sum(s.get("pnl", 0.0) for s in settled) / len(settled), 2) if settled else 0.0
    pnls = [s.get("pnl", 0.0) for s in settled]
    max_loss = round(min(pnls), 2) if pnls and min(pnls) < 0 else 0.0
    return {
        "trigger_rate_p1": round(sum(1 for s in sigs if s.get("priority") == "P1" and trig(s)) /
                                 max(sum(1 for s in sigs if s.get("priority") == "P1"), 1) * 100, 1),
        "trigger_rate_all": trigger_rate,
        "target_hit_rate": target_hit_rate,
        "avg_hit_days": avg_hit_days,
        "avg_profit_loss_ratio": avg_pl,
        "direction_accuracy": direction_acc,
        "expected_vs_actual": {"rows": [], "avg_gap": exp_vs_actual},
        "signal_expected_value": expected_value,
        "max_loss": max_loss,
    }


def _p0_execution(sigs: list[dict]) -> dict:
    """P0 执行率：P0 信号中 status ∈ {executed, settled} 的比例 + 明细。"""
    p0s = [s for s in sigs if s.get("priority") == "P0"]
    if not p0s:
        return {"rate": None, "executed": 0, "total": 0, "pending": []}
    executed = [s for s in p0s if s.get("status") in ("executed", "settled")]
    pending = [s for s in p0s if s.get("status") not in ("executed", "settled")]
    rate = round(len(executed) / len(p0s) * 100, 1)
    return {
        "rate": rate,
        "executed": len(executed),
        "total": len(p0s),
        "pending": [{"signal_id": s.get("signal_id"), "name": s.get("name"),
                     "status": s.get("status")} for s in pending],
    }


def _inject_harness_lib():
    """把 harness automation 目录加入 sys.path（导入 lib.signal_quality）。"""
    lib_dir = Path(__file__).resolve().parent.parent.parent / "my_doc" / "每日复盘" / "harness" / "automation"
    if str(lib_dir) not in sys.path:
        sys.path.insert(0, str(lib_dir))


def _cloud_signal_rows(signal_date: str) -> list[dict]:
    """从云库 signal_tracking 表读取某日信号（signal_date 为 YYYYMMDD → 转 YYYY-MM-DD）。"""
    try:
        import cloud_db
    except ImportError:
        return []
    if not cloud_db.enabled():
        return []
    iso = f"{signal_date[:4]}-{signal_date[4:6]}-{signal_date[6:8]}"
    try:
        rows = cloud_db.select(
            "signal_tracking",
            filters=[("signal_date", "eq", iso)],
            order="signal_id",
        )
        return rows
    except Exception:
        return []


def _report_markdown(signal_date: str) -> str | None:
    """读 daily_reports 中某日 每日信号 markdown（YYYYMMDD）。"""
    iso = f"{signal_date[:4]}-{signal_date[4:6]}-{signal_date[6:8]}"
    report = db.report_get(iso, "每日信号")
    return report["markdown"] if report else None


def _report_types(signal_date: str) -> list[str]:
    iso = f"{signal_date[:4]}-{signal_date[4:6]}-{signal_date[6:8]}"
    return db.report_types_for_date(iso)


def _daily_signals_from_markdown(target_date: str) -> dict:
    """过渡期兜底：markdown 解析路径（原 get_daily_signals 逻辑）。"""
    if target_date:
        report = db.report_get(target_date, "每日信号")
        if report is None:
            # BUG-FIX(2026-09-07)：原引用不存在的 date_str → NameError 500，应为 404
            raise HTTPException(404, f"未找到 {target_date} 的每日信号")
    else:
        dates_map = db.report_dates_with_types()
        found = next((d for d, types in dates_map.items() if "每日信号" in types), None)
        if found is None:
            raise HTTPException(404, "暂无每日信号数据")
        report = db.report_get(found, "每日信号")

    return {
        "date": report["report_date"],
        "signals": [],
        "markdown": report["markdown"],
        "parsed": _parse_signals(report["markdown"]),
        "types": db.report_types_for_date(report["report_date"]),
        "source": "markdown",
    }


@router.get("/reports")
def get_reports(
    report_type: str | None = Query(None, alias="type"),
    limit: int = 50,
    date: str | None = None,
):
    """报告列表（不含 markdown）。?type=&limit=&date= 过滤。"""
    if date:
        rows = []
        for t in db.report_types_for_date(date):
            r = db.report_get(date, t)
            if r:
                rows.append(
                    {
                        k: r[k]
                        for k in (
                            "id",
                            "report_date",
                            "report_type",
                            "status",
                            "generated_at",
                            "source_file",
                        )
                    }
                )
        return {"items": rows, "count": len(rows)}
    items = db.report_list(limit=min(max(limit, 1), 500), report_type=report_type)
    return {"items": items, "count": len(items)}


@router.get("/reports/{report_date}/{report_type}")
def get_report(report_date: str, report_type: str):
    report = db.report_get(report_date, report_type)
    if report is None:
        raise HTTPException(404, f"未找到 {report_date}/{report_type}")
    return report


@router.post("/reports/import")
def post_reports_import():
    """手动重扫 reports/ 目录（幂等 upsert）。"""
    result = scheduler.import_reports_from_disk()
    return {"ok": True, **result}


# ═════════════════════════════════════════════════════════════════
# 调度器
# ═════════════════════════════════════════════════════════════════


@router.get("/scheduler/tasks")
def get_scheduler_tasks():
    """task_schedule.json 中每日复盘任务 + 今日交易日状态 + 最近一次运行。"""
    from agent import db as agent_db

    today = datetime.now().date()
    today_str = today.strftime("%Y-%m-%d")
    is_td = scheduler.is_trading_day(today)
    online = agent_db.meta_get("xiaoman_online") == "1"

    def _is_daily(task):
        """每天运行一次：非 hourly 且 days_of_week 是全部工作日或 None。"""
        if task.get("hourly"):
            return False
        days = task.get("days_of_week")
        if days is None:
            return True
        return len(days) >= 5

    def _last_run_for_task(task, latest):
        """构造 last_run，daily 且今天未运行 → 返回 None。"""
        if latest is None:
            return None
        if _is_daily(task) and (latest["run_time"] or "").startswith(today_str):
            return {
                "status": latest["status"],
                "trigger": latest["trigger"],
                "run_time": latest["run_time"],
                "duration_sec": latest["duration_sec"],
                "id": latest["id"],
            }
        if _is_daily(task):
            return None
        return {
            "status": latest["status"],
            "trigger": latest["trigger"],
            "run_time": latest["run_time"],
            "duration_sec": latest["duration_sec"],
            "id": latest["id"],
        }

    tasks = []
    # BUG-FIX(2026-09-07)：原对每个 task 调一次 scheduler_latest（N+1 云往返，
    # 拖慢后台页刷新）→ 改批量一次取全部 task 的最近运行。
    scoped = scheduler.scoped_tasks()
    latest_map = db.scheduler_latest_map([t["task_id"] for t in scoped])
    for t in scoped:
        latest = latest_map.get(t["task_id"])
        tasks.append(
            {
                "task_id": t["task_id"],
                "description": t.get("description", ""),
                "target_time": t.get("target_time")
                or f"每小时 :{t.get('target_minute', '?')}",
                "hourly": bool(t.get("hourly")),
                "days_of_week": t.get("days_of_week"),
                "trading_day_required": bool(t.get("trading_day_required", False)),
                "prompt_file": t.get("prompt_file", ""),
                "is_daily": _is_daily(t),
                "last_run": _last_run_for_task(t, latest),
            }
        )

    # 拆分：每日一次 vs 其他频率，各自按时间排序
    daily_tasks = [t for t in tasks if t["is_daily"]]
    other_tasks = [t for t in tasks if not t["is_daily"]]

    def _time_sort_key(task):
        t = task["target_time"]
        try:
            h, m = t.split(":")
            return (int(h), int(m))
        except (ValueError, IndexError):
            return (99, 0)

    daily_tasks.sort(key=_time_sort_key)
    other_tasks.sort(key=_time_sort_key)

    return {
        "date": today.isoformat(),
        "is_trading_day": is_td,
        "next_trading_day": (scheduler.next_trading_day(today) or today).isoformat(),
        "auto_enabled": scheduler.engine.auto_enabled(),
        "online": online,
        "sched_running": scheduler.engine._thread is not None
        and scheduler.engine._thread.is_alive(),
        "last_tick": scheduler.engine.last_tick,
        "last_error": scheduler.engine.last_error,
        "tick_seconds": scheduler.TICK_SECONDS,
        "current_task": scheduler.current_task(),
        "tasks": tasks,
        "daily_tasks": daily_tasks,
        "other_tasks": other_tasks,
    }


@router.get("/scheduler/status")
def get_scheduler_status():
    return scheduler.engine.status()


@router.get("/scheduler/engine")
def get_scheduler_engine():
    """当前执行引擎（dsh=主 / claude=辅）与可选项。"""
    from dashboard import scheduler as sched_mod

    return {
        "engine": sched_mod.resolve_engine(),
        "available": ["dsh", "claude"],
        "default": sched_mod.DEFAULT_ENGINE,
        "dsh_installed": sched_mod._find_dsh() is not None,
    }


@router.put("/scheduler/engine")
def put_scheduler_engine(payload: dict):
    """切换执行引擎：dsh | claude（持久化到 meta，下次运行生效）。"""
    from dashboard import scheduler as sched_mod

    engine = str((payload or {}).get("engine", "")).strip().lower()
    if engine not in ("dsh", "claude"):
        raise HTTPException(400, "engine 必须是 dsh 或 claude")
    if engine == "dsh" and sched_mod._find_dsh() is None:
        raise HTTPException(400, "本机未安装 dsh CLI，无法切换到 dsh")
    db.meta_set("scheduler_engine", engine)
    return {"ok": True, "engine": engine}


@router.post("/scheduler/auto")
def post_scheduler_auto(payload: dict):
    """切换内置调度引擎的 auto 模式（持久化到 DB，引擎每 tick 读 meta，即时生效）。

    body: {"enabled": true|false}
    """
    enabled = bool((payload or {}).get("enabled"))
    scheduler.engine.set_auto_enabled(enabled)
    return {
        "ok": True,
        "auto_enabled": scheduler.engine.auto_enabled(),
        "message": "自动调度已开启（引擎随 dashboard 进程运行）"
        if enabled
        else "自动调度已关闭（仅保留手动触发）",
    }


@router.post("/scheduler/run/{task_id}")
def post_scheduler_run(task_id: str):
    """手动立即运行任务（绕过时间/交易日门控）。同任务并发返回 409。"""
    result = scheduler.run_task_by_id(task_id, trigger="manual")
    if not result.get("started"):
        code = 409 if result.get("reason") == "busy" else 400
        raise HTTPException(code, result.get("message", "无法运行"))
    return result


@router.post("/scheduler/stop/{task_id}")
def post_scheduler_stop(task_id: str):
    """停止正在执行的任务（转发给 Agent 终止子进程）。未运行返回 409。"""
    result = scheduler.dispatch_stop_to_agent(task_id)
    if not result.get("stopped"):
        code = 409 if result.get("reason") == "not_running" else 502
        raise HTTPException(code, result.get("message", "无法停止"))
    return result


@router.get("/scheduler/runs")
def get_scheduler_runs(task_id: str | None = None, limit: int = 50):
    return {
        "items": db.scheduler_runs_list(task_id=task_id, limit=min(max(limit, 1), 200))
    }


@router.get("/scheduler/runs/{run_id}/log")
def get_scheduler_run_log(run_id: int):
    run = db.scheduler_run_get(run_id)
    if run is None:
        raise HTTPException(404, f"运行记录 {run_id} 不存在")
    return run


# ═════════════════════════════════════════════════════════════════
# 企业微信信号通知
# ═════════════════════════════════════════════════════════════════


@router.get("/notify/status")
def get_notify_status():
    """通知配置/线程状态。"""
    return notify.watcher.status()


@router.post("/notify/test")
def post_notify_test():
    """发一条测试消息验证企业微信凭证链路。"""
    return notify.send_test()


@router.post("/notify/scan")
def post_notify_scan():
    """手动立即扫描今日信号触发记录并推送新触发。"""
    return notify.scan()
