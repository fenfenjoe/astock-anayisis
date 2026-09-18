-- ═══════════════════════════════════════════════════════════════════════
-- astock-dashboard 迁移到 AIDAP PostgreSQL 引擎 · 新 workspace 一键建库 DDL
-- 2026-09-17 · 合并自 scripts/cloud_schema*.sql（均为 PostgreSQL 方言，幂等）
--
-- 用途：在新建的 AIDAP PostgreSQL 引擎 workspace 上执行本文件，即可重建
-- 与旧 Supabase 引擎 workspace 同构的 22 张权威表。
--
-- 执行方式（用户建好 workspace + 提供连接串后）：
--   1) byted-supabase-cli db query -f etf-strategies/scripts/cloud_schema_pg.sql
--      （若 CLI 支持；否则用 pg8000 直连执行，见 migrate_import.py 前序步骤）
--   2) 或 psql/pg8000 连接后逐段执行本文件
--
-- 表清单（22 张，来源文件）：
--   users/portfolio_holdings/portfolio_trades/portfolio_meta/daily_reports/
--     scheduler_runs/agent_sessions/agent_messages/agent_articles/agent_opinions/
--     agent_knowledge/agent_metadata/agent_sources/agent_activities/tickets
--       ← scripts/cloud_schema.sql
--   platform_cookies/platform_reachability ← cloud_schema_platform.sql
--   agent_notices                          ← cloud_schema_notices.sql(+result 列)
--   strategy_kb/strategy_metrics/daily_signals ← cloud_schema_strategy.sql
--   signal_tracking                        ← cloud_schema_signal_tracking.sql
--   唯一索引（daily_signals/daily_reports/portfolio_holdings/agent_knowledge/
--     agent_sources）                      ← cloud_schema_unique.sql
--
-- 注意：kline_daily / backtest_nav 是本地 SQLite 可重建缓存（不在云库），无需迁移。
-- ═══════════════════════════════════════════════════════════════════════

-- ── A. 账号与配置 ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
  id            BIGSERIAL PRIMARY KEY,
  username      TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  display_name  TEXT,
  role          TEXT NOT NULL DEFAULT 'user',
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TEXT NOT NULL DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
  last_login    TEXT
);

-- ── B. 组合账本 ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS portfolio_holdings (
  id         BIGSERIAL PRIMARY KEY,
  code       TEXT NOT NULL,
  name       TEXT,
  shares     NUMERIC NOT NULL DEFAULT 0,
  cost_price NUMERIC NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
);

CREATE TABLE IF NOT EXISTS portfolio_trades (
  id         BIGSERIAL PRIMARY KEY,
  trade_date TEXT NOT NULL,
  name       TEXT,
  code       TEXT,
  quantity   NUMERIC NOT NULL DEFAULT 0,
  price      NUMERIC NOT NULL DEFAULT 0,
  side       TEXT NOT NULL,
  remark     TEXT,
  created_at TEXT NOT NULL DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
);

CREATE TABLE IF NOT EXISTS portfolio_meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);

-- ── C. 每日复盘 / 调度 ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS daily_reports (
  id           BIGSERIAL PRIMARY KEY,
  report_date  TEXT NOT NULL,
  report_type  TEXT,
  markdown     TEXT,
  status       TEXT,
  generated_at TEXT,
  source_file  TEXT
);

CREATE TABLE IF NOT EXISTS scheduler_runs (
  id           BIGSERIAL PRIMARY KEY,
  task_id      TEXT,
  window_key   TEXT,
  trigger      TEXT,
  run_time     TEXT,
  status       TEXT,
  pid          TEXT,
  duration_sec NUMERIC,
  output       TEXT,
  completed_at TEXT
);

