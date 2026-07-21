✅ 已完成 (2026-07-21)

1. **BUG自动修复**: `etf-strategies/automation/prompts/bug_auto_fix.md` — 每小时 :07 执行
   - `auto_fix_eligible=true` → 自动修复 → 测试通过→FIXED，失败→MANUAL_REVIEW
   - `auto_fix_eligible=false` → 标记 MANUAL_REVIEW，展现在 `BUG_INDEX.md` "⚠️ 待人工审核" 区域
   - 报告归档: `bugs/archive/AUTO_FIX_REPORT_*.md`

2. **优化需求Steering**: 
   - ETF策略: `etf-strategies/automation/steering/` — 按 `REQ_TEMPLATE.md` 创建需求，自动化任务自动读取
   - 每日复盘: `my_doc/每日复盘/harness/automation/steering/` — 同上
   - 状态流: OPEN → IN_PROGRESS (自动) → ADOPTED/REJECTED/IMPLEMENTED (人工确认)