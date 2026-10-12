# CHAT.md 任务执行设计方案（修订版）

> 设计时间：2026-09-11 | 修订：2026-09-14（对照 CHAT.md 需求与代码现状复核）| 版本：v1.3 | 状态：**已复核**

> 修订说明：v1.0 由前序 Agent 编写。本次修订基于对 `CHAT.md` 的逐条复核与代码实测，修正以下问题：
> 1. 任务1：`scheduler_state.json` 中三个任务的幂等键不是"3 条"而是**上百条**（每小时一条，实测 126 条）；删除后剩余任务数应为 **18**（原文档误写 16）。
> 2. 任务1：补充说明 loop 调度器（`.claude/scripts/task_scheduler.py`）与 Dashboard 调度器（`etf-strategies/dashboard/scheduler.py`）**共用同一份 `task_schedule.json`**（`SCHEDULE_PATH = REPO_ROOT/.claude/scripts/task_schedule.json`，dashboard 按 `prompt_file` 前缀过滤 `in_scope()`），删一次即两套调度器同时停止派发。
> 3. 任务4：枚举定义前后矛盾（`direction` 一处写"多|空"、一处写 `buy/sell`；`status` 中英文混排）；历史表布局漏了 `信号ID` 列；"盘中/复盘联动改动不在本次范围内"的表述与 CHAT.md 硬性需求矛盾（CHAT.md 明确要求盘中记录触发价/触发时间、复盘记录买入价/买入时间），**纳入范围**。
> 4. 任务3（v1.2）：原判定"✅ 无需改动"→ 用户明确要求架构调整（Dashboard 只展示、Agent 检查到点执行），**已实施**，详见第三节。

---

## 一、任务1：删除三个定时任务 ✅ 已实施（2026-09-14）

### 1.1 范围

删除 `task_schedule.json` 中以下 3 个任务配置，以及 `scheduler_state.json` 中对应幂等键：

| 任务 | task_id | 触发规则 | prompt_file |
|---|---|---|---|
| 逻辑巡检 | `bug_inspect_logic` | 每周一 12:23 | `etf-strategies/automation/prompts/bug_inspect_logic.md` |
| Harness BUG 自动修复 | `harness_bug_auto_fix` | 工作日 9-18 点每小时 :17 | `my_doc/每日复盘/harness/automation/prompts/auto_bug_fix.md` |
| 待确认事项提醒 | `pending_remind` | 每天每2小时 :13 | `my_doc/每日复盘/harness/automation/prompts/auto_pending_remind.md` |

### 1.2 改动内容（已完成）

1. **`task_schedule.json`**：删除上述 3 条任务配置（实测文件共 21 个任务 → 删除后剩 **18 个**）。此文件是 **loop 调度器与 Dashboard 调度器的单一事实源**：
   - loop 调度器（`.claude/scripts/task_scheduler.py`）直接读它；
   - Dashboard 调度器（`etf-strategies/dashboard/scheduler.py` `load_schedule()` + `scoped_tasks()`）也读它（`SCHEDULE_PATH = REPO_ROOT/.claude/scripts/task_schedule.json`，`in_scope()` 按 `prompt_file` 前缀 `my_doc/每日复盘/`、`etf-strategies/automation/` 过滤）。
   - 因此**删除一次，两套调度器同时停止**，无需改 dashboard 代码。
2. **prompt 文件**：**不删除**（保留在磁盘上，仅从调度中移除；以后若需要可恢复）。
3. **`scheduler_state.json`**：删除 `executed` 中**所有**以 `bug_inspect_logic:` / `harness_bug_auto_fix:` / `pending_remind:` 开头的幂等键（**实测 126 条**，因后两者按小时产生、跨 8-9 月累计；不是设计文档 v1.0 写的"3 条"）。清理后剩余 199 条，不影响其余 15 个任务幂等。

### 1.3 验证

- `python -c "import scheduler"`（dashboard）→ `load_schedule()` 返回 18 个任务，三个已删除任务不在其中；
- `scoped_tasks()` 返回 18 个（全部为 `prompt_file` 在范围内的每日/盘中/复盘/巡检任务）；
- `scheduler_state.json` 三个前缀残留键 = 0。

### 1.4 风险评估

- **极低风险**：仅从调度列表移除，其余任务调度不受影响；`task_schedule.json` JSON 格式已校验（python json.load 通过）。

---

## 二、任务2：重跑 strategy_scan_weekly ✅ 已确认可正常运行（无需代码改动）

