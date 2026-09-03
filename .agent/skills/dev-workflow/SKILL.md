---
name: dev-workflow
description: 开发任务标准流程（superpowers 精简版）— brainstorming → writing-plans → TDD → executing-plans → code-review 五步，调试走 systematic-debugging。触发条件：写或改代码/脚本、构建数据工具、调试、重构工程、实施 REQ 时。取数与投研分析不走本流程。
user-invocable: true
origin: migrated-from-superpowers
---

# dev-workflow — 开发任务标准流程（superpowers 精简版）

> 本 skill 替代原 Claude 插件 superpowers 在本项目的用法。**仅当出现开发需求时启用**；A 股取数与投研分析不进入本流程（按 CLAUDE.md 第一/二节执行）。

## 触发判定

- **触发**：写或改 Python/JS/TS 等代码、构建数据工具、调试代码、重构工程、实施 REQ（`auto_req_implement` 强制走本流程）。
- **不触发**：取数（走 `a-stock-data`）、过投资框架、写投研报告、每日复盘编排（走 `daily-review-harness`）。
- **铁律不变**：开发脚本里凡需 A 股真实数据的，仍走 `a-stock-data`，不因进入开发流程而豁免数据纪律。
- **临时脚本清理**：一次性取数脚本用 `_*.py` 命名、跑完即删。

## 五步流程（不可跳过，禁止不假思索的实现）

### 1. Brainstorming（构思 — 必做）

- 先想清楚：做什么、为什么、约束条件、验收标准。
- 涉及 UI/前端的需求，必须先调 `frontend-design` 定美学方向，再进入本步。
- 输出：需求理解 + 方案要点（简短即可，不写长篇）。

### 2. Writing Plans（写计划）

- 拆解为实现步骤，标注每步的输入/输出/涉及文件。
- 涉及数据获取的步骤标注"走 `a-stock-data`"。
- 涉及 UI 的标注"完成后用 `design-critique` 自检"。

### 3. TDD（测试先行 — 强制门禁）

- 先写失败测试，再写实现，直到测试通过。
- **无测试不得推进**（REQ 闭环硬性要求，无测试不得进入 IMPLEMENTED/CLOSED）。
- 本项目测试入口：
  - 每日复盘 harness：`cd my_doc/每日复盘/harness/automation && python -m pytest tests/ -v`
  - ETF 回测：见 `testing` skill。

### 4. Executing Plans（执行）

- 按计划实现，每步完成后跑相关测试。
- 失败即回到第 3 步修复，不掩盖失败。

### 5. Code Review（代码评审 — 必做）

- 自查清单：命名清晰、边界处理、错误处理、与 CLAUDE.md 纪律一致（数据来源标注、输出纪律、临时脚本清理）。
- 涉及金融计算/信号逻辑的改动 → 标注 **MANUAL_REVIEW**，需人工确认后才算完成。

## 调试：systematic-debugging

- 不瞎猜。流程：**复现**（最小用例）→ **定位**（二分/日志/单步）→ **假设** → **验证修复** → **回归测试**。
- 根因与修复记录到对应 `bugs/` 或 `automation/logs/`（如适用）。

## REQ 闭环纪律

- 生命周期：OPEN → IN_PROGRESS（自动化任务推进）→ IMPLEMENTED（代码已写+测试通过）→ CLOSED（测试通过+用户确认）。
- 禁止跳过 brainstorming（不假思索的实现=返工）；禁止跳过 TDD（无测试不得推进）。
- 涉及 A 股数据的 REQ 仍走 `a-stock-data`。

## 与本项目其他 skill 的关系

- 数据获取：`a-stock-data`（铁律）
- 前端设计：`frontend-design`（定方向）→ 本流程 → `design-critique`（评审）
- 每日复盘：`daily-review-harness`（编排，不走本流程）
