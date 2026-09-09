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
from pathlib import Path
from datetime import date, datetime, timedelta
from contextlib import contextmanager

DB_PATH = Path(__file__).resolve().parent / "data" / "cache.db"

# ── 云端权威数据库后端（DASHBOARD_DB_BACKEND=cloud 时启用）：
#    权威表（users/portfolio/daily_reports/scheduler_runs/metadata/strategy_kb/
#    strategy_metrics/daily_signals）直接读写火山 Supabase Postgres（PostgREST），
#    跨机器一致；kline_daily / backtest_nav（可重建缓存）仍走本地 SQLite。
#    2026-09-07 移除 DB_MODE=memory（TOS 快照互覆机制），仅保留 file/cloud 两后端。
USE_CLOUD = os.environ.get("DASHBOARD_DB_BACKEND", "").lower() == "cloud"

# cloud_db helpers（总是导入，测试可动态把 USE_CLOUD 置 True）
try:
    from cloud_db import (delete as _cd_delete, insert as _cd_insert,
                          select as _cd_select, select_one as _cd_select_one,
                          update as _cd_update, upsert as _cd_upsert)
except ImportError:  # pragma: no cover
    _cd_delete = _cd_insert = _cd_select = None
    _cd_select_one = _cd_update = _cd_upsert = None


def _now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _cd_json_fields(row):
    """云行 JSONB 字段已是对象，无需转换；此函数保留以兼容形状。"""
    return row


# ── Connection management ──
@contextmanager
def get_conn():
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

# cloud 模式本地仅保留"可重建缓存"表（kline_daily / backtest_nav），
# 权威表全部在云 Postgres（见 scripts/cloud_schema*.sql）。
_CACHE_SCHEMA = """
CREATE TABLE IF NOT EXISTS kline_daily (
    code        TEXT NOT NULL,
    date        TEXT NOT NULL,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL NOT NULL,
    volume      REAL,
    updated_at  TEXT DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (code, date)
);
CREATE TABLE IF NOT EXISTS backtest_nav (
    strategy_name TEXT NOT NULL,
    date          TEXT NOT NULL,
    nav           REAL,
    drawdown      REAL,
    PRIMARY KEY (strategy_name, date)
);
"""

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
--   backtest_window  回测数据窗口 (如"2012-05-28~2026-08-31 (约14年)")
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

    cloud 模式：云表已由 schema 建好；本地仅保留 kline/nav 缓存表。
    file 模式：本地 SQLite 全量 schema。
    """
    if USE_CLOUD:
        with get_conn() as conn:
            conn.executescript(_CACHE_SCHEMA)
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
    if USE_CLOUD:
        row = _cd_select_one("portfolio_meta", filters=[("key", "eq", "seeded")])
        return row is not None and row.get("value") == "1"
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM metadata WHERE key='seeded'").fetchone()
        return row is not None and row["value"] == "1"


def mark_seeded():
    if USE_CLOUD:
        _cd_upsert("portfolio_meta", {"key": "seeded", "value": "1"}, on_conflict="key")
        return
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
    if USE_CLOUD:
        row = {
            "strategy_id": strategy_id, "name": name, "category": category,
            "category_cn": category_cn, "annual_return": annual_return,
            "sharpe": sharpe, "max_drawdown": max_drawdown, "calmar": calmar,
            "win_rate": win_rate, "turnover": turnover,
            "excess_return": excess_return, "assets_json": assets,
            "description": description, "backtest_window": backtest_window,
        }
        _cd_upsert("strategy_metrics", row, on_conflict="strategy_id")
        return
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
    if USE_CLOUD:
        # PostgREST 无 CAST(substr) 自然序；云上 strategy_id 已是 S1..S16 递增，
        # 用数字排序需 RPC，这里退化为字母序（S1..S16 前缀 S 相同，数字位排序正确）
        order_clause = f"{col}.{direction.lower()}"
        if col == "strategy_id":
            order_clause = "strategy_id.asc"
        rows = _cd_select("strategy_metrics", order=order_clause)
    else:
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
            d["assets"] = json.loads(assets_raw) if isinstance(assets_raw, str) else assets_raw
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
    if USE_CLOUD:
        r = _cd_select_one("strategy_metrics",
                           filters=[("strategy_id", "eq", strategy_id)])
        if not r:
            return None
        d = dict(r)
        d["id"] = d.pop("strategy_id")
        d["assets"] = json.loads(d.get("assets_json", "[]")) if isinstance(d.get("assets_json"), str) else (d.get("assets_json") or [])
        d["ann_val"] = d.get("annual_return")
        d["dd_val"] = d.get("max_drawdown")
        d["desc"] = d.get("description", "")
        return d
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
    if USE_CLOUD:
        # BUG-FIX(2026-09-07)：改用 on_conflict upsert（唯一约束 uq_daily_signals_strat_date_asset）
        # 取代 select-then-insert —— 后者在双进程并发写同一信号时会产生重复行。
        _cd_upsert("daily_signals", {
            "strategy_id": strategy_id, "signal_date": signal_date,
            "asset_code": asset_code, "asset_name": asset_name,
            "target_weight": target_weight, "prev_weight": prev_weight,
            "weight_change": target_weight - prev_weight, "action": action,
            "updated_at": _now_str(),
        }, on_conflict="strategy_id,signal_date,asset_code")
        return
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO daily_signals
            (strategy_id, signal_date, asset_code, asset_name,
             target_weight, prev_weight, weight_change, action, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
        """, (strategy_id, signal_date, asset_code, asset_name,
              target_weight, prev_weight, target_weight - prev_weight, action))


