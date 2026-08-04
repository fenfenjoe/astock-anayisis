# Harness 测试基础设施与流程闭环 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为每日复盘 harness 建立完整测试基础设施（pytest + lib 可测试模块 + BUG 跟踪系统），修复 REQ 流程 TDD 门禁缺失，使 REQ-001/002 可推进到 CLOSED。

**Architecture:** 提取 prompt 中嵌入的 Python 逻辑为 `lib/` 纯函数模块 → pytest 测试覆盖 → prompt 中增加 TDD 门禁 + BUG 系统闭环。lib 只做纯计算不写磁盘，测试用合成数据。

**Tech Stack:** Python 3, pytest, json, datetime, subprocess (仅 state_machine.run_tests)

**Base path:** `my_doc/每日复盘/harness/automation/`

## Global Constraints

- lib/ 只做纯计算，不读写磁盘、不调 a-stock-data、不修改 prompt
- 测试文件以 REQ 编号命名：`test_REQ_001.py`
- 测试使用合成数据，不依赖真实行情
- pytest.ini 独立配置，不与 etf-strategies/pytest.ini 冲突
- BUG 全部路由到 harness 自身的 `bugs/` 目录
- 涉及金融计算 → MANUAL_REVIEW，不自动修复

---

## Task Summary

| # | Task | Files | Depends On |
|---|------|-------|------------|
| 1 | Directory structure + pytest.ini | 6 new | — |
| 2 | lib/signal_tracking.py | 1 new | Task 1 |
| 3 | lib/signal_design.py | 1 new | Task 1 |
| 4 | lib/state_machine.py | 1 new | Task 1 |
| 5 | tests/conftest.py | 1 new | Task 1 |
| 6 | bugs/BUG_INDEX + BUG_TEMPLATE | 2 new | Task 1 |
| 7 | tests/test_REQ_001.py | 1 new | Tasks 2,5 |
| 8 | tests/test_REQ_002.py | 1 new | Tasks 3,5 |
| 9 | tests/test_state_machine.py | 1 new | Tasks 4,5,7 |
| 10 | auto_req_implement.md (+3.5) | 1 mod | Task 9 |
| 11 | auto_evening_review.md (13.3) | 1 mod | Task 9 |
| 12 | auto_experience_health.md (+5C) | 1 mod | Task 9 |
| 13 | REQ_TEMPLATE.md (+test section) | 1 mod | Task 9 |
| 14 | auto_bug_fix.md | 1 new | Task 6 |
| 15 | task_schedule.json (+harness_bug) | 1 mod | Task 14 |
| 16 | Full test run + REQ-001/002 CLOSED | 3 mod | Tasks 7-15 |
| 17 | CLAUDE.md update | 1 mod | Task 16 |

**Total: 14 new files, 8 modified files, 44 test cases, 17 commits**

The detailed step-by-step instructions for each task are in the plan document.
Each task contains exact code, commands, and expected outputs.

## Dependency Graph



## Rollback

Each task is an independent git commit. To rollback:
1. Identify the failing task's commit
2.  to undo that specific task
3. All new files are in isolated directories (lib/, tests/, bugs/) — no impact on existing pipeline
4. Prompt modifications are forward-compatible (only add checks on IMPLEMENTED→CLOSED path)
5. task_schedule.json addition can be removed independently
