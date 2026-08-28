"""SQLite 缓存数据库 — Dashboard 数据持久化层.

Tables
------
kline_daily         K线日数据（增量同步）
strategy_metrics    策略回测指标
daily_signals       每日信号快照
strategy_kb         策略知识库
backtest_nav        权益曲线 NAV 数据
metadata            key-value 元数据（种子标记等）
"""
import sqlite3
import json
import os
import threading
from pathlib import Path
from datetime import date, datetime, timedelta
from contextlib import contextmanager

DB_PATH = Path(__file__).resolve().parent / "data" / "cache.db"

# ── 严格零本地：DB_MODE=memory 时用内存库（:memory:），
#    启动从 TOS 载入最新快照（cloud_restore），定时/退出快照回传（cloud_backup）。
#    默认 file 模式（向后兼容 + 测试/降级）。
USE_MEMORY = os.environ.get("DB_MODE", "").lower() == "memory"
_mem_lock = threading.RLock()
_mem_conn: sqlite3.Connection | None = None

# TOS 读写（严格零本地内存库的快照源；未配置云时置 None → 恢复/备份 no-op）
try:
    from cloud_store import (get_object as _cs_get, put_object as _cs_put,
                             list_objects as _cs_list)
except ImportError:
    _cs_get = _cs_put = _cs_list = None


def _memory_conn() -> sqlite3.Connection:
    global _mem_conn
    if _mem_conn is None:
        _mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
        _mem_conn.row_factory = sqlite3.Row
        _mem_conn.execute("PRAGMA foreign_keys=ON")
    return _mem_conn


def cloud_restore() -> bool:
    """memory 模式：从 TOS 最新 cache.db 快照载入（serialize/deserialize，纯内存）。

    返回 True=已载入；False=无快照/TOS 不可用（调用方建空 schema）。
    """
    if not USE_MEMORY or _cs_get is None or _cs_list is None:
        return False
    try:
        keys = [k for k in _cs_list("sqlite/") if k.endswith("/cache.db")]
        if not keys:
            return False
        data = _cs_get(max(keys))  # 字典序=时间序，取最新
        if not data:
            return False
        _memory_conn().deserialize(data)
        return True
    except Exception:
        return False


def cloud_backup() -> bool:
    """memory 模式：导出快照并上传 TOS（sqlite/<ts>/cache.db）。"""
    if not USE_MEMORY or _cs_put is None:
        return False
    try:
        data = _memory_conn().serialize()
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        _cs_put(f"sqlite/{ts}/cache.db", data)
        return True
    except Exception:
        return False


def cloud_backup_loop(interval_seconds: int = 900) -> None:
    """后台定时快照回传（daemon 线程，仅 memory 模式生效）。"""
    while True:
        try:
            cloud_backup()
        except Exception:
            pass
        threading.Event().wait(interval_seconds)


