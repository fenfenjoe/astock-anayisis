# 自动修复报告 — 2026-09-23 13:11

## 本轮扫描
- 扫描时间: 2026-09-23T13:11+08:00
- 发现 OPEN BUG: 1 个（BUG-048，2026-09-23 12:20 bug_inspect_code 发现）
- AUTO_FIX 候选: 0 个
- MANUAL_REVIEW 候选: 1 个（BUG-048，auto_fix_eligible=false；bugs/open 下其余 8 项 BUG-005/007/012/013/014/015/038/039 均为 MANUAL_REVIEW 且已含自动修复判定，沿用既有判定无新增动作）

## 自动修复结果

| BUG-ID | 标题 | 结果 | 详情 |
|--------|------|------|------|
| BUG-048 | persona.md 上移后 /api/agent/profile 的 basic 节解析为空，test_profile_returns_basic_and_activity 失败（全量 700passed/1failed） | ⚠️ MANUAL_REVIEW | 根因是 persona 单一事实源从仓库迁移到用户级 `~/.dsh/personas/xiaoman/persona.md`（RUNTIME 字符串格式）后，profile 端点/测试仍依赖仓库 persona.md 的 `## 基本` 节；修复需人工裁决「端点改读新源/解析 RUNTIME 格式」vs「测试降级」，属架构决策（与 BUG-038 同类），auto_fix_eligible=false，按安全原则不自动修复 |

## 升级到人工审核

| BUG-ID | 标题 | 原因 |
|--------|------|------|
| BUG-048 | persona.md 上移后 profile basic 节解析为空 | persona 单一事实源迁移架构决策（端点改读新源 vs 测试降级），auto_fix_eligible=false |

> 现有 MANUAL_REVIEW 9 项：BUG-005/007/012/013/014/015/038/039（沿用既有判定）+ BUG-048（本轮新增）。均保留在 `bugs/open/`，待人工审阅后执行 bug_fix_template.md 流程。

## 执行日志
- 2026-09-23T13:11+08:00 扫描到 1 个 OPEN BUG（BUG-048）
- 2026-09-23T13:11+08:00 BUG-048: manual_review → MANUAL_REVIEW（auto_fix_eligible=false，架构决策；BUG 报告状态已更新 + 追加「## 自动修复判定」章节，保留在 bugs/open/）
- 2026-09-23T13:11+08:00 更新 BUG_INDEX.md 完成（OPEN: 1→0, MANUAL_REVIEW: 8→9）；BUG-048 加入「⚠️ 待人工审核」表
