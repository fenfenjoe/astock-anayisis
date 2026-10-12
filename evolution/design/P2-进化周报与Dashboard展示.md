# P2 落地：进化周报（含 Dashboard 展示）+ 负反馈机制 + 观察期计时

> 自进化框架 P2 落地（用户确认："继续落地 P2，但周报要在 Dashboard 展示，我不看 markdown 了"）
> 日期：2026-09-24 | 状态：**已实施（负反馈 + 观察期 + 周报 + Dashboard + 真实数据验证）**
> **2026-10 修订**：用户反馈 HTML 报告难看（"还不如之前的生成markdown然后渲染"）→ 全量回退
> HTML 报告管线（早盘/复盘/进化周报均恢复 仅 .md + Dashboard markdown 渲染）；本文件中 HTML
> 相关设计作废，保留仅为历史记录。

## 〇、实施结果（验收全部达成）

1. **负反馈机制（P2a）**：`track_feedback()`（框架引擎 verify.py + 项目 lib 薄壳引用）——跨轮次连续无改善 → halt。11 项测试。
2. **观察期计时（P2b）**：`due_for_verification()`——REQ 到期才验证，非法日期安全降级。11 项测试。
3. **进化周报生成器（P2c）**：`lib/evolution_report.py`（纯函数，六节数据组装 + markdown 渲染），8 项测试。
4. **Dashboard 接入（P2d，2026-10 回退后）**：
   - scheduler `_report_type_from_name` 加"进化周报"（放"周报"前防吞）+ `_HTML_REPORT_TYPES` 加"进化周报"（现为 **markdown 优先**：.md 入库，有 .md 时跳过 .html）
   - `auto_evolution_weekly.md` prompt：仅产出 `.md`（回退后不再产出 .html）
   - task_schedule.json 加 `evolution_weekly`（周五 17:30）
   - 前端零改动（`renderReportContent` 自动判 HTML/markdown；DB 存 markdown → 走 markdown 渲染）
5. **真实数据端到端验收（回退前）**：
   - `reports/weekly/2026-09-23_进化周报.md`（六节）+ `.html`（Tech Noir，3.8KB）
   - Dashboard import 验证：HTML 优先入库（DB 内容以 `<!DOCTYPE html>` 开头），`.md` 留磁盘 ✅
   - **2026-10 回退后**：云库 force re-import 为 markdown，Dashboard 走 markdown 渲染 ✅
6. **全量测试**：harness **655 passed, 1 skipped** + etf-strategies **705 passed, 18 skipped** 全绿无回归。

**顺带修复（P1 遗留断点）**：agent 认识页读不到"小满"姓名（P1 上移 persona 时丢"## 基本"节）→
用户级 persona.md 重构为完整人设卡（基本节 + RUNTIME 块）；agent `PERSONAS_DIR` 指向
`~/.dsh/personas/`；behaviors.md / reading.md 上移用户级（对应"P3 上移"需求）。
sync 脚本 --check 通过（运行时 persona 不变）。

## 一、目标

把"进化"从指标闭环升级为**周度可见、可追溯、有刹车**的完整机制：

1. **进化周报**（每周五产出）：本周 Agent 进化全景——指标变化 / REQ 进展 / 对照验证结果 / 负反馈状态
2. **Dashboard 展示**：周报产出 `.html`（Tech Noir）+ `.md`（机器解析），走现有报告 import 链路
3. **负反馈机制**：连续 N 轮无改善 → 自动暂停+回滚建议（goals.md 写了但没代码化）
4. **观察期计时**：REQ 进 IMPLEMENTED 时记观察期到期日，验证只捞到期 REQ（不用人工扫）

## 二、进化周报内容（六节）