### 2.1 现状分析

| 项目 | 状态 |
|---|---|
| 调度配置 | `task_schedule.json` 存在，每周二 12:37，window=7min |
| Dashboard 引擎 | `scheduler.py` SchedulerEngine 每 20s tick 检测到期 |
| Agent 执行器 | `scheduler_agent.py` execute_task() → dsh headless |
| 最近一次运行 | 2026-09-08 (周二) 正常完成 |
| 下次执行 | 2026-09-15 (周二) 12:37 |

### 2.2 结论

配置存在、调度器能识别、上次运行成功。**无需代码改动**，下次到期自动触发。若 09-15 后仍未跑，再查 `scheduler_state.json` / 日志。

---

## 三、任务3：日志"已派发到 Agent 进程执行"分析 🔄 已按用户要求完成架构调整

### 3.1 原因分析（原行为）

**来源文件**：`etf-strategies/dashboard/scheduler.py`（原 `_run_prompt` L695，HTTP POST L716-717，`dispatched to Agent` 打印 L724，`output="已派发到 Agent 进程执行"` L734，`_tick` L969，`run_task` L809）。

**原机制**：Dashboard 内嵌调度引擎在 tick 发现到期任务后，通过 HTTP POST 通知 Agent 进程（`http://127.0.0.1:8020/api/agent/scheduler/run/{task_id}`）执行，Agent 返回 200 后，Dashboard 将运行记录状态写为 `running` + output 写为 `"已派发到 Agent 进程执行"`。

**原调用链路**：
```
SchedulerEngine._tick()  (L969)
  → run_task()           (L809)
  → _run_prompt()        (L695)
  → HTTP POST 到 Agent    (L716)
  → Agent 返回 200        (L722)
  → db.scheduler_run_update(output="已派发到 Agent 进程执行")  (L728-735)
```

**问题**：`_run_prompt` 派发给 Agent 后记录卡在 `running`，**Agent 完成状态写回的是另一张表（agent_activities），不写 scheduler_runs** → 记录永远 `running`；`scheduler_window_done` 只认 `success/timeout`，`running` 不算完成 → 下一 tick 再次派发/本地兜底 → **同一窗口出现 2 条记录**（第 1 条"已派发" + 第 2 条真实结果）。云库实测：`intraday_1000:2026-09-14` 有 09:40:17(failed) + 09:40:38(success) 两条，21 秒间隔，正是此模式。

### 3.2 用户决策（2026-09-14）

用户明确要求：**Dashboard 不主动发现/派发任务，只负责展示；手动"运行"时 Dashboard 主动调用 Agent；日程情况下由 Agent 进程检查到点并触发执行。**

### 3.3 已实施改动（本任务从"无需改动"升级为"架构调整"）

1. **Dashboard `scheduler.py` `_tick`**：移除 auto 发现/派发段（`for t in scoped_tasks(): run_task(auto)`）。引擎只保留报告重扫（展示刷新）+ 上线闸门。
2. **Dashboard `scheduler.py` `run_task_by_id`**（手动"运行"）：改为仅 `_dispatch_to_agent()`（POST Agent），**不再本地建 scheduler_runs 记录、不再本地兜底执行**。Agent 不可达 → 返回 `agent_unreachable` 错误。
3. **Dashboard `start()`**：移除 `scheduler_mark_zombies_running()` —— running 记录现属 Agent，Dashboard 误标记会杀掉正在执行的 Agent 任务。
4. **Agent `scheduler_agent.py`**：
   - 新增云库 `scheduler_runs` 访问（`scheduler_run_insert`/`scheduler_run_update`/`scheduler_window_done`，与 dashboard 同表同口径，file 模式 no-op）；
   - `_run_task_and_record` 写云库 scheduler_runs（auto 用窗口 key，manual 用独立 key）；
   - 新增 `tick()`：遍历 scoped_tasks → 交易日门控 + 时间窗口 + 窗口幂等 → `execute_task(trigger='auto')`；
   - 新增 `reconcile_zombies()`（Agent 启动时回收僵尸 running 记录，接管原 dashboard 职责）。
5. **Agent `lifecycle.py`**：`tick()` 上线后调用 `scheduler_agent.tick()`（Agent 进程检查到点任务）。
6. **Agent `__main__.py`**：启动时调用 `reconcile_zombies()`。

### 3.4 调整后架构