def signals_delete_by_strategy(strategy_id: str):
    """删除某策略的全部信号（刷新信号前的清空步骤）。云模式走云删除。"""
    if USE_CLOUD:
        _cd_delete("daily_signals", filters=[("strategy_id", "eq", strategy_id)])
        return
    with get_conn() as conn:
        conn.execute("DELETE FROM daily_signals WHERE strategy_id=?", (strategy_id,))


def signals_get_latest(strategy_id: str) -> list[dict] | None:
    """Get latest signal for a strategy. Returns list of asset entries."""
    if USE_CLOUD:
        rows = _cd_select("daily_signals", filters=[("strategy_id", "eq", strategy_id)],
                          order="signal_date.desc,id.desc", limit=1)
        if not rows:
            return None
        latest_date = rows[0]["signal_date"]
        return _cd_select("daily_signals",
                          filters=[("strategy_id", "eq", strategy_id),
                                   ("signal_date", "eq", latest_date)],
                          order="id.asc")
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
    if USE_CLOUD:
        _cd_delete("daily_signals", filters=[("signal_date", "lt", cutoff)])
        return
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
    if USE_CLOUD:
        row = {
            "strategy_id": strategy_id, "name": name, "class_name": class_name,
            "category": category, "intro": intro, "stock_selection": stock_selection,
            "market_timing": market_timing, "factors": factors,
            "rebalance": rebalance, "strengths": strengths, "weaknesses": weaknesses,
            "backtest_params": backtest_params, "source_url": source_url,
            "process_desc": process_desc,
        }
        _cd_upsert("strategy_kb", row, on_conflict="strategy_id")
        return
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
    if USE_CLOUD:
        r = _cd_select_one("strategy_kb", filters=[("strategy_id", "eq", strategy_id)])
        if not r:
            return None
        d = dict(r)
        d["id"] = d.pop("strategy_id")
        d["source_url"] = d.get("source_url", "") or ""
        d["process_desc"] = d.get("process_desc", "") or ""
        bp = d.pop("backtest_params", {})
        if isinstance(bp, str):
            try:
                d["backtest"] = json.loads(bp)
            except (json.JSONDecodeError, TypeError):
                d["backtest"] = {}
        else:
            d["backtest"] = bp or {}
        return d
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
    if USE_CLOUD:
        return _cd_select_one("users", filters=[("username", "eq", username)])
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()
        return dict(r) if r else None


