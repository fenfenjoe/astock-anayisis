# 自动修复报告 — 2026-09-09 15:27

## 本轮扫描
- 扫描时间: 2026-09-09T15:27+08:00
- 发现 OPEN BUG: 1 个（BUG-033，2026-09-09 12:15 bug_inspect_data 发现，13:12/14:11 两轮因未收盘顺延）
- AUTO_FIX 候选: 1 个（auto_fix_eligible=true）
- MANUAL_REVIEW 候选: 0 个（bugs/open 下其余 9 项 BUG-005/007/012/013/014/015/025/029/030 均为 MANUAL_REVIEW 且已含自动修复判定，无需处理）

## 自动修复结果

| BUG-ID | 标题 | 结果 | 详情 |
|--------|------|------|------|
| BUG-033 | 活跃 ETF 513100（纳指ETF）缺 09-09 bar — 13 个活跃 ETF 中唯一无当日数据 | ✅ FIXED | 收盘后腾讯双端点（fqkline qt 3位 + qfq 日K 舍入自洽）确认官方收盘 O=2.233 C=2.234 H=2.235 L=2.225 V=875760 amount=195292257，merge keep="last" 写回 cache/513100.parquet；13 只活跃 ETF 最后数据日期全部对齐 2026-09-09 |

## 修复过程技术要点（记录备查）

- **前置条件**：13:12/14:11 两轮均因 A股 15:00 未收盘、09-09 官方 bar 未定型而顺延（遵循 REQ-001「交易时段内不把盘中 partial/异常 bar 当完整日K 写死」+ BUG-026 教训）。本轮 15:2x 已收盘，腾讯 fqkline qt 时间戳 20260909152155、market 标记 SH_close_已收盘 → 官方 bar 定型，满足补拉条件。
- **数据源**：东财 push2his 仍不可达（ConnectionError，网络被风控，同 12:15/13:07/14:11 记录）→ 按 a-stock-data 优先级 + BUG 建议修复走**腾讯双端点**：
  - 腾讯 fqkline `qt` 字段（3位精度官方收盘）：O=2.233 C=2.234 H=2.235 L=2.225 V=875760(手) amount=195292257(元, qt[35]="2.234/875760/195292257") amp=0.45
  - 腾讯 qfq 日K 09-09（2位显示）：2.23/2.23/2.24/2.23 V=875760 → 与 qt 3位值**十进制半进位舍入完全自洽**（2.235→2.24, 2.225→2.23；Python float round() 因浮点表示会误判，须用 Decimal ROUND_HALF_UP）+ vol 完全一致 → 双端点确认 bar 定型且自洽
  - 新浪日K / 百度股市通 09-09 数据未更新（T+1 或空），东财不可达 → 腾讯为当前唯一可靠源
- **写入**：merge `keep="last"` 覆盖写回 `cache/513100.parquet`（3位精度与历史一致）；修复前备份至 `_tmp_backup_033/513100.parquet`；09-08 close=2.233 保留正确；结构检查 high>=max(open,close) / low<=min(open,close) / 正数全部通过。
- **效果**：13 只活跃策略 ETF（159915/510180/510300/510500/511260/511880/512010/512480/512660/512800/512880/513100/518880）最后数据日期**全部一致 = 2026-09-09**，513100 不再滞后一个交易日，信号生成不会因 513100 数据陈旧产生动量/收益偏差。

## 升级到人工审核

本轮无新增 MANUAL_REVIEW（BUG-005/007/012/013/014/015/025/029/030 保持待人工审核状态不变，9 个）。

## 测试验证

- 定向: `pytest tests/ -k "test_backtest or test_strategies" --tb=short` → **65 passed**（修复前基线一致）
- 全量回归: `pytest tests/ --tb=short` → **526 passed, 18 skipped, 3 failed**（3 failed = BUG-029×2 + BUG-030×1，均为 auto_fix_eligible=false 的 MANUAL_REVIEW 桌宠前端契约缺陷，非本轮引入；对比 09-08 基线 437 passed/14 skipped/3 failed 失败集合一致，无新增失败）

## 执行日志
- 2026-09-09T15:27+08:00 扫描到 1 个 OPEN BUG（BUG-033）
- 2026-09-09T15:23+08:00 BUG-033: auto_fix → 腾讯双端点确认官方收盘 bar → 写入 cache/513100.parquet → 修复成功 → FIXED（13 只活跃 ETF 全部对齐 09-09）
- 2026-09-09T15:27+08:00 定向 65 passed + 全量回归 526 passed/18 skipped/3 failed（3 failed 为 MANUAL_REVIEW 的 BUG-029/030，无新增失败）
- 2026-09-09T15:27+08:00 更新 BUG_INDEX.md 完成（OPEN: 1→0, FIXED: 19→20, MANUAL_REVIEW: 9→9）；BUG-033.md 移至 closed/
