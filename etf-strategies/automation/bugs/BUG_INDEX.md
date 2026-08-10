# BUG 索引

> 自动生成，由 bug_inspect_code.md、bug_inspect_logic.md、bug_inspect_data.md 和 bug_auto_fix.md 维护。
> 状态: OPEN | IN_PROGRESS | FIXED | VERIFIED | WONT_FIX | DUPLICATE

---

## 统计

| 状态 | 数量 |
|------|------|
| OPEN | 0 |
| IN_PROGRESS | 0 |
| VERIFIED | 1 |
| WONT_FIX | 1 |
| MANUAL_REVIEW | 0 |

---

## ⚠️ 待人工审核 (MANUAL_REVIEW)

> 以下 BUG 因涉及计算逻辑/算法正确性/金融公式，需人工审阅决定修复方案。
> 操作: 审阅 `bugs/open/BUG-{NNN}.md`，手动执行 `bug_fix_template.md` 流程修复。

当前无待人工审核 BUG。

---

## BUG 列表

<!-- BUG 条目由自动巡检脚本追加在下方 -->

<!-- BUG_TABLE_START -->
| BUG-001 | Dashboard同步测试策略计数不匹配 | tests | MEDIUM | VERIFIED | 2026-07-23 |
| BUG-002 | 3个已注册策略(S14/S15/S16/S17)无专项测试，覆盖率<40% | strategies | MEDIUM | FIXED | 2026-08-10 |
| BUG-003 | 动量家族R²截断不一致:S4/S8未用max(r_sq,0),其余已截断 | strategies | LOW | WONT_FIX | 2026-08-10 |
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

---

## 修复分支索引

| BUG ID | 分支名 | 状态 | 合并日期 |
|--------|--------|------|---------|
| - | - | - | - |
