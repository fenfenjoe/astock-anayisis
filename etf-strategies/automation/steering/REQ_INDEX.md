# ETF 策略优化需求索引

> 最后更新: 2026-09-03

## 状态汇总

| 状态 | 数量 |
|------|------|
| OPEN | 1 |
| IN_PROGRESS | 0 |
| IMPLEMENTED | 0 |
| CLOSED | 0 |
| ADOPTED | 0 |
| REJECTED | 0 |

## 需求列表

| ID | 标题 | 优先级 | 影响范围 | 状态 | 创建日期 |
|----|------|--------|---------|------|---------|
| REQ-001 | 数据刷新流程防护 — 收盘后强制补全当日 bar + 非活跃/持仓标的定期刷新 | P1 | 数据质量 | OPEN | 2026-09-03 |

---

## 使用说明

1. 在 `open/` 下按 `REQ_TEMPLATE.md` 模板创建新需求文件
2. 在本文件的需求列表中新增对应条目
3. 自动化任务执行时自动读取 `open/` 中的需求并纳入工作范围
4. 需求状态变迁: OPEN → IN_PROGRESS (自动化任务自动推进) → IMPLEMENTED (代码已写) → CLOSED (测试通过+用户确认)
   - ADOPTED: 需求被采纳但无需代码实现（如流程改进）
   - REJECTED: 任何阶段均可拒绝
5. **实施必须走 superpowers 流程**（见 REQ_TEMPLATE.md）：brainstorming → writing-plans → TDD → executing-plans → code-review
6. 缺少测试的需求不得推进到 CLOSED，最高停留在 IMPLEMENTED