# ── Connection management ──
@contextmanager
def get_conn():
    if USE_MEMORY:
        conn = _memory_conn()
        with _mem_lock:
            yield conn
            conn.commit()
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Schema ──
SCHEMA = """
-- ═══════════════════════════════════════════════════════════════════
-- Table: kline_daily — ETF K线日数据缓存
-- ═══════════════════════════════════════════════════════════════════
-- 用途: 缓存所有策略涉及ETF的日线行情，支持增量刷新（按 code + date 去重）
-- 数据来源: 东财 push2his API → get_kline() → SQLite
-- 刷新策略: 增量 — 查 MAX(date) 仅拉取缺失日期段
-- 行数估算: 25个ETF × ~3500交易日 ≈ 87,500行
-- 相关模块: sync.py:sync_kline(), db.py:kline_*() CRUD函数
--
-- 字段说明:
--   code       ETF代码 (如510300/513100/159915)，与 daily_signal.STRAT_MAP 一致
--   date       交易日 YYYY-MM-DD
--   open/high/low/close/volume  日线OHLCV，前复权
--   updated_at 写入时间戳
CREATE TABLE IF NOT EXISTS kline_daily (
    code        TEXT NOT NULL,
    date        TEXT NOT NULL,          -- YYYY-MM-DD
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL NOT NULL,
    volume      REAL,
    updated_at  TEXT DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (code, date)
);

-- ═══════════════════════════════════════════════════════════════════
-- Table: strategy_metrics — 策略回测绩效指标
-- ═══════════════════════════════════════════════════════════════════
-- 用途: 存储最近一次全量回测的绩效指标，Dashboard策略全景表直接读取此表
-- 数据来源: 首次启动从 sync.py:BENCHMARKS 种子；POST /api/backtest/run 可刷新
-- 行数: 16行（S1~S16），每行一个策略
-- 相关模块: sync.py:seed_all(), app.py:/api/strategies
--
-- 字段说明:
--   strategy_id     策略编号 S1~S16
--   name/category    策略名称/类别(动量/趋势/因子/…)
--   category_cn      类别中文全称
--   annual_return    年化收益率(小数, 如0.3362=33.62%)；NULL=待回测
--   sharpe           夏普比率(无风险利率=0)
--   max_drawdown     最大回撤(负数, 如-0.2851=-28.51%)
--   calmar           Calmar比率 = 年化/|最大回撤|
--   win_rate         日胜率(日收益>0占比)
--   turnover         年化换手率(双边)
--   excess_return    相对S1基准超额年化收益
--   assets_json      资产池JSON数组 ["510300(沪深300ETF)", …]
--   description      策略一句话描述
--   backtest_window  回测数据窗口 (如"2012-05-28~2026-07-01 (约14年)")
--   updated_at       数据更新时间
CREATE TABLE IF NOT EXISTS strategy_metrics (
    strategy_id     TEXT PRIMARY KEY,    -- S1..S16
    name            TEXT NOT NULL,
    category        TEXT,
    category_cn     TEXT,
    annual_return   REAL,
    sharpe          REAL,
    max_drawdown    REAL,
    calmar          REAL,
    win_rate        REAL,
    turnover        REAL,
    excess_return   REAL,
    assets_json     TEXT,                -- JSON array of "code(name)" strings
    description     TEXT,
    backtest_window TEXT,
    updated_at      TEXT DEFAULT (datetime('now','localtime'))
);

-- ═══════════════════════════════════════════════════════════════════
-- Table: daily_signals — 每日交易信号快照
-- ═══════════════════════════════════════════════════════════════════
-- 用途: 缓存每个策略每日对各ETF的买卖建议，避免重复调API计算
-- 数据来源: sync.py:sync_daily_signals() 或首次 API 调用时实时生成
-- 刷新策略: 每个策略每日仅保留最新一条信号记录（生成时 DELETE 旧数据再 INSERT）
--           旧于30天的信号由 signals_delete_old() 自动清理
-- 行数估算: 16策略 × 平均4个ETF = ~64行/天（仅保留当日）
-- 相关模块: sync.py:sync_daily_signals(), app.py:_generate_and_store_signal()
--
-- 字段说明:
--   id              自增主键
--   strategy_id     策略编号(S1~S16)
--   signal_date     信号日期(通常为最近交易日)
--   asset_code      资产代码
--   asset_name      资产名称(中文)
--   target_weight   建议目标权重(0.0~1.0)
--   prev_weight     上一期权重
--   weight_change   权重变动 = target - prev (±1.0)
--   action          操作方向: BUY(买入) | SELL(卖出) | HOLD(持有)
--   updated_at       写入时间戳
CREATE TABLE IF NOT EXISTS daily_signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id     TEXT NOT NULL,
    signal_date     TEXT NOT NULL,       -- YYYY-MM-DD
    asset_code      TEXT NOT NULL,
    asset_name      TEXT,
    target_weight   REAL,
    prev_weight     REAL,
    weight_change   REAL,
    action          TEXT,                -- BUY | SELL | HOLD
    updated_at      TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(strategy_id, signal_date, asset_code)
);

-- ═══════════════════════════════════════════════════════════════════
-- Table: strategy_kb — 策略知识库
-- ═══════════════════════════════════════════════════════════════════
-- 用途: 存储每个策略的详细文档(原理/择股逻辑/因子/优劣势/回测参数)
-- 数据来源: 首次启动从 strategy_kb.py:KB 种子，之后不变（静态知识）
-- 行数: 16行（S1~S16）
-- 相关模块: sync.py:seed_all(), app.py:/api/strategies/{sid}
--
-- 字段说明:
--   strategy_id      策略编号 S1~S16
--   name/class_name  策略名称/Python类名
--   category         策略类别(被动投资/动量/趋势/…)
--   intro            策略简介(200字)
--   stock_selection  择股逻辑说明
--   market_timing    择时逻辑说明
--   factors          使用因子说明
--   rebalance        调仓节奏说明
--   strengths        策略优势
--   weaknesses       策略劣势
--   backtest_params  回测参数JSON {initial_capital, commission, window, …}
CREATE TABLE IF NOT EXISTS strategy_kb (
    strategy_id TEXT PRIMARY KEY,
    name        TEXT,
    class_name  TEXT,
    category    TEXT,
    intro       TEXT,
    stock_selection TEXT,
    market_timing   TEXT,
    factors     TEXT,
    rebalance   TEXT,
    strengths   TEXT,
    weaknesses  TEXT,
    source_url      TEXT,                -- 策略来源URL（研报/文章/源码链接）
    process_desc    TEXT,                -- 策略执行过程中文描述
    backtest_params TEXT,                -- JSON object
    updated_at  TEXT DEFAULT (datetime('now','localtime'))
);

-- ═══════════════════════════════════════════════════════════════════
-- Table: backtest_nav — 权益曲线净值数据
-- ═══════════════════════════════════════════════════════════════════
-- 用途: 存储全量回测的周频NAV序列，供 ECharts 权益曲线/回撤曲线渲染
-- 数据来源: sync.py:sync_backtest_nav() 运行全量回测生成
-- 采样频率: 每周一次(每5个交易日取1个点)，减少数据传输量
-- 行数估算: 16策略 × ~700周 ≈ 11,200行
-- 相关模块: sync.py:sync_backtest_nav(), app.py:/api/charts/equity
--
-- 字段说明:
--   strategy_name  策略全名 (如 "S1_买入持有"、"S4_多资产动量轮动")
--   date           采样日期 YYYY-MM-DD (周频)
--   nav            累计净值 (起始=1.0)
--   drawdown       当前回撤 (负数, 如-0.15=-15%)
CREATE TABLE IF NOT EXISTS backtest_nav (
    strategy_name TEXT NOT NULL,         -- e.g. "S1_买入持有"
    date          TEXT NOT NULL,         -- YYYY-MM-DD (weekly sampled)
    nav           REAL NOT NULL,
    drawdown      REAL,
    PRIMARY KEY (strategy_name, date)
);

-- ═══════════════════════════════════════════════════════════════════
-- Table: users — Dashboard 登录用户
-- ═══════════════════════════════════════════════════════════════════
-- 用途: 存储Dashboard登录用户及密码哈希（bcrypt），支持多用户访问控制
-- 行数估计: <10行（小团队内部工具）
-- 相关模块: auth.py, app.py
--
-- 字段说明:
--   id            自增主键
--   username      登录用户名（唯一）
--   password_hash bcrypt哈希（$2b$12$...）
--   display_name  显示名称（中文）
--   role          角色: admin / viewer
--   is_active     0=禁用, 1=启用
--   created_at    创建时间
--   last_login    最后登录时间
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name  TEXT,
    role          TEXT NOT NULL DEFAULT 'admin',
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT DEFAULT (datetime('now','localtime')),
    last_login    TEXT
);

-- ═══════════════════════════════════════════════════════════════════
-- Table: metadata — 系统元数据
-- ═══════════════════════════════════════════════════════════════════
-- 用途: key-value 存储系统级标记(种子是否完成等)
-- 行数: <10行
--
-- 当前key:
--   seeded = "1"  数据库已完成首次种子初始化
CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- ═══════════════════════════════════════════════════════════════════
-- Indexes
-- ═══════════════════════════════════════════════════════════════════
-- idx_kline_code   : 按代码查询K线(最常用)              → kline_daily(code)
-- idx_kline_date   : 增量刷新时查 MAX(date)             → kline_daily(date)
-- idx_signal_sid   : 按策略+日期查今日信号(最常用)       → daily_signals(strategy_id, signal_date)
-- idx_nav_name     : 按策略名查NAV序列(图表渲染)         → backtest_nav(strategy_name)
CREATE INDEX IF NOT EXISTS idx_kline_code ON kline_daily(code);
CREATE INDEX IF NOT EXISTS idx_kline_date ON kline_daily(date);
CREATE INDEX IF NOT EXISTS idx_signal_sid   ON daily_signals(strategy_id, signal_date);
CREATE INDEX IF NOT EXISTS idx_nav_name     ON backtest_nav(strategy_name);

-- ═══════════════════════════════════════════════════════════════════
-- Table: portfolio_holdings — 每日复盘持仓快照（权威持仓）
-- ═══════════════════════════════════════════════════════════════════
-- 用途: 存储用户当前持仓（1 code 一行），是持仓的唯一权威来源，
--       与 my_doc/每日复盘/harness/config/持仓.md 双向同步
-- 数据来源: 手动配置（PUT /api/portfolio/holdings）或东财自动获取（可选实验）
-- 刷新策略: 替换式 — 保存时 DELETE 全部再 INSERT（持仓.md 是快照语义）
-- 相关模块: portfolio.py（解析/回写 持仓.md）、api_daily.py
--
-- 字段说明:
--   code        ETF代码（如 159227/513100），UNIQUE
--   name        股票名称
--   shares      持仓数量（份）
--   cost_price  成本价（元）
CREATE TABLE IF NOT EXISTS portfolio_holdings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT NOT NULL,
    name       TEXT,
    shares     REAL NOT NULL,
    cost_price REAL,
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    UNIQUE(code)
);

-- ═══════════════════════════════════════════════════════════════════
-- Table: portfolio_meta — 组合/账户级 key-value 元数据
-- ═══════════════════════════════════════════════════════════════════
-- 用途: 存组合维度状态（类似现有 metadata 表的 KV 模式）
-- 相关模块: portfolio.py / api_daily.py / eastmoney.py
--
-- 当前key:
--   total_assets          总资产（str float）
--   available_cash        可用现金
--   account_source        数据源: manual | eastmoney
--   eastmoney_config      东财凭据（Fernet 加密 JSON）
--   eastmoney_has_creds   是否已配置东财凭据
--   last_eastmoney_error  最近一次东财刷新错误
--   last_refresh_at       最近一次实时估值刷新时间
--   valuation_snapshot    估值快照 JSON（每行持仓 mv/cost/pnl + 汇总）
--   holdings_md_mtime     持仓.md 文件 mtime（防止重复反向解析）
CREATE TABLE IF NOT EXISTS portfolio_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- ═══════════════════════════════════════════════════════════════════
-- Table: portfolio_trades — 调仓交易记录
-- ═══════════════════════════════════════════════════════════════════
-- 用途: 交易日志（导入自 my_doc/每日复盘/每日调仓.md 的"调仓记录"表）
-- 数据来源: 每日调仓.md 解析导入（v1 不回写文件）
-- 相关模块: scheduler.py:import_trades_from_md()
CREATE TABLE IF NOT EXISTS portfolio_trades (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,            -- 2026-07-08
    name       TEXT,
    code       TEXT,
    quantity   REAL,
    price      REAL,
    side       TEXT,                     -- 买入 | 卖出
    remark     TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);

-- ═══════════════════════════════════════════════════════════════════
-- Table: daily_reports — 每日复盘报告/信号 markdown
-- ═══════════════════════════════════════════════════════════════════
-- 用途: 存储每日复盘系统生成的报告/信号全文，供 dashboard 页面展示
-- 数据来源: scheduler.py:import_reports_from_disk() 扫描 reports/ 目录导入
--           （或 claude 运行完成后导入）
-- 刷新策略: upsert（report_date+report_type UNIQUE，幂等）
-- 相关模块: scheduler.py / api_daily.py
--
-- 字段说明:
--   report_date  YYYYMMDD（目录名；周报解析自文件名）
--   report_type  早盘报告 | 复盘报告 | 每日信号 | 早盘机会 | 周报 | 周度组合回顾
--   markdown     报告全文（markdown）
--   status       ready | stale | generating
--   source_file  reports/20260720/每日信号.md（相对仓库根）
CREATE TABLE IF NOT EXISTS daily_reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date  TEXT NOT NULL,          -- YYYYMMDD
    report_type  TEXT NOT NULL,
    markdown     TEXT NOT NULL,
    status       TEXT DEFAULT 'ready',
    generated_at TEXT DEFAULT (datetime('now','localtime')),
    source_file  TEXT,
    UNIQUE(report_date, report_type)
);

-- ═══════════════════════════════════════════════════════════════════
-- Table: scheduler_runs — 定时任务运行日志 + 幂等记录
-- ═══════════════════════════════════════════════════════════════════
-- 用途: dashboard 内置调度器（scheduler.py）每次运行的记录；
--       window_key 唯一防 auto 重复执行（幂等，与 /loop task_scheduler 兼容）
-- 相关模块: scheduler.py / api_daily.py
--
-- 字段说明:
--   task_id      任务ID（如 morning_analysis）
--   window_key   窗口幂等 key（如 "evening_review:2026-08-13"；manual 用独立 key）
--   trigger      auto | manual
--   run_time     开始时间（ISO）
--   status       running | success | failed | timeout | skipped
--   pid          claude 子进程 PID
--   duration_sec 运行时长（秒）
--   output       stdout/stderr 尾部（~8KB）
--   completed_at 完成时间
CREATE TABLE IF NOT EXISTS scheduler_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      TEXT NOT NULL,
    window_key   TEXT,
    trigger      TEXT DEFAULT 'auto',
    run_time     TEXT NOT NULL,
    status       TEXT,
    pid          INTEGER,
    duration_sec REAL,
    output       TEXT,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_trades_date ON portfolio_trades(trade_date);
CREATE INDEX IF NOT EXISTS idx_reports_date ON daily_reports(report_date);
CREATE INDEX IF NOT EXISTS idx_sched_task  ON scheduler_runs(task_id);
CREATE INDEX IF NOT EXISTS idx_sched_time  ON scheduler_runs(run_time);
"""


