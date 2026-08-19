"""每日复盘集成 API — 持仓/资产/报告/信号/调度 (api_daily).

路由前缀 /api，全部走 JWT 认证（依赖 get_current_user）。
- Phase 0: 持仓/资产 配置 + 实时市值刷新 + 东财实验配置
- Phase 1/2: 每日信号 / 报告 / 调度器 路由（随 scheduler.py 一起加入）

⚠️ 路由冲突陷阱：不得用 /api/signals/daily —— 现有 GET /api/signals/{sid} 会先匹配。
   每日信号一律走独立前缀 /api/daily-signals。
"""
import json
import re
import threading
from datetime import datetime

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


# 并发保护：价格刷新 / 东财刷新 各自串行，避免同操作为并发写坏估值快照
_price_refresh_lock = threading.Lock()
_em_refresh_lock = threading.Lock()


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
    """组装 GET /api/portfolio 的完整响应（持仓 + 估值 + meta + 东财状态）。"""
    meta = {
        "total_assets": _meta_num("total_assets"),
        "available_cash": _meta_num("available_cash"),
        "account_source": db.meta_get("account_source", "manual"),
        "last_refresh_at": db.meta_get("last_refresh_at"),
    }
    snapshot_raw = db.meta_get("valuation_snapshot")
    try:
        snapshot = json.loads(snapshot_raw) if snapshot_raw else None
    except (json.JSONDecodeError, TypeError):
        snapshot = None

    has_creds = db.meta_get("eastmoney_has_creds") == "1"
    return {
        "holdings": db.portfolio_holdings_get_all(),
        "trades_count": len(db.portfolio_trades_get_all()),
        "meta": meta,
        "valuation": snapshot,
        "eastmoney": {
            "has_creds": has_creds,
            "account_suffix": db.meta_get("eastmoney_account_suffix"),
            "note": db.meta_get("eastmoney_note"),
            "last_error": db.meta_get("last_eastmoney_error"),
            "experimental": True,
        },
        "server_time": _now_str(),
    }


def _recompute_valuation_and_store(refresh_prices: bool = False, available_cash: float | None = None):
    """重算估值并持久化 valuation_snapshot（不触发同步时用缓存价）。"""
    holdings = db.portfolio_holdings_get_all()
    if available_cash is None:
        available_cash = _meta_num("available_cash", 0.0)
    val = portfolio.compute_valuation(holdings, available_cash=available_cash,
                                      refresh_prices=refresh_prices)
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
        rows.append({"code": code, "name": r.name or code,
                     "shares": float(r.shares or 0),
                     "cost_price": r.cost_price})
    if not rows:
        raise HTTPException(400, "持仓不能为空")

    db.portfolio_holdings_replace(rows)

    # 回写 持仓.md（保持 prompt 期望的表格格式）
    try:
        portfolio.write_holdings_md(rows)
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
    return {"started": True, "message": "市值刷新已在后台启动", "server_time": _now_str()}


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
    db.meta_set("eastmoney_account_suffix", eastmoney.account_suffix({"account": account}))
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
                db.meta_set("last_eastmoney_error", f"{datetime.now():%Y-%m-%d %H:%M:%S} 东财拉取失败: {e}")
                return  # 手动数据保持不动

            rows = data.get("holdings") or []
            if not rows:
                db.meta_set("last_eastmoney_error",
                            f"{datetime.now():%Y-%m-%d %H:%M:%S} 东财返回持仓为空（可能需人工过验证码）")
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
    return {"started": True, "message": "东财刷新已在后台启动", "server_time": _now_str()}


# ═════════════════════════════════════════════════════════════════
# 每日信号 / 报告（只读展示）
# ═════════════════════════════════════════════════════════════════

# 信号总表列名（与 每日信号.md 模板列一致）
_SIGNAL_COLUMNS = [
    "优先级", "标的", "触发条件", "操作类型", "状态", "方向", "紧急度",
    "升级条件", "预期收益日", "有效时段", "仓位", "操作来源", "生成依据", "信号ID",
]


