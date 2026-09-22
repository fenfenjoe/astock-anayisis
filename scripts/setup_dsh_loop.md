# DSH 自动化循环 — 设置与管理指南（精确触发版 v2）

> 替代旧版 7 分钟轮询（dsh-automation-loop 已删除）。**核心变化：轮询 → 精确时刻触发，空闲零 token。**

## 架构（v2）

```
Windows 计划任务（精确时刻，各一个）
  ├─ dsh-trigger-morning  09:07  → python dsh_trigger.py --task morning_analysis
  └─ dsh-trigger-evening  15:52  → python dsh_trigger.py --task evening_review
        │
        ▼
  dsh_trigger.py（复用 task_scheduler.py 交易日/幂等/窗口逻辑）
    ├─ 非交易日/已执行 → 跳过（0 token）
    └─ 到点 → 标记完成 → 派发独立 dsh headless 进程执行任务 prompt
```

特性对比：

| 特性 | 7 分钟轮询（旧，已删） | 精确触发（新） |
|------|----------------------|---------------|
| 空闲消耗 | ~205 次/天模型调用（cache 读 6,800 万/天） | **0**（纯脚本判定） |
| 触发精度 | 目标后 0~7 分钟 | 目标时刻（±秒级） |
| 恢复 | — | StartWhenAvailable + ±3h 容差窗口 |
| 任务隔离 | 独立进程 | 独立进程（不变） |

## 任务清单（全部 21 个，已恢复原调度节奏）

| 计划任务 | 触发器 | 触发的 task_id | 说明 |
|---------|--------|---------------|------|
| dsh-trigger-morning | 09:07 | morning_analysis | 早盘分析 + 每日信号 |
| dsh-trigger-intraday-0940/1000/1030/1100 | 09:40/10:00/10:30/11:00 | intraday_* | 盘中检查 ×4 |
| dsh-trigger-intraday-1330/1400/1430 | 13:30/14:00/14:30 | intraday_* | 盘中检查 ×3 |
| dsh-trigger-evening | 15:52 | evening_review | 收盘复盘（13 步 + 次日 staging） |
| dsh-trigger-bugfix | 09:07~18:07 每小时 :07 | bug_auto_fix | BUG 自动修复 |
| dsh-trigger-harness-bugfix | 09:17~18:17 每小时 :17 | harness_bug_auto_fix | Harness BUG 自动修复 |
| dsh-trigger-pending-remind | 09:13/11:13/…/21:13 每 2h | pending_remind | 待确认事项提醒 |
| dsh-trigger-bug-inspect-data | 12:07 | bug_inspect_data | 数据质量巡检 |
| dsh-trigger-bug-inspect-code | 12:17 | bug_inspect_code | 代码巡检 |
| dsh-trigger-bug-inspect-logic | 12:23 (周一) | bug_inspect_logic | 逻辑巡检 |
| dsh-trigger-strategy-scan | 12:37 (周二) | strategy_scan_weekly | 策略发现 |
| dsh-trigger-experience-health | 12:47 (周三) | experience_health | 经验库健康 + Steering |
| dsh-trigger-weekly-portfolio | 13:17 (周四) | weekly_portfolio | 周度组合回顾 |
| dsh-trigger-req-implement | 12:57 | req_implement | REQ 自动实施 |
| dsh-trigger-logic-inspect | 17:07 (每天) | logic_inspect | 逻辑巡检 |
| dsh-trigger-signal-quality | 16:30 (周三) | signal_quality_weekly | 信号质量周报 |

> 全部由 `dsh_trigger.py` 执行：非交易日/非计划星期/已执行自动跳过（幂等）；周度任务按 task_schedule.json 的 days_of_week 判定。

## 查看执行情况（可观测性）

```powershell
# 1) 一键状态：今日调度状态 + 最近派发日志
python .claude/scripts/dsh_status.py

# 2) 计划任务运行结果（LastTaskResult: 0=成功, 267009=触发但被脚本跳过）
Get-ScheduledTask -TaskName "dsh-trigger-*" | Get-ScheduledTaskInfo |
    Select TaskName, LastRunTime, LastTaskResult | Sort LastRunTime -Descending

# 3) 任务执行日志（headless stdout/stderr）
dir .dsh\logs\

# 4) 任务自身写入的执行日志
dir my_doc\每日复盘\harness\automation\logs   # 复盘侧
dir etf-strategies\automation\logs            # ETF 侧

# 5) 今日调度幂等状态
python .claude/scripts/task_scheduler.py --status
python .claude/scripts/task_scheduler.py --list-running
```

## 管理命令

```powershell
# 查看
Get-ScheduledTask -TaskName "dsh-trigger-*"
# 停用/启用
Disable-ScheduledTask -TaskName "dsh-trigger-morning"
Enable-ScheduledTask  -TaskName "dsh-trigger-morning"
# 手动触发一次（不等待计划时刻）
python .claude/scripts/dsh_trigger.py --task morning_analysis --dry-run   # 只判定
python .claude/scripts/dsh_trigger.py --task evening_review --force        # 强制执行
# 今日执行状态
python .claude/scripts/task_scheduler.py --status
```

## 派发日志

`.dsh/logs/{task_id}-{timestamp}.log`（headless stdout/stderr）。

## skill 同步（重要）

DSH 侧的 8 个原始 skill（a-stock-data 等）是 `.claude/skills/` 的副本：
**在 Claude 侧改了 skill 后，必须同步**，否则 DSH 用旧版：

```powershell
python .claude/scripts/sync_claude_skills.py --dry-run   # 查看差异
python .claude/scripts/sync_claude_skills.py             # 同步
```

> harness 模板/经验/automation prompts 是共享单份文件，无需同步。

## 回滚

1. `Unregister-ScheduledTask -TaskName "dsh-trigger-morning","dsh-trigger-evening" -Confirm:$false`
2. 恢复轮询：注册 `dsh-automation-loop`（每 7 分钟跑 `dsh_loop_scheduler.py`）
3. Claude /loop 照旧：`/loop 7m /clear && 执行 .claude/prompts/loop_runner.md`