def init_db():
    """Create all tables and indexes if they don't exist.

    memory 模式：先从 TOS 载入最新快照（空连接 deserialize），无快照才建空 schema。
    """
    if USE_MEMORY:
        if not cloud_restore():
            _memory_conn().executescript(SCHEMA)
        with get_conn() as conn:
            _migrate(conn)
        return
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn):
    """轻量迁移（幂等）：新增列兼容老库。"""
    try:
        conn.execute("ALTER TABLE strategy_kb ADD COLUMN source_url TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE strategy_kb ADD COLUMN process_desc TEXT")
    except Exception:
        pass


def is_seeded():
    """Check whether the DB has been seeded with initial strategy data."""
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM metadata WHERE key='seeded'").fetchone()
        return row is not None and row["value"] == "1"


def mark_seeded():
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES('seeded', '1')")


# ═══════════════════════════════════════════════════════════════
# K-line CRUD
# ═══════════════════════════════════════════════════════════════

def kline_latest_date(code: str) -> str | None:
    """Return the latest date (YYYY-MM-DD) for a code, or None if no data."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MAX(date) as d FROM kline_daily WHERE code=?", (code,)
        ).fetchone()
        return row["d"] if row and row["d"] else None


def kline_upsert(code: str, date_str: str, open_: float, high: float,
                 low: float, close: float, volume: float = 0.0):
    """Insert or update a single K-line row."""
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO kline_daily (code, date, open, high, low, close, volume, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
        """, (code, date_str, open_, high, low, close, volume))


