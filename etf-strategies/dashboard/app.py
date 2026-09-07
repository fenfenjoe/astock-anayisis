"""AStock ETF 量化策略 Dashboard — FastAPI 后端 (v2: SQLite-backed).

启动: python dashboard/app.py  →  http://localhost:8000
"""
import sys
import os
import json
import threading
import traceback
from pathlib import Path
from datetime import date, timedelta
import pandas as pd
import numpy as np

_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

# 加载 etf-strategies/.env（DB_MODE 等在 db 模块 import 前生效）
try:
    from load_env import load_env_file
    load_env_file()
except ImportError:
    pass

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Depends, APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from dashboard import db as db_mod
from dashboard.db import (
    init_db, is_seeded, metrics_get_all, metrics_get_one,
    signals_get_latest, kb_get, nav_get_all, nav_has_data,
    user_count, user_create,
)
from dashboard.sync import seed_all, sync_daily_signals, sync_backtest_nav
from dashboard.auth import (
    get_current_user, create_token, verify_password, hash_password,
    check_rate_limit, record_login_failure, clear_rate_limit,
    get_secret_key_warning,
)
from dashboard.api_daily import router as daily_router
from dashboard.api_agent import router as agent_router
from dashboard import scheduler as daily_scheduler


# ═══════════════════════════════════════════════════════════════
# Startup / Shutdown (lifespan)
# ═══════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: restore-from-cloud (optional) → init DB, seed, pre-load modules.

    测试免疫（2026-08-31 事故修复）：pytest 环境（PYTEST_CURRENT_TEST 存在）
    下跳过全部启动副作用——云恢复下载会覆盖本地真实账本，import_* 会用真实
    文件覆盖真实 DB，upload 会把本地报告推上云。测试进程必须零副作用。

    启动提速（2026-09-02）：重负载的「cloud_sync --download 全量恢复 + 每日复盘
    导入 + 调度器/通知启动」移入后台 daemon 线程，uvicorn 立即绑定端口即可访问；
    内存库（cache.db 快照）恢复仍在 init_db() 同步完成，保证 API 读到数据。
    """
    _in_test = os.environ.get("PYTEST_CURRENT_TEST") is not None \
        or os.environ.get("DSH_TEST") == "1"

    init_db()

    # ── 初始化 agent.db（会话/文章/知识库）：dashboard 也要读它，
    #    否则 /api/agent/* （如 status 的 heartbeat）会因表不存在而报错。
    #    file 模式建表；cloud 模式直接连云（见 agent/db.py USE_CLOUD）。 ──
    try:
        from agent import db as agent_db
        agent_db.init_db()
    except Exception as e:
        print(f"[app]   WARNING: agent.db init failed: {e}")

    # ── Seed default admin user if no users exist ──
    if not _in_test and user_count() == 0:
        import secrets
        import os as _os
        default_password = _os.environ.get("DASHBOARD_ADMIN_PASSWORD", "") or secrets.token_hex(8)[:16]
        user_create(
            username="admin",
            password_hash=hash_password(default_password),
            display_name="管理员",
            role="admin",
        )
        print("[app] ========================================")
        print(f"[app]  默认管理员账号: admin / {default_password}")
        print("[app]  请登录后立即修改密码")
        print("[app] ========================================")

    # ── Warn about auto-generated secret key ──
    key_warning = get_secret_key_warning()
    if key_warning:
        print(f"[app] {key_warning}")

    # Always run seed_all — metrics & KB upserts are idempotent, so new
    # strategies are picked up automatically without requiring a DB reset.
    # NOTE: seed_all() internally calls _update_source_urls() and
    # _update_process_descs() — no need to call them again here.
    if not _in_test:
        print("[app] Syncing strategy definitions (idempotent)...")
        seed_all()
    else:
        print("[app]   (test env) skipped seed_all")

    # Pre-import heavy modules (eliminates cold-start on first API call)
    print("[app] Pre-loading strategy modules...")
    try:
        import daily_signal  # noqa: F401
        print(f"[app]   daily_signal loaded ({len(daily_signal.STRAT_MAP)} strategies)")
    except Exception as e:
        print(f"[app]   WARNING: daily_signal pre-load failed: {e}")

    # ── Background: pre-generate signals (runs after server is already live) ──
    def _warm_cache():
        if _in_test:
            return  # 测试环境不预热信号缓存（避免真实取数/写库）
        print("[app] Background: warming signal cache...")
        try:
            results = sync_daily_signals()
            ok = sum(1 for v in results.values() if v > 0)
            print(f"[app]   Signal cache ready: {ok}/{len(results)} strategies")
        except Exception as e:
            print(f"[app]   WARNING: signal warm-up failed: {e}")

    threading.Thread(target=_warm_cache, daemon=True).start()

    # ── 后台：调度器引擎最先启动 + 每日复盘导入 ──
    #    全部移入 daemon 线程，不阻塞端口绑定。测试环境整体跳过。
    #    BUG-FIX(2026-09-07)：引擎必须先于报告导入启动——导入是云调用可能耗时数分钟，
    #    若后启动引擎会错过导入期间的调度窗口（如 13:30 intraday_1330 窗口在
    #    13:34 重启后未被捕获）。引擎 start() 幂等，先启动不丢窗口。
    def _bg_restore_and_import():
        # ── 1. 调度引擎最先启动（幂等，立即开始 tick，绝不因导入慢而错过窗口）──
        try:
            daily_scheduler.start()
        except Exception as e:
            print(f"[app]   WARNING: scheduler start failed: {e}")

        # ── 2. 每日复盘集成：导入历史报告/持仓/交易（可与引擎并行）──
        print("[app] Importing 每日复盘 data (reports/holdings/trades)...")
        try:
            up = daily_scheduler.upload_reports_to_cloud()
            r = daily_scheduler.import_reports_from_disk()
            print(f"[app]   reports uploaded: {up.get('uploaded', 0)}, "
                  f"imported: {r.get('imported', 0)}")
        except Exception as e:
            print(f"[app]   WARNING: reports import failed: {e}")
        try:
            if daily_scheduler.import_holdings_from_md():
                print("[app]   holdings imported from 持仓.md")
            if daily_scheduler.import_trades_from_md():
                print("[app]   trades imported from 每日调仓.md")
        except Exception as e:
            print(f"[app]   WARNING: holdings/trades import failed: {e}")

        # ── 3. 企业微信信号触发通知 watcher（未配置则静默空转）──
        try:
            from dashboard import notify as notify_mod
            notify_mod.start()
        except Exception as e:
            print(f"[app]   WARNING: notify watcher start failed: {e}")

    if not _in_test:
        threading.Thread(target=_bg_restore_and_import, daemon=True).start()
    else:
        print("[app]   (test env) skipped cloud restore / import / scheduler / notify")

    print("[app] Startup complete — server ready at http://localhost:8000")
    yield  # <== Server starts accepting requests HERE

    # ── 关闭：调度引擎/通知 watcher 随 Web 进程停止（daemon 线程也会随进程退出，
    #    这里显式 stop 让关闭更干净，避免正在 tick 的半截操作）──
    print("[app] Shutdown...")
    try:
        daily_scheduler.engine.stop()
    except Exception as e:
        print(f"[app]   WARNING: scheduler stop failed: {e}")
    try:
        from dashboard import notify as notify_mod
        notify_mod.stop()
    except Exception:
        pass


app = FastAPI(title="AStock ETF Dashboard", version="2.0", lifespan=lifespan)
BASE_DIR = Path(__file__).resolve().parent

# Static files
_static_dir = BASE_DIR / "static"
_static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# ── Protected API sub-router (all /api/* routes require authentication) ──
protected = APIRouter(prefix="/api", dependencies=[Depends(get_current_user)])


# ═══════════════════════════════════════════════════════════════
# Auth Routes (UNPROTECTED — on main app, not the protected router)
# ═══════════════════════════════════════════════════════════════

@app.post("/api/auth/login")
async def auth_login(request: Request):
    """Login — validate credentials, return JWT access token."""
    import json as _json
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "请求格式错误")

    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    if not username or not password:
        raise HTTPException(400, "用户名和密码不能为空")

    client_ip = request.client.host if request.client else "unknown"

    # Rate-limit check
    check_rate_limit(client_ip)

    from dashboard.db import user_get_by_username, user_update_last_login
    user = user_get_by_username(username)

    if not user or not user.get("is_active"):
        record_login_failure(client_ip)
        raise HTTPException(401, "用户名或密码错误")

    if not verify_password(password, user["password_hash"]):
        record_login_failure(client_ip)
        raise HTTPException(401, "用户名或密码错误")

    # Success — clear rate limit + stamp login
    clear_rate_limit(client_ip)
    user_update_last_login(username)

    token = create_token({
        "username": user["username"],
        "role": user.get("role", "admin"),
        "display_name": user.get("display_name", user["username"]),
    })

    return JSONResponse({
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "username": user["username"],
            "display_name": user.get("display_name", user["username"]),
            "role": user.get("role", "admin"),
        },
    })


@app.post("/api/auth/logout")
async def auth_logout():
    """Logout — client-side token clearing is sufficient for JWT."""
    return JSONResponse({"status": "ok", "message": "已登出"})


@app.get("/api/auth/me")
async def auth_me(user: dict = Depends(get_current_user)):
    """Return current user info (requires valid token)."""
    return JSONResponse({
        "username": user["username"],
        "display_name": user.get("display_name", user["username"]),
        "role": user.get("role", "viewer"),
    })


@app.post("/api/auth/change-password")
async def auth_change_password(request: Request, user: dict = Depends(get_current_user)):
    """Change the current user's password (requires valid token)."""
    import json as _json
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "请求格式错误")

    old_password = body.get("old_password") or ""
    new_password = body.get("new_password") or ""

    if not old_password or not new_password:
        raise HTTPException(400, "新旧密码不能为空")
    if len(new_password) < 6:
        raise HTTPException(400, "新密码长度不能少于6位")

    from dashboard.db import user_get_by_username, user_change_password
    db_user = user_get_by_username(user["username"])
    if not db_user:
        raise HTTPException(401, "用户不存在")

    if not verify_password(old_password, db_user["password_hash"]):
        raise HTTPException(400, "原密码错误")

    user_change_password(user["username"], hash_password(new_password))
    return JSONResponse({"status": "ok", "message": "密码修改成功"})


