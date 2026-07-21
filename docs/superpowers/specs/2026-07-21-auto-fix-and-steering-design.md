# BUG 自动修复 + 优化需求 Steering 系统设计

**日期**: 2026-07-21
**状态**: approved

---

## 1. 背景与目标

当前 `etf-strategies/automation/` 和 `每日复盘/harness/automation/` 两个自动化系统已实现巡检发现 BUG + 人工触发修复的闭环。用户提出两个改进需求：

1. **BUG 自动修复**：巡检发现 BUG 后，系统自动判断可否自动修复并执行，减少人工介入
2. **优化需求 Steering**：提供一种机制让用户在自动化迭代过程中注入优化建议和需求，把控迭代方向

---

## 2. BUG 自动修复系统

### 2.1 自动修复分层

| 层级 | 判定条件 | 示例 | 处理方式 |
|------|---------|------|---------|
| AUTO_FIX | 机械性、确定性修复，不涉及计算逻辑 | REG-001~004 注册遗漏、DAT-005 路径配置、DASH-002 表结构 | 自动修复 → 跑测试 → 成功则 FIXED，失败则升级到 MANUAL_REVIEW |
| MANUAL_REVIEW | 涉及金融计算、逻辑判断、算法正确性 | ENG-001~004 计算逻辑、MET-001~006 指标公式、STR-003 未来数据泄露 | 记录到 BUG_INDEX.md "⚠️ 待人工审核"区域 |

### 2.2 触发时机

- **巡检任务**：按现有频率执行（代码巡检每日 02:00，逻辑审计每周日 02:00，数据质量交易日 08:00）
- **自动修复任务**：**每小时执行**（minute=7，即 `7 * * * *`），独立 cron job
  - 选择 minute=7 以错开整点高峰，且不与巡检任务的 02:00/08:00 冲突
  - 巡检任务在 02:00 执行，自动修复 03:07 即可覆盖；下一次 04:07、05:07...持续扫描

### 2.3 架构流程

```
巡检任务 → 发现BUG
  → 记录 bugs/open/BUG-{NNN}.md
  → 标记 auto_fix_eligible: true | false

自动修复任务（7 * * * *）:
  → 扫描 bugs/open/ 中所有 OPEN BUG
  → auto_fix_eligible=true
      → 自动修复 → 跑测试验证
      → 成功: 状态 → FIXED, 移动到 bugs/closed/
      → 失败: 状态 → MANUAL_REVIEW, 保留在 bugs/open/
  → auto_fix_eligible=false
      → 状态 → MANUAL_REVIEW, 保留在 bugs/open/
  → 有实质工作时生成 AUTO_FIX_REPORT.md 到 bugs/archive/
  → 空闲轮次仅写执行日志
```

### 2.4 auto_fix_eligible 判定规则

由巡检 Prompt 在发现 BUG 时执行以下决策树：

```
1. 涉及金融计算公式？ → true → MANUAL_REVIEW
2. 涉及算法逻辑/边界条件？ → true → MANUAL_REVIEW
3. 涉及未来数据泄露？ → true → MANUAL_REVIEW
4. 涉及注册/配置/测试覆盖/导入/路径？ → true → AUTO_FIX
5. 涉及 Dashboard 表结构/认证流程？ → true → AUTO_FIX（确定性修改）
6. 不确定 → MANUAL_REVIEW（安全原则）
```

### 2.5 新增/修改文件清单

**新增**：
- `etf-strategies/automation/prompts/bug_auto_fix.md` — 自动修复 Prompt

**修改**：
- `etf-strategies/automation/bugs/BUG_INDEX.md` — 顶部新增 "⚠️ 待人工审核" 区域
- `etf-strategies/automation/prompts/bug_inspect_code.md` — BUG 报告增加 `auto_fix_eligible` 字段
- `etf-strategies/automation/prompts/bug_inspect_logic.md` — BUG 报告增加 `auto_fix_eligible` 字段
- `etf-strategies/automation/prompts/bug_inspect_data.md` — BUG 报告增加 `auto_fix_eligible` 字段
- `CLAUDE.md` §7.2 — 新增自动修复任务调度
- `.claude/settings.json` — 新增 `bug_auto_fix` cron hook（若 session start hook 已存在则修改之）

