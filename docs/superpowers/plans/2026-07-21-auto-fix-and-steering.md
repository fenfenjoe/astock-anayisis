# BUG自动修复 + 优化需求Steering 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 ETF 策略和每日复盘自动化系统增加 BUG 自动修复能力 + 优化需求 Steering 用户注入机制

**Architecture:** 本计划全部为 prompt 工程和文档修改 — 修改 3 个巡检 Prompt 增加 `auto_fix_eligible` 字段，新建 1 个自动修复 Prompt，新建 2 套 Steering 目录结构，更新 CLAUDE.md 调度表。无 Python 代码变更。

**Tech Stack:** Markdown prompts, YAML 配置, 目录结构

## Global Constraints

- 所有 A 股数据获取必须走 `a-stock-data` skill
- 自动修复不替代人类判断 — MANUAL_REVIEW BUG 必须人工确认
- 安全原则：不确定能否自动修复时默认标记 MANUAL_REVIEW
- 不破坏现有巡检 Prompt 的其余逻辑
- Steering 状态 ADOPTED/REJECTED/IMPLEMENTED 仅由用户手动设置

---

### Task 1: 更新 BUG_INDEX.md — 新增 MANUAL_REVIEW 状态和待人工审核区域

**Files:**
- Modify: `etf-strategies/automation/bugs/BUG_INDEX.md`

**Interfaces:**
- Produces: "⚠️ 待人工审核" 表格区域供自动修复 Prompt 写入

- [ ] **Step 1: 读取当前 BUG_INDEX.md**

已在上文读取，确认当前结构。

- [ ] **Step 2: 修改 BUG_INDEX.md**

在统计表的 WONT_FIX 行后增加 MANUAL_REVIEW 行；在 BUG 列表区域前插入 "⚠️ 待人工审核" 区域。

需要替换整个文件内容。使用 Edit 工具进行以下修改：

**修改 1**：在统计表中增加 MANUAL_REVIEW 行

```
old: | WONT_FIX | 0 |

new: | WONT_FIX | 0 |
     | MANUAL_REVIEW | 0 |
```

**修改 2**：在 BUG 列表区域前插入待人工审核区域

```
old: ## BUG 列表

new: ## ⚠️ 待人工审核 (MANUAL_REVIEW)

     > 以下 BUG 因涉及计算逻辑/算法正确性/金融公式，需人工审阅决定修复方案。
     > 操作: 审阅 `bugs/open/BUG-{NNN}.md`，手动执行 `bug_fix_template.md` 流程修复。

     | BUG-ID | 严重级别 | 标题 | 发现日期 | 涉及文件 | 原因 |
     |--------|---------|------|---------|---------|------|
     | (暂无) | - | - | - | - | - |

     ---

     ## BUG 列表
```

**修改 3**：更新文件头部的维护者说明

```
old: > 自动生成，由 bug_inspect_code.md 和 bug_inspect_logic.md 维护。

new: > 自动生成，由 bug_inspect_code.md、bug_inspect_logic.md、bug_inspect_data.md 和 bug_auto_fix.md 维护。
```

- [ ] **Step 3: 验证修改**

重新读取 BUG_INDEX.md，确认结构正确。

- [ ] **Step 4: Commit**

```bash
git add etf-strategies/automation/bugs/BUG_INDEX.md
git commit -m "feat: BUG_INDEX.md 新增 MANUAL_REVIEW 状态和待人工审核区域

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 修改三个巡检 Prompt — 增加 auto_fix_eligible 字段

**Files:**
- Modify: `etf-strategies/automation/prompts/bug_inspect_code.md`
- Modify: `etf-strategies/automation/prompts/bug_inspect_logic.md`
- Modify: `etf-strategies/automation/prompts/bug_inspect_data.md`

**Interfaces:**
- Produces: BUG 报告中包含 `auto_fix_eligible` 字段，供 `bug_auto_fix.md` 读取

- [ ] **Step 1: 修改 bug_inspect_code.md — BUG 报告模板**

在第六步"生成 BUG 报告"的 BUG 报告模板中，在"状态: OPEN"行后增加 `auto_fix_eligible` 字段和判定决策树。

```
old: - **状态**: OPEN
     - **发现时间**: {ISO时间戳}