```
定时任务调度：
  Agent 进程（scheduler_agent.tick()，由 lifecycle.AgentLoop 每 tick 调用）
    → 遍历 scoped_tasks()：交易日 + task_due_now + scheduler_window_done 未完成
    → execute_task(trigger='auto') → 写云库 scheduler_runs (running → 终态)
  Dashboard：
    → 引擎只做报告重扫（展示刷新），不再派发
    → 手动「运行」= POST Agent（Agent 写云库记录，trigger=manual）
    → 只读展示云库 scheduler_runs
```

**效果**：每条任务每个窗口只有 1 条工作日志，状态真实（Agent 完成即回写），不再出现"已派发到 Agent 进程执行"卡 `running` + 重复记录。

### 3.5 备注

- **Claude Code loop**（`.claude/scripts/task_scheduler.py`，`scheduler_state.json` 幂等）是另一套独立调度器。若它与 Agent 进程同时启用，可能双跑；本次未改动它。用户可自行决定是否停用 loop（CHAT.md 任务1 已从 `task_schedule.json` 删除 3 条任务，loop 与 Agent 共用该文件）。
- **外部 cron**（`scheduler_cli.py` / Windows 计划任务）当前未激活（schtasks 无相关任务），`run_task`/`run_task_sync` 保留为休眠基础设施。

---

## 四、任务4：重做"每日信号"页面 🔄 待实施（2026-09-14 复核：尚未实施）

> v1.1 修订：本任务在 v1.0 写完后**未实施**（前端仍是旧版：`sigToggle`/`sigLoadLatest`/`renderMarkdown` 均在；后端无 history/trigger/enums API；云表无 trigger_price/trigger_time/entry_time 列；无枚举校验）。本节给出修订后的完整实施方案。

### 4.1 需求还原（对照 CHAT.md 第 4 条）

1. **去"原文视图"**：不再有原文/表格切换按钮，不再渲染 markdown。
2. **全云库化**：
   - **读**：`每日信号` 页一律读云库 `signal_tracking` 表，markdown 解析兜底逻辑移除；
   - **写**：早报、盘中分析**不再维护"原文"**（不再生成/维护 `每日信号.md` 的 markdown 正文作为数据载体），数据直接落云库（含枚举严格约束）。
3. **页面改为查询页**，三个表：
   - **表1 今日信号**：仅当天生成的信号。列（按顺序，只这 8 列）：`优先级 | 标的 | 操作类型 | 仓位 | 有效时段 | 状态 | 目标/止损 | 信号ID`。今天无信号或非交易日 → 空表。
   - **表2 历史信号查询**：字段与表1 基本一致，**第一列加"日期"列**，按日期**倒序**。查询条件（下拉/输入过滤）：日期、标的、操作类型、状态、信号ID。**操作类型、状态用枚举下拉**；生成信号时也**严格按枚举值**。
   - **表3 信号触发记录**：展示已触发信号的 触发价/触发时间（含日期、信号ID、标的、触发条件）。
4. **盘中记录触发**：盘中分析检查信号是否触发，**记录触发价、触发时间**（写入云库 `trigger_price`/`trigger_time`）。
5. **复盘关联交易**：复盘分析检查"录入交易"（`portfolio_trades` / `每日调仓.md`）中是否有该标的的交易记录，**有则记录买入价、买入时间**到信号（写入云库 `entry_price`/`entry_time`）。
6. **不再生成以下旧特性**：P0 执行追踪、盘中验证记录、盘中追加信号、信号与早盘报告对照、信号评价（复盘时填入）、当日信号统计、信号收益追踪（复盘时填入）、信号数量检查（自检）。

### 4.2 枚举值权威定义（v1.1 修订，与代码实测一致）

| 字段 | 云库/代码存储值 | 前端显示映射 | 说明 |
|---|---|---|---|
| `trade_type` 操作类型 | `buy` / `sell` | 买入 / 卖出 | 生成严格用 buy/sell |
| `status` 状态 | `待执行` / `已触发` / `已执行` / `已过期` / `已废弃` / `已取消` / `settled` | 同左 | 结算专用 `settled`（英文，与中文枚举并存，来自 `settle_due_signals`） |
| `direction` 方向 | `buy` / `sell` | 多 / 空 | **修正 v1.0 误写"多/空"**；实际存储 buy/sell |
| `priority` 优先级 | `P0` / `P1` / `P2` | 同左 | |
| `urgency` 紧急度 | `high` / `low` | 高 / 低 | |
| `source` 来源 | `morning_analysis` / `intraday_check` / `evening_review` | 早盘/盘中/复盘 | |
| `outcome` 结果 | `hit` / `stopped` / `miss` | 命中/止损/未达标 | |

