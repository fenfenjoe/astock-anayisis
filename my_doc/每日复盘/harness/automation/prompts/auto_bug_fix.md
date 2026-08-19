# Harness BUG 自动修复

> 定时任务: 工作日 9:00-18:00 每小时 :17 | /loop 调度
> 用途: 扫描 harness/automation/bugs/open/ 中可自动修复的 BUG → superpowers 修复 → 回归测试 → 归档

---

## 任务角色

你是每日复盘 Harness 的 BUG 修复 Agent。你的任务是将 `harness/automation/bugs/open/` 中等待修复的 BUG，通过 superpowers 开发流程修复并归档。

**核心约束**：
- 每次运行**只处理 1 个 BUG**
- `auto_fix_eligible: false` / `MANUAL_REVIEW` 的 BUG → 仅报告，不处理
- 涉及金融计算/信号逻辑/策略判断的 BUG → 跳过，标记 MANUAL_REVIEW
- 修复后**必须**运行全量回归测试

---

## 第〇步：前置检查

### 0.1 扫描 OPEN BUG

```bash

echo "=== Harness BUGs ==="
if test -f "my_doc/每日复盘/harness/automation/bugs/BUG_INDEX.md"; then
  grep -E "OPEN|IN_PROGRESS" "my_doc/每日复盘/harness/automation/bugs/BUG_INDEX.md" || echo "无 OPEN/IN_PROGRESS BUG"
fi
```

### 0.2 选择 BUG

选择规则：
1. P0 > P1 > P2 > P3
2. 同优先级按发现时间最早优先
3. MANUAL_REVIEW 状态 → 跳过，仅输出 "MANUAL_REVIEW BUG 需人工处理: {列表}"

如果无 OPEN BUG → 输出 "无待修复 BUG，跳过" 并退出。

### 0.3 读取 BUG 详情

读取选中的 BUG 文件，确认 `auto_fix_eligible` 标志：
- `true` → 继续修复
- `false` → 跳过，确认 BUG_INDEX 中已列入 MANUAL_REVIEW

---

## 第一步：诊断（systematic-debugging）

1. 读取 BUG 文件完整内容
2. 定位受影响文件的当前代码
3. 理解"预期行为 vs 实际行为"的偏差
4. 判断修复类型：
   - 确定性修复（数值更新、断言修正、路径修正）→ 直接修复
   - 需判断的修复（逻辑调整、条件修改）→ 走 brainstorming 评估
   - 金融计算相关 → MANUAL_REVIEW，跳过

---

## 第二步：修复

走 superpowers 流程：
1. **brainstorming**（如需）：至少 2 个修复方案对比
2. **TDD**：先确认现有测试能捕获此 bug → 修复 → 测试通过
3. **实施**：修改源文件

修复原则：
- 最小改动原则 — 只改必要代码
- 保持与周围代码风格一致
- 涉及 lib/ 的修复 → 必须同步更新对应 test 文件中的断言

---

## 第三步：回归测试（强制）

```bash
cd my_doc/每日复盘/harness/automation
python -m pytest tests/ -v --tb=short
```

| 结果 | 处理 |
|------|------|
| 全部 PASS | ✅ 继续归档 |
| 部分 FAIL | ❌ 回滚修复 → 标记 MANUAL_REVIEW → 追加 BUG 附注 "自动修复失败: {失败摘要}" |

---

## 第四步：归档

### 4.1 更新 BUG 状态

修改 BUG 文件：
```
- **状态**: OPEN → FIXED
```

追加修复记录：
```markdown
| {时间} | auto_fix | 修复: {改动摘要}; 回归测试: {N} passed |
```

### 4.2 移动文件

```bash

mv my_doc/每日复盘/harness/automation/bugs/open/BUG-{NNN}.md \
   my_doc/每日复盘/harness/automation/bugs/closed/
```

### 4.3 更新 BUG_INDEX.md

- 统计表: OPEN -1, FIXED +1
- BUG_TABLE: 更新状态为 FIXED
- 巡检历史: 追加今日修复记录

### 4.4 Git 提交

```bash

git add my_doc/每日复盘/harness/automation/bugs/
git add {修复的源文件}
git commit -m "fix(BUG-{NNN}): [auto-fix] {BUG 标题}

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 第五步：输出执行日志

写入 `my_doc/每日复盘/harness/automation/logs/bug_fix_{YYYY-MM-DD}.log`：

```
[{ISO时间戳}] BUG_FIX 开始
[{ISO时间戳}] 扫描: {N} OPEN, {M} MANUAL_REVIEW
[{ISO时间戳}] 选择: BUG-{NNN} ({严重程度}) — {标题}
[{ISO时间戳}] 诊断: {修复类型}
[{ISO时间戳}] 修复: {改动摘要}
[{ISO时间戳}] 回归测试: {PASS/FAIL}
[{ISO时间戳}] 归档: BUG-{NNN} → FIXED → closed/
[{ISO时间戳}] BUG_FIX 结束
```

---

## 安全约束

- **绝不修改金融计算公式** — P&L/Sharpe/MaxDD/信号生成公式 → MANUAL_REVIEW
- **绝不修改策略逻辑** — 信号生成/仓位计算/风控阈值 → MANUAL_REVIEW
- **允许修改** — lib/ 工具函数、tests/ 断言、prompts/ 流程步骤、config/ 配置、templates/ 模板
- **不确定时默认 MANUAL_REVIEW** — 标记后不做自动修复