# ═══════════════════════════════════════════════════════════════
# Runtime state (backtest progress tracking)
# ═══════════════════════════════════════════════════════════════

_cache = {
    "backtest_status": "idle",  # idle | running | done | error
    "backtest_message": "",
    "backtest_lock": threading.Lock(),
}

_klines_syncing = threading.Lock()  # guard against concurrent K-line sync


# ═══════════════════════════════════════════════════════════════
# Routes: Page
# ═══════════════════════════════════════════════════════════════

@app.get("/")
async def index():
    template_path = BASE_DIR / "templates" / "dashboard.html"
    if not template_path.exists():
        return JSONResponse({"error": "dashboard.html not found"}, status_code=500)
    return FileResponse(str(template_path))


# ═══════════════════════════════════════════════════════════════
# Routes: Strategies (from DB)
# ═══════════════════════════════════════════════════════════════

@protected.get("/strategies")
async def list_strategies(
    sort_by: str = Query("strategy_id", description="Sort field"),
    order: str = Query("asc", description="Sort order: asc|desc"),
):
    """Return all 16 strategies with metrics from the database."""
    data = metrics_get_all(sort_by=sort_by, order=order)
    return JSONResponse(data)


@protected.get("/strategies/{sid}")
async def get_strategy_detail(sid: str):
    """Return KB + metrics for one strategy."""
    sid = sid.upper()
    kb = kb_get(sid)
    metrics = metrics_get_one(sid)

    if not kb and not metrics:
        raise HTTPException(404, f"Strategy '{sid}' not found")

    result = {"id": sid}
    if kb:
        result.update({
            "name": kb.get("name", ""), "class_name": kb.get("class_name", ""),
            "category": kb.get("category", ""), "intro": kb.get("intro", ""),
            "stock_selection": kb.get("stock_selection", ""),
            "market_timing": kb.get("market_timing", ""),
            "factors": kb.get("factors", ""), "rebalance": kb.get("rebalance", ""),
            "strengths": kb.get("strengths", ""), "weaknesses": kb.get("weaknesses", ""),
            "backtest": kb.get("backtest", {}),
            "source_url": kb.get("source_url", ""),
            "process_desc": kb.get("process_desc", ""),
        })
    if metrics:
        result["metrics"] = {
            "annual_return": f"{metrics['annual_return']:.2f}%" if metrics.get("annual_return") is not None else "—",
            "sharpe": metrics.get("sharpe"),
            "max_drawdown": f"{metrics['max_drawdown']:.2f}%" if metrics.get("max_drawdown") is not None else "—",
            "calmar": metrics.get("calmar"),
            "win_rate": f"{metrics['win_rate']:.1f}%" if isinstance(metrics.get("win_rate"), (int, float)) else metrics.get("win_rate", "—"),
            "turnover": metrics.get("turnover"),
        }
    return result


# ═══════════════════════════════════════════════════════════════
# Shared Helper: DB-first price loading (used by signals/rebalances/diagnostics)
# ═══════════════════════════════════════════════════════════════

