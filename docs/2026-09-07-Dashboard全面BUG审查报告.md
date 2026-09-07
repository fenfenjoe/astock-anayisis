# AStock ETF Dashboard 全面 BUG 审查报告（2026-09-07）

> 触发：用户重启 dashboard + agent 两个进程后报告"小满定时任务不工作"；随后要求对 Dashboard 项目做总体 BUG 审查。
> 审查方式：3 个并行子代理（agent 进程 / dashboard API+安全 / 前端集成）+ 本助手直接验证（云库、调度器、双进程）。
> 结论：调度器已恢复正常（14:00 已正常 auto 派发 intraday_1400）；本次审查发现并修复 15 处真实 BUG，另记录 15 处待办风险。

---

## 一、Issue 1：重启后"定时任务不工作"排查结论

### 结论：引擎已正常工作，14:00 已成功 auto 派发 —— 问题根因已定位并修复

**排查证据链**（云库 `scheduler_runs` + 双调度器状态）：
1. dashboard 引擎重启后活着且在 tick：日志 `[scheduler] engine started (auto=True)` + `[scheduler] report rescan imported ...`；云 `reports_scan_state` 含 `tos:20260907/*`（引擎处理了今天报告）。
2. 门控全部通过：`agent_online()=True`（云 `xiaoman_online='1'`）、`auto_enabled()=True`、`is_trading_day(2026-09-07)=True`。
3. **14:00:18 引擎成功 auto 派发 `intraday_1400`（id=827，trigger=auto）** —— 重启后首次 auto 运行，准点触发。
4. agent 进程健康：心跳 13:39~13:51 持续更新，RSS/自定义源 13:39 拉取，状态机正常流转（gaming→reading 事件）。

**用户看到"没在工作"的原因**：
- 今早 09:07 等盘中窗口触发时，跑的还是**旧代码**（Q1 门控 bug 未重启生效前）→ 未 auto 派发（只有 09:21 手动跑）。
- 重启（13:34）后到 14:00 之间**无到期窗口**，属正常空档，不是故障。

**发现并修复的真实缺陷（启动时序）**：
- `dashboard/app.py` `_bg_restore_and_import()`：原先把 `daily_scheduler.start()` 放在报告导入（云调用，可能数分钟）**之后**，导致重启后错过启动期间已到期的窗口（今天 13:30 intraday_1330 被错过）。
- ✅ **已修复**：引擎 `start()` 移到后台线程第一步（导入之前），导入与引擎并行。引擎 `start()` 幂等，先启动不丢窗口。

**架构性风险（需用户决策）**：项目存在**两套调度器并存**：
- **dashboard 引擎**（`scheduler.py`，Web "工作日程"页，幂等=云 `scheduler_runs`）
- **Claude Code /loop**（`task_scheduler.py`，幂等=`.claude/scripts/scheduler_state.json`）

两者跑同一套任务（morning_analysis/intraday_*/evening_review/bug_auto_fix…），**幂等系统互不感知** → 同一任务可能被两套各执行一次（重复分析、重复发文）。今天实测：Claude loop 13:46 跑了 intraday_1330（dashboard 引擎因启动时序错过）；dashboard 引擎 14:00 跑了 intraday_1400（Claude loop 状态无该条目）。**建议**：明确一套为唯一执行者（如 dashboard 引擎接管全部，或 Claude loop 关闭 dashboard 侧对应任务），避免双执行。

---

## 二、本次已修复的 BUG（15 处）

### 云迁移相关（核心，均与"云权威"原则相关）