new: - **状态**: OPEN
     - **auto_fix_eligible**: true | false
       - 判定: 注册遗漏/路径硬编码/导入缺失/测试缺失 → true
       - 判定: 涉及计算公式/算法逻辑/策略行为 → false
       - 判定: 不确定 → false（安全原则）
     - **发现时间**: {ISO时间戳}
```

- [ ] **Step 2: 修改 bug_inspect_logic.md — BUG 报告模板**

在第���步"生成 BUG 报告"中，说明 BUG 报告格式同代码巡检（已包含 auto_fix_eligible）。额外增加提示：逻辑巡检发现的 BUG 通常涉及策略逻辑/算法缺陷，`auto_fix_eligible` 默认为 `false`。

在第五步末尾追加：

```markdown
**注意**：逻辑巡检发现的 BUG 默认 `auto_fix_eligible: false`，因为涉及策略逻辑判断和金融算法。仅在极少数机械性错误（如笔误 `>` 写成 `<` 且有明确 KB 佐证）时标记为 `true`。
```

- [ ] **Step 3: 修改 bug_inspect_data.md — BUG 报告模板**

在第五步"生成 BUG 报告"中，说明格式同代码巡检。增加数据质量特有的判定规则提示：

```markdown
**auto_fix_eligible 判定**：
- 缓存过期需要重新拉取 → true（自动执行 `a-stock-data` 重拉）
- 跨源价差 >0.5% 需排查根因 → false（需判断哪个源正确）
- 数据缺失需补拉 → true（自动执行数据拉取）
- 异常价格跳动疑似除权 → false（需判断是除权还是数据错误）
```

- [ ] **Step 4: Commit**

```bash
git add etf-strategies/automation/prompts/bug_inspect_code.md etf-strategies/automation/prompts/bug_inspect_logic.md etf-strategies/automation/prompts/bug_inspect_data.md
git commit -m "feat: 三个巡检Prompt增加 auto_fix_eligible 字段

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 创建 bug_auto_fix.md — BUG 自动修复 Prompt

**Files:**
- Create: `etf-strategies/automation/prompts/bug_auto_fix.md`

**Interfaces:**
- Consumes: `bugs/open/BUG-{NNN}.md` 中的 `auto_fix_eligible` 字段
- Consumes: `bugs/BUG_INDEX.md` 获取 OPEN BUG 列表
- Produces: `bugs/archive/AUTO_FIX_REPORT_{YYYY-MM-DD}_{HH-mm}.md`
- Produces: 更新 BUG 报告状态、移动文件、更新 BUG_INDEX.md

- [ ] **Step 1: 创建 bug_auto_fix.md**

```markdown
# BUG 自动修复（每小时）

> 定时任务: 每小时 :07 | CronCreate durable
> 用途: 扫描 OPEN BUG → AUTO_FIX 自动修复 → MANUAL_REVIEW 标记 → 生成修复报告

---

## 任务角色

你是量化系统的自动修复工兵。你的任务是扫描所有 OPEN 状态的 BUG，对 `auto_fix_eligible=true` 的 BUG 执行自动修复，对 `auto_fix_eligible=false` 的 BUG 标记为 MANUAL_REVIEW。

---

## 第一步：扫描 OPEN BUG

读取 `etf-strategies/automation/bugs/BUG_INDEX.md`，提取所有 OPEN 状态的 BUG ID。

如果 OPEN BUG 数量 = 0 → 输出 "无待处理 BUG，跳过" 并退出（不生成报告，仅写日志）。

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
   - 测试失败 或 修复引入新问题 → **修复失败**，回滚修改，状态 → MANUAL_REVIEW
5. **提交修复**：
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

- 修复过程中发现新的关联问题 → 创建新 BUG 报告，标记 Related
- 修复导致其他测试失败 → 自动回滚，在报告中记录
- BUG_INDEX.md 损坏 → 从 `bugs/open/` 和 `bugs/closed/` 重建索引
- git 操作失败（如冲突）→ 跳过该 BUG，标记为 MANUAL_REVIEW，记录失败原因

---

## 安全约束

- **绝不修改金融计算公式** — 任何涉及年化收益/Sharpe/MaxDD/信号生成公式的代码
- **绝不修改策略逻辑** — 涉及信号生成/仓位计算/风控阈值的代码
- **允许修改** — 注册/导入/路径/配置/测试/文档
- **不确定时默认不修** — auto_fix_eligible 已为 false 的绝不尝试修复
```

