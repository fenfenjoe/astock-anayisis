-- 盘中检查记录云表（2026-09-24 新增 · Dashboard「每日信号」页点击信号行展开检查结果）
-- 表名：signal_check_records
-- 作用：盘中检查（09:40/10:00/10:30/11:00/13:30/14:00/14:30 七个检查点）对**每条**信号
--       的每次检查结果落库（含未触发/已过期/已执行/跳过终态），一行 = 一条信号 × 一个检查点。
--       与 signal_trigger_records 的区别：触发记录只记"已触发"事件；本表记**每次检查**的完整结果
--       （现价 vs 交易价、触发判定、状态流转、检查摘要），供 Dashboard 行展开查看盘中检查轨迹。
-- 幂等：IF NOT EXISTS + UNIQUE(signal_id, check_date, check_time)，同检查点重跑不重复。
-- 执行方式：
--   Supabase：byted-supabase-cli db query -f etf-strategies/scripts/cloud_schema_signal_check_records.sql
--   PostgreSQL 引擎：python scripts/pg_exec_sql.py scripts/cloud_schema_signal_check_records.sql
CREATE TABLE IF NOT EXISTS signal_check_records (
  id            BIGSERIAL PRIMARY KEY,
  signal_id     TEXT NOT NULL,          -- 关联信号 SIG-YYYYMMDD-NN（→ signal_tracking.signal_id）
  check_date    TEXT,                   -- 检查日期（YYYY-MM-DD）
  check_time    TEXT,                   -- 检查时间（HH:MM）
  check_point   TEXT,                   -- 检查点标签（09:40/10:00/10:30/11:00/13:30/14:00/14:30）
  ticker        TEXT,                   -- 6 位代码
  name          TEXT,                   -- 标的名称
  price         REAL,                   -- 检查时现价
  trade_price   REAL,                   -- 交易价（触发判定基准）
  condition_met TEXT,                   -- 触发判定：触发/未触发/已过期/已执行/跳过（终态）
  status_before TEXT,                   -- 检查前状态（中文：未触发/已触发/已过期/已执行/已结算）
  status_after  TEXT,                   -- 检查后状态（同上）
  note          TEXT,                   -- 检查摘要（如：现价 0.714 ≥ 交易价 0.71 → 触发；75%窗口过期）
  created_at    TEXT,                   -- 首次入库时间
  updated_at    TEXT,                   -- 最近更新时间
  UNIQUE (signal_id, check_date, check_time)  -- 幂等：同信号同检查点只一条（同检查点重跑不重复）
);

-- 常用查询索引
CREATE INDEX IF NOT EXISTS idx_signal_check_records_signal ON signal_check_records(signal_id);
CREATE INDEX IF NOT EXISTS idx_signal_check_records_date ON signal_check_records(check_date);

-- 注意：以下 GRANT 为 Supabase（postgrest）专用；AIDAP PostgreSQL 引擎（pgdirect）
-- 无 service_role/anon/authenticated 角色，执行会报 42704 —— pgdirect 场景请忽略本节。
-- GRANT ALL ON signal_check_records TO service_role;
-- GRANT SELECT ON signal_check_records TO anon, authenticated;
-- GRANT USAGE, SELECT ON SEQUENCE signal_check_records_id_seq TO service_role;
