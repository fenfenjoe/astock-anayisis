-- astock-dashboard 云端权威 schema 增补：社交平台 Cookie + 可访问性缓存（方案 v1.10 §9.4）
-- 幂等（IF NOT EXISTS）；由 byted-supabase-cli db query -f 执行

-- ── 社交平台 Cookie（微博/小红书；用户主动提供，完整 Cookie 串）──
CREATE TABLE IF NOT EXISTS platform_cookies (
  platform_id TEXT PRIMARY KEY,          -- weibo | xhs
  cookie      TEXT NOT NULL,             -- 完整 Cookie 串（用户从浏览器复制）
  updated_at  TEXT NOT NULL DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
);

-- ── 平台可访问性缓存（服务器缓存：首次启动判定 + 真实访问自校准）──
CREATE TABLE IF NOT EXISTS platform_reachability (
  platform_id TEXT PRIMARY KEY,          -- weibo | xhs | x | zhihu | xueqiu
  reachable   BOOLEAN NOT NULL DEFAULT FALSE,
  checked_at  TEXT NOT NULL DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS')),
  reason      TEXT                       -- 判定依据（无 Cookie / 探测失败 / 未实施访问逻辑…）
);

-- ── 权限：service_role 全权；Data API 暴露给 anon/authenticated（读取/写入）──
GRANT ALL ON TABLE platform_cookies        TO service_role;
GRANT ALL ON TABLE platform_reachability   TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE platform_cookies      TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE platform_reachability TO anon, authenticated;
