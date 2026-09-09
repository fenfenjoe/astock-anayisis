-- 每日复盘 · 信号追踪云表（记忆体系 Phase 3 · 信号云库化）
-- 表名：signal_tracking（与本地 signal_tracking.json 对应；策略引擎的 daily_signals 表保留不动）
-- Schema = 12 列信号表 + 复盘回填 + 追踪结算全量 25 字段（方案 v1.10 §9.2）
-- 幂等：IF NOT EXISTS；由 byted-supabase-cli db query -f 执行
CREATE TABLE IF NOT EXISTS signal_tracking (
  signal_id       TEXT PRIMARY KEY,      -- SIG-YYYYMMDD-NN
  -- 12 列信号表字段
  signal_date     TEXT,                  -- 信号生成日（YYYY-MM-DD）
  priority        TEXT,                  -- P0/P1/P2
  ticker          TEXT,                  -- 6 位代码
  name            TEXT,                  -- 标的名称
  trigger_condition TEXT,                -- 触发条件
  trade_type      TEXT,                  -- buy/sell
  direction       TEXT,                  -- buy/sell（方向）
  urgency         TEXT,                  -- high/low
  expected_trigger_rate REAL,            -- 预期触发率 %
  target_price    REAL,                  -- 目标价（显式价）
  stop_price      REAL,                  -- 止损价（显式价）
  target_pct      REAL,                  -- 目标 %（百分比写法）
  stop_pct        REAL,                  -- 止损 %（百分比写法）
  valid_window    TEXT,                  -- 有效时段
  position        TEXT,                  -- 仓位描述
  status          TEXT,                  -- 待执行/已触发/已执行/已过期/已废弃/已取消/settled
  source          TEXT,                  -- morning_analysis / intraday_check / evening_review
  -- 复盘回填列
  eval_decision_quality TEXT,            -- 决策质量评价
  eval_execution_quality TEXT,           -- 执行质量评价
  outcome         TEXT,                  -- hit/stopped/miss
  settle_price    REAL,                  -- 结算价
  pnl             REAL,                  -- 盈亏
  holding_days    INTEGER,               -- 持有天数
  -- 追踪结算列（对齐 signal_tracking.json）
  expected_return_date TEXT,             -- 预期收益日
  entry_price     REAL,                  -- 入场价
  shares          INTEGER,               -- 份额
  status_history  JSONB,                 -- 状态流转历史
  avoided_loss    REAL,                  -- 避免的损失
  settle_date     TEXT,                  -- 结算日
  exit_date       TEXT,                  -- 出场日
  cost_basis      REAL,                  -- 成本基准（卖出信号）
  sell_price      REAL,                  -- 卖出价（卖出信号）
  created_at      TEXT,                  -- 首次入库时间
  updated_at      TEXT                   -- 最近更新时间
);

-- 常用查询索引
CREATE INDEX IF NOT EXISTS idx_signal_tracking_date ON signal_tracking(signal_date);
CREATE INDEX IF NOT EXISTS idx_signal_tracking_status ON signal_tracking(status);

-- 暴露给 Data API（与现有云表一致：service_role 经 REST 访问）
GRANT ALL ON signal_tracking TO service_role;
GRANT SELECT ON signal_tracking TO anon, authenticated;