> 枚举约束落点（v1.1 修订，不只是 cloud 层）：
> - `signal_tracking_cloud.py` `to_row()`/`cloud_upsert_signals()`/`cloud_update_fields()` — 写入前校验；
> - `lib/signal_tracking.py` `parse_signal_markdown()`/`merge_new_signals()` — 生成/解析侧校验；
> - 早盘/盘中 prompt 生成信号时按枚举词元。

### 4.3 页面布局（HTML）

```
┌─ 📡 每日信号 ──────────────────────────────────────────────────┐
│  ┌─ 今日信号 ────────────────────────────────────────────────┐ │
│  │ 表头: 优先级|标的|操作类型|仓位|有效时段|状态|目标/止损|信号ID│ │
│  │ 今日无信号/非交易日 → 空表                                  │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌─ 历史信号查询 ────────────────────────────────────────────┐ │
│  │ 查询: 日期[date] 标的[text] 操作类型[▼buy/sell] 状态[▼]   │ │
│  │       信号ID[text]  [查询][重置]                           │ │
│  │ 表头: 日期|优先级|标的|操作类型|仓位|有效时段|状态|目标/止损|信号ID│ │
│  │ 按日期倒序 + 分页                                        │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌─ 信号触发记录 ────────────────────────────────────────────┐ │
│  │ 表头: 日期|信号ID|标的|触发条件|触发价|触发时间|(买入价|买入时间)│ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌─ 信号质量评估（保留，不变）──────────────────────────────┐ │
└──────────────────────────────────────────────────────────────────┘
```

> 修订：表2 历史信号表**含 `信号ID` 列**（v1.0 布局漏列）；表3 触发记录追加 买入价/买入时间（便于复盘回填可见）。

### 4.4 后端 API 变更（`api_daily.py`）

| 接口 | 类型 | 变更说明 |
|---|---|---|
| `GET /api/daily-signals` | 修改 | 去掉 markdown/parsed 兜底；仅返回今日云库信号（8 字段视图）；空则空表 |
| `GET /api/signal-history` | 新增 | 历史信号分页查询：`?date=&ticker=&trade_type=&status=&signal_id=&page=&page_size=`，按 `signal_date` 倒序 |
| `GET /api/signal-enums` | 新增 | 返回 `{trade_type, status, direction, priority, urgency, source, outcome}` 枚举（供前端下拉） |
| `GET /api/signal-triggers` | 新增 | 信号触发记录查询：`trigger_price`/`trigger_time` 非空的行，按日期倒序 |
| `POST /api/signal-trigger` | 新增 | 盘中记录触发价/触发时间：`{signal_id, trigger_price, trigger_time}` → 云库更新 |
| `POST /api/signal-entry` | 新增 | 复盘关联录入交易：`{signal_id, entry_price, entry_time}` → 云库更新 |
| `GET /api/signal-quality` | 保留 | 信号质量评估不变 |

> 校验：POST 两个接口校验 `signal_id` 存在、枚举/数值合法；写云库走 `signal_tracking_cloud.cloud_update_fields`（含枚举校验）。

### 4.5 前端 JS 变更（`daily.js` + `dashboard.html`）

| 函数 | 变更 |
|---|---|
| `sigLoad()` | 重写：加载今日信号（`/api/daily-signals`）+ 历史列表（`/api/signal-history`）+ 触发记录（`/api/signal-triggers`）+ 枚举（`/api/signal-enums`） |
| `sigLoadLatest()` | 删除 |
| `sigRender()` | 重写：仅渲染结构化表（8 列视图），不渲染 markdown |
| `sigToggle()` | 删除（无原文/表格切换） |
| `renderCloudSignals()` | 修改：今日表用 8 字段列 |
| `renderMarkdown()` | 删除（不再用于信号页；报告页 `rep-content` 仍用，`marked.js` 保留） |
| `sigHistoryLoad()` / `sigHistorySearch()` / `sigHistoryReset()` | 新增：历史查询/过滤/分页 |
| `sigTriggerLoad()` | 新增：触发记录表 |
| `sigqLoad()` / 质量渲染 | 保留 |

### 4.6 数据库变更