def kline_upsert_batch(rows: list[tuple]):
    """Batch insert K-line rows. rows: [(code, date, open, high, low, close, volume), ...]"""
    with get_conn() as conn:
        conn.executemany("""
            INSERT OR REPLACE INTO kline_daily (code, date, open, high, low, close, volume, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
        """, rows)


def kline_get(code: str, start: str = None, end: str = None) -> list[dict]:
    """Return K-line rows for a code in [start, end]."""
    with get_conn() as conn:
        sql = "SELECT * FROM kline_daily WHERE code=? "
        params = [code]
        if start:
            sql += "AND date >= ? "; params.append(start)
        if end:
            sql += "AND date <= ? "; params.append(end)
        sql += "ORDER BY date ASC"
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def kline_get_dataframe(code: str, start: str = None, end: str = None):
    """Return K-line data as a pandas DataFrame (close prices)."""
    import pandas as pd
    rows = kline_get(code, start, end)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    return df[["open", "high", "low", "close", "volume"]]


def kline_all_codes() -> list[str]:
    """Return all distinct ETF codes in the K-line table."""
    with get_conn() as conn:
        return [r["code"] for r in conn.execute(
            "SELECT DISTINCT code FROM kline_daily ORDER BY code").fetchall()]


# ═══════════════════════════════════════════════════════════════
# Strategy Metrics CRUD
# ═══════════════════════════════════════════════════════════════

