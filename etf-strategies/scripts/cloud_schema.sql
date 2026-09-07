-- astock-dashboard 云端权威 schema（PostgreSQL 17 / Supabase 版）
-- 首次建库：由 byted-supabase-cli db query -f 执行，幂等（IF NOT EXISTS）

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