| 节 | 内容 | 数据源 |
|----|------|--------|
| 一、本周指标概览 | 信号质量/报告质量分 vs 目标（gap） | signal_quality_history + report_quality_history + goals.md |
| 二、目标达成进度 | 每个 goal 的 current/target/gap/status | gap_analysis.compute_gaps |
| 三、REQ 进展 | OPEN/IN_PROGRESS/IMPLEMENTED/CLOSED 统计 + 本周新增 | steering/open/ + REQ_INDEX |
| 四、对照验证结果 | 到期 REQ 的 before/after/improved/action | req_evolution（P2 已有） |
| 五、负反馈状态 | 连续无改善的 REQ（≥N 轮）→ 暂停/回滚建议 | 新增 neg_feedback 追踪 |
| 六、下周建议 | 差距归因 + 定向 REQ 建议 + 需人工确认项 | gap_analysis.gen_req_suggestion |

## 三、Dashboard 接入（复用成熟链路）

```
evolution_weekly 任务（周五 17:30）
  → 生成 reports/weekly/{YYYY-MM-DD}_进化周报.md（机器解析；2026-10 回退后仅此一种产出，Dashboard markdown 渲染）
  → scheduler.import_reports_from_disk() 扫描导入 daily_reports 表（markdown 优先）
  → Dashboard「报告」页按 report_type 列出，markdown 渲染（前端零改动）
```

需要的小改动（etf-strategies/dashboard/scheduler.py）：
1. `_report_type_from_name`：known 列表**最前**加"进化周报"（避免被"周报"前缀吞）
2. `_HTML_REPORT_TYPES`：加"进化周报"（**2026-10 回退后为 markdown 优先**：.md 入库，有 .md 时跳过 .html）
3. `report_type` 已通用（前端 `renderReportContent` 自动判 HTML/markdown）

## 四、负反馈机制（P2a，代码化）

**现状**：goals.md 写了"连续 3 轮无改善 → 自动暂停+回滚+换方向"，但 `suggest_action` 只给单次建议，无跨轮次状态。

**设计**：`lib/req_evolution.py` 增加**跨轮次追踪**：

```python
def track_feedback(verification_log: list, rounds: int = 3) -> dict
    # verification_log: [{req_id, date, eval_result, action}]
    # 返回 {req_id: {no_improve_streak, status: 'normal'|'halt'|'rollback_suggest'}}
    # no_improve_streak >= rounds → status='halt'（自动暂停，建议回滚）
```

状态机：
- `improved` → streak 清零
- `no_change` / `insufficient` → streak +1
- streak ≥ 3 → `halt`（周报五节标红，建议 MANUAL_REVIEW 人工裁定回滚）

## 五、观察期计时（P2b，到期判定自动化）

**现状**：P2 设计"观察期到期才验证"，但没自动化——靠 gap_analysis prompt 人工扫 REQ 处理记录。

**设计**：REQ 进 IMPLEMENTED 时，在 `steering/` 的 REQ 文件或统一状态文件记录 `implemented_date`；gap_analysis 用 `parse_evolution_fields` 的 `observation_weeks` 计算 `due_date = implemented_date + observation_weeks`，只验证 `due_date <= today` 的 REQ：

```python
def due_for_verification(req, implemented_date: str, today: str) -> bool
    # due_date = implemented_date + observation_weeks 周
    # 返回 due_date <= today（到期才验证）
```

## 六、实施步骤（TDD）

1. **P2a**：`track_feedback()` + 测试（streak 逻辑/清零/halt 阈值）
2. **P2b**：`due_for_verification()` + 测试（到期判定/边界）
3. **P2c**：`lib/evolution_report.py`（纯函数：六节数据组装）+ 测试；prompt `auto_evolution_weekly.md`（产出 .md + .html）
4. **P2d**：scheduler.py 加"进化周报"类型 + `_HTML_REPORT_TYPES`；task_schedule.json 加 `evolution_weekly`（周五 17:30）；etf-strategies 测试
5. **验收**：全量测试 + 真实数据生成一份进化周报（.md + .html）+ 冒烟 import

## 七、验收标准

1. 负反馈：连续 3 轮 no_change → halt（周报标红 + 建议人工）
2. 观察期：未到期 REQ 不验证；到期自动进验证
3. 周报：真实数据产出 `.md`（六节）+ `.html`（Tech Noir，Dashboard 可渲染）
4. Dashboard：scheduler import 识别"进化周报"类型 + HTML 优先入库
5. 全量测试无回归（harness 636 + etf-strategies）