def metrics_upsert(strategy_id: str, name: str, category: str, category_cn: str,
                   annual_return: float | None, sharpe: float | None,
                   max_drawdown: float | None, calmar: float | None,
                   win_rate: float | None, turnover: float | None,
                   excess_return: float | None,
                   assets: list[str], description: str, backtest_window: str):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO strategy_metrics
            (strategy_id, name, category, category_cn, annual_return, sharpe,
             max_drawdown, calmar, win_rate, turnover, excess_return,
             assets_json, description, backtest_window, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, datetime('now','localtime'))
        """, (strategy_id, name, category, category_cn, annual_return, sharpe,
              max_drawdown, calmar, win_rate, turnover, excess_return,
              json.dumps(assets, ensure_ascii=False), description, backtest_window))


def metrics_get_all(sort_by: str = "strategy_id", order: str = "asc") -> list[dict]:
    """Return all strategy metrics as list of dicts, with computed display fields."""
    valid_cols = {"strategy_id", "annual_return", "sharpe", "max_drawdown", "calmar"}
    col = sort_by if sort_by in valid_cols else "strategy_id"
    direction = "ASC" if order == "asc" else "DESC"
    # Natural sort for strategy_id (S1, S2, ..., S10, ...)
    if col == "strategy_id":
        order_clause = f"CAST(substr(strategy_id, 2) AS INTEGER) {direction}"
    else:
        nulls = "NULLS LAST"
        order_clause = f"{col} {direction} {nulls}"

    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT * FROM strategy_metrics ORDER BY {order_clause}
        """).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        d["id"] = d.pop("strategy_id")
        assets_raw = d.pop("assets_json", "[]")
        try:
            d["assets"] = json.loads(assets_raw)
        except (json.JSONDecodeError, TypeError):
            d["assets"] = []

        # Display-friendly fields
        d["ann_val"] = d.get("annual_return")
        d["dd_val"] = d.get("max_drawdown")
        d["desc"] = d.get("description", "")

        # Format strings for frontend
        for key in ("annual_return", "max_drawdown"):
            v = d.get(key)
            d[key] = f"{v:.2f}%" if v is not None else "—"
        d["sharpe"] = round(d["sharpe"], 2) if d.get("sharpe") is not None else None
        d["calmar"] = round(d["calmar"], 2) if d.get("calmar") is not None else None
        d["win_rate"] = f"{d['win_rate']:.1f}%" if d.get("win_rate") is not None else "—"
        d["turnover"] = round(d["turnover"], 1) if d.get("turnover") is not None else None
        d["excess_return"] = f"{d['excess_return']:+.2f}%" if d.get("excess_return") is not None else "—"
        d["backtest_window"] = d.get("backtest_window") or "待回测"

        result.append(d)
    return result