**`signal_tracking` 表新增字段**（`etf-strategies/scripts/cloud_schema_signal_tracking.sql`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `trigger_price` | REAL | 触发价（盘中回填） |
| `trigger_time` | TEXT | 触发时间（盘中回填，`HH:MM`） |
| `entry_time` | TEXT | 买入时间（复盘关联交易回填） |

> `entry_price`、`shares` 已在 schema 中。需要新增的是 `trigger_price`、`trigger_time`、`entry_time` 三列。
> 存量历史信号这三列为 NULL，不影响查询。

### 4.7 盘中/复盘 prompt 联动（v1.1 修订：纳入范围，非"不在本次范围内"）

**`auto_intraday_check.md`**：
- 触发验证：信号触发 → 调用 `POST /api/signal-trigger`（或等价 lib：`signal_tracking_cloud.cloud_update_fields(signal_id, {trigger_price, trigger_time})`）写云库；
- 保留 `## 信号触发记录` 章节作为人读记录（内容与云库一致），或直接移除该 markdown 章节（数据在云库表3 展示）；
- 移除：`## 盘中验证记录`、`## 盘中追加信号`、`## P0 执行追踪` 章节及对应 REQ-007 逻辑。

**`auto_evening_review.md`**：
- 信号入库（`parse_signal_markdown → merge_new_signals → upsert_signals`）保留（这是云库数据入口）；
- 新增：检查"录入交易"（`portfolio_trades` / `每日调仓.md`）中是否有该标的交易 → 有则 `POST /api/signal-entry` 写 `entry_price`/`entry_time`；
- 移除：信号评价（决策/执行质量）、当日信号统计、信号收益追踪（P&L 结算）、信号数量检查、信号与早盘报告对照、P0 执行率统计等旧章节。

> 注：移除的章节有部分复用 `lib/signal_quality.py`（周报 `auto_signal_quality_weekly.md` 仍消费云库，保留不动）。

### 4.8 文件变更清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `etf-strategies/dashboard/templates/dashboard.html` | 修改 | 重写 `#view-signals` 区域为三表 + 查询区 |
| `etf-strategies/dashboard/static/js/daily.js` | 修改 | 信号相关函数重写 |
| `etf-strategies/dashboard/api_daily.py` | 修改 | 新增/修改信号 API + 枚举校验 |
| `etf-strategies/scripts/cloud_schema_signal_tracking.sql` | 修改 | 新增 trigger_price/trigger_time/entry_time 列 |
| `my_doc/每日复盘/harness/automation/lib/signal_tracking_cloud.py` | 修改 | 枚举校验 + 新列写入支持 |
| `my_doc/每日复盘/harness/automation/prompts/auto_intraday_check.md` | 修改 | 触发记录写云库 + 移除旧章节 |
| `my_doc/每日复盘/harness/automation/prompts/auto_evening_review.md` | 修改 | 交易关联写云库 + 移除旧章节 |
| `docs/signal-enums.md` | 新增 | 枚举值权威定义（同 4.2） |

### 4.9 风险点（v1.1 修订）

1. **marked.js 依赖**：信号页不再用 markdown，但**报告页 `rep-content` 仍用 `renderMarkdown`**，不能删 marked.js。
2. **信号质量评估依赖**：`signal-quality` 与周报 `auto_signal_quality_weekly.md` 复用云库 `signal_tracking` 表，本次改动不影响其数据源。
3. **存量历史信号**：新增列全为 NULL，不影响查询与展示。
4. **盘中/复盘 prompt 改动**：这两处 prompt 是数据闭环关键（触发价/买入价写入云库），**在本次范围内**（v1.0 曾写"不在范围内"，已修正）。
5. **云库 DDL 迁移**：新增三列需在云库执行（byted-supabase-cli db query 或等价），本地 schema 文件同步更新；执行前先备份表。

---

## 五、附录：删除后任务全景（18 个）

删除 `bug_inspect_logic` / `harness_bug_auto_fix` / `pending_remind` 后，`task_schedule.json` 实存 **18 个任务**：

