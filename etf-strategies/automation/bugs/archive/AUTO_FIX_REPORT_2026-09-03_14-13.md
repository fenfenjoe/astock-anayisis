# 自动修复报告 — 2026-09-03 14:13

## 本轮扫描
- 扫描时间: 2026-09-03T14:07+08:00
- 发现 OPEN BUG: 2 个（BUG-019 / BUG-020，均为 bug_inspect_data 2026-09-03 12:21 发现）
- AUTO_FIX 候选: 2 个（均 auto_fix_eligible=true）
- MANUAL_REVIEW 候选: 0 个

## 自动修复结果

| BUG-ID | 标题 | 结果 | 详情 |
|--------|------|------|------|
| BUG-019 | 11/13 活跃 ETF 缓存 09-02 日K为盘中快照 | ✅ FIXED | 11 个缓存确定性增量重拉（东财 push2his `start=20260901/end=20260902` + merge keep="last"）并截断 >09-02 的盘中 partial 行。修复后 11/11 缓存最后日K = 09-02 完整收盘 bar，与东财权威逐字段一致、与腾讯 qfq 日K diff=0.0000% |
| BUG-020 | 5 个非活跃 cache parquet 缓存过期（mtime=09-01，缺 09-01/09-02） | ✅ FIXED | 5 个缓存增量重拉追加 09-01/09-02 完整 bar。修复后 5/5 缓存最后日K = 09-02，东财+腾讯双源验证 diff=0.0000% |

## 修复过程技术要点（记录备查）

- **BUG-019 修复前状态复核**：巡检(12:21)后 13:20 有一次 `refresh=True` 刷新已把 09-02 覆盖为完整收盘 bar，但同时写入 09-03 盘中快照（13:20 截点）→ 最后日K = partial 09-03。按本 BUG 建议修复口径（end=09-02，避免 partial bar 作为最后日K）执行增量重拉 + 截断 >09-02 行，恢复 DAT-001「最后日K = 完整收盘 bar」不变量。
- 东财 push2his 本次**网络可达、无风控**（12:21 巡检时 RemoteDisconnected 13/13，已恢复），16 只一次拉取成功，无需冷却重试。
- 修复脚本复用 `data.py` merge 逻辑（concat + `duplicated(keep='last')`），与 BUG-016 修复模式一致；修复前 16 个 parquet 已备份（`_tmp_backup/`）供回滚，验证通过后已清理。

## 升级到人工审核

本轮无新增 MANUAL_REVIEW（BUG-005/007/012/013/014/015 保持待人工审核状态不变，6 个）。

## 架构性改进登记（流程根因 → REQ）

| REQ-ID | 标题 | 原因 |
|--------|------|------|
| REQ-001 | 数据刷新流程防护 — 收盘后强制补全当日 bar + 非活跃/持仓标的定期刷新 | BUG-016/019（盘中快照无收盘兜底补全）与 BUG-004/008/020（非活跃标的反复过期）的流程根因，需架构/调度层改动，已创建到 `steering/open/REQ-001.md` 并登记 REQ_INDEX |

## 测试验证

- 定向: `pytest tests/ -k "test_backtest or test_strategies" --tb=short` → **65 passed**
- 全量回归: `pytest tests/ -v --tb=short` → **436 passed, 1 skipped, 0 failed**（1 skipped 为网络相关，与历史运行一致）
- 数据修复验证: 16/16 缓存 09-01/09-02 OHLC 与东财权威逐字段一致 + `high>=max(open,close)` / `low<=min(open,close)` 结构检查通过 + 09-02 close 与腾讯官方 qfq 日K 全部 diff=0.0000%（双源）

## 执行日志
- 2026-09-03T14:07+08:00 扫描到 2 个 OPEN BUG
- 2026-09-03T14:08+08:00 BUG-019: auto_fix → 增量重拉 09-01~09-02 + 截断 partial → 修复成功 → FIXED（11/11 双源验证一致）
- 2026-09-03T14:09+08:00 BUG-020: auto_fix → 增量重拉 09-01~09-02 → 修复成功 → FIXED（5/5 双源验证一致）
- 2026-09-03T14:11+08:00 全量回归 436 passed, 1 skipped, 0 failed
- 2026-09-03T14:13+08:00 更新 BUG_INDEX.md 完成（OPEN: 2→0, FIXED: 10→12, MANUAL_REVIEW: 6→6）
- 2026-09-03T14:13+08:00 创建 REQ-001（流程根因：收盘后补全当日 bar + 非活跃标的定期刷新）
