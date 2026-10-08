# 自动修复报告 — 2026-10-08 13:16

## 本轮扫描
- 扫描时间: 2026-10-08T13:16:21+08:00
- 发现 OPEN BUG: 2 个（BUG-054 / BUG-056，均 2026-10-08 12:1x 数据巡检发现，写入 bugs/open/）
- AUTO_FIX 候选: 2 个（BUG-054: auto_fix_eligible=true 但受盘中时间约束推迟；BUG-056: auto_fix_eligible=true 本轮执行）
- MANUAL_REVIEW 候选: 0 个（bugs/open 下其余 8 项 BUG-005/007/012/013/014/015/038/039 均为 MANUAL_REVIEW 且已含自动修复判定，沿用既有判定无新增动作）

## 自动修复结果

| BUG-ID | 标题 | 结果 | 详情 |
|--------|------|------|------|
| BUG-054 | 4 个活跃 ETF 缓存含 10-08 盘中 partial bar（159915/510180/513100/518880） | ⏸️ DEFERRED（保持 OPEN） | auto_fix_eligible=true 但本报告明确「必须收盘后 ≥15:00 执行，盘中轮不得以 partial 覆盖 partial」（BUG-040/034/026/016 教训）。本轮 13:07 为盘中轮（13:09 < 15:00），不执行缓存刷新；留待收盘后轮次（≥15:00，如 16:07 轮）对 4 ETF 执行 get_kline(refresh=True, end=2026-10-08) 补全官方收盘 bar。BUG 报告已追加推迟记录 |
| BUG-056 | bug_inspect_data 第四步「自然日>3天」判断跨国庆误报 9 个活跃 ETF 数据缺失 | ✅ FIXED | 第四步判定由「自然日 >3 天」改为「交易日」口径（缓存末日期 < 最近完整交易日 → 缺失；复用 trading_calendar.is_trading_day，节假日天然跳过）。修复后脚本实测 `OK: 所有 13 个活跃 ETF 数据完整`；last_complete_trading_day 7 场景单测全 PASS；pytest 定向 65 passed；全量回归见下 |

## 升级到人工审核

| BUG-ID | 标题 | 原因 |
|--------|------|------|
| （无） | - | 本轮无新增 MANUAL_REVIEW |

> 现有 MANUAL_REVIEW 8 项：BUG-005/007/012/013/014/015/038/039（沿用既有判定）。均保留在 `bugs/open/`，待人工审阅后执行 bug_fix_template.md 流程。

## 执行日志
- 2026-10-08T13:16+08:00 扫描到 2 个 OPEN BUG（BUG-054 / BUG-056）
- 2026-10-08T13:16+08:00 BUG-054: auto_fix → ⏸️ 推迟（盘中 13:09 < 15:00，按报告约束禁止 partial 覆盖 partial）→ 保持 OPEN，留待收盘后轮次（≥15:00）
- 2026-10-08T13:16+08:00 BUG-056: auto_fix → 修改 bug_inspect_data.md 第四步脚本（自然日→交易日口径）→ 脚本实测 OK → FIXED（报告移入 bugs/closed/）
- 2026-10-08T13:16+08:00 更新 BUG_INDEX.md 完成（OPEN: 2→1, FIXED: 40→41）；BUG-056 状态 OPEN→FIXED
- 2026-10-08T13:16+08:00 全量回归 pytest tests/ → **706 passed / 17 skipped / 0 failed（exit 0 复核确认）**；定向 `-k "test_backtest or test_strategies"` → 65 passed
- 2026-10-08T13:2x+08:00 提交: `13728a0` fix(BUG-056) + `d2217b0` chore(BUG-056)（归档）