- [ ] **Step 2: 创建 bugs/archive/ 目录**

```bash
mkdir -p E:/ideaworkspace/astock-anayisis/etf-strategies/automation/bugs/archive/
```

在 archive/ 目录下创建一个 `.gitkeep` 文件，确保空目录被 git 追踪。

- [ ] **Step 3: Commit**

```bash
git add etf-strategies/automation/prompts/bug_auto_fix.md etf-strategies/automation/bugs/archive/.gitkeep
git commit -m "feat: 创建 BUG 自动修复 Prompt (每小时执行)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 创建 ETF 策略 Steering 系统

**Files:**
- Create: `etf-strategies/automation/steering/REQ_TEMPLATE.md`
- Create: `etf-strategies/automation/steering/REQ_INDEX.md`
- Create: `etf-strategies/automation/steering/open/.gitkeep`
- Create: `etf-strategies/automation/steering/in_progress/.gitkeep`
- Create: `etf-strategies/automation/steering/closed/.gitkeep`

- [ ] **Step 1: 创建目录结构**

```bash
mkdir -p E:/ideaworkspace/astock-anayisis/etf-strategies/automation/steering/{open,in_progress,closed}
```

- [ ] **Step 2: 创建 REQ_TEMPLATE.md**

```markdown
# REQ-{NNN}: {标题}

- **创建时间**: YYYY-MM-DD HH:MM
- **优先级**: P0(紧急) | P1(高) | P2(中) | P3(低)
- **影响范围**: 代码巡检 | 逻辑审计 | 数据质量 | 策略发现 | 其他
- **状态**: OPEN

## 需求描述

（详细描述优化需求的内容，越具体越好）

## 期望结果

（描述期望达到的效果，尽量可衡量）

## 约束/注意事项

（如有特殊约束，在此说明）

## 处理记录

| 时间 | 操作 | 备注 |
|------|------|------|
| YYYY-MM-DD | 创建 | - |
```

- [ ] **Step 3: 创建 REQ_INDEX.md**

```markdown
# ETF 策略优化需求索引

> 最后更新: (尚无需求)

## 状态汇总

| 状态 | 数量 |
|------|------|
| OPEN | 0 |
| IN_PROGRESS | 0 |
| ADOPTED | 0 |
| REJECTED | 0 |
| IMPLEMENTED | 0 |

## 需求列表

| ID | 标题 | 优先级 | 影响范围 | 状态 | 创建日期 |
|----|------|--------|---------|------|---------|
| (暂无) | - | - | - | - | - |

---

## 使用说明

1. 在 `open/` 下按 `REQ_TEMPLATE.md` 模板创建新需求文件
2. 在本文件的需求列表中新增对应条目
3. 自动化任务执行时自动读取 open/ 中的需求并纳入工作范围
4. 需求状态变迁: OPEN → IN_PROGRESS (自动) → ADOPTED / REJECTED / IMPLEMENTED (人工确认)
```

- [ ] **Step 4: Commit**

```bash
git add etf-strategies/automation/steering/
git commit -m "feat: 创建 ETF 策略 Steering 系统

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 创建每日复盘 Steering 系统

