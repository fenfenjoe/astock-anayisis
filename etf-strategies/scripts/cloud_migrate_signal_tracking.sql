-- ═══════════════════════════════════════════════════════════════════════
-- 云库 DDL 迁移：signal_tracking 表新增 盘中/复盘回填三列（CHAT.md 任务4）
-- 2026-09-14 · 幂等（ADD COLUMN IF NOT EXISTS，可重复执行）
--
-- 执行方式（在项目根目录，需已 byted-supabase-cli login + link 到对应 workspace）：
--   1) 备份（先做！设计文档风险点5）。注意：本 CLI 的 db dump 无 -t/--table 参数，
--      单表备份用 db query SELECT 导出，或全 public schema data-only dump：
--      a) 单表数据导出（推荐，最轻量）：
--         byted-supabase-cli db query "SELECT * FROM signal_tracking;" > signal_tracking_backup_YYYYMMDD.json
--      b) 全 public schema 数据备份（含 signal_tracking + 其他表）：
--         byted-supabase-cli db dump --data-only -s public -f signal_tracking_backup_YYYYMMDD.sql
--   2) 执行迁移：
--      byted-supabase-cli db query -f etf-strategies/scripts/cloud_migrate_signal_tracking.sql
--   3) 验证：
--      byted-supabase-cli db query "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='signal_tracking' AND column_name IN ('trigger_price','trigger_time','entry_time') ORDER BY column_name;"
--
-- 说明：新列仅由盘中/复盘 prompt 写入（cloud_upsert/cloud_update），存量行三列为 NULL
--       属预期；Dashboard「信号触发记录」表只展示 trigger_price 非空的行。
-- ═══════════════════════════════════════════════════════════════════════

ALTER TABLE signal_tracking ADD COLUMN IF NOT EXISTS trigger_price REAL;
ALTER TABLE signal_tracking ADD COLUMN IF NOT EXISTS trigger_time  TEXT;
ALTER TABLE signal_tracking ADD COLUMN IF NOT EXISTS entry_time    TEXT;

-- 校验（应返回 3 行）
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'signal_tracking'
  AND column_name IN ('trigger_price', 'trigger_time', 'entry_time')
ORDER BY column_name;
