-- astock-dashboard 云端权威 schema 增量迁移：agent_notices 待办状态机（2026-09-09）
-- 新增 result 列（小满处理结果：成功=小满回复，失败=失败原因）；幂等（IF NOT EXISTS 防重）。

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'agent_notices' AND column_name = 'result'
  ) THEN
    ALTER TABLE agent_notices ADD COLUMN result TEXT;
  END IF;
END $$;
