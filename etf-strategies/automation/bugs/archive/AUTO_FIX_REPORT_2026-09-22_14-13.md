# 自动修复报告 — 2026-09-22 14:13

## 本轮扫描
- 扫描时间: 2026-09-22T14:13:27+08:00
- 发现 OPEN BUG: 1 个
- AUTO_FIX 候选: 1 个
- MANUAL_REVIEW 候选: 0 个

## 自动修复结果

| BUG-ID | 标题 | 结果 | 详情 |
|--------|------|------|------|
| BUG-047 | test_cloud_db.py 单元测试未适配 pgdirect 后端迁移 — `_mock_cloud` fixture 只 mock PostgREST 路径，pgdirect 下误连真实云库（10 项 FAILED + 触发云端认证限流） | ✅ FIXED | `_mock_cloud` fixture 增加 `_BACKEND="postgrest"` + `_PG_ENABLED=False` 强制走 mocked `_req` 路径（方案 a）；test_cloud_db 15 passed + test_cloud_db_pg 33 passed；全量 670 passed / 17 skipped / 0 failed（修复前基线 660 passed + 10 failed） |

## 升级到人工审核

本轮无新增 MANUAL_REVIEW。

## 执行日志
- 2026-09-22T14:13:27+08:00 扫描到 1 个 OPEN BUG（BUG-047，auto_fix_eligible=true）
- 2026-09-22T14:13:27+08:00 BUG-047: auto_fix → 修复成功 → FIXED（fixture 补强 _BACKEND/_PG_ENABLED mock；复现 10 FAILED 含云端防爆破限流 → 修复后 48 passed/2 skipped 专项 + 670 passed/0 failed 全量回归）
- 2026-09-22T14:13:27+08:00 更新 BUG_INDEX.md 完成（OPEN 1→0, FIXED 34→35）
