# Harness BUG 索引

> 由 harness_bug_auto_fix 和测试发现流程维护。
> 状态: OPEN | IN_PROGRESS | FIXED | VERIFIED | WONT_FIX | DUPLICATE | MANUAL_REVIEW

---

## 统计

| 状态 | 数量 |
|------|------|
| OPEN | 0 |
| IN_PROGRESS | 0 |
| FIXED | 6 |
| VERIFIED | 0 |
| WONT_FIX | 1 |
| MANUAL_REVIEW | 3 |

---

## ⚠️ 待人工审核 (MANUAL_REVIEW)

> 以下 BUG 因涉及计算逻辑/算法正确性/金融公式，需人工审阅决定修复方案。

| BUG-ID | 严重级别 | 标题 | 发现日期 | 涉及文件 | 原因 |
|--------|---------|------|---------|---------|------|
| BUG-007 | P1 | B4 报 STALE — staging mtime 早于 evening_review 完成时间（疑似检查逻辑误报） | 2026-08-27 | staging_verify.py / task_state.json | staging 内容已刷新（含 8/28）但 mtime<completed_at；需判定流程违规 or 检查误报 |
| BUG-008 | P2 | C1 早盘报告检查关键词漂移：「前次预测回顾/海外市场传导」vs 检查「上期预判回顾/事件验证」 | 2026-08-27 | auto_logic_inspect.md C1 / auto_morning_analysis.md | 报告结构与自动化 prompt 一致，检查脚本关键词未同步 |
| BUG-009 | P2 | C3 复盘报告检查关键词漂移：「次日核心关注」vs 检查「次日核心变量」 | 2026-08-27 | auto_logic_inspect.md C3 / 复盘报告 / 复盘模板 | 8/26 BUG-003 修复后再次漂移，命名三处不一致 |

---

## BUG 列表

<!-- BUG_TABLE_START -->
| BUG-001 | P3 | ~~每日调仓.md 当前持仓表与 config 冲突~~（误报，两文件一致） | 2026-08-18 | 复盘验证 | WONT_FIX | config/持仓.md | 误用早盘旧 config（5标的含纳指），实际两文件一致（4标的无纳指）；config 8/18 15:23 已更新 |
| BUG-002 | P2 | 归档检查失败：归档机制自 8/25 退化"仅写归档说明.md"，A1/A2 仍按旧文件名 | 2026-08-26 | 逻辑巡检 | FIXED | auto_evening_review.md 11.0 | 先覆盖后归档致原件丢失；已恢复"先归档后生成"流程（用户确认 1A） |
| BUG-003 | P2 | 复盘报告缺「做T建议复盘/核心回顾/操作预案」章节（结构漂移） | 2026-08-26 | 逻辑巡检 | FIXED | auto_logic_inspect.md C3 | 报告章节命名被替代；C3 已适配新命名并实测 PASS（用户确认 2B） |
| BUG-004 | P2 | D1 持仓解析失败：每日调仓.md 表格前"持仓："说明行致正则失配 | 2026-08-26 | 逻辑巡检 | FIXED | 每日调仓.md + D1 脚本 | 格式漂移，解析失败（内容实际一致）；解析正则已容忍标题与表格间非表格行（D1+复盘模板 4.5） |
| BUG-005 | P1 | D4 信号模型一致性检查脚本失效：CHECK_TARGETS 解包错误 | 2026-08-26 | 逻辑巡检 | FIXED | auto_logic_inspect.md D4 | lib 升三元组、prompt 未同步 |
| BUG-006 | P3 | E2 BUG_INDEX 统计口径误报：closed 目录 WONT_FIX 被误计 FIXED | 2026-08-26 | 逻辑巡检 | FIXED | auto_logic_inspect.md E2 | 按目录文件数而非状态字段统计；E2 已改为按文件内 **状态**: 字段计数（OPEN/IN_PROGRESS/FIXED/WONT_FIX 分别统计），实测 E2:PASS，回归 208 passed |
| BUG-007 | P1 | B4 报 STALE — staging mtime 早于 evening_review 完成时间（疑似检查逻辑误报） | 2026-08-27 | 逻辑巡检 | MANUAL_REVIEW | staging_verify.py / task_state.json | staging 内容已刷新（含 8/28）但 mtime<completed_at；需判定流程违规 or 检查误报；C4 同步 WARN staging_generated 字段为空 |
| BUG-008 | P2 | C1 早盘报告检查关键词漂移：「前次预测回顾/海外市场传导」vs 检查「上期预判回顾/事件验证」 | 2026-08-27 | 逻辑巡检 | MANUAL_REVIEW | auto_logic_inspect.md C1 | 报告结构与 auto_morning_analysis.md 12 模块一致，检查脚本关键词未同步 |
| BUG-009 | P2 | C3 复盘报告检查关键词漂移：「次日核心关注」vs 检查「次日核心变量」 | 2026-08-27 | 逻辑巡检 | MANUAL_REVIEW | auto_logic_inspect.md C3 | 8/26 BUG-003 修复后再次漂移，报告/模板/检查三处命名不一致 |
| BUG-010 | P2 | auto_logic_inspect 检查脚本缺陷：C1/C2/C3 引号语法错误 + C4/D2 缺 UTF-8 致 Windows 无法运行 | 2026-08-27 | 逻辑巡检 | FIXED | auto_logic_inspect.md C1-C4/D2 | 已修复（auto_fix）：C1/C2/C3 `f = 'f'my_doc/...''` → f-string；C4/D2 `python -c` → `python -X utf8 -c`；新增回归测试 test_logic_inspect_scripts.py；回归 211 passed（1 环境性失败与修复无关，修复前已复现） |
<!-- BUG_TABLE_END -->

---

## 巡检历史

| 日期 | 发现方式 | 新增 | 修复 | 仍开放 |
|------|---------|------|------|--------|
| 2026-07-27 | 初始化 | 0 | 0 | 0 |
| 2026-08-18 | 复盘验证 | 1 | 1(误报关闭) | 0 |
| 2026-08-26 | 逻辑巡检 | 5 | 0 | 5 |
| 2026-08-26 | auto_fix(BUG-005) | 0 | 1 | 4 |
| 2026-08-26 | 人工确认(1A/2B/3) | 0 | 2 | 2(BUG-004/006) |
| 2026-08-26 | auto_fix(BUG-004) | 0 | 1 | 1(BUG-006) |
| 2026-08-27 | auto_fix(BUG-006) | 0 | 1 | 0 |
| 2026-08-27 | 逻辑巡检 | 3 | 0 | 3(BUG-007/008/009, 均 MANUAL_REVIEW) |
| 2026-08-27 | 逻辑巡检(补记脚本缺陷) | 1 | 0 | 4(BUG-007/008/009 MANUAL_REVIEW + BUG-010 OPEN) |
| 2026-08-27 | auto_fix(BUG-010) | 0 | 1 | 3(BUG-007/008/009, 均 MANUAL_REVIEW) |

---

## 修复分支索引

| BUG ID | 分支名 | 状态 | 合并日期 |
|--------|--------|------|---------|
| - | - | - | - |