**Files:**
- Create: `my_doc/每日复盘/harness/automation/steering/REQ_TEMPLATE.md`
- Create: `my_doc/每日复盘/harness/automation/steering/REQ_INDEX.md`
- Create: `my_doc/每日复盘/harness/automation/steering/open/.gitkeep`
- Create: `my_doc/每日复盘/harness/automation/steering/in_progress/.gitkeep`
- Create: `my_doc/每日复盘/harness/automation/steering/closed/.gitkeep`

- [ ] **Step 1: 创建目录结构**

```bash
mkdir -p E:/ideaworkspace/astock-anayisis/my_doc/每日复盘/harness/automation/steering/{open,in_progress,closed}
```

- [ ] **Step 2: 创建 REQ_TEMPLATE.md**

```markdown
# REQ-{NNN}: {标题}

- **创建时间**: YYYY-MM-DD HH:MM
- **优先级**: P0(紧急) | P1(高) | P2(中) | P3(低)
- **影响范围**: 早盘分析 | 盘中检查 | 收盘复盘 | 周度回顾 | 经验健康 | 其他
- **状态**: OPEN

## 需求描述

（详细描述优化需求的内容，越具体越好）

## 期望结果

（描述期望达到的效果，尽量可衡量）

## 约束/注意事项

（如有特殊约束，在此说明）

## 处理记录

| 时间 | 操作 | 备注 |
|------|------|------|
| YYYY-MM-DD | 创建 | - |
```

- [ ] **Step 3: 创建 REQ_INDEX.md**

```markdown
# 每日复盘优化需求索引

> 最后更新: (尚无需求)

## 状态汇总

| 状态 | 数量 |
|------|------|
| OPEN | 0 |
| IN_PROGRESS | 0 |
| ADOPTED | 0 |
| REJECTED | 0 |
| IMPLEMENTED | 0 |

## 需求列表

| ID | 标题 | 优先级 | 影响范围 | 状态 | 创建日期 |
|----|------|--------|---------|------|---------|
| (暂无) | - | - | - | - | - |

---

## 使用说明

1. 在 `open/` 下按 `REQ_TEMPLATE.md` 模板创建新需求文件
2. 在本文件的需求列表中新增对应条目
3. 自动化任务执行时自动读取 open/ 中的需求并纳入工作范围
4. 需求状态变迁: OPEN → IN_PROGRESS (自动) → ADOPTED / REJECTED / IMPLEMENTED (人工确认)
```

- [ ] **Step 4: Commit**

```bash
git add my_doc/每日复盘/harness/automation/steering/
git commit -m "feat: 创建每日复盘 Steering 系统

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 更新 CLAUDE.md — 调度表 + Steering 说明

**Files:**
- Modify: `CLAUDE.md` (lines 170-208)

**Interfaces:**
- 文档变更，无代码接口

- [ ] **Step 1: 在 §7.2 的调度表中新增自动修复行**

在"策略发现"行之后插入新行：

```
old: | 策略发现 | 每周六 10:00 | `strategy_scan_weekly.md` | 各平台搜索→筛选→去重→输出候选 |

new: | 策略发现 | 每周六 10:00 | `strategy_scan_weekly.md` | 各平台搜索→筛选→去重→输出候选 |
     | **BUG自动修复** | **每小时 :07** | `bug_auto_fix.md` | 扫描OPEN BUG → AUTO_FIX修复 → MANUAL_REVIEW标记 → 生成报告 |
```

- [ ] **Step 2: 修改 §7.2 BUG 管理描述**

将当前 BUG 管理描述更新为包含自动修复：

```
old: **BUG 管理**：巡检Prompt只负责发现+记录（`bugs/open/BUG-{NNN}.md`），修复需人工触发 `bug_fix_template.md`。采用 Git 分支 `bugfix/BUG-{NNN}-{desc}` + 规范commit。BUG 生命周期：OPEN → IN_PROGRESS → FIXED → VERIFIED。