def metrics_get_one(strategy_id: str) -> dict | None:
    """Get a single strategy's metrics."""
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM strategy_metrics WHERE strategy_id=?", (strategy_id,)
        ).fetchone()
        if not r:
            return None
        d = dict(r)
        d["id"] = d.pop("strategy_id")
        d["assets"] = json.loads(d.get("assets_json", "[]"))
        d["ann_val"] = d.get("annual_return")
        d["dd_val"] = d.get("max_drawdown")
        d["desc"] = d.get("description", "")
        return d


# ═══════════════════════════════════════════════════════════════
# Daily Signals CRUD
# ═══════════════════════════════════════════════════════════════

def signals_upsert(strategy_id: str, signal_date: str, asset_code: str,
                   asset_name: str, target_weight: float, prev_weight: float,
                   action: str):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO daily_signals
            (strategy_id, signal_date, asset_code, asset_name,
             target_weight, prev_weight, weight_change, action, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
        """, (strategy_id, signal_date, asset_code, asset_name,
              target_weight, prev_weight, target_weight - prev_weight, action))


def signals_get_latest(strategy_id: str) -> list[dict] | None:
    """Get latest signal for a strategy. Returns list of asset entries."""
    with get_conn() as conn:
        # Find latest signal_date for this strategy
        date_row = conn.execute(
            "SELECT MAX(signal_date) as d FROM daily_signals WHERE strategy_id=?",
            (strategy_id,)
        ).fetchone()
        if not date_row or not date_row["d"]:
            return None

        rows = conn.execute(
            "SELECT * FROM daily_signals WHERE strategy_id=? AND signal_date=?",
            (strategy_id, date_row["d"])
        ).fetchall()
        return [dict(r) for r in rows]


def signals_delete_old(days: int = 30):
    """Delete signals older than `days` to keep the table lean."""
    cutoff = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        conn.execute("DELETE FROM daily_signals WHERE signal_date < ?", (cutoff,))


# ═══════════════════════════════════════════════════════════════
# Strategy KB CRUD
# ═══════════════════════════════════════════════════════════════

def kb_upsert(strategy_id: str, name: str, class_name: str, category: str,
              intro: str, stock_selection: str, market_timing: str,
              factors: str, rebalance: str, strengths: str, weaknesses: str,
              backtest_params: dict, source_url: str = "",
              process_desc: str = ""):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO strategy_kb
            (strategy_id, name, class_name, category, intro, stock_selection,
             market_timing, factors, rebalance, strengths, weaknesses,
             source_url, process_desc, backtest_params, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, datetime('now','localtime'))
        """, (strategy_id, name, class_name, category, intro, stock_selection,
              market_timing, factors, rebalance, strengths, weaknesses,
              source_url, process_desc,
              json.dumps(backtest_params, ensure_ascii=False)))


def kb_get(strategy_id: str) -> dict | None:
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM strategy_kb WHERE strategy_id=?", (strategy_id,)
        ).fetchone()
        if not r:
            return None
        d = dict(r)
        d["id"] = d.pop("strategy_id")
        d["source_url"] = d.get("source_url", "") or ""
        d["process_desc"] = d.get("process_desc", "") or ""
        bp = d.pop("backtest_params", "{}")
        try:
            d["backtest"] = json.loads(bp)
        except (json.JSONDecodeError, TypeError):
            d["backtest"] = {}
        return d


# ═══════════════════════════════════════════════════════════════
# Backtest NAV CRUD
# ═══════════════════════════════════════════════════════════════

def nav_upsert_batch(rows: list[tuple]):
    """Batch insert NAV rows. rows: [(strategy_name, date, nav, drawdown), ...]"""
    with get_conn() as conn:
        conn.executemany("""
            INSERT OR REPLACE INTO backtest_nav (strategy_name, date, nav, drawdown)
            VALUES (?, ?, ?, ?)
        """, rows)


