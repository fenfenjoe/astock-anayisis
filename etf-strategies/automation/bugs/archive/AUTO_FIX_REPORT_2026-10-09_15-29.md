# 自动修复报告 — 2026-10-09 15:29

## 本轮扫描
- 扫描时间: 2026-10-09T15:29:04+08:00
- 发现 OPEN BUG: 2 个（BUG-057 / BUG-058）
- AUTO_FIX 候选: 2 个（BUG-057/058: auto_fix_eligible=true，本轮 15:2x 已收盘 ≥15:00，满足执行条件）
- MANUAL_REVIEW 候选: 0 个（bugs/open 下其余 9 项 BUG-005/007/012/013/014/015/038/039/059 均为 MANUAL_REVIEW 且已含自动修复判定，沿用既有判定无新增动作）

## 自动修复结果

| BUG-ID | 标题 | 结果 | 详情 |
|--------|------|------|------|
| BUG-057 | 6/13 活跃 ETF 缓存含 10-08 盘中 partial bar（510300/510500/512010/512480/512660/512800） | ✅ FIXED | 收盘后（15:21 ≥15:00）东财 push2his 探针 RemoteDisconnected（网络被风控，同 BUG-054 10-08 记录）→ 按 REQ-001 许可回退腾讯 qfq 日K。写入前双重校验：复权基准 09-30 diff=0（6/6）+ 腾讯双端点自洽（qfq 10-08 收盘 == 实时昨收，6/6）。备份至 `_tmp_backup_057_058/`，仅替换 10-08 一行 merge keep="last"。验证：缓存 10-08 close 4.389/7.279/0.382/0.914/1.095/0.859 与腾讯 qfq 逐字段（O/C/H/L/V）MATCH 6/6（diff=0.000%），OHLC 结构合法，get_kline(refresh=False) 读取路径正确。全量回归 717 passed/1 failed（test_get_kline_returns_dataframe 为东财不可达时缓存回退路径 index.name 断言失配，pre-existing 环境问题，读取 2026-01~06 区间与本修复 10-08 行无交集，无因果关系） |
| BUG-058 | 非活跃缓存 512100 缺 10-08 bar + 4 个非活跃 ETF（159227/159326/159992/515880）10-08 partial | ✅ FIXED | 同 BUG-057 流程（腾讯 qfq 日K + 双重校验 7/7）。512100 追加 10-08 官方 bar（缓存原止于 09-30），159227/159326/159992/515880（及 WARN 的 002142/601398）替换 10-08 partial 行。验证：缓存 10-08 close 2.904/0.969/1.545/0.839/0.594/35.68/8.31 MATCH 7/7（diff=0.000%），get_kline(refresh=False) 读取路径正确。全量回归同 BUG-057 |

## 升级到人工审核

| BUG-ID | 标题 | 原因 |
|--------|------|------|
| （无） | - | 本轮无新增 MANUAL_REVIEW |

> 现有 MANUAL_REVIEW 9 项：BUG-005/007/012/013/014/015/038/039/059（沿用既有判定）。均保留在 `bugs/open/`，待人工审阅后执行 bug_fix_template.md 流程。

## 本轮相关观察

- **全量回归 1 项失败（非本次修复引入，pre-existing 环境问题）**：`tests/test_data.py::test_get_kline_returns_dataframe`（`assert df.index.name == "date"` 失败）— 该测试 `get_kline(refresh=True)` 强制走东财 API，本轮东财 push2his 不可达（RemoteDisconnected，同 10-08 记录）→ `get_kline` 静默回退读缓存（不抛异常，故不触发 `pytest.skip`）→ 缓存回退路径返回的 DataFrame `index.name` 为 None → 断言失败。该失败与本次缓存修复（仅改 13 个 parquet 的 10-08 行，git-ignored）**无因果关系**：修复前后 diff 验证确认非 10-08 行全部 `rest_diff=0`，且测试读取 2026-01~06 区间。东财可达时该测试正常通过（BUG-034 修复记录 09-10 曾 7 passed）。建议随环境恢复自动转绿，或后续人工裁定是否将该测试改为「东财不可达时跳过」。
- **东财不可达影响面**：本轮东财 push2his 仍被网络风控（RemoteDisconnected，同 10-08 15:19 BUG-054 修复记录），故修复全部走腾讯 qfq 日K 兜底（REQ-001 已许可），与 BUG-034/054 先例一致。
- **缓存修复范围**：仅修正 10-08 官方收盘 bar（`end=2026-10-08`），未写入 10-09 盘中/当日 bar — 符合 DAT-002「缓存末 bar = 最近完整交易日官方收盘 bar」及既有 13 活跃 ETF 缓存约定（全部止于 10-08）。10-09 bar 由下一轮数据巡检/晚间任务推进。

## 执行日志
- 2026-10-09T15:22+08:00 扫描到 2 个 OPEN BUG（BUG-057/058，auto_fix_eligible=true）
- 2026-10-09T15:22+08:00 BUG-057: 收盘后轮（15:21 ≥15:00）— 东财探针 RemoteDisconnected → 腾讯 qfq 日K（复权基准 09-30 diff=0 + 双端点自洽 6/6）→ 仅替换 10-08 行 merge keep="last" → 缓存 MATCH 6/6（diff=0.000%）→ 修复成功 → FIXED
- 2026-10-09T15:22+08:00 BUG-058: 收盘后轮（15:21 ≥15:00）— 同流程（双校验 7/7）→ 512100 追加 10-08 bar、6 只替换 10-08 行 → 缓存 MATCH 7/7（diff=0.000%）→ 修复成功 → FIXED
- 2026-10-09T15:29+08:00 更新 BUG_INDEX.md 完成（OPEN 2→0, FIXED 42→44；BUG-057/058 列表状态 OPEN→FIXED；巡检历史追加"自动修复 0 新 2 修 0 留"）
- 2026-10-09T15:29+08:00 BUG-057.md/BUG-058.md 移入 bugs/closed/；无新增 MANUAL_REVIEW
- 2026-10-09T15:29+08:00 相关观察：全量回归 717 passed / 1 failed（test_get_kline_returns_dataframe，东财不可达时缓存回退 index.name 断言失配，pre-existing 环境问题，与本次修复无因果关系）
- 2026-10-09T15:29+08:00 临时脚本（_bug_fix_*.py / _net_test.py / _fqkline_probe.py / _diff_check.py 等）跑完即删；备份保留于 `_tmp_backup_057_058/`
