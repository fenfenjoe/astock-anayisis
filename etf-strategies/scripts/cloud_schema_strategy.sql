-- 补充云 schema：策略定义 / 指标 / 每日信号（权威表，跨机一致）
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
