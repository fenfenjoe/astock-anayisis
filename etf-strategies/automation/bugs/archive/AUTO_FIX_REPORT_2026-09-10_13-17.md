# 自动修复报告 — 2026-09-10 13:17

## 本轮扫描
- 扫描时间: 2026-09-10T13:17+08:00
- 发现 OPEN BUG: 5 个（BUG-035 / 036 / 037 / 038 / 039）
- AUTO_FIX 候选: 3 个（BUG-035 / 036 / 037，`auto_fix_eligible=true`）
- MANUAL_REVIEW 候选: 2 个（BUG-038 / 039，`auto_fix_eligible=false`）

## 自动修复结果

| BUG-ID | 标题 | 结果 | 详情 |
|--------|------|------|------|
| BUG-035 | 测试未适配 dashboard/api_agent.py 反向代理重构（27 项 FAILED/ERROR） | ✅ FIXED | 采纳方案 (a)：test_agent_api / test_agent_notices 改为进程内直测 `agent/api.py`（`TestClient(agent_api.app)` + 关闭 X-Api-Key 校验 + monkeypatch `agent_api.dsh_runner`）；新增 `TestDashboardProxyContract` 6 项锁定代理层透传/降级契约。27 项全部转绿 |
| BUG-036 | scheduler_agent 失败通知调用签名不匹配，TypeError 被静默吞掉 | ✅ FIXED | 调用点改用 `agent_db.notice_create("notice", title, content, source="agent")`；`except: pass` → `logger.warning`（通知 + 建单两处）；移除失效的 `notices_mod` 导入 |
| BUG-037 | 本地 file 后端 SCHEMA 缺 `tickets` 表，ticket_* 四函数全部 OperationalError | ✅ FIXED | `agent/db.py` SCHEMA 补建 `tickets` 表（与 `scripts/cloud_schema.sql` 对齐）+ status 索引；`tests/test_agent_db.py` 新增建表断言 + ticket CRUD 测试（防复发） |

## 升级到人工审核

| BUG-ID | 标题 | 原因 |
|--------|------|------|
| BUG-038 | agent/__main__._ensure_cloud() 晚于 agent.db 导入执行，USE_CLOUD 导入时固化 | 导入时序/后端选择策略决策（(a) 提前导入顺序 / (b) 惰性求值 / (c) db.py 缺省兜底），与 BUG-025 同族，`auto_fix_eligible=false` → MANUAL_REVIEW |
| BUG-039 | scheduler_agent 声称 tick loop 驱动定时任务，实际未接入生命周期 | 架构迁移节奏决策（谁是唯一调度方 + 防双跑互斥开关），`auto_fix_eligible=false` → MANUAL_REVIEW |

## 验证

| 项目 | 修复前 | 修复后 |
|------|--------|--------|
| `pytest tests/test_agent_api.py tests/test_agent_notices.py` | 2 failed + 17 errors + 8 failed（27 项） | 47 passed |
| `pytest tests/test_agent_db.py` | 27 passed（无 ticket 覆盖） | 29 passed（+2 ticket 测试） |
| `pytest tests/`（全量） | 13 failed, 499 passed, 18 skipped, 17 errors | **534 passed, 3 failed, 18 skipped** |

剩余 3 项失败 = `tests/test_pet_frontend.py`（BUG-029 ×2 + BUG-030 ×1），均为 MANUAL_REVIEW、`auto_fix_eligible=false`，**非本轮修复范围**（前端契约/视觉设计决策，需人工裁决）。

BUG-036/037 另经运行时验证（临时脚本 `_verify_bugfix.py`，跑完即删）：file 后端 + tmp db 下触发失败任务 → 工单写入成功（status=analyzing）+ `agent_notices` 新增 1 条 `kind=notice / source=agent`（修复前 TypeError 致通知永不生成）。

## 执行日志
- 2026-09-10T13:17+08:00 扫描到 5 个 OPEN BUG（035/036/037/038/039）
- 2026-09-10T13:18+08:00 BUG-037: auto_fix → SCHEMA 补 tickets 表 + 2 项防复发测试 → 修复成功 → FIXED
- 2026-09-10T13:19+08:00 BUG-036: auto_fix → notice_create 调用点修正 + 日志留痕 → 修复成功 → FIXED
- 2026-09-10T13:20+08:00 BUG-035: auto_fix → 测试改直测 agent/api.py + 代理层契约测试 → 修复成功 → FIXED
- 2026-09-10T13:24+08:00 BUG-038: manual_review → 已含「## 自动修复判定」，状态 OPEN → MANUAL_REVIEW
- 2026-09-10T13:24+08:00 BUG-039: manual_review → 已含「## 自动修复判定」，状态 OPEN → MANUAL_REVIEW
- 2026-09-10T13:25+08:00 全量回归 534 passed / 3 failed（余 3 项为 BUG-029/030 MANUAL_REVIEW）
- 2026-09-10T13:26+08:00 BUG-035/036/037 报告状态改 FIXED 并移至 `bugs/closed/`
- 2026-09-10T13:26+08:00 更新 BUG_INDEX.md 完成（OPEN 5→0, FIXED 22→25, MANUAL_REVIEW 8→10）
- 2026-09-10T13:27+08:00 git commit 修复（BUG-035/036/037）