| # | 文件 | 问题 | 修复 |
|---|------|------|------|
| 1 | `agent/db.py:594` | `knowledge_with_memory` 云分支过滤**反相**（`memory is null` 返回无记忆条目，SQLite 分支是 `IS NOT NULL`）→ 阅读记忆/个人档案取反数据 | 改为 `("memory","not.is",None)`，已实测 PASS |
| 2 | `dashboard/app.py` | `_generate_and_store_signal` 直写本地 sqlite `daily_signals`，云模式本地无此表 → 全新机 500 / 迁移机写本地读云端（信号不跨机共享） | 改走云 `signals_delete_by_strategy` + `signals_upsert` |
| 3 | `dashboard/sync.py` | `sync_daily_signals` 同样直写本地 sqlite（同 2） | 同上，云模式 `count` 改云查询 |
| 4 | `dashboard/db.py` | `signals_upsert`/`report_upsert` 云分支是 select-then-insert，双进程并发写会重复 | 改 `_cd_upsert(on_conflict=...)`，依赖新加唯一约束 |
| 5 | `scripts/cloud_schema_unique.sql`（新） | `daily_signals`/`daily_reports`/`portfolio_holdings`/`agent_knowledge`/`agent_sources` 云表缺唯一约束 | 已建 5 个唯一索引（幂等），防并发重复 |
| 6 | `agent/db.py` | `source_add` 云分支 plain insert，撞新唯一约束会 409 | 改 `_cd_upsert(on_conflict="name")` |
| 7 | `cloud_db.py` | 过滤器 bool 值拼 `eq.True`（Python str），PostgREST 只认小写 `eq.true` → 过滤异常/空结果 | 三处 filter 循环统一 bool→小写 true/false |
| 8 | `agent/core/lifecycle.py` | RSS **假健康**：所有源失败时 `fetch_and_store` 返回 errors 不抛异常，原代码仍无条件写 `last_rss_fetch_at` → RSSHub 挂掉时看板显示健康实则零新素材 | 仅当"配置了源且全部失败"才不写时间戳（feeds==0 保持节流语义），15 测试通过 |

### 后端 API / 安全

| # | 文件 | 问题 | 修复 |
|---|------|------|------|
| 9 | `dashboard/api_daily.py:476` | `get_daily_signals` 引用未定义 `date_str` → 指定日期无信号时 **500 而非 404** | 改 `{date}`，已修 |
| 10 | `dashboard/app.py` | 后台线程先导入后启动引擎 → 错过启动期间调度窗口 | 引擎先启动（见 Issue 1） |

### 前端

| # | 文件 | 问题 | 修复 |
|---|------|------|------|
| 11 | `dashboard/static/js/agent.js` | SSE 聊天错误被 `thinkBubble.remove()` 静默删掉 → 用户无任何错误提示 | 错误时保留错误气泡并 return |
| 12 | `dashboard/static/js/daily.js` | 信号日期选择器失效（`sigLoad` 恒渲染 `dates[0]`）→ 无法看历史信号 | 用 `sel.value` 渲染选中日期 |
| 13 | `dashboard/static/js/daily.js` | 信号表格缺"触发条件"列（12 列变 11 列，静默丢数据） | 补回并统一顺序 |
| 14 | `dashboard/static/js/agent.js` + `auth.js` | agent.js 三处裸 fetch（删会话/聊天/删素材源）token 过期时静默失败，不跳登录；`deleteSource` 甚至不查 resp.ok | auth.js 新增 `Auth.fetchDelete`，三处统一改用 `Auth.fetchPost/fetchDelete`（401→清 token+跳登录），deleteSource 补 resp.ok 检查 |

### 测试

| # | 文件 | 问题 | 修复 |
|---|------|------|------|
| 15 | `tests/test_agent_db_cloud.py` | `test_cloud_activities` 断言全局无 open 活动，运行中 agent 真实活动导致 flaky | 改为断言自己创建的活动已关闭 |

---

## 三、确认无需改 / 既有失败已消解