def nav_get_all(strategy_names: list[str] | None = None) -> dict:
    """Return NAV data in {dates: [...], series: {name: [nav, ...]}, drawdowns: {name: [dd, ...]}} format."""
    with get_conn() as conn:
        if strategy_names:
            placeholders = ",".join("?" * len(strategy_names))
            rows = conn.execute(
                f"SELECT * FROM backtest_nav WHERE strategy_name IN ({placeholders}) ORDER BY date",
                strategy_names
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM backtest_nav ORDER BY date"
            ).fetchall()

    if not rows:
        return {"dates": [], "series": {}, "drawdowns": {}}

    # Pivot: build {strategy_name: {date: nav}}
    dates_set = {}
    series = {}
    drawdowns = {}
    for r in rows:
        name = r["strategy_name"]
        d = r["date"]
        if d not in dates_set:
            dates_set[d] = True
        series.setdefault(name, []).append(r["nav"])
        drawdowns.setdefault(name, []).append(r["drawdown"] or 0.0)

    dates = sorted(dates_set.keys())

    # Ensure all series have the same length as dates (pad with null for gaps).
    # This is critical when different strategies have NAV data for different
    # date ranges (e.g., after running a single-strategy backtest).
    for name in list(series.keys()):
        name_dates = set()
        # Build a date→nav lookup for this series
        lookup = {}
        for r in rows:
            if r["strategy_name"] == name:
                lookup[r["date"]] = (r["nav"], r["drawdown"] or 0.0)
        # Pad to full date axis
        padded_nav = []
        padded_dd = []
        for d in dates:
            if d in lookup:
                padded_nav.append(lookup[d][0])
                padded_dd.append(lookup[d][1])
            else:
                padded_nav.append(None)
                padded_dd.append(None)
        series[name] = padded_nav
        drawdowns[name] = padded_dd

    return {"dates": dates, "series": series, "drawdowns": drawdowns}


def nav_has_data() -> bool:
    with get_conn() as conn:
        r = conn.execute("SELECT 1 FROM backtest_nav LIMIT 1").fetchone()
        return r is not None


# ═══════════════════════════════════════════════════════════════
# Users CRUD
# ═══════════════════════════════════════════════════════════════

def user_get_by_username(username: str) -> dict | None:
    """Lookup a user by username. Returns dict with keys: id, username,
    password_hash, display_name, role, is_active, created_at, last_login."""
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()
        return dict(r) if r else None


def user_create(username: str, password_hash: str, display_name: str = "",
                role: str = "admin"):
    """Create a new user. Raises ValueError on duplicate username."""
    import sqlite3
    with get_conn() as conn:
        try:
            conn.execute("""
                INSERT INTO users (username, password_hash, display_name, role)
                VALUES (?, ?, ?, ?)
            """, (username, password_hash, display_name, role))
        except sqlite3.IntegrityError:
            raise ValueError(f"User '{username}' already exists")


def user_update_last_login(username: str):
    """Stamp last_login for a user."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET last_login=datetime('now','localtime') WHERE username=?",
            (username,)
        )


def user_change_password(username: str, new_hash: str):
    """Change a user's password hash."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET password_hash=? WHERE username=?",
            (new_hash, username)
        )


def user_list_all() -> list[dict]:
    """Return all users (without password hashes)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, username, display_name, role, is_active, created_at, last_login FROM users ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def user_count() -> int:
    """Return total number of users."""
    with get_conn() as conn:
        r = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()
        return r["c"] if r else 0


# ═══════════════════════════════════════════════════════════════
# Portfolio Holdings CRUD (每日复盘持仓)
# ═══════════════════════════════════════════════════════════════

def portfolio_holdings_replace(rows: list[dict]):
    """Replace all holdings (snapshot semantics — DELETE all then INSERT).

    rows: [{code, name, shares, cost_price}, ...]
    """
    with get_conn() as conn:
        conn.execute("DELETE FROM portfolio_holdings")
        conn.executemany("""
            INSERT OR REPLACE INTO portfolio_holdings (code, name, shares, cost_price, updated_at)
            VALUES (?, ?, ?, ?, datetime('now','localtime'))
        """, [(r.get("code"), r.get("name"), r.get("shares"), r.get("cost_price")) for r in rows])


def portfolio_holdings_get_all() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM portfolio_holdings ORDER BY code"
        ).fetchall()
        return [dict(r) for r in rows]


def portfolio_holdings_count() -> int:
    with get_conn() as conn:
        r = conn.execute("SELECT COUNT(*) as c FROM portfolio_holdings").fetchone()
        return r["c"] if r else 0


# ═══════════════════════════════════════════════════════════════
# Portfolio Trades CRUD (调仓记录)
# ═══════════════════════════════════════════════════════════════

def portfolio_trades_replace_all(rows: list[dict]):
    """Replace all trades (import from 每日调仓.md). rows: [{trade_date, name, code, quantity, price, side, remark}]"""
    with get_conn() as conn:
        conn.execute("DELETE FROM portfolio_trades")
        conn.executemany("""
            INSERT INTO portfolio_trades (trade_date, name, code, quantity, price, side, remark, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
        """, [(r.get("trade_date"), r.get("name"), r.get("code"),
               r.get("quantity"), r.get("price"), r.get("side"), r.get("remark")) for r in rows])


def portfolio_trades_get_all() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM portfolio_trades ORDER BY trade_date DESC, id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════
# Portfolio Meta CRUD (组合级 KV)
# ═══════════════════════════════════════════════════════════════

def meta_get(key: str, default=None):
    with get_conn() as conn:
        r = conn.execute("SELECT value FROM portfolio_meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r and r["value"] is not None else default


def meta_set(key: str, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO portfolio_meta(key, value) VALUES(?, ?)",
            (key, value),
        )


def meta_get_prefix(prefix: str) -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT key, value FROM portfolio_meta WHERE key LIKE ?", (prefix + "%",)
        ).fetchall()
        return {r["key"]: r["value"] for r in rows}


# ═══════════════════════════════════════════════════════════════
# Daily Reports CRUD (每日复盘报告/信号)
# ═══════════════════════════════════════════════════════════════

def report_upsert(report_date: str, report_type: str, markdown: str,
                  source_file: str = "", status: str = "ready"):
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO daily_reports
            (report_date, report_type, markdown, status, generated_at, source_file)
            VALUES (?, ?, ?, ?, datetime('now','localtime'), ?)
        """, (report_date, report_type, markdown, status, source_file))