| # | task_id | 触发规则 | 类型 |
|---|---|---|---|
| 1 | morning_analysis | 工作日 09:07 | 每日 |
| 2 | intraday_0940 | 工作日 09:40 | 盘中 |
| 3 | intraday_1000 | 工作日 10:00 | 盘中 |
| 4 | intraday_1030 | 工作日 10:30 | 盘中 |
| 5 | intraday_1100 | 工作日 11:00 | 盘中 |
| 6 | intraday_1330 | 工作日 13:30 | 盘中 |
| 7 | intraday_1400 | 工作日 14:00 | 盘中 |
| 8 | intraday_1430 | 工作日 14:30 | 盘中 |
| 9 | evening_review | 工作日 15:52 | 每日 |
| 10 | bug_auto_fix | 小时 :07, 9-18 | 周期 |
| 11 | bug_inspect_data | 工作日 12:07 | 每日 |
| 12 | bug_inspect_code | 工作日 12:17 | 每日 |
| 13 | strategy_scan_weekly | 周二 12:37 | 每周 |
| 14 | experience_health | 周三 12:47 | 每周 |
| 15 | weekly_portfolio | 周四 13:17 | 每周 |
| 16 | req_implement | 工作日 12:57 | 每日 |
| 17 | logic_inspect | 每天 17:07 | 每日 |
| 18 | signal_quality_weekly | 周三 16:30 | 每周 |

> 修正：v1.0 附录称"保留 16 个任务"有误（按 21−3=18 应为 18）；且附录当时列出的行数(18)与实际(18)一致，仅文字"16"错误。

---

## 六、2026-09-21 Dashboard 续优化（v1.3 追加）

> 两个改动：① 修复盘中检查覆盖已执行信号状态；② 信号触发记录落库 + 每日信号页点击展开。

### 6.1 终态状态保护（BUG-FIX）

**背景事故**（2026-09-21）：通信ETF/创新药ETF 两条信号用户已在 Dashboard「一键执行」（云库 `status=executed`），盘中检查 §5.3 用 `parse_signal_rows_all` 重新解析 markdown 后整体 `cloud_upsert_signals`，把 executed 覆盖成 expired/triggered。

**修复（双保险）**：
1. **数据层硬保护**（`lib/signal_tracking_cloud.py`）：
   - 新增终态等级 `_STATUS_FINALITY`：open(0) < triggered(1) < expired(2) < executed(3)=partial_executed(3) < settled(4)；
   - `cloud_upsert_signals` upsert 前先查云库既有状态（`_protect_existing_terminal`），若既有终态等级 ≥ 新状态等级 → 保留既有状态；
   - `cloud_update_fields` 同样保护（fields 含 status 时先取既有状态）。
   - 升级流转（triggered→executed、executed→settled）不受影响。
2. **prompt 指引**（`auto_intraday_check.md`）：
   - §3.0 新增"已执行信号保护"：验证前先加载云库当日信号状态（`cloud_load_signals`），终态信号（executed/partial_executed/settled）跳过——不验证、不改 markdown 状态列、不追加触发记录、不写云库降级；
   - §5.1/5.2/特别说明 同步标注终态信号不可改。

### 6.2 信号触发记录落库 + 前端展开

**需求**：盘中生成的"信号触发记录"落库并通过 signal_id 关联；每日信号页点击某条信号，在数据下方展开关联触发记录表格。

**实现**：
1. **新云表 `signal_trigger_records`**（`scripts/cloud_schema_signal_trigger_records.sql` + 并入 `cloud_schema_pg.sql`）：
   - 列：signal_id / trigger_date / trigger_time / priority / ticker / name / action_type / condition / status / suggest / result / created_at / updated_at；
   - 幂等键：`UNIQUE(signal_id, trigger_time)`（同信号同触发时间只一条，同检查点重跑不重复）。
2. **lib**（`lib/signal_tracking_cloud.py`）：
   - `to_trigger_row(rec)` / `cloud_upsert_trigger_records(records)`（on_conflict=signal_id,trigger_time）/ `cloud_load_trigger_records(signal_id, trigger_date)`；
3. **盘中 prompt**（`auto_intraday_check.md` §5.2）：触发记录追加 markdown 行的同时，调用 `cloud_upsert_trigger_records` 落库（终态信号不追加）。
4. **API**（`api_daily.py`）：`GET /api/signal-trigger-records?signal_id=&date=&limit=` → `{items}`。
5. **前端**（`daily.js` + `dashboard.css`）：信号行「信号ID」单元格可点击展开（▸/▾），下方插入 colspan 明细行，内嵌触发记录表格（触发时间|优先级|标的|操作类型|触发条件摘要|状态|建议操作|用户操作），带缓存（视图进入时清空）。

**DDL 已应用到 live pg 库**（pgdirect 后端，GRANT 仅 Supabase 生效，pg 端不需 GRANT）。

---