def _load_prices_from_db(assets: list[str], lookback_days: int = 300):
    """Load prices from SQLite kline_daily table, auto-syncing fresh data first.

    For each asset, this function ensures the K-line cache is up-to-date by
    calling sync_kline() (which is a no-op if data is already fresh), then
    loads from SQLite. Falls back to API if SQLite is empty.

    Returns a pd.DataFrame with assets as columns, dates as index.
    Raises RuntimeError if no data is available.
    """
    from dashboard.db import kline_get_dataframe
    from dashboard.sync import sync_kline
    from backtest.data import get_kline

    end_d = date.today().strftime("%Y-%m-%d")
    start_d = (date.today() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    series = {}
    for code in assets:
        # ── Ensure K-line cache is fresh BEFORE loading ──
        # sync_kline() is incremental — returns immediately if data is already
        # up-to-date (latest date >= today). Only fetches new data when needed.
        try:
            sync_kline(code)
        except Exception:
            pass  # Sync failure is non-fatal; proceed with whatever is in DB

        best_close = None

        # 1) SQLite is the primary cache — use it if data is sufficient.
        #    sync_kline() above ensures it's fresh; no need for redundant API call.
        try:
            df = kline_get_dataframe(code, start_d, end_d)
            if df is not None and len(df) >= 2:
                best_close = df["close"]
        except Exception:
            pass

        # 2) Fallback to API/parquet ONLY if SQLite is empty or has too little data
        #    (e.g., first run, DB reset, or code not yet cached).
        #    With the get_kline() refresh=False optimization, this is a parquet
        #    cache read — zero API calls if parquet covers the range.
        if best_close is None:
            try:
                kdf = get_kline(code, start=start_d, end=end_d, refresh=False)
                if kdf is not None and len(kdf) >= 2:
                    best_close = kdf["close"]
            except Exception:
                pass

        if best_close is not None:
            series[code] = best_close

    if not series:
        raise RuntimeError("无法获取任何资产数据，请检查网络")
    prices = pd.DataFrame(series).dropna()
    if len(prices) < 2:
        raise RuntimeError(f"数据不足（仅 {len(prices)} 个交易日），无法生成信号")
    return prices


# ═══════════════════════════════════════════════════════════════
# Routes: K-line Sync (ensure fresh data before signals/rebalances)
# ═══════════════════════════════════════════════════════════════

@protected.post("/klines/ensure/{sid}")
async def ensure_klines_fresh(sid: str):
    """Ensure K-line data is up-to-date for a strategy's ETF codes.

    Checks each code in the strategy's asset pool and incrementally
    fetches any missing data. Returns immediately if data is already fresh.
    """
    from daily_signal import STRAT_MAP
    from dashboard.sync import sync_kline

    sid = sid.upper()
    if sid not in STRAT_MAP:
        raise HTTPException(404, f"Strategy '{sid}' not found")

    _sname, strat = STRAT_MAP[sid]
    results = {}
    total_new = 0
    for code in strat.assets:
        try:
            n = sync_kline(code)
            results[code] = n
            total_new += n
        except Exception as e:
            results[code] = -1  # Mark as failed
            print(f"[app] K-line sync failed for {code}: {e}")

    return JSONResponse({
        "status": "done",
        "strategy_id": sid,
        "total_new_rows": total_new,
        "details": results,
        "message": "数据已是最新" if total_new == 0 else f"已补充 {total_new} 行K线数据",
    })


# ═══════════════════════════════════════════════════════════════
# Routes: Daily Signals (from DB, with lazy generation)
# ═══════════════════════════════════════════════════════════════

def _generate_and_store_signal(sid: str) -> dict | None:
    """Generate today's signal for one strategy and store in DB.

    Uses DB-cached K-line data first (via _load_prices_from_db),
    falling back to API only if the cache is empty.
    """
    from daily_signal import STRAT_MAP, get_etf_name

    sid = sid.upper()
    if sid not in STRAT_MAP:
        return None

    sname, strat = STRAT_MAP[sid]
    for etf in strat.assets:
        try:
            get_etf_name(etf)
        except Exception:
            pass

    lookback = max(500, getattr(strat, "lookback", 25) + 100)
    prices = _load_prices_from_db(strat.assets, lookback_days=lookback)
    # Use live=True where supported (strategy decides how to use it; e.g., weekly
    # strategies may apply resample regardless of the live flag)
    import inspect
    try:
        sig = inspect.signature(strat.generate)
        if 'live' in sig.parameters:
            weights = strat.generate(prices, live=True)
        else:
            weights = strat.generate(prices)
    except (ValueError, TypeError):
        # inspect.signature can fail on built-ins — fall back to try/except
        try:
            weights = strat.generate(prices, live=True)
        except TypeError:
            weights = strat.generate(prices)

    today_w = weights.iloc[-1]
    prev_w = weights.iloc[-2] if len(weights) > 1 else today_w * 0
    # signal_date = 最新收盘价日期的明天（信号执行日）
    # 例：最新K线7/21 → 信号日期7/22（今天盘中执行）
    # 例：最新K线7/22 → 信号日期7/23（收盘后，明天执行）
    from datetime import timedelta
    data_date = weights.index[-1].date()
    signal_date = (data_date + timedelta(days=1)).strftime("%Y-%m-%d")

    # ── Data staleness detection ──
    # Compare data_date (latest K-line) vs today; flag when ≥3 days behind
    # (avoids false positives on weekends/holidays).
    days_behind = (date.today() - data_date).days
    data_stale = days_behind >= 3
    staleness_msg = None
    if data_stale:
        staleness_msg = (
            f"K线数据更新至 {data_date}，距今日落后 {days_behind} 天，同步可能异常"
        )

    assets_data = []
    actions = []
    for etf in strat.assets:
        tw = float(today_w.get(etf, 0.0))
        pw = float(prev_w.get(etf, 0.0))
        diff = tw - pw
        name = get_etf_name(etf)

        if diff > 0.001:
            action = "BUY"
        elif diff < -0.001:
            action = "SELL"
        else:
            action = "HOLD"

        assets_data.append({
            "code": etf, "name": name,
            "target_weight": round(tw, 4), "prev_weight": round(pw, 4),
            "change": round(diff, 4), "action": action,
        })
        if action in ("BUY", "SELL"):
            actions.append({"code": etf, "name": name, "action": action,
                          "change_pct": round(abs(diff) * 100, 1)})

    # Store in DB — single transaction: DELETE old + INSERT new
    # BUG-FIX(2026-09-07)：云模式必须走云 signals_upsert/signals_delete_by_strategy，
    # 原先直接 get_conn() 写本地 daily_signals 在云模式下本地无此表（只有 kline/backtest_nav 缓存表），
    # 全新机器直接 500，迁移机器写本地读云端 → 信号不跨机共享，违背云权威原则。
    from dashboard.db import signals_delete_by_strategy, signals_upsert
    signals_delete_by_strategy(sid)
    for a in assets_data:
        signals_upsert(sid, signal_date, a["code"], a["name"],
                       a["target_weight"], a["prev_weight"], a["action"])

    holdings = sorted(
        [{"code": etf, "name": get_etf_name(etf),
          "weight": round(float(today_w.get(etf, 0)), 4)}
         for etf in strat.assets if today_w.get(etf, 0) > 0.001],
        key=lambda x: -x["weight"],
    )

    return {
        "strategy_id": sid, "strategy_name": sname,
        "signal_date": signal_date,
        "data_start": str(prices.index[0].date()),
        "data_end": str(prices.index[-1].date()),
        "trading_days": len(prices),
        "assets": assets_data, "actions": actions,
        "holdings": holdings, "has_signals": len(actions) > 0,
        "data_stale": data_stale,
        "staleness_msg": staleness_msg,
    }


@protected.get("/signals/{sid}")
async def get_signal(sid: str):
    """Get today's signal for a strategy. Checks DB first, generates if stale."""
    sid = sid.upper()

    # Check DB first
    cached = signals_get_latest(sid)
    today_str = date.today().strftime("%Y-%m-%d")
    if cached:
        cached_date = cached[0]["signal_date"]
        cached_updated = (cached[0].get("updated_at") or "")[:10]

        # Case 1: Signal already covers today — perfect cache hit
        # Case 2: Signal was already generated today (updated_at matches today).
        #   Only serve from cache if the signal_date is reasonably fresh.
        #   If data is ≥1 day behind, force regeneration because the initial
        #   sync may have run before the API had the latest trading day's data.
        days_behind = (date.today() - date.fromisoformat(cached_date)).days
        stale = days_behind >= 3
        stale_msg = None

        if cached_date == today_str:
            # Perfect: signal is for today
            pass
        elif cached_updated == today_str and days_behind <= 1:
            # Generated today with yesterday's data — acceptable
            # (e.g., morning sync before market open, or weekend/holiday)
            pass
        elif cached_updated == today_str and days_behind >= 2:
            # Generated today but data is ≥2 days behind — the API may now
            # have newer data that wasn't available during the initial sync.
            # Fall through to regenerate.
            cached = None
        else:
            # Not generated today — regenerate
            cached = None

        if cached is not None:
            # Build staleness info
            if stale:
                stale_msg = (
                    f"数据更新至 {cached_date}，距今日落后 {days_behind} 天，"
                    f"K线同步可能异常"
                )

            # Return from cache
            assets_data = []
            actions = []
            holdings = []
            for r in cached:
                assets_data.append({
                    "code": r["asset_code"], "name": r["asset_name"],
                    "target_weight": r["target_weight"],
                    "prev_weight": r["prev_weight"],
                    "change": r["weight_change"],
                    "action": r["action"],
                })
                if r["action"] in ("BUY", "SELL"):
                    actions.append({
                        "code": r["asset_code"], "name": r["asset_name"],
                        "action": r["action"],
                        "change_pct": round(abs(r["weight_change"]) * 100, 1),
                    })
                if r["target_weight"] and r["target_weight"] > 0.001:
                    holdings.append({
                        "code": r["asset_code"], "name": r["asset_name"],
                        "weight": r["target_weight"],
                    })
            holdings.sort(key=lambda x: -x["weight"])

            # Get strategy name from metrics table
            m = metrics_get_one(sid)
            sname = m["name"] if m else sid

            return JSONResponse({
                "strategy_id": sid, "strategy_name": sname,
                "signal_date": cached_date,
                "assets": assets_data, "actions": actions,
                "holdings": holdings,
                "has_signals": len(actions) > 0,
                "data_start": "", "data_end": "", "trading_days": 0,
                "_cached": True,
                "data_stale": stale,
                "staleness_msg": stale_msg,
            })

    # Not cached at all → generate
    try:
        result = _generate_and_store_signal(sid)
        if result is None:
            raise HTTPException(404, f"Strategy '{sid}' not found")
        return JSONResponse(result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Signal generation failed: {e}\n\n{traceback.format_exc()}")


@protected.get("/signals")
async def get_all_signals_summary():
    """Get a lightweight signal summary for all strategies (reads DB cache)."""
    try:
        from daily_signal import STRAT_MAP
    except ImportError:
        return JSONResponse({"strategies": [], "total_buy": 0, "total_sell": 0})

    strategies_summary = []
    total_buy = 0
    total_sell = 0

    for sid in sorted(STRAT_MAP.keys()):
        cached = signals_get_latest(sid)
        if cached:
            buy_c = sum(1 for r in cached if r["action"] == "BUY")
            sell_c = sum(1 for r in cached if r["action"] == "SELL")
            total_buy += buy_c
            total_sell += sell_c
            strategies_summary.append({
                "id": sid, "name": STRAT_MAP[sid][0],
                "signal_date": cached[0]["signal_date"],
                "buy_count": buy_c, "sell_count": sell_c,
                "hold_count": len(cached) - buy_c - sell_c,
                "has_signals": (buy_c + sell_c) > 0,
                "holdings_count": sum(1 for r in cached if r["target_weight"] and r["target_weight"] > 0.001),
            })
        else:
            strategies_summary.append({
                "id": sid, "name": STRAT_MAP[sid][0], "error": True,
            })

    return JSONResponse({
        "strategies": strategies_summary,
        "total_buy": total_buy, "total_sell": total_sell,
        "strategies_with_signals": sum(1 for s in strategies_summary if s.get("has_signals")),
    })


# ═══════════════════════════════════════════════════════════════
# Routes: Refresh (triggers sync)
# ═══════════════════════════════════════════════════════════════

@protected.post("/refresh/signals")
async def refresh_signals():
    """Force-regenerate all daily signals and store in DB."""
    try:
        results = sync_daily_signals()
        ok = sum(1 for v in results.values() if v > 0)
        fail = sum(1 for v in results.values() if v < 0)
        return JSONResponse({
            "status": "done", "ok": ok, "fail": fail,
            "details": results,
        })
    except Exception as e:
        raise HTTPException(500, str(e))


@protected.post("/refresh/klines")
async def refresh_klines():
    """Incrementally sync K-line data for all ETF codes."""
    from dashboard.sync import sync_all_klines

    if _klines_syncing.locked():
        return JSONResponse({"status": "already_running", "message": "K-line sync already in progress"})

    def run():
        with _klines_syncing:
            sync_all_klines()
    threading.Thread(target=run, daemon=True).start()
    return JSONResponse({"status": "started", "message": "K-line sync running in background"})


# ═══════════════════════════════════════════════════════════════
# Routes: Charts (from DB NAV table, with lazy backtest)
# ═══════════════════════════════════════════════════════════════

def _run_backtest_task():
    """Run full backtest in background and store NAV data."""
    with _cache["backtest_lock"]:
        if _cache["backtest_status"] == "running":
            return
        _cache["backtest_status"] = "running"
        _cache["backtest_message"] = "Running full backtest..."
    print("[app] Starting backtest task...")

    try:
        results = sync_backtest_nav(
            progress_callback=lambda msg: _cache.update({"backtest_message": msg})
        )
        ok = sum(1 for v in results.values() if v > 0)
        _cache["backtest_status"] = "done"
        _cache["backtest_message"] = f"Backtest complete — {ok} strategies"
        print(f"[app] Backtest complete: {ok} strategies")
    except Exception as e:
        _cache["backtest_status"] = "error"
        _cache["backtest_message"] = str(e)
        print(f"[app] Backtest failed: {e}")
        traceback.print_exc()


@protected.get("/charts/equity")
async def get_equity_data(
    strategies: str = Query(None, description="Comma-separated strategy names"),
):
    """Return NAV data for ECharts. Triggers backtest if DB has no cached NAV."""
    if not nav_has_data():
        if _cache["backtest_status"] != "running":
            threading.Thread(target=_run_backtest_task, daemon=True).start()
        return JSONResponse({
            "status": _cache["backtest_status"],
            "message": _cache["backtest_message"],
            "data": None,
        }, status_code=202)

    data = nav_get_all()
    if not data["dates"]:
        return JSONResponse({"status": "empty", "data": None}, status_code=202)

    # Filter if requested
    if strategies:
        selected = [s.strip() for s in strategies.split(",")]
        filtered_series = {k: v for k, v in data["series"].items() if k in selected}
        filtered_dd = {k: v for k, v in data["drawdowns"].items() if k in selected}
    else:
        filtered_series = data["series"]
        filtered_dd = data["drawdowns"]

    return JSONResponse({
        "status": "done",
        "dates": data["dates"],
        "series": filtered_series,
        "drawdowns": filtered_dd,
    })


@protected.get("/charts/status")
async def get_chart_status():
    return JSONResponse({
        "status": _cache["backtest_status"],
        "message": _cache["backtest_message"],
        "ready": nav_has_data(),
    })


@protected.post("/backtest/run")
async def trigger_backtest():
    """Trigger full backtest (background thread)."""
    if _cache["backtest_status"] == "running":
        return JSONResponse({"status": "running", "message": "Backtest already in progress"})
    threading.Thread(target=_run_backtest_task, daemon=True).start()
    return JSONResponse({"status": "started", "message": "Backtest started"})


@protected.post("/report/{sid}")
async def generate_report(sid: str):
    """Generate one-year backtest HTML report for a strategy.

    严格零本地：生成后上传 TOS（report/），本地文件删除（云模式）；
    云未配置时保留本地（降级）。
    """
    sid = sid.upper()
    try:
        from daily_signal import STRAT_MAP
        if sid not in STRAT_MAP:
            raise HTTPException(404, f"Strategy '{sid}' not found")
        from html_report import generate_report as gen_report
        sname, strat = STRAT_MAP[sid]
        filepath = gen_report(sid, strat)
        stored = "local"
        try:
            from cloud_store import put_object
            name = os.path.basename(str(filepath))
            with open(filepath, "rb") as f:
                put_object(f"report/{name}", f.read())
            Path(filepath).unlink(missing_ok=True)   # 云模式：本地不落盘
            stored = "tos"
        except Exception:
            pass  # 云未配置/失败 → 保留本地文件
        return JSONResponse({
            "status": "done", "strategy_id": sid,
            "strategy_name": sname, "report_path": str(filepath),
            "stored": stored,
        })
    except ImportError as e:
        raise HTTPException(500, f"Import failed: {e}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Report generation failed: {e}")


@protected.get("/report/file/{name}")
async def get_report_file(name: str):
    """读取回测报告 HTML（云模式从 TOS 读；降级读本地 report/）。"""
    if "/" in name or ".." in name or not name.endswith(".html"):
        raise HTTPException(400, "非法文件名")
    try:
        from cloud_store import get_object
        data = get_object(f"report/{name}")
        if data is not None:
            return Response(content=data, media_type="text/html; charset=utf-8")
    except Exception:
        pass
    local = Path(__file__).resolve().parent.parent / "report" / name
    if local.exists():
        return Response(content=local.read_bytes(),
                        media_type="text/html; charset=utf-8")
    raise HTTPException(404, "报告不存在")


@protected.get("/strategies/{sid}/source")
async def get_strategy_source(sid: str):
    """Return the Python source code of a strategy."""
    sid = sid.upper()
    try:
        from dashboard.sync import STRATEGY_DEFS
    except ImportError:
        raise HTTPException(500, "Cannot import strategy definitions")

    sdef = None
    for s in STRATEGY_DEFS:
        if s["id"] == sid:
            sdef = s
            break

    if sdef is None:
        raise HTTPException(404, f"Strategy '{sid}' not found")

    # Convert module path to file path: backtest.strategies.buy_hold → backtest/strategies/buy_hold.py
    mod_path = sdef["mod"]
    rel_path = mod_path.replace(".", "/") + ".py"
    file_path = _PARENT / rel_path

    if not file_path.exists():
        raise HTTPException(404, f"Source file not found: {rel_path}")

    try:
        source_code = file_path.read_text(encoding="utf-8")
        return JSONResponse({
            "strategy_id": sid,
            "strategy_name": sdef["name"],
            "file_path": rel_path,
            "source_code": source_code,
            "lines": len(source_code.splitlines()),
        })
    except Exception as e:
        raise HTTPException(500, f"Failed to read source: {e}")


@protected.get("/strategies/{sid}/rebalances")
async def get_rebalance_history(sid: str):
    """Return last 10 rebalance events grouped by date.

    Each date = one rebalance record, containing all ETF weight changes on that day.
    """
    from daily_signal import STRAT_MAP, get_etf_name

    sid = sid.upper()
    if sid not in STRAT_MAP:
        raise HTTPException(404, f"Strategy '{sid}' not found")

    try:
        sname, strat = STRAT_MAP[sid]
        lookback = max(500, getattr(strat, "lookback", 25) + 100)
        prices = _load_prices_from_db(strat.assets, lookback_days=lookback)
        weights = strat.generate(prices)

        # Group weight changes by date
        from collections import OrderedDict
        date_groups = OrderedDict()  # date_str -> list of ETF changes
        for i in range(1, len(weights)):
            date_str = str(weights.index[i].date())
            for etf in strat.assets:
                delta = weights.iloc[i].get(etf, 0) - weights.iloc[i-1].get(etf, 0)
                if abs(delta) > 0.001:  # 0.1% threshold for grouping
                    if date_str not in date_groups:
                        date_groups[date_str] = []
                    date_groups[date_str].append({
                        "code": etf,
                        "name": get_etf_name(etf),
                        "from_weight": round(float(weights.iloc[i-1].get(etf, 0)) * 100, 1),
                        "to_weight": round(float(weights.iloc[i].get(etf, 0)) * 100, 1),
                        "change_pct": round(float(delta) * 100, 1),
                        "action": "加仓" if delta > 0 else "减仓",
                    })

        # Build rebalance records (one per date)
        rebalance_dates = []
        for date_str, etf_changes in date_groups.items():
            total_buy = sum(1 for c in etf_changes if c["action"] == "加仓")
            total_sell = sum(1 for c in etf_changes if c["action"] == "减仓")
            rebalance_dates.append({
                "date": date_str,
                "total_buy": total_buy,
                "total_sell": total_sell,
                "changes": etf_changes,
            })

        # Return last 10 rebalance dates
        return JSONResponse({
            "strategy_id": sid,
            "strategy_name": sname,
            "total_dates": len(rebalance_dates),
            "rebalances": rebalance_dates[-10:],
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to compute rebalances: {e}")


@protected.get("/strategies/{sid}/diagnostics")
async def get_strategy_diagnostics(sid: str):
    """Return strategy-specific internal state (canary scores, momentum values, etc.)."""
    from daily_signal import STRAT_MAP, get_etf_name

    sid = sid.upper()
    if sid not in STRAT_MAP:
        raise HTTPException(404, f"Strategy '{sid}' not found")

    try:
        sname, strat = STRAT_MAP[sid]
        lookback = max(500, getattr(strat, "lookback", 25) + 100)
        prices = _load_prices_from_db(strat.assets, lookback_days=lookback)

        diagnostics = strat.get_diagnostics(prices)
        diagnostics["strategy_id"] = sid
        diagnostics["strategy_name"] = sname

        # Add ETF names to scores
        if "scores" in diagnostics:
            named_scores = {}
            for code, score in diagnostics["scores"].items():
                named_scores[f"{code} {get_etf_name(code)}"] = score
            diagnostics["scores"] = named_scores

        # Add ETF names to score_details (年化收益 / R² / 综合得分 明细)
        if "score_details" in diagnostics:
            named_details = {}
            for code, detail in diagnostics["score_details"].items():
                named_details[f"{code} {get_etf_name(code)}"] = detail
            diagnostics["score_details"] = named_details

        return JSONResponse(diagnostics)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Diagnostics failed: {e}\n\n{traceback.format_exc()}")


@protected.post("/backtest/{sid}")
async def run_single_strategy_backtest(sid: str):
    """Run full-window backtest for a single strategy and persist metrics to DB."""
    import importlib
    import re
    sid = sid.upper()

    try:
        from dashboard.sync import STRATEGY_DEFS
    except ImportError:
        raise HTTPException(500, "Cannot import strategy definitions")

    # Find strategy definition
    sdef = None
    for s in STRATEGY_DEFS:
        if s["id"] == sid:
            sdef = s
            break

    if sdef is None:
        raise HTTPException(404, f"Strategy '{sid}' not found in STRATEGY_DEFS")

    # Parse backtest window — start_date from config, end_date ALWAYS today
    window_str = sdef.get("window", "")
    match = re.match(r"(\d{4}-\d{2}-\d{2})~(\d{4}-\d{2}-\d{2})", window_str)
    if match:
        start_date = match.group(1)
    else:
        start_date = "2012-05-28"
    end_date = date.today().strftime("%Y-%m-%d")

    try:
        # Import strategy class
        mod = importlib.import_module(sdef["mod"])
        StratClass = getattr(mod, sdef["cls"])
        strat = StratClass(**sdef["kwargs"])

        # Load prices — try both SQLite and API/parquet, use whichever has more data
        from backtest.data import get_kline
        from dashboard.db import kline_get_dataframe
        series = {}
        for code in strat.assets:
            best_close = None
            best_len = 0
            # 1) Try SQLite cache
            try:
                df = kline_get_dataframe(code, start_date, end_date)
                if df is not None and len(df) >= 2:
                    best_close = df["close"]
                    best_len = len(df)
            except Exception:
                pass
            # 2) Try API → parquet (keep if it has more data than SQLite)
            try:
                kdf = get_kline(code, start=start_date, end=end_date, refresh=False)
                if kdf is not None and len(kdf) > best_len:
                    best_close = kdf["close"]
                    best_len = len(kdf)
            except Exception:
                pass
            if best_close is not None:
                series[code] = best_close
        prices = pd.DataFrame(series).dropna()

        if len(prices) < 20:
            raise HTTPException(400, f"Insufficient price data ({len(prices)} rows)")

        # Run backtest
        w = strat.generate(prices)
        from backtest.engine import backtest as run_bt
        result = run_bt(prices, w)

        # Compute metrics
        # years for annualization: must use actual price data span (not window)
        n_days = (prices.index[-1] - prices.index[0]).days
        years = max(0.5, n_days / 365.25)
        total_ret = result.nav.iloc[-1] / result.nav.iloc[0] - 1
        annual_return = (1 + total_ret) ** (1 / years) - 1

        # years for display: computed from window dates (reliable, not data-dependent)
        from datetime import datetime
        win_start = datetime.strptime(start_date, "%Y-%m-%d")
        win_end = datetime.strptime(end_date, "%Y-%m-%d")
        window_years = max(1, round((win_end - win_start).days / 365.25))

        daily_rets = result.nav.pct_change().dropna()
        sharpe = float(daily_rets.mean() / daily_rets.std() * np.sqrt(252)) if daily_rets.std() > 0 else 0.0

        peak = result.nav.cummax()
        dd_series = result.nav / peak - 1
        max_drawdown = float(dd_series.min())

        calmar = annual_return / abs(max_drawdown) if max_drawdown < 0 else 0.0

        win_rate = float((daily_rets > 0).sum() / len(daily_rets) * 100) if len(daily_rets) > 0 else 0.0

        # Annual turnover (approx from weight changes)
        w_diff = w.diff().abs().sum(axis=1)
        turnover = float(w_diff.mean() * 252) if len(w_diff) > 0 else 0.0

        # Excess return vs S1 benchmark (if available)
        excess_return = None
        try:
            from dashboard.db import metrics_get_one
            s1 = metrics_get_one("S1")
            if s1 and s1.get("ann_val") is not None:
                excess_return = annual_return * 100 - s1["ann_val"]
        except Exception:
            pass

        # Persist metrics to DB
        from dashboard.db import metrics_upsert, nav_upsert_batch
        assets_display = [f"{c}" for c in strat.assets]
        backtest_window_display = f"{start_date}~{end_date} (约{window_years}年)"

        metrics_upsert(
            strategy_id=sid,
            name=sdef["name"],
            category=sdef["category"],
            category_cn=sdef.get("category_cn", sdef["category"]),
            annual_return=round(annual_return * 100, 2),
            sharpe=round(sharpe, 2),
            max_drawdown=round(max_drawdown * 100, 2),
            calmar=round(calmar, 2),
            win_rate=round(win_rate, 1),
            turnover=round(turnover, 1),
            excess_return=round(excess_return, 2) if excess_return is not None else None,
            assets=assets_display,
            description=sdef["desc"],
            backtest_window=backtest_window_display,
        )

        # ── Also persist NAV data for equity curve (weekly sampling) ──
        # Single transaction: DELETE old + INSERT new
        strategy_name = f"{sid}_{sdef['name']}"
        weekly_nav = result.nav.iloc[::5]
        weekly_dd = dd_series.iloc[::5]
        nav_rows = []
        for i in range(len(weekly_nav)):
            d_str = str(weekly_nav.index[i].date())
            nv = float(weekly_nav.iloc[i])
            dd = float(weekly_dd.iloc[i]) if i < len(weekly_dd) else 0.0
            nav_rows.append((strategy_name, d_str, nv, dd))
        from dashboard.db import get_conn
        with get_conn() as conn:
            conn.execute("DELETE FROM backtest_nav WHERE strategy_name=?", (strategy_name,))
            conn.executemany("""
                INSERT OR REPLACE INTO backtest_nav (strategy_name, date, nav, drawdown)
                VALUES (?, ?, ?, ?)
            """, nav_rows)

        return JSONResponse({
            "status": "done",
            "strategy_id": sid,
            "strategy_name": sdef["name"],
            "annual_return": f"{annual_return*100:.2f}%",
            "sharpe": round(sharpe, 2),
            "max_drawdown": f"{max_drawdown*100:.2f}%",
            "calmar": round(calmar, 2),
            "win_rate": f"{win_rate:.1f}%",
            "turnover": round(turnover, 1),
            "backtest_window": backtest_window_display,
        })
    except HTTPException:
        raise
    except ImportError as e:
        raise HTTPException(500, f"Import failed: {e}")
    except Exception as e:
        raise HTTPException(500, f"Backtest failed: {e}\n\n{traceback.format_exc()}")


# ═══════════════════════════════════════════════════════════════
# Routes: Score Curves
# ═══════════════════════════════════════════════════════════════

SCORING_STRATEGIES = {"S4", "S8", "S12", "S13", "S14", "S15", "S16", "S17", "S18", "S19"}


def _compute_momentum_scores(prices, lookback=25, clamp_r2=False):
    """计算动量打分曲线：年化收益 × R²（与 MomentumRotation 策略公式一致）。

    对每只 ETF 取最近 lookback 天的对数价格做 OLS 回归：
    - 年化收益 = exp(日斜率 × 250) - 1
    - R² = 1 - SS_res / SS_tot
    - 得分 = 年化收益 × (clamp_r2 ? max(R², 0) : R²)

    clamp_r2=True 用于 S15/S16/S17，与策略内部的 max(r_sq, 0) 一致。
    """
    log_prices = np.log(prices)
    scores = pd.DataFrame(index=prices.index, columns=prices.columns, dtype=float)
    for i in range(lookback, len(prices)):
        # 窗口含当日：与策略 generate() 一致 [i-lookback+1, i+1)
        window = log_prices.iloc[i - lookback + 1: i + 1]
        for col in prices.columns:
            y = window[col].dropna().values
            if len(y) < lookback // 2:
                continue
            x = np.arange(len(y)).astype(float)
            slope, intercept = np.polyfit(x, y, 1)
            # 年化收益 = exp(日斜率 × 250) - 1（与 MomentumRotation 一致）
            ann_ret = np.exp(slope * 250) - 1
            # R² = 1 - SS_res / SS_tot
            y_pred = slope * x + intercept
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = (len(y) - 1) * np.var(y, ddof=1) if len(y) > 1 else 1e-12
            r2 = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
            scores.iloc[i, prices.columns.get_loc(col)] = ann_ret * (max(r2, 0) if clamp_r2 else r2)
    return scores



def _compute_three_factor_scores(prices, lookback=25):
    log_prices = np.log(prices)
    scores = pd.DataFrame(index=prices.index, columns=prices.columns, dtype=float)
    for i in range(lookback, len(prices)):
        window = log_prices.iloc[i - lookback + 1: i + 1]
        window_prices = prices.iloc[i - lookback + 1: i + 1]
        for col in prices.columns:
            y = window[col].dropna().values
            p = window_prices[col].dropna().values
            if len(y) < lookback // 2:
                continue
            x = np.arange(len(y)).astype(float)
            slope, intercept = np.polyfit(x, y, 1)
            y_pred = slope * x + intercept
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
            slope_score = (np.exp(slope * 250) - 1) * r2
            ma = np.mean(p)
            dev_slope = (p[-1] / ma - 1) / (len(p) / 252) if ma > 0 and len(p) > 0 else 0.0
            dev_s, _ = np.polyfit(np.arange(len(p)).astype(float), p / ma, 1) if ma > 0 else (0, 0)
            dev_score = float(dev_s * 252)
            direction = y[-1] - y[0]
            path = np.sum(np.abs(np.diff(y)))
            eff_score = direction / path if path > 0 else 0.0
            raw = 0.4 * slope_score + 0.3 * dev_score + 0.3 * eff_score
            scores.iloc[i, prices.columns.get_loc(col)] = raw
    return scores


def _compute_adaptive_momentum_scores(prices, lb_min=15, lb_max=120, vol_short=10, vol_long=60, ratio_cap=2.0):
    log_prices = np.log(prices)
    rets = prices.pct_change()
    scores = pd.DataFrame(index=prices.index, columns=prices.columns, dtype=float)
    max_lb = max(lb_max, vol_long) + 5
    for i in range(max_lb, len(prices)):
        for col in prices.columns:
            ret_series = rets[col].iloc[:i+1].dropna()
            if len(ret_series) < vol_long:
                continue
            short_vol = ret_series.iloc[-vol_short:].std() * np.sqrt(252) if len(ret_series) >= vol_short else 0.0
            long_vol = ret_series.iloc[-vol_long:].std() * np.sqrt(252) if len(ret_series) >= vol_long else 0.01
            vol_ratio = min(ratio_cap, short_vol / long_vol) if long_vol > 0 else 1.0
            lb = int(lb_min + (lb_max - lb_min) * (1 - vol_ratio))
            lb = max(lb_min, min(lb_max, lb))
            if i < lb:
                continue
            window = log_prices[col].iloc[i - lb + 1: i + 1]
            y = window.dropna().values
            if len(y) < lb // 2:
                continue
            x = np.arange(len(y)).astype(float)
            slope, intercept = np.polyfit(x, y, 1)
            y_pred = slope * x + intercept
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - np.mean(y)) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
            ann_ret = np.exp(slope * 250) - 1
            scores.iloc[i, prices.columns.get_loc(col)] = ann_ret * r2
    return scores


@protected.get("/scores/{sid}")
async def get_score_curves(sid: str):
    sid = sid.upper()
    try:
        from daily_signal import STRAT_MAP, get_etf_name

        if sid not in STRAT_MAP:
            raise HTTPException(404, f"Strategy '{sid}' not found")

        sname, strat = STRAT_MAP[sid]
        # Dynamic lookback: strategies with large momentum windows (e.g. S18 mom_long=200)
        # need more calendar days to leave enough chart points after warmup.
        max_lb = max(
            getattr(strat, 'mom_long', 0),
            getattr(strat, 'mom_lookback', 0),
            getattr(strat, 'lookback', 0),
            25,
        )
        lookback_days = max(400, int(max_lb * 3.5))
        prices = _load_prices_from_db(strat.assets, lookback_days=lookback_days)
        if len(prices) < 20:
            raise HTTPException(400, "Insufficient price data")

        if sid == "S4":
            score_df = _compute_momentum_scores(prices, lookback=getattr(strat, 'lookback', 25))
        elif sid == "S8":
            score_df = _compute_three_factor_scores(prices, lookback=getattr(strat, 'lookback', 25))
        elif sid == "S14":
            score_df = _compute_adaptive_momentum_scores(
                prices,
                lb_min=getattr(strat, 'lb_min', 15),
                lb_max=getattr(strat, 'lb_max', 120),
                vol_short=getattr(strat, 'vol_short', 10),
                vol_long=getattr(strat, 'vol_long', 60),
                ratio_cap=getattr(strat, 'ratio_cap', 2.0),
            )
        elif sid in ("S12", "S13"):
            # S12/S13 use multi-factor scoring that can't be replicated without volume
            # data. Use target weights as a proxy visualization (not actual scores).
            w = strat.generate(prices)
            score_df = w.reindex(prices.index, method='ffill')
        elif sid == "S15":
            # S15 使用 max(r_sq, 0) 截断 R²，与 TrendFilterMomentum._momentum_score 一致
            lb = getattr(strat, 'mom_lookback', 25)
            score_df = _compute_momentum_scores(prices, lookback=lb, clamp_r2=True)
        elif sid in ("S16", "S17"):
            # S16/S17 使用 max(r_sq, 0) 截断 R²，与 canary_defense._momentum_score 一致
            lb = getattr(strat, 'mom_lookback', 25)
            score_df = _compute_momentum_scores(prices, lookback=lb, clamp_r2=True)
            # Only show trading ETF pool scores (not bond/gold/cash monitoring assets)
            etf_pool = getattr(strat, 'etf_pool', list(score_df.columns))
            score_df = score_df[[c for c in etf_pool if c in score_df.columns]]
        elif sid == "S18":
            # S18: RSRS增强反转动量 = 25日动量 - (200日动量 / 6)
            mom_short = getattr(strat, 'mom_short', 25)
            mom_long = getattr(strat, 'mom_long', 200)
            rev_scale = getattr(strat, 'reversal_scale', 6.0)
            scores_25 = _compute_momentum_scores(prices, lookback=mom_short, clamp_r2=True)
            scores_200 = _compute_momentum_scores(prices, lookback=mom_long, clamp_r2=True)
            # Align indices
            common_idx = scores_25.index.intersection(scores_200.index)
            score_df = scores_25.loc[common_idx] - (scores_200.loc[common_idx] / rev_scale)
            # Only show ETF pool scores (not cash)
            etf_pool = getattr(strat, 'etf_pool', list(score_df.columns))
            score_df = score_df[[c for c in etf_pool if c in score_df.columns]]
        elif sid == "S19":
            # S19: 低相关ETF轮动 = 标准25日动量打分
            lb = getattr(strat, 'lookback', 25)
            score_df = _compute_momentum_scores(prices, lookback=lb, clamp_r2=True)
        else:
            w = strat.generate(prices)
            score_df = w.reindex(prices.index, method='ffill')

        score_df = score_df.dropna(how='all')
        if len(score_df) > 52:
            # Subsample evenly but ALWAYS include the last data point
            n = len(score_df)
            step = max(1, n // 52)
            indices = sorted(set(list(range(0, n - 1, step)) + [n - 1]))
            score_df = score_df.iloc[indices]

        asset_names = {}
        for code in score_df.columns:
            asset_names[code] = get_etf_name(code)

        score_series = {}
        for col in score_df.columns:
            vals = [float(v) if not (isinstance(v, float) and np.isnan(v)) else None
                    for v in score_df[col].values]
            score_series[col] = vals

        return JSONResponse({
            "strategy_id": sid, "strategy_name": sname,
            "is_scoring": sid in SCORING_STRATEGIES,
            "dates": [str(d.date()) for d in score_df.index],
            "assets": list(score_df.columns),
            "asset_names": asset_names,
            "scores": score_series,
        })
    except ImportError as e:
        raise HTTPException(500, f"Import failed: {e}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Score computation failed: {e}\n\n{traceback.format_exc()}")


# ═══════════════════════════════════════════════════════════════
# Routes: 1-Year Performance vs Shanghai Composite Index
# ═══════════════════════════════════════════════════════════════

def _fetch_index_kline(code: str, start: str, end: str) -> pd.Series | None:
    """Fetch index daily K-line (close prices) from Sina Finance API.

    Supports Shanghai indices (sh000001 = 上证指数) and Shenzhen indices
    (sz399001 = 深证成指). Returns a pd.Series with datetime index.
    """
    import requests as req

    # Map code to Sina symbol: 000001 → sh000001, 399001 → sz399001
    if code.startswith("000"):
        symbol = f"sh{code}"
    elif code.startswith("399"):
        symbol = f"sz{code}"
    elif code.startswith(("5", "6")):
        symbol = f"sh{code}"
    else:
        symbol = f"sz{code}"

    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": symbol, "scale": "240", "ma": "no", "datalen": "400"}
    try:
        r = req.get(url, params=params,
                    headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        r.encoding = "utf-8"
        records = r.json()
        if not records or not isinstance(records, list):
            return None
        data = {}
        for rec in records:
            d = rec.get("day", "")
            close_str = rec.get("close", "")
            if d and close_str:
                try:
                    data[d] = float(close_str)
                except (ValueError, TypeError):
                    continue
        if not data:
            return None
        s = pd.Series(data, name=code)
        s.index = pd.to_datetime(s.index)
        s = s.sort_index()
        # Filter to requested date range
        s = s[(s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))]
        return s if len(s) >= 2 else None
    except Exception:
        return None


@protected.get("/strategies/{sid}/perf-1y")
async def get_one_year_performance(sid: str):
    """Return 1-year performance: strategy NAV vs Shanghai Composite Index.

    Returns daily NAV curves (normalized to 1.0 at start) and key metrics:
    strategy return, index return, excess return, Sharpe, max drawdown,
    volatility, Calmar, win rate, beta, alpha, information ratio.
    """
    import importlib
    from backtest.engine import backtest as run_bt
    from backtest.data import get_kline
    from dashboard.db import kline_get_dataframe

    sid = sid.upper()
    try:
        from dashboard.sync import STRATEGY_DEFS
    except ImportError:
        raise HTTPException(500, "Cannot import strategy definitions")

    sdef = None
    for s in STRATEGY_DEFS:
        if s["id"] == sid:
            sdef = s
            break
    if sdef is None:
        raise HTTPException(404, f"Strategy '{sid}' not found")

    try:
        # Date range: last 1 year + extra lookback for strategy warmup
        end_d = date.today().strftime("%Y-%m-%d")
        one_year_ago = (date.today() - timedelta(days=365)).strftime("%Y-%m-%d")
        # Extra lookback for strategy (some need 200+ days for MA/indicators)
        lookback_start = (date.today() - timedelta(days=730)).strftime("%Y-%m-%d")

        # Import strategy
        mod = importlib.import_module(sdef["mod"])
        StratClass = getattr(mod, sdef["cls"])
        strat = StratClass(**sdef["kwargs"])

        # Ensure K-line freshness
        from dashboard.sync import sync_kline
        for code in strat.assets:
            try:
                sync_kline(code)
            except Exception:
                pass

        # Load prices from DB for the full lookback window
        series = {}
        for code in strat.assets:
            try:
                df = kline_get_dataframe(code, lookback_start, end_d)
                if df is not None and len(df) >= 2:
                    series[code] = df["close"]
            except Exception:
                pass
            if code not in series:
                try:
                    kdf = get_kline(code, start=lookback_start, end=end_d, refresh=False)
                    if kdf is not None and len(kdf) >= 2:
                        series[code] = kdf["close"]
                except Exception:
                    pass

        if not series:
            raise HTTPException(400, "Insufficient price data")

        prices = pd.DataFrame(series).dropna()
        if len(prices) < 20:
            raise HTTPException(400, f"Only {len(prices)} trading days available")

        # Generate weights and run backtest
        try:
            w = strat.generate(prices, live=True)
        except TypeError:
            w = strat.generate(prices)
        result = run_bt(prices, w)

        # ── Slice to last 1 year for reporting ──
        one_year_nav = result.nav[result.nav.index >= one_year_ago]
        one_year_returns = result.returns[result.returns.index >= one_year_ago]

        if len(one_year_nav) < 5:
            raise HTTPException(400, f"Only {len(one_year_nav)} days in 1-year window")

        # Normalize NAV to start at 1.0
        base_nav = one_year_nav.iloc[0]
        strat_nav = one_year_nav / base_nav

        # ── Fetch Shanghai Composite Index ──
        index_code = "000001"
        idx_series = _fetch_index_kline(index_code, one_year_ago, end_d)

        # ── Compute index NAV (normalized to 1.0 at same start) ──
        has_index = idx_series is not None and len(idx_series) >= 2

        if has_index:
            # Align index dates to strategy dates (forward fill)
            idx_aligned = idx_series.reindex(strat_nav.index, method="ffill").dropna()
            if len(idx_aligned) < 2:
                has_index = False
            else:
                idx_base = idx_aligned.iloc[0]
                idx_nav = idx_aligned / idx_base
                # Only keep dates where both exist
                common_idx = strat_nav.index.intersection(idx_nav.index)
                strat_nav_aligned = strat_nav.loc[common_idx]
                idx_nav_aligned = idx_nav.loc[common_idx]

        # ── Compute metrics ──
        daily_rets = one_year_returns.dropna()
        n_days = len(daily_rets)
        years_1y = max(0.25, n_days / 252)

        # Strategy metrics
        strat_total_ret = strat_nav.iloc[-1] / strat_nav.iloc[0] - 1
        strat_ann_ret = (1 + strat_total_ret) ** (1 / years_1y) - 1 if years_1y > 0 else 0.0
        strat_vol = float(daily_rets.std() * np.sqrt(252)) if len(daily_rets) > 1 else 0.0
        strat_sharpe = float(strat_ann_ret / strat_vol) if strat_vol > 0 else 0.0
        strat_peak = strat_nav.cummax()
        strat_dd = strat_nav / strat_peak - 1
        strat_max_dd = float(strat_dd.min())
        strat_calmar = strat_ann_ret / abs(strat_max_dd) if strat_max_dd < 0 else 0.0
        strat_win_rate = float((daily_rets > 0).sum() / len(daily_rets) * 100) if len(daily_rets) > 0 else 0.0

        metrics = {
            "strategy_return": round(strat_total_ret * 100, 2),
            "strategy_ann_return": round(strat_ann_ret * 100, 2),
            "strategy_sharpe": round(strat_sharpe, 2),
            "strategy_max_drawdown": round(strat_max_dd * 100, 2),
            "strategy_volatility": round(strat_vol * 100, 2),
            "strategy_calmar": round(strat_calmar, 2),
            "strategy_win_rate": round(strat_win_rate, 1),
            "trading_days": n_days,
            "period_start": str(strat_nav.index[0].date()),
            "period_end": str(strat_nav.index[-1].date()),
        }

        if has_index and len(idx_nav_aligned) >= 2:
            idx_total_ret = idx_nav_aligned.iloc[-1] / idx_nav_aligned.iloc[0] - 1
            idx_ann_ret = (1 + idx_total_ret) ** (1 / years_1y) - 1 if years_1y > 0 else 0.0
            excess_total = strat_total_ret - idx_total_ret
            excess_ann = strat_ann_ret - idx_ann_ret

            # Tracking error (annualized std of excess daily returns)
            idx_daily = idx_nav_aligned.pct_change().dropna()
            common_rets = daily_rets.loc[daily_rets.index.intersection(idx_daily.index)]
            idx_common = idx_daily.loc[idx_daily.index.intersection(common_rets.index)]
            tracking_error = float((common_rets - idx_common).std() * np.sqrt(252)) if len(common_rets) > 1 else 0.0
            info_ratio = excess_ann / tracking_error if tracking_error > 0 else 0.0

            # Beta (to index) — computed over common dates
            aligned_idx = idx_nav_aligned.reindex(strat_nav_aligned.index, method="ffill")
            strat_daily = strat_nav_aligned.pct_change().dropna()
            idx_daily_aligned = aligned_idx.pct_change().dropna()
            common_dates = strat_daily.index.intersection(idx_daily_aligned.index)
            if len(common_dates) > 10:
                beta = float(np.cov(strat_daily.loc[common_dates], idx_daily_aligned.loc[common_dates])[0, 1]
                            / np.var(idx_daily_aligned.loc[common_dates]))
            else:
                beta = None

            # Alpha (annualized)
            if beta is not None and beta != 0:
                alpha = strat_ann_ret - beta * idx_ann_ret
            else:
                alpha = None

            # Max drawdown for index too
            idx_peak = idx_nav_aligned.cummax()
            idx_dd = idx_nav_aligned / idx_peak - 1
            idx_max_dd = float(idx_dd.min())

            metrics.update({
                "index_return": round(idx_total_ret * 100, 2),
                "index_ann_return": round(idx_ann_ret * 100, 2),
                "index_max_drawdown": round(idx_max_dd * 100, 2),
                "excess_return": round(excess_total * 100, 2),
                "excess_ann_return": round(excess_ann * 100, 2),
                "beta": round(beta, 2) if beta is not None else None,
                "alpha": round(alpha * 100, 2) if alpha is not None else None,
                "info_ratio": round(info_ratio, 2) if tracking_error > 0 else None,
                "tracking_error": round(tracking_error * 100, 2),
            })

            return JSONResponse({
                "status": "done",
                "strategy_id": sid,
                "strategy_name": sdef["name"],
                "index_code": index_code,
                "index_name": "上证指数",
                "dates": [str(d.date()) for d in strat_nav_aligned.index],
                "strategy_nav": [float(v) for v in strat_nav_aligned.values],
                "index_nav": [float(v) for v in idx_nav_aligned.values],
                "metrics": metrics,
            })
        else:
            # No index data — return strategy-only
            return JSONResponse({
                "status": "done",
                "strategy_id": sid,
                "strategy_name": sdef["name"],
                "dates": [str(d.date()) for d in strat_nav.index],
                "strategy_nav": [float(v) for v in strat_nav.values],
                "index_nav": None,
                "index_name": "上证指数(数据不可用)",
                "metrics": metrics,
            })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Performance computation failed: {e}\n\n{traceback.format_exc()}")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def _kill_existing_on_port(port: int) -> bool:
    """Kill the process already listening on *port* (Windows only). Returns True if killed."""
    import platform
    import re
    if platform.system() != "Windows":
        return False
    try:
        import subprocess
        result = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.splitlines():
            if "LISTENING" not in line:
                continue
            # Require whitespace after port number to avoid matching :80001 for :8000
            m = re.search(rf":{port}\s", line)
            if not m:
                continue
            parts = line.strip().split()
            pid = parts[-1] if parts else None
            if pid and pid.isdigit():
                subprocess.run(["taskkill", "/PID", pid, "/F"],
                               capture_output=True, timeout=10)
                print(f"[dashboard] Killed old process (PID={pid}) on port {port}")
                return True
    except Exception:
        pass
    return False


# ── Mount the protected API router ──
app.include_router(protected)
# ── 每日复盘集成 API（持仓/资产/信号/报告/调度，同样走 JWT）──
app.include_router(daily_router)
# ── 拟人 Agent「小满」API（聊天/文章/状态）──
app.include_router(agent_router)

if __name__ == "__main__":
    import uvicorn
    PORT = int(__import__("os").environ.get("DASHBOARD_PORT", "8000"))
    print(f"[dashboard] AStock ETF Dashboard v2 starting at http://localhost:{PORT}")

    if _kill_existing_on_port(PORT):
        import time
        time.sleep(0.5)  # let OS release the port

    uvicorn.run(app, host="0.0.0.0", port=PORT)
