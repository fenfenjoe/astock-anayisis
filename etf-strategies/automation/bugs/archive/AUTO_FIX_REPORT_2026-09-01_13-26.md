# 自动修复报告 — 2026-09-01 13:26

## 本轮扫描
- 扫描时间: 2026-09-01T13:07+08:00
- 发现 OPEN BUG: 2 个（BUG-016 / BUG-017）
- AUTO_FIX 候选: 2 个
- MANUAL_REVIEW 候选: 0 个

## 自动修复结果

| BUG-ID | 标题 | 结果 | 详情 |
|--------|------|------|------|
| BUG-016 | 缓存 2026-08-31 日K为盘中快照（11/18 缓存跨源价差 >0.5%） | ✅ FIXED | 对全部 18 个缓存做确定性重拉（东财 push2his 月内增量 `start=20260801/end=20260831` + data.py merge `keep="last"` 覆盖 partial bar）。修复后 18/18 缓存 08-31 close 与三源真实收盘价 diff=0.0%，`high >= close` 结构性检查全通过 |
| BUG-017 | bug_inspect_data 第四步脚本缺陷（hasattr 恒 False → 活跃 ETF 集合恒空） | ✅ FIXED | `bug_inspect_data.md` 第四步脚本改用 `list_strategies._default_assets(cls)` 实例化取 assets（try/except 兜底），修复后实测输出 `活跃策略 ETF 总数: 13` + `OK: 所有 13 个活跃 ETF 数据完整`，完整性门恢复真实检查能力 |

## 升级到人工审核

本轮无新增 MANUAL_REVIEW（BUG-005/007/012/013/014/015 保持待人工审核状态不变）。

## 测试验证

- 全量回归: `pytest tests/ -v --tb=short` → **408 passed, 1 skipped, 0 failed**（1 skipped 为网络相关）
- BUG-017 修复验证: 修复后第四步脚本逻辑实测输出 13 只活跃 ETF 且全部完整
- BUG-016 修复验证: 全量扫描 18 只缓存 08-31 bar → 0 MISMATCH、0 结构性异常

## 修复过程中的技术要点（记录备查）

- `get_kline(code, start='2012-05-28', end='2026-08-31', refresh=True)` 全量重拉时，历史较长标的（如 510300/510180）的长区间请求被东财 push2his 断开（`RemoteDisconnected`），且 `get_kline` 对 API 异常**静默回退读缓存**（无 WARN、无报错）→ 缓存未更新且不易察觉。改为月内增量重拉（响应小、稳定）+ 失败重试 3 次 + 冷却后单独补拉（512480/510180/601398 首轮被风控，45s 冷却后成功）。
- 建议后续 REQ：① `get_kline` API 异常回退缓存时输出 WARN；② 数据刷新入口增加"非交易时段才写当日 bar / 收盘后强制补全当日 bar"防护（BUG-016 流程根因）。

## 执行日志
- 2026-09-01T13:07+08:00 扫描到 2 个 OPEN BUG
- 2026-09-01T13:15+08:00 BUG-017: auto_fix → 修复成功 → FIXED（bug_inspect_data.md 第四步脚本）
- 2026-09-01T13:20+08:00 BUG-016: auto_fix → 修复成功 → FIXED（18/18 缓存 08-31 完整收盘 bar）
- 2026-09-01T13:25+08:00 全量回归 408 passed, 1 skipped, 0 failed
- 2026-09-01T13:26+08:00 更新 BUG_INDEX.md 完成（OPEN: 2→0, FIXED: 7→9, MANUAL_REVIEW: 6→6）