### 2.6 BUG_INDEX.md "待人工审核"区域设计

```markdown
## ⚠️ 待人工审核 (MANUAL_REVIEW)

| BUG-ID | 严重级别 | 标题 | 发现日期 | 涉及文件 | 原因 |
|--------|---------|------|---------|---------|------|
| BUG-004 | CRITICAL | RSRS计算除零未处理 | 2026-07-22 | rsrs_momentum.py | 涉及计算逻辑 |
| BUG-007 | HIGH | 回测引擎信号滞后2天 | 2026-07-23 | engine.py | 涉及引擎算法 |

> **操作**: 审阅 bug report (`bugs/open/BUG-{NNN}.md`)，如需手动修复，执行 `bug_fix_template.md` 流程
```

### 2.7 AUTO_FIX_REPORT.md 格式

```markdown
# 自动修复报告 — 2026-07-22 03:07

## 本轮扫描
- 扫描时间: 2026-07-22 03:07:00
- 发现 OPEN BUG: 5 个
- AUTO_FIX 候选: 3 个
- MANUAL_REVIEW 候选: 2 个

## 自动修复结果

| BUG-ID | 标题 | 结果 | 详情 |
|--------|------|------|------|
| BUG-001 | 新策略未注册到 run_backtest.py | ✅ FIXED | 已添加 import 和注册 |
| BUG-002 | 缓存路径硬编码为 /tmp | ✅ FIXED | 已改为 cache/ |
| BUG-003 | 测试覆盖率低于阈值 | ❌ UPGRADED→MANUAL_REVIEW | 自动生成的测试未通过，需人工介入 |

## 升级到人工审核

| BUG-ID | 标题 | 原因 |
|--------|------|------|
| BUG-003 | 测试覆盖率低于阈值 | 自动生成测试未通过 |
| BUG-004 | RSRS计算除零未处理 | 计算逻辑，禁止自动修复 |
| BUG-005 | 回测引擎信号滞后 | 引擎算法，禁止自动修复 |
```

---

## 3. 优化需求 Steering 系统

### 3.1 设计原则

- **文件投递 + 队列管理**：每个需求独立文件，有状态生命周期，可追溯
- **非侵入集成**：自动化任务执行时检查待处理需求，纳入工作范围
- **双项目对称**：ETF 策略和每日复盘各自有独立的 steering 目录

### 3.2 目录结构

```
etf-strategies/automation/steering/
├── REQ_INDEX.md           # 需求索引（状态汇总表）
├── REQ_TEMPLATE.md        # 需求模板（用户参考）
├── open/                  # 待处理需求 REQ-{NNN}.md
├── in_progress/           # 处理中
└── closed/                # 已采纳/已拒绝/已实现
```

每日复盘项目同理：
```
my_doc/每日复盘/harness/automation/steering/
├── REQ_INDEX.md
├── REQ_TEMPLATE.md
├── open/
├── in_progress/
└── closed/
```

### 3.3 需求模板

```markdown
# REQ-{NNN}: {标题}

- **创建时间**: YYYY-MM-DD HH:MM
- **优先级**: P0(紧急) | P1(高) | P2(中) | P3(低)
- **影响范围**: 代码巡检 | 逻辑审计 | 数据质量 | 策略发现 | 每日复盘 | 其他
- **状态**: OPEN

## 需求描述
（详细描述优化需求的内容）

## 期望结果
（描述期望达到的效果）

## 约束/注意事项
（如有特殊约束，在此说明）

## 处理记录
| 时间 | 操作 | 备注 |
|------|------|------|
| YYYY-MM-DD | 创建 | - |
```

### 3.4 状态生命周期

```
OPEN → IN_PROGRESS → ADOPTED    （已采纳，纳入工作）
                   → REJECTED   （经分析不接受）
                   → IMPLEMENTED（已实现并验证）
```

### 3.5 REQ_INDEX.md 格式

