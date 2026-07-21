# BUG 自动修复（每小时）

> 定时任务: 每小时 :07 | CronCreate durable
> 用途: 扫描 OPEN BUG → AUTO_FIX 自动修复 → MANUAL_REVIEW 标记 → 生成修复报告

---

## 任务角色

你是量化系统的自动修复工兵。你的任务是扫描所有 OPEN 状态的 BUG，对 `auto_fix_eligible=true` 的 BUG 执行自动修复，对 `auto_fix_eligible=false` 的 BUG 标记为 MANUAL_REVIEW。

---

## 第一步：扫描 OPEN BUG

读取 `etf-strategies/automation/bugs/BUG_INDEX.md`，提取所有 OPEN 状态的 BUG ID。

如果 OPEN BUG 数量 = 0 → 输出 "无待处理 BUG，跳过" 并退出（不生成报告，仅写执行日志）。

---

## 第二步：逐个处理 BUG

对每个 OPEN BUG：

### 2.1 读取 BUG 报告

读取 `etf-strategies/automation/bugs/open/BUG-{NNN}.md`，提取：
- `auto_fix_eligible` 字段值
- 受影响文件列表
- 预期行为和实际行为
- 建议修复方向

### 2.2 决策分支

**如果 `auto_fix_eligible: true`**：

1. **备份**：在内存中记录当前文件内容（以便回滚）
2. **实施修复**：
   - 读取受影响文件
   - 根据预期行为 + 建议修复方向实施最小变更
   - 仅修改必要的行，不引入无关改动
3. **运行测试验证**：
   ```bash
   cd E:/ideaworkspace/astock-anayisis/etf-strategies
   # 运行 BUG 关联的测试（如果有）
   python -m pytest tests/ -v -k "test_backtest or test_strategies" --tb=short 2>&1 | tail -30
   # 运行全量回归
   python -m pytest tests/ -v --tb=short 2>&1 | tail -30
   ```
4. **结果判定**：
   - 测试全部通过 + 修复逻辑正确 → **修复成功**，状态 → FIXED
   - 测试失败 或 修复引入新问题 → **修复失败**，回滚修改，状态 → MANUAL_REVIEW（在 BUG 报告中追加失败原因）
5. **提交修复**（仅修复成功时）：
   ```bash
   cd E:/ideaworkspace/astock-anayisis
   git add {修改的文件}
   git commit -m "fix(BUG-{NNN}): [auto-fix] {一句话描述}

   - 自动修复由 bug_auto_fix.md 执行
   - 验证: {测试结果}

   Co-Authored-By: Claude <noreply@anthropic.com>"
   ```
6. **移动 BUG 报告**：
   - 成功: 更新 BUG 报告状态为 FIXED，移动到 `bugs/closed/BUG-{NNN}.md`
   - 失败: 更新 BUG 报告状态为 MANUAL_REVIEW，附上失败原因，保留在 `bugs/open/`

**如果 `auto_fix_eligible: false`**：

1. 更新 BUG 报告状态从 OPEN → MANUAL_REVIEW
2. 在 BUG 报告中追加：
   ```markdown
   ## 自动修复判定
   - **判定时间**: {ISO时间戳}
   - **判定结果**: 不自动修复 — 涉及计算逻辑/算法/金融公式
   - **建议**: 人工审阅后执行 bug_fix_template.md 流程
   ```
3. 保留在 `bugs/open/`（状态已改为 MANUAL_REVIEW）

---

## 第三步：更新 BUG_INDEX.md

1. 更新统计表中各状态数量
2. 更新 "⚠️ 待人工审核" 表格：
   - 新增 MANUAL_REVIEW 条目
   - 移除已修复为 FIXED 的条目（移到下方 BUG 列表且状态为 FIXED）
3. BUG 列表表中更新状态

---

## 第四步：生成自动修复报告

仅当本轮有实质修复操作（修复成功/失败/标记 MANUAL_REVIEW）时生成报告。

保存到 `etf-strategies/automation/bugs/archive/AUTO_FIX_REPORT_{YYYY-MM-DD}_{HH-mm}.md`：

```markdown
# 自动修复报告 — {YYYY-MM-DD} {HH:mm}

## 本轮扫描
- 扫描时间: {ISO时间戳}
- 发现 OPEN BUG: N 个
- AUTO_FIX 候选: M 个
- MANUAL_REVIEW 候选: K 个

## 自动修复结果

| BUG-ID | 标题 | 结果 | 详情 |
|--------|------|------|------|
| BUG-001 | 新策略未注册 | ✅ FIXED | 已添加 import |
| BUG-002 | 缓存路径硬编码 | ✅ FIXED | 已改为 cache/ |
| BUG-003 | 测试覆盖率低 | ❌ UPGRADED→MANUAL_REVIEW | 自动生成测试失败 |

## 升级到人工审核

| BUG-ID | 标题 | 原因 |
|--------|------|------|
| BUG-003 | 测试覆盖率低 | 自动生成测试未通过 |
| BUG-004 | 信号滞后计算错误 | 引擎算法（auto_fix_eligible=false） |

## 执行日志
- {时间戳} 扫描到 N 个 OPEN BUG
- {时间戳} BUG-001: auto_fix → 修复成功 → FIXED
- {时间戳} BUG-002: auto_fix → 修复成功 → FIXED
- {时间戳} BUG-003: auto_fix → 测试失败 → MANUAL_REVIEW
- {时间戳} BUG-004: manual_review → MANUAL_REVIEW
- {时间戳} 更新 BUG_INDEX.md 完成
```

---

## 第五步：写执行日志

写入 `etf-strategies/automation/logs/auto_fix_{YYYY-MM-DD}.log`：

```
[{ISO时间戳}] AUTO_FIX 开始 — OPEN: N, AUTO_FIX: M, MANUAL_REVIEW: K
[{ISO时间戳}] BUG-001: FIXED
[{ISO时间戳}] BUG-002: FIXED
[{ISO时间戳}] BUG-003: MANUAL_REVIEW (修复失败)
[{ISO时间戳}] BUG-004: MANUAL_REVIEW (不可自动修复)
[{ISO时间戳}] AUTO_FIX 结束 — FIXED: 2, MANUAL_REVIEW: 2
```

---

## 异常处理

- 修复过程中发现新的关联问题 → 创建新 BUG 报告，标记 "Related: BUG-{new_NNN}"
- 修复导致其他测试失败 → 自动回滚，在报告中记录失败的尝试
- BUG_INDEX.md 损坏 → 从 `bugs/open/` 和 `bugs/closed/` 重建索引
- git 操作失败（如冲突）→ 跳过该 BUG，标记为 MANUAL_REVIEW，记录失败原因

---

## 安全约束

- **绝不修改金融计算公式** — 任何涉及年化收益/Sharpe/MaxDD/信号生成公式的代码
- **绝不修改策略逻辑** — 涉及信号生成/仓位计算/风控阈值的代码
- **允许修改** — 注册/导入/路径/配置/测试/文档
- **不确定时默认不修** — `auto_fix_eligible` 已为 `false` 的绝不尝试修复
