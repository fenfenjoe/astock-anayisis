-- astock-dashboard 云端权威 schema 增补：提示/待办（REQ-002，聊天页「📌 提示与待办」）
-- 幂等（IF NOT EXISTS）；由 byted-supabase-cli db query -f 执行

-- ── 提示/待办：小满主动发；提示不需回复，待办回复后按 todo_type 回调执行 ──
-- 待办状态机：open(未处理) → replied(已回复) → done(处理成功)；失败回 open 记 result=失败原因；
--             dismissed=用户忽略
CREATE TABLE IF NOT EXISTS agent_notices (
  id         BIGSERIAL PRIMARY KEY,
  kind       TEXT NOT NULL,                -- notice=提示 | todo=待办
  status     TEXT NOT NULL DEFAULT 'open', -- open | replied | done | dismissed
  title      TEXT NOT NULL,
  content    TEXT NOT NULL,
  todo_type  TEXT,                         -- 待办回调类型（cookie_provide…）
  todo_data  JSONB,                        -- 待办负载（{"platform_id":"weibo"}）
  reply      TEXT,                         -- 用户回复
  reply_at   TEXT,
  result     TEXT,                         -- 小满处理结果（成功=回复；失败=失败原因）
  read_at    TEXT,                         -- NULL=未读（聊天 tab 小红点）
  source     TEXT,                         -- 生成来源（evening_review / agent…）
  created_at TEXT NOT NULL DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
);

-- ── 权限：service_role 全权；Data API 暴露给 anon/authenticated ──
GRANT ALL ON TABLE agent_notices TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE agent_notices TO anon, authenticated;