```markdown
# 优化需求索引

> 最后更新: YYYY-MM-DD HH:MM

## 状态汇总
| 状态 | 数量 |
|------|------|
| OPEN | 2 |
| IN_PROGRESS | 1 |
| ADOPTED | 0 |
| REJECTED | 0 |
| IMPLEMENTED | 3 |

## 需求列表

| ID | 标题 | 优先级 | 影响范围 | 状态 | 创建日期 |
|----|------|--------|---------|------|---------|
| REQ-001 | 增加波动率过滤 | P1 | 策略发现 | IN_PROGRESS | 2026-07-21 |
| REQ-002 | 早盘增加港股权重 | P2 | 每日复盘 | OPEN | 2026-07-22 |
| REQ-003 | 优化东财限流策略 | P1 | 数据质量 | IMPLEMENTED | 2026-07-19 |
```

### 3.6 与自动化任务的集成方式

各自动化 Prompt 在执行时增加一个步骤：

```
步骤 0: 检查 Steering 需求
  → 读取 steering/REQ_INDEX.md
  → 筛选 status=OPEN 且 matching 当前任务影响范围的需求
  → 将需求内容纳入分析上下文
  → 若需求被处理，更新状态到 IN_PROGRESS 或移动文件到 in_progress/
```

**关键约束**：
- 自动化任务不能修改 REQ 的状态为 ADOPTED/REJECTED/IMPLEMENTED，只能推进到 IN_PROGRESS
- 状态 ADOPTED/REJECTED/IMPLEMENTED 由用户手动设置（或在用户确认后由 Claude 代操作）
- 但自动化可以在报告末尾附上对需求的回应/建议

### 3.7 用户使用流程

1. **创建需求**：在 `steering/open/` 下新建 `REQ-{NNN}.md`，按模板填写
2. **更新索引**：手动更新 `REQ_INDEX.md`，或要求 Claude 代为更新
3. **观察进展**：在后续的 AUTO_FIX_REPORT、巡检报告、复盘报告中看到需求被引用和处理
4. **确认结果**：需求被处理后，手动将状态改为 ADOPTED/REJECTED/IMPLEMENTED

---

## 4. CLAUDE.md 变更

在 §7.2 调度表中新增：

| 任务 | 频率 | Prompt | 用途 |
|------|------|--------|------|
| **BUG自动修复** | **每小时 (:07)** | `bug_auto_fix.md` | 扫描 OPEN BUG → AUTO_FIX 自动修复 → MANUAL_REVIEW 标记 → 生成报告 |

在 §7.2 后新增 §7.2.1：

```markdown
### 7.2.1 优化需求 Steering

用户可通过 `etf-strategies/automation/steering/` 和 `每日复盘/harness/automation/steering/` 注入优化需求。

- **创建需求**: 在 `steering/open/` 下按模板创建 `REQ-{NNN}.md`
- **自动集成**: 巡检/修复/发现任务执行时自动读取待处理需求并纳入工作范围
- **状态管理**: OPEN → IN_PROGRESS (自动) → ADOPTED/REJECTED/IMPLEMENTED (人工确认)
```

---

## 5. 每日复盘项目的变更

每日复盘项目（`my_doc/每日复盘/harness/automation/`）只涉及 steering 系统（不涉及 BUG 自动修复——ETF 策略项目才有 BUG 管理）。

**新增**：
- `my_doc/每日复盘/harness/automation/steering/` 目录及初始文件

**修改**（可选，后续迭代）：
- 五个每日复盘 Prompt 增加 "步骤 0: 检查 Steering 需求"

---

## 6. 约束与纪律

- **自动修复不替代人类判断**：MANUAL_REVIEW 的 BUG 必须人工确认，自动修复失败的 BUG 保留追踪
- **报告透明**：每次自动修复必须生成报告（有实质工作）或日志（空闲轮次）
- **安全原则**：不确定能否自动修复时，默认标记 MANUAL_REVIEW
- **幂等**：同一 BUG 已被修复后，自动修复任务自动跳过
- **不破坏现有流程**：巡检 Prompt 仅增加 auto_fix_eligible 字段，其余逻辑不变
