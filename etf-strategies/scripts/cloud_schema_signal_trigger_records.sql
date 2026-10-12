-- 信号触发记录云表（2026-09-21 新增 · Dashboard「每日信号」页点击信号展开触发记录）
-- 表名：signal_trigger_records
-- 作用：盘中分析生成的「信号触发记录」明细落库，通过 signal_id 与 signal_tracking 关联。
--       一行 = 一次信号触发事件（含触发时间/优先级/标的/操作类型/触发条件摘要/状态/建议操作/用户操作）。
-- 幂等：IF NOT EXISTS + UNIQUE(signal_id, trigger_time)，可重复执行。
-- 执行方式：
--   Supabase：byted-supabase-cli db query -f etf-strategies/scripts/cloud_schema_signal_trigger_records.sql
--   PostgreSQL 引擎：python scripts/pg_exec_sql.py scripts/cloud_schema_signal_trigger_records.sql
CREATE TABLE IF NOT EXISTS signal_trigger_records (
  id            BIGSERIAL PRIMARY KEY,
  signal_id     TEXT NOT NULL,          -- 关联信号 SIG-YYYYMMDD-NN（→ signal_tracking.signal_id）
  trigger_date  TEXT,                   -- 触发记录所属日（YYYY-MM-DD）
  trigger_time  TEXT,                   -- 触发时间（HH:MM）
  priority      TEXT,                   -- P0/P1/P2
  ticker        TEXT,                   -- 6 位代码
  name          TEXT,                   -- 标的名称
  action_type   TEXT,                   -- 操作类型（建仓/减仓/正T/反T/止损/观察）
  condition     TEXT,                   -- 触发条件摘要
  status        TEXT,                   -- 当前状态（已触发/已过期/已执行…）
  suggest       TEXT,                   -- 建议操作
  result        TEXT,                   -- 用户操作（待用户填写/已执行/放弃/错过）
  created_at    TEXT,                   -- 首次入库时间
  updated_at    TEXT,                   -- 最近更新时间
  UNIQUE (signal_id, trigger_time)      -- 幂等：同信号同触发时间只一条（同检查点重跑不重复）
);

-- 常用查询索引
CREATE INDEX IF NOT EXISTS idx_signal_trigger_records_signal ON signal_trigger_records(signal_id);
CREATE INDEX IF NOT EXISTS idx_signal_trigger_records_date ON signal_trigger_records(trigger_date);

-- 暴露给 Data API（与现有云表一致：service_role 经 REST 访问）
GRANT ALL ON signal_trigger_records TO service_role;
GRANT SELECT ON signal_trigger_records TO anon, authenticated;
GRANT USAGE, SELECT ON SEQUENCE signal_trigger_records_id_seq TO service_role;