- **`run_post_pipeline` 测试失败**：项目自动化系统（bug_auto_fix）已把测试改名为 `run_publish_pipeline`，实测 15 个 behavior/lifecycle 测试全过。
- **`r1["rss"] is not None` 测试失败**：根因是测试宿主进程读到云 `last_rss_fetch_at`（RSS 被节流）。`tests/conftest.py` 强制 `AGENT_DB_BACKEND=file` 隔离已修复，实测通过。
- **云不可达 fail-fast**：`cloud_db` 未配置→fail-safe 空结果（测试/本地友好）；配置了但不可达→抛 `CloudDBError`（启动/接口 500）。**属合理设计**（配置了云却连不上应响亮失败而非静默空数据），保留。
- **JSONB 往返**：`assets`/`backtest`/`sources`/`topics` 云→前端数组消费验证通过，无误报。
- **agent 状态机/活动模型**：switch_state 关旧开新正确；reading/writing 是动作事件（自动关闭），gaming 等是状态段（持续 open），符合设计。

---

## 四、待办风险（建议后续处理，未在本次改动）

### 🔴 建议尽快
1. **双调度器并存**（见 Issue 1）→ 二选一，防重复执行。
2. **无角色鉴权**：`viewer` 角色可执行全部写操作（开关调度/触发重型任务/删会话/覆盖东财凭据）。建议 admin-only 接口加角色校验。
3. **JWT 无即时注销**：`is_active` 不参与校验，禁用后 token 8h 内仍有效。建议校验时读 `is_active`。

### 🟠 中等
4. **心跳-存活阈值不匹配**：`lifecycle.py:97` 单轮 tick 若 RSS+自定义+阅读+发文全到期且 LLM 慢可达 850s+，超 `api_agent.py:89` 900s 判定会误判离线；且心跳是第一步，云瞬时故障整轮中止。建议分步 try + 长任务前后各写心跳。
5. **全进程零日志 + 异常吞没**：RSS/发文/云故障全静默（RSS 假健康已在本次修复 #8；其余步骤仍缺日志）。建议加 logging。
6. **发文管线非事务**（`behavior.py:157-168`）：article_create 后任一步失败 → published_on 未写 → 下 tick 重发重复文章。
7. **writing 读改写竞态**（`lifecycle.py:187-206`）：tick 置 writing 后发布窗口内用户手动切状态被静默回滚（跨进程丢失更新）。
8. **活动台账跨进程误关**（`db.py activity_close_open` 关"最新 open"而非自己开的）：可能关错 dashboard 手动切换的活动。
9. **持仓/交易 replace 云分支非原子**：DELETE 全部 + 逐行 INSERT（N+1 请求），中途失败丢数据。建议改批量 upsert。
10. **调度 runs 列表返回全量 output**：30s 轮询浪费带宽。建议列表接口排除 output 列。
11. **云不可达时调度引擎关键路径阻塞**：`_tick` 内 rescan/agent_online/auto_enabled 的云调用在派发前同步执行（启动时序已修，引擎内 rescan 仍为复发点）。建议 rescan 移子线程 + meta 读加短 TTL 缓存。

### 🟡 低
12. `behavior.py:229-230` sleep 前置闸门死代码（`max(1,w)` 强制 ≥1）；`config.py` 5 个常量定义未用。
13. 云后端 `strategy_id` 排序字典序（S10 在 S2 前），靠前端重排兜底。
14. `meta_get("published_on")` 重复云请求；打字机长消息 O(n²)。

---

## 五、测试状态汇总

- 完整非 realcloud 套件（`-m "not realcloud"`）：**461 passed, 1 skipped, 13 deselected 全绿**
  （原基线为 458 passed + 4 failed + 2 skipped；4 个既有失败已由自动化修复 `run_post_pipeline` + conftest 强制 `AGENT_DB_BACKEND=file` 修复 rss 测试而消解）
- 云测试套件（realcloud，需显式 env）：**26 passed**（cloud_db 15 + dashboard_db 6 + agent_db 5）
- 调度/行为/生命周期定向：**39 passed**

## 六、改动文件清单

后端：`agent/db.py`、`dashboard/app.py`、`dashboard/db.py`、`dashboard/sync.py`、`dashboard/api_daily.py`、`cloud_db.py`
前端：`dashboard/static/js/agent.js`、`dashboard/static/js/daily.js`
新增：`scripts/cloud_schema_unique.sql`
测试：`tests/test_agent_db_cloud.py`
