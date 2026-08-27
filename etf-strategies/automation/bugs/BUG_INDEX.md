# BUG 索引

> 自动生成，由 bug_inspect_code.md、bug_inspect_logic.md、bug_inspect_data.md 和 bug_auto_fix.md 维护。
> 状态: OPEN | IN_PROGRESS | FIXED | VERIFIED | WONT_FIX | DUPLICATE

---

## 统计

| 状态 | 数量 |
|------|------|
| OPEN | 0 |
| IN_PROGRESS | 0 |
| FIXED | 3 |
| VERIFIED | 1 |
| WONT_FIX | 1 |
| MANUAL_REVIEW | 1 |

---

## ⚠️ 待人工审核 (MANUAL_REVIEW)

> 以下 BUG 因涉及计算逻辑/算法正确性/金融公式，需人工审阅决定修复方案。
> 操作: 审阅 `bugs/open/BUG-{NNN}.md`，手动执行 `bug_fix_template.md` 流程修复。

| BUG-ID | 标题 | 原因 |
|--------|------|------|
| BUG-005 | 胜率计算分母与正确性定义不符（非零收益天数 vs 总交易日数） | 指标口径决策（MET-005），auto_fix_eligible=false |

---

## BUG 列表

<!-- BUG 条目由自动巡检脚本追加在下方 -->

<!-- BUG_TABLE_START -->
| BUG-001 | Dashboard同步测试策略计数不匹配 | tests | MEDIUM | VERIFIED | 2026-07-23 |
| BUG-002 | 3个已注册策略(S14/S15/S16/S17)无专项测试，覆盖率<40% | strategies | MEDIUM | FIXED | 2026-08-10 |
| BUG-003 | 动量家族R²截断不一致:S4/S8未用max(r_sq,0),其余已截断 | strategies | LOW | WONT_FIX | 2026-08-10 |
| BUG-004 | cache/512100.parquet缓存过期(2026-07-22,>24h) | data | MEDIUM | FIXED | 2026-08-27 |
| BUG-005 | 胜率计算分母与正确性定义不符(非零收益天数vs总交易日数) | metrics | MEDIUM | MANUAL_REVIEW | 2026-08-27 |
| BUG-006 | 正确性定义引用的6个测试节点不存在,reporting.py覆盖率0% | tests | MEDIUM | FIXED | 2026-08-27 |
<!-- BUG_TABLE_END -->

---

## 巡检历史

| 日期 | 巡检类型 | 新增 | 修复 | 仍开放 |
|------|---------|------|------|--------|
| 2026-07-23 | 代码巡检 | 1 | 1 | 0 |
| 2026-07-24 | 代码巡检 | 0 | 0 | 0 |
| 2026-07-27 | 代码巡检 | 0 | 0 | 0 |
| 2026-07-27 | 逻辑巡检 | 0 | 0 | 0 |
| 2026-08-07 | 代码巡检 | 0 | 0 | 0 |
| 2026-08-10 | 代码巡检 | 1 | 0 | 1 |
| 2026-08-10 | 逻辑巡检 | 1 | 0 | 2 |
| 2026-08-10 | 自动修复 | 0 | 1 | 1 |
| 2026-08-10 | 人工审阅 | 0 | 1 | 0 |
| 2026-08-27 | 数据巡检 | 1 | 0 | 1 |
| 2026-08-27 | 代码巡检 | 2 | 0 | 3 |
| 2026-08-27 | 自动修复 | 0 | 2 | 1 |

---

## 修复分支索引

| BUG ID | 分支名 | 状态 | 合并日期 |
|--------|--------|------|---------|
| - | - | - | - |