def user_create(username: str, password_hash: str, display_name: str = "",
                role: str = "admin"):
    """Create a new user. Raises ValueError on duplicate username."""
    if USE_CLOUD:
        exists = _cd_select_one("users", filters=[("username", "eq", username)],
                                columns="id")
        if exists:
            raise ValueError(f"User '{username}' already exists")
        _cd_insert("users", {
            "username": username, "password_hash": password_hash,
            "display_name": display_name, "role": role, "is_active": True,
        })
        return
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
    if USE_CLOUD:
        _cd_update("users", {"last_login": _now_str()},
                   filters=[("username", "eq", username)])
        return
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET last_login=datetime('now','localtime') WHERE username=?",
            (username,)
        )


def user_change_password(username: str, new_hash: str):
    """Change a user's password hash."""
    if USE_CLOUD:
        _cd_update("users", {"password_hash": new_hash},
                   filters=[("username", "eq", username)])
        return
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET password_hash=? WHERE username=?",
            (new_hash, username)
        )


def user_list_all() -> list[dict]:
    """Return all users (without password hashes)."""
    if USE_CLOUD:
        return _cd_select("users", columns="id,username,display_name,role,is_active,created_at,last_login",
                          order="id.asc")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, username, display_name, role, is_active, created_at, last_login FROM users ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]


def user_count() -> int:
    """Return total number of users."""
    if USE_CLOUD:
        rows = _cd_select("users", columns="id")
        return len(rows)
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
    if USE_CLOUD:
        _cd_delete("portfolio_holdings", filters=[("id", "gt", 0)])
        for r in rows:
            _cd_insert("portfolio_holdings", {
                "code": r.get("code"), "name": r.get("name"),
                "shares": r.get("shares"), "cost_price": r.get("cost_price"),
                "updated_at": _now_str(),
            })
        return
    with get_conn() as conn:
        conn.execute("DELETE FROM portfolio_holdings")
        conn.executemany("""
            INSERT OR REPLACE INTO portfolio_holdings (code, name, shares, cost_price, updated_at)
            VALUES (?, ?, ?, ?, datetime('now','localtime'))
        """, [(r.get("code"), r.get("name"), r.get("shares"), r.get("cost_price")) for r in rows])


def portfolio_holdings_get_all() -> list[dict]:
    if USE_CLOUD:
        return _cd_select("portfolio_holdings", order="code.asc")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM portfolio_holdings ORDER BY code"
        ).fetchall()
        return [dict(r) for r in rows]


def portfolio_holdings_count() -> int:
    if USE_CLOUD:
        return len(_cd_select("portfolio_holdings", columns="id"))
    with get_conn() as conn:
        r = conn.execute("SELECT COUNT(*) as c FROM portfolio_holdings").fetchone()
        return r["c"] if r else 0


# ═══════════════════════════════════════════════════════════════
# Portfolio Trades CRUD (调仓记录)
# ═══════════════════════════════════════════════════════════════

def portfolio_trades_replace_all(rows: list[dict]):
    """Replace all trades (import from 每日调仓.md). rows: [{trade_date, name, code, quantity, price, side, remark}]"""
    if USE_CLOUD:
        _cd_delete("portfolio_trades", filters=[("id", "gt", 0)])
        for r in rows:
            _cd_insert("portfolio_trades", {
                "trade_date": r.get("trade_date"), "name": r.get("name"),
                "code": r.get("code"), "quantity": r.get("quantity"),
                "price": r.get("price"), "side": r.get("side"),
                "remark": r.get("remark"), "created_at": _now_str(),
            })
        return
    with get_conn() as conn:
        conn.execute("DELETE FROM portfolio_trades")
        conn.executemany("""
            INSERT INTO portfolio_trades (trade_date, name, code, quantity, price, side, remark, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
        """, [(r.get("trade_date"), r.get("name"), r.get("code"),
               r.get("quantity"), r.get("price"), r.get("side"), r.get("remark")) for r in rows])


def portfolio_trades_get_all() -> list[dict]:
    if USE_CLOUD:
        return _cd_select("portfolio_trades", order="trade_date.desc,id.desc")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM portfolio_trades ORDER BY trade_date DESC, id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════
# Portfolio Meta CRUD (组合级 KV)
# ═══════════════════════════════════════════════════════════════