-- ── D. Agent 拟人数据 ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_sessions (
  id         BIGSERIAL PRIMARY KEY,
  persona    TEXT,
  title      TEXT,
  created_at TEXT NOT NULL DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_messages (
  id         BIGSERIAL PRIMARY KEY,
  session_id BIGINT REFERENCES agent_sessions(id) ON DELETE CASCADE,
  role       TEXT,
  content    TEXT,
  sources    JSONB,
  created_at TEXT NOT NULL DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
);

CREATE TABLE IF NOT EXISTS agent_articles (
  id           BIGSERIAL PRIMARY KEY,
  title        TEXT,
  summary      TEXT,
  content      TEXT,
  topics       JSONB,
  sources      JSONB,
  status       TEXT,
  kind         TEXT,
  published_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_opinions (
  id         BIGSERIAL PRIMARY KEY,
  topic      TEXT,
  opinion    TEXT,
  article_id BIGINT,
  created_at TEXT NOT NULL DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
);

CREATE TABLE IF NOT EXISTS agent_knowledge (
  id           BIGSERIAL PRIMARY KEY,
  source       TEXT,
  title        TEXT,
  url          TEXT,
  summary      TEXT,
  content      TEXT,
  viewpoint    TEXT,
  emotion      TEXT,
  memory       TEXT,
  read_at      TEXT,
  published_at TEXT,
  consumed     BOOLEAN NOT NULL DEFAULT FALSE,
  fetched_at   TEXT
);

CREATE TABLE IF NOT EXISTS agent_metadata (
  key   TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS agent_sources (
  id         BIGSERIAL PRIMARY KEY,
  name       TEXT,
  url        TEXT,
  kind       TEXT,
  note       TEXT,
  enabled    BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TEXT NOT NULL DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
);

CREATE TABLE IF NOT EXISTS agent_activities (
  id         BIGSERIAL PRIMARY KEY,
  kind       TEXT,
  label      TEXT,
  source     TEXT,
  started_at TEXT,
  ended_at   TEXT,
  note       TEXT,
  tokens     BIGINT
);

-- 索引（高频查询路径）
CREATE INDEX IF NOT EXISTS idx_agent_messages_session ON agent_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_daily_reports_date ON daily_reports(report_date);
CREATE INDEX IF NOT EXISTS idx_scheduler_runs_task ON scheduler_runs(task_id);
CREATE INDEX IF NOT EXISTS idx_agent_knowledge_url ON agent_knowledge(url);

-- ── E. 工单系统（BUG/REQ 管理）───────────────────────────────────
CREATE TABLE IF NOT EXISTS tickets (
  id          TEXT PRIMARY KEY,
  kind        TEXT NOT NULL,
  title       TEXT NOT NULL,
  description TEXT,
  severity    TEXT NOT NULL DEFAULT 'p2',
  status      TEXT NOT NULL DEFAULT 'open',
  source_task TEXT,
  assignee    TEXT DEFAULT 'xiaoman',
  created_at  TEXT NOT NULL DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
  updated_at  TEXT NOT NULL DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
  result      TEXT,
  log_entries JSONB
);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);

-- ── F. 社交平台 Cookie + 可访问性 ──────────────────────────────
CREATE TABLE IF NOT EXISTS platform_cookies (
  platform_id TEXT PRIMARY KEY,
  cookie      TEXT NOT NULL,
  updated_at  TEXT NOT NULL DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
);

CREATE TABLE IF NOT EXISTS platform_reachability (
  platform_id TEXT PRIMARY KEY,
  reachable   BOOLEAN NOT NULL DEFAULT FALSE,
  checked_at  TEXT NOT NULL DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
  reason      TEXT
);

-- ── G. 提示/待办（REQ-002）────────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_notices (
  id         BIGSERIAL PRIMARY KEY,
  kind       TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'open',
  title      TEXT NOT NULL,
  content    TEXT NOT NULL,
  todo_type  TEXT,
  todo_data  JSONB,
  reply      TEXT,
  reply_at   TEXT,
  result     TEXT,
  read_at    TEXT,
  source     TEXT,
  created_at TEXT NOT NULL DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
);

-- ── H. 策略定义 / 指标 / 每日信号 ──────────────────────────────
CREATE TABLE IF NOT EXISTS strategy_kb (
  strategy_id     TEXT PRIMARY KEY,
  name            TEXT,
  class_name      TEXT,
  category        TEXT,
  intro           TEXT,
  stock_selection TEXT,
  market_timing   TEXT,
  factors         TEXT,
  rebalance       TEXT,
  strengths       TEXT,
  weaknesses      TEXT,
  backtest_params JSONB,
  source_url      TEXT,
  process_desc    TEXT
);

CREATE TABLE IF NOT EXISTS strategy_metrics (
  strategy_id     TEXT PRIMARY KEY,
  name            TEXT,
  category        TEXT,
  category_cn     TEXT,
  annual_return   NUMERIC,
  sharpe          NUMERIC,
  max_drawdown    NUMERIC,
  calmar          NUMERIC,
  win_rate        NUMERIC,
  turnover        NUMERIC,
  excess_return   NUMERIC,
  assets_json     JSONB,
  description     TEXT,
  backtest_window TEXT
);

CREATE TABLE IF NOT EXISTS daily_signals (
  id            BIGSERIAL PRIMARY KEY,
  strategy_id   TEXT NOT NULL,
  signal_date   TEXT NOT NULL,
  asset_code    TEXT,
  asset_name    TEXT,
  target_weight NUMERIC,
  prev_weight   NUMERIC,
  weight_change NUMERIC,
  action        TEXT,
  updated_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_daily_signals_strat_date
  ON daily_signals(strategy_id, signal_date);

-- ── I. 信号追踪（12 列信号表 + 复盘回填 + 追踪结算 25 字段）──────
CREATE TABLE IF NOT EXISTS signal_tracking (
  signal_id       TEXT PRIMARY KEY,
  signal_date     TEXT,
  priority        TEXT,
  ticker          TEXT,
  name            TEXT,
  trigger_condition TEXT,
  trade_type      TEXT,
  direction       TEXT,
  urgency         TEXT,
  expected_trigger_rate REAL,
  trade_price     REAL,
  target_price    REAL,
  stop_price      REAL,
  target_pct      REAL,
  stop_pct        REAL,
  valid_window    TEXT,
  position        TEXT,
  status          TEXT,
  source          TEXT,
  trigger_price   REAL,
  trigger_time    TEXT,
  entry_time      TEXT,
  eval_decision_quality TEXT,
  eval_execution_quality TEXT,
  outcome         TEXT,
  settle_price    REAL,
  pnl             REAL,
  holding_days    INTEGER,
  expected_return_date TEXT,
  entry_price     REAL,
  shares          INTEGER,
  status_history  JSONB,
  avoided_loss    REAL,
  settle_date     TEXT,
  exit_date       TEXT,
  cost_basis      REAL,
  sell_price      REAL,
  created_at      TEXT,
  updated_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_signal_tracking_date ON signal_tracking(signal_date);
CREATE INDEX IF NOT EXISTS idx_signal_tracking_status ON signal_tracking(status);

-- ── J. 唯一约束（防双进程并发重复，云权威多进程架构关键保障）──────
CREATE UNIQUE INDEX IF NOT EXISTS uq_daily_signals_strat_date_asset
  ON daily_signals(strategy_id, signal_date, asset_code);
CREATE UNIQUE INDEX IF NOT EXISTS uq_daily_reports_date_type
  ON daily_reports(report_date, report_type);
CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_holdings_code
  ON portfolio_holdings(code);
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_knowledge_url
  ON agent_knowledge(url);
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_sources_name
  ON agent_sources(name);

-- ═══════════════════════════════════════════════════════════════════════
-- 校验：建库后应返回 22 张表
-- SELECT table_name FROM information_schema.tables
-- WHERE table_schema='public' ORDER BY table_name;
-- ═══════════════════════════════════════════════════════════════════════