def report_get(report_date: str, report_type: str) -> dict | None:
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM daily_reports WHERE report_date=? AND report_type=?",
            (report_date, report_type),
        ).fetchone()
        return dict(r) if r else None


def report_list(limit: int = 50, report_type: str | None = None) -> list[dict]:
    """Return report metadata (no markdown) sorted by date desc."""
    sql = "SELECT id, report_date, report_type, status, generated_at, source_file FROM daily_reports"
    params: list = []
    if report_type:
        sql += " WHERE report_type=?"
        params.append(report_type)
    sql += " ORDER BY report_date DESC, report_type"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def report_get_dates() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT report_date FROM daily_reports ORDER BY report_date DESC"
        ).fetchall()
        return [r["report_date"] for r in rows]


def report_types_for_date(report_date: str) -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT report_type FROM daily_reports WHERE report_date=? ORDER BY report_type",
            (report_date,),
        ).fetchall()
        return [r["report_type"] for r in rows]


# ═══════════════════════════════════════════════════════════════
# Scheduler Runs CRUD (定时任务运行日志 + 幂等)
# ═══════════════════════════════════════════════════════════════

def scheduler_run_insert(task_id: str, window_key: str, trigger: str,
                         run_time: str, status: str = "running") -> int:
    with get_conn() as conn:
        cur = conn.execute("""
            INSERT INTO scheduler_runs (task_id, window_key, trigger, run_time, status)
            VALUES (?, ?, ?, ?, ?)
        """, (task_id, window_key, trigger, run_time, status))
        return cur.lastrowid


def scheduler_run_update(run_id: int, **fields):
    """Update a scheduler run row. fields: status/pid/duration_sec/output/completed_at/window_key"""
    allowed = {"status", "pid", "duration_sec", "output", "completed_at", "window_key", "run_time", "trigger", "task_id"}
    sets = [k for k in fields if k in allowed]
    if not sets:
        return
    assignments = ", ".join(f"{k}=?" for k in sets)
    params = [fields[k] for k in sets] + [run_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE scheduler_runs SET {assignments} WHERE id=?", params)


def scheduler_runs_list(task_id: str | None = None, limit: int = 50) -> list[dict]:
    sql = "SELECT * FROM scheduler_runs"
    params: list = []
    if task_id:
        sql += " WHERE task_id=?"
        params.append(task_id)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def scheduler_run_get(run_id: int) -> dict | None:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM scheduler_runs WHERE id=?", (run_id,)).fetchone()
        return dict(r) if r else None


def scheduler_window_done(task_id: str, window_key: str) -> bool:
    """Return True if a non-failed run already exists for (task_id, window_key)."""
    with get_conn() as conn:
        r = conn.execute(
            "SELECT 1 FROM scheduler_runs WHERE task_id=? AND window_key=? AND status IN ('success','timeout') LIMIT 1",
            (task_id, window_key),
        ).fetchone()
        return r is not None


def scheduler_latest(task_id: str) -> dict | None:
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM scheduler_runs WHERE task_id=? ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        return dict(r) if r else None


def scheduler_running_tasks() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT task_id FROM scheduler_runs WHERE status='running'"
        ).fetchall()
        return [r["task_id"] for r in rows]