def meta_get(key: str, default=None):
    if USE_CLOUD:
        row = _cd_select_one("portfolio_meta", filters=[("key", "eq", key)])
        return row["value"] if row and row.get("value") is not None else default
    with get_conn() as conn:
        r = conn.execute("SELECT value FROM portfolio_meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r and r["value"] is not None else default


def meta_set(key: str, value):
    if USE_CLOUD:
        _cd_upsert("portfolio_meta", {"key": key, "value": value}, on_conflict="key")
        return
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO portfolio_meta(key, value) VALUES(?, ?)",
            (key, value),
        )


def meta_get_prefix(prefix: str) -> dict:
    if USE_CLOUD:
        rows = _cd_select("portfolio_meta", filters=[("key", "like", prefix + "%")])
        return {r["key"]: r["value"] for r in rows}
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT key, value FROM portfolio_meta WHERE key LIKE ?", (prefix + "%",)
        ).fetchall()
        return {r["key"]: r["value"] for r in rows}


def meta_get_all() -> dict:
    """一次取回全部 portfolio_meta（云模式 1 次往返；表极小，行数通常 <20）。

    2026-09-08 性能优化：GET /api/portfolio 原先对每个 key 单独 meta_get
    （云模式 = N 次 HTTPS 往返，实测单次 ~0.08-0.8s），改批量后降为 1 次。
    """
    if USE_CLOUD:
        rows = _cd_select("portfolio_meta", columns="key,value")
        return {r["key"]: r["value"] for r in rows if r.get("value") is not None}
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM portfolio_meta").fetchall()
        return {r["key"]: r["value"] for r in rows if r["value"] is not None}


# ═══════════════════════════════════════════════════════════════
# Daily Reports CRUD (每日复盘报告/信号)
# ═══════════════════════════════════════════════════════════════