def _parse_signals(markdown: str) -> list[dict]:
    """从 每日信号.md 解析「信号总表」为结构化行。

    规则：定位 '## 信号总表' 段，取其中 markdown 表格，按 _SIGNAL_COLUMNS 映射。
    解析失败返回 []（调用方 fallback 到全文渲染，绝不硬失败）。
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
    for line in lines[idx + 1:]:
        if line.strip().startswith("## "):
            break  # 下一个段落结束
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        # 跳过表头/分隔行：表头含 '优先级'，分隔行全为 -/: 字符
        joined = "".join(cells)
        if "优先级" in joined:
            continue
        if joined and set(joined) <= set("-|: "):
            continue
        # 尽量按列数填充，不足补空
        record = {}
        for j, col in enumerate(_SIGNAL_COLUMNS):
            record[col] = cells[j] if j < len(cells) else ""
        # 信号ID 缺失则该行跳过（信号行必须含 ID）
        if not record.get("信号ID"):
            continue
        rows.append(record)
    return rows


@router.get("/daily-signals")
def get_daily_signals(date: str | None = None):
    """每日信号：?date=YYYYMMDD（默认最新）。返回 {date, markdown, parsed, types}。"""
    if date:
        report = db.report_get(date, "每日信号")
        if report is None:
            raise HTTPException(404, f"未找到 {date_str} 的每日信号")
    else:
        # 取最近一个有每日信号的日期
        dates = db.report_get_dates()
        found = None
        for d in dates:
            if "每日信号" in db.report_types_for_date(d):
                found = d
                break
        if found is None:
            raise HTTPException(404, "暂无每日信号数据")
        report = db.report_get(found, "每日信号")

    return {
        "date": report["report_date"],
        "markdown": report["markdown"],
        "parsed": _parse_signals(report["markdown"]),
        "types": db.report_types_for_date(report["report_date"]),
    }


@router.get("/reports")
def get_reports(report_type: str | None = Query(None, alias="type"),
                limit: int = 50, date: str | None = None):
    """报告列表（不含 markdown）。?type=&limit=&date= 过滤。"""
    if date:
        rows = []
        for t in db.report_types_for_date(date):
            r = db.report_get(date, t)
            if r:
                rows.append({k: r[k] for k in
                             ("id", "report_date", "report_type", "status", "generated_at", "source_file")})
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
    today = datetime.now().date()
    is_td = scheduler.is_trading_day(today)
    tasks = []
    for t in scheduler.scoped_tasks():
        latest = db.scheduler_latest(t["task_id"])
        tasks.append({
            "task_id": t["task_id"],
            "description": t.get("description", ""),
            "target_time": t.get("target_time") or f"每小时 :{t.get('target_minute','?')}",
            "hourly": bool(t.get("hourly")),
            "days_of_week": t.get("days_of_week"),
            "trading_day_required": bool(t.get("trading_day_required", False)),
            "prompt_file": t.get("prompt_file", ""),
            "last_run": {
                "status": latest["status"] if latest else None,
                "trigger": latest["trigger"] if latest else None,
                "run_time": latest["run_time"] if latest else None,
                "duration_sec": latest["duration_sec"] if latest else None,
                "id": latest["id"] if latest else None,
            } if latest else None,
        })
    return {
        "date": today.isoformat(),
        "is_trading_day": is_td,
        "next_trading_day": (scheduler.next_trading_day(today) or today).isoformat(),
        "auto_enabled": scheduler.engine.auto_enabled(),
        "tasks": tasks,
    }


@router.get("/scheduler/status")
def get_scheduler_status():
    return scheduler.engine.status()


@router.post("/scheduler/run/{task_id}")
def post_scheduler_run(task_id: str):
    """手动立即运行任务（绕过时间/交易日门控）。同任务并发返回 409。"""
    result = scheduler.run_task_by_id(task_id, trigger="manual")
    if not result.get("started"):
        code = 409 if result.get("reason") == "busy" else 400
        raise HTTPException(code, result.get("message", "无法运行"))
    return result


@router.get("/scheduler/runs")
def get_scheduler_runs(task_id: str | None = None, limit: int = 50):
    return {"items": db.scheduler_runs_list(task_id=task_id, limit=min(max(limit, 1), 200))}


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