new: **BUG 管理**：巡检Prompt负责发现+记录（`bugs/open/BUG-{NNN}.md`），并标记 `auto_fix_eligible`。自动修复任务（`bug_auto_fix.md`，每小时 :07）扫描 OPEN BUG：
     - `auto_fix_eligible=true` → 自动修复 → 测试通过则 FIXED，失败则升级为 MANUAL_REVIEW
     - `auto_fix_eligible=false` → 标记 MANUAL_REVIEW，展现在 `BUG_INDEX.md` "⚠️ 待人工审核" 区域
     - MANUAL_REVIEW BUG 需人工执行 `bug_fix_template.md` 修复流程
     - 采用 Git 分支 `bugfix/BUG-{NNN}-{desc}` + 规范commit
     - BUG 生命周期：OPEN → (自动修复) → FIXED / MANUAL_REVIEW → IN_PROGRESS → FIXED → VERIFIED
```

- [ ] **Step 3: 在 §7.2 末尾新增 §7.2.1 Steering 小节**

在 "正确性定义" 段落后、"### 7.3 每日复盘自动化调度" 之前插入：

```markdown
    ### 7.2.1 优化需求 Steering

    用户可通过 `etf-strategies/automation/steering/` 注入优化需求，把控自动化迭代方向。

    - **创建需求**：在 `steering/open/` 下按 `REQ_TEMPLATE.md` 模板创建 `REQ-{NNN}.md`，并在 `REQ_INDEX.md` 中登记
    - **自动集成**：巡检/修复/发现任务执行时自动读取 `steering/open/` 中待处理需求，纳入工作范围
    - **状态管理**：OPEN → IN_PROGRESS (自动化任务自动推进) → ADOPTED/REJECTED/IMPLEMENTED (用户人工确认)

    每日复盘项目同样有独立的 steering 目录：`my_doc/每日复盘/harness/automation/steering/`。
```

- [ ] **Step 4: 更新 §7.5 关键纪律**

将"自动化不替代人类判断"条目更新：

```
old: - **自动化不替代人类判断**：BUG 只发现不自动修复；策略发现绿灯候选需要人工确认后才转化

new: - **自动化不替代人类判断**：MANUAL_REVIEW BUG 必须人工确认；策略发现绿灯候选需要人工确认后才转化
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md 更新 — 新增自动修复任务调度 + Steering 系统说明

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: 更新 CHAT.md — 标记需求完成

**Files:**
- Modify: `CHAT.md`

- [ ] **Step 1: 替换 CHAT.md 内容**

将当前内容替换为完成记录：

```
old: 我希望巡检发现BUG后，也会自动修复BUG。并且要有报告。

     这2个项目在配置了loop相关的架构之后，我理解它们便会自动迭代&优化功能。
     但有时我希望把控迭代的方向，可能会给之后的优化提一些优化建议、优化需求，因此需要提供一种方式让我能在过程中提需求。

new: ✅ 已完成 (2026-07-21)

     1. BUG自动修复: `etf-strategies/automation/prompts/bug_auto_fix.md` — 每小时 :07 执行，auto_fix_eligible=true 自动修，false 标记 MANUAL_REVIEW 待人工审核。报告 → `bugs/archive/AUTO_FIX_REPORT_*.md`
     2. 优化需求Steering: `etf-strategies/automation/steering/` 和 `my_doc/每日复盘/harness/automation/steering/` — 按模板创建需求文件，自动化任务自动读取并纳入工作范围
```

- [ ] **Step 2: Commit**

```bash
git add CHAT.md
git commit -m "docs: CHAT.md 标记 BUG自动修复+Steering 需求完成

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: 最终验证

- [ ] **Step 1: 验证所有新文件存在**

```bash
ls -la etf-strategies/automation/prompts/bug_auto_fix.md
ls -la etf-strategies/automation/bugs/archive/
ls -la etf-strategies/automation/steering/REQ_INDEX.md
ls -la etf-strategies/automation/steering/REQ_TEMPLATE.md
ls -la my_doc/每日复盘/harness/automation/steering/REQ_INDEX.md
ls -la my_doc/每日复盘/harness/automation/steering/REQ_TEMPLATE.md
```

- [ ] **Step 2: 验证 git log 包含所有 commit**

```bash
git log --oneline -8
```

- [ ] **Step 3: Summarize完成状态**