def report_upsert(report_date: str, report_type: str, markdown: str,
                  source_file: str = "", status: str = "ready"):
    if USE_CLOUD:
        # BUG-FIX(2026-09-07)：改用 on_conflict upsert（唯一约束 uq_daily_reports_date_type）
        # 取代 select-then-insert —— 后者在双进程并发写同一报告时会产生重复行。
        _cd_upsert("daily_reports", {
            "report_date": report_date, "report_type": report_type,
            "markdown": markdown, "status": status,
            "generated_at": _now_str(), "source_file": source_file,
        }, on_conflict="report_date,report_type")
        return
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO daily_reports
            (report_date, report_type, markdown, status, generated_at, source_file)
            VALUES (?, ?, ?, ?, datetime('now','localtime'), ?)
        """, (report_date, report_type, markdown, status, source_file))


def report_get(report_date: str, report_type: str) -> dict | None:
    if USE_CLOUD:
        return _cd_select_one("daily_reports",
                              filters=[("report_date", "eq", report_date),
                                       ("report_type", "eq", report_type)])
    with get_conn() as conn:
        r = conn.execute(
            "SELECT * FROM daily_reports WHERE report_date=? AND report_type=?",
            (report_date, report_type),
        ).fetchone()
        return dict(r) if r else None


def report_list(limit: int = 50, report_type: str | None = None) -> list[dict]:
    """Return report metadata (no markdown) sorted by date desc."""
    if USE_CLOUD:
        filters = [("report_type", "eq", report_type)] if report_type else None
        return _cd_select("daily_reports",
                          columns="id,report_date,report_type,status,generated_at,source_file",
                          filters=filters, order="report_date.desc,report_type.asc",
                          limit=limit)
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
    if USE_CLOUD:
        rows = _cd_select("daily_reports", columns="report_date",
                          order="report_date.desc")
        seen = []
        for r in rows:
            if r["report_date"] not in seen:
                seen.append(r["report_date"])
        return seen
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT report_date FROM daily_reports ORDER BY report_date DESC"
        ).fetchall()
        return [r["report_date"] for r in rows]


def report_types_for_date(report_date: str) -> list[str]:
    if USE_CLOUD:
        rows = _cd_select("daily_reports", columns="report_type",
                          filters=[("report_date", "eq", report_date)],
                          order="report_type.asc")
        return [r["report_type"] for r in rows]
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT report_type FROM daily_reports WHERE report_date=? ORDER BY report_type",
            (report_date,),
        ).fetchall()
        return [r["report_type"] for r in rows]


def report_dates_with_types() -> dict[str, list[str]]:
    """一次取回 日期 → 报告类型列表 的映射（日期倒序）。

    2026-09-08 性能优化：GET /api/daily-signals 找"最近含每日信号的日期"时，
    原先 report_get_dates() + 逐日 report_types_for_date() = N+1 次云往返
    （每天 0.08-0.8s，历史 60+ 天 → 数秒~数十秒）→ 改单次查询 + Python 聚合。
    """
    if USE_CLOUD:
        rows = _cd_select("daily_reports", columns="report_date,report_type",
                          order="report_date.desc,report_type.asc")
    else:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT report_date, report_type FROM daily_reports "
                "ORDER BY report_date DESC, report_type"
            ).fetchall()
            rows = [dict(r) for r in rows]
    out: dict[str, list[str]] = {}
    for r in rows:
        d = r["report_date"]
        t = r["report_type"]
        if d not in out:
            out[d] = []
        if t not in out[d]:
            out[d].append(t)
    return out


# ═══════════════════════════════════════════════════════════════
# Scheduler Runs CRUD (定时任务运行日志 + 幂等)
# ═══════════════════════════════════════════════════════════════

def scheduler_run_insert(task_id: str, window_key: str, trigger: str,
                         run_time: str, status: str = "running") -> int:
    if USE_CLOUD:
        row = _cd_insert("scheduler_runs", {
            "task_id": task_id, "window_key": window_key, "trigger": trigger,
            "run_time": run_time, "status": status,
        })
        return row["id"] if row else 0
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
    if USE_CLOUD:
        patch = {k: fields[k] for k in sets}
        _cd_update("scheduler_runs", patch, filters=[("id", "eq", run_id)])
        return
    assignments = ", ".join(f"{k}=?" for k in sets)
    params = [fields[k] for k in sets] + [run_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE scheduler_runs SET {assignments} WHERE id=?", params)


def scheduler_runs_list(task_id: str | None = None, limit: int = 50) -> list[dict]:
    if USE_CLOUD:
        # BUG-FIX(2026-09-07)：列表只取轻量元数据列，不拉完整 output（可能几千字符，
        # 每刷一次后台页下载 15+ 份 → 慢）。完整 output 由 /scheduler/runs/{id}/log 按需返回。
        cols = "id,task_id,trigger,status,window_key,run_time,duration_sec,completed_at"
        filters = [("task_id", "eq", task_id)] if task_id else None
        return _cd_select("scheduler_runs", columns=cols, filters=filters,
                          order="id.desc", limit=limit)
    sql = "SELECT id,task_id,trigger,status,window_key,run_time,duration_sec,completed_at FROM scheduler_runs"
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
    if USE_CLOUD:
        return _cd_select_one("scheduler_runs", filters=[("id", "eq", run_id)])
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM scheduler_runs WHERE id=?", (run_id,)).fetchone()
        return dict(r) if r else None


def scheduler_window_done(task_id: str, window_key: str,
                          max_failures: int | None = None) -> bool:
    """Return True if the window is considered consumed for (task_id, window_key).

    语义：
    - success/timeout 存在 → 已完成（True）
    - failed 累计达 max_failures（默认 None=不启用失败限次）→ 已消耗（True），
      阻止同一窗口内无限制重试（2026-08-31 重试风暴修复）
    - 否则 False（可重试）
    """
    if USE_CLOUD:
        done = _cd_select_one(
            "scheduler_runs", columns="id",
            filters=[("task_id", "eq", task_id), ("window_key", "eq", window_key),
                     ("status", "in", "(success,timeout)")],
        )
        if done:
            return True
        if max_failures is not None:
            failed = _cd_select(
                "scheduler_runs", columns="id",
                filters=[("task_id", "eq", task_id), ("window_key", "eq", window_key),
                         ("status", "eq", "failed")],
            )
            if len(failed) >= max_failures:
                return True
        return False
    with get_conn() as conn:
        r = conn.execute(
            "SELECT 1 FROM scheduler_runs WHERE task_id=? AND window_key=? AND status IN ('success','timeout') LIMIT 1",
            (task_id, window_key),
        ).fetchone()
        if r is not None:
            return True
        if max_failures is not None:
            c = conn.execute(
                "SELECT COUNT(*) AS c FROM scheduler_runs "
                "WHERE task_id=? AND window_key=? AND status='failed'",
                (task_id, window_key),
            ).fetchone()
            if c and c["c"] >= max_failures:
                return True
        return False


def scheduler_latest(task_id: str) -> dict | None:
    if USE_CLOUD:
        # BUG-FIX(2026-09-07)：latest 供任务表"最近运行"状态展示，同样不拉 output。
        cols = "id,task_id,trigger,status,window_key,run_time,duration_sec,completed_at"
        return _cd_select_one("scheduler_runs", columns=cols,
                              filters=[("task_id", "eq", task_id)], order="id.desc")
    with get_conn() as conn:
        r = conn.execute(
            "SELECT id,task_id,trigger,status,window_key,run_time,duration_sec,completed_at "
            "FROM scheduler_runs WHERE task_id=? ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        return dict(r) if r else None


def scheduler_latest_map(task_ids: list[str]) -> dict[str, dict]:
    """批量取多个任务各自的最近一次运行（每组 task_id 取 id 最大一条）。

    BUG-FIX(2026-09-07)：任务表端点原对每个 task_id 单独查一次云（N+1，~19 次
    往返拖慢后台页）。改为一次查询：拉最近 N 条元数据（id desc 最新在前），
    每个 task_id 保留第一条即其最近运行。N 取 task 数 * 每任务可能运行数，
    兜底取 500（scheduler_runs 行数量级小，够用且只取元数据列）。
    """
    if not task_ids:
        return {}
    if USE_CLOUD:
        cols = "id,task_id,trigger,status,window_key,run_time,duration_sec,completed_at"
        rows = _cd_select("scheduler_runs", columns=cols, order="id.desc", limit=500)
    else:
        qmarks = ",".join("?" for _ in task_ids)
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id,task_id,trigger,status,window_key,run_time,duration_sec,completed_at "
                f"FROM scheduler_runs WHERE task_id IN ({qmarks}) ORDER BY id DESC LIMIT 500",
                task_ids,
            ).fetchall()
            rows = [dict(r) for r in rows]
    result: dict[str, dict] = {}
    for r in rows:  # id desc → 每个 task_id 第一次出现即最新
        tid = r.get("task_id")
        if tid in task_ids and tid not in result:
            result[tid] = r
    return result


def scheduler_running_tasks() -> list[str]:
    if USE_CLOUD:
        rows = _cd_select("scheduler_runs", columns="task_id",
                          filters=[("status", "eq", "running")])
        seen = []
        for r in rows:
            if r["task_id"] not in seen:
                seen.append(r["task_id"])
        return seen
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT task_id FROM scheduler_runs WHERE status='running'"
        ).fetchall()
        return [r["task_id"] for r in rows]


def scheduler_mark_zombies_running() -> int:
    """把遗留的 running 记录标记为 failed（进程重启中断）。

    引擎/进程重启后，_run_prompt 的后台线程随旧进程被杀，DB 里的 running
    记录永远收不到终态（success/failed/timeout）——成为僵尸记录，UI 会一直
    显示"运行中"。start() 时调用本函数统一回收。

    返回被清理的记录数。
    """
    note = "\n\n[interrupted] 进程重启，任务被中断（未收到终态，标记为 failed）。"
    if USE_CLOUD:
        ids = _cd_select("scheduler_runs", columns="id",
                         filters=[("status", "eq", "running")])
        if not ids:
            return 0
        now = datetime.now().isoformat()
        for r in ids:
            _cd_update("scheduler_runs",
                       {"status": "failed", "completed_at": now},
                       filters=[("id", "eq", r["id"])])
        return len(ids)
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT id FROM scheduler_runs WHERE status='running'"
        ).fetchall()
        ids = [r["id"] for r in cur]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        now = datetime.now().isoformat()
        conn.execute(
            f"UPDATE scheduler_runs SET status='failed', completed_at=?, "
            f"output=COALESCE(output,'') || ? WHERE id IN ({placeholders})",
            [now, note, *ids],
        )
        return len(ids)
