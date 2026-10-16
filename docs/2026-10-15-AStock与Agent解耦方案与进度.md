# astock-anayisis 与 Agent 解耦改造 —— 实施方案与进度（2026-10-15）

> 本文档是**续跑交接文档**：记录改造目标、用户已确认的决策、当前进度（已完成/进行中/待办）、
> 所有路径引用点、验证清单。另开对话续跑时，先读本文档，再按「待完成任务」顺序执行。
>
> 最后更新：2026-10-16（§四 待完成任务已全部完成，见 §六 变更记录）

---

## 一、任务背景与最终目标

用户要求将 `E:\ideaworkspace\astock-anayisis`（A股投研项目）从「Agent + Web 糅合系统」重构为
**「提供给 Agent 使用的纯量化系统」**：

1. **降低与 agent 的耦合**：把 `/.agents`、`/.dsh`、agent 运行时、自动化层等 agent 相关内容
   全部迁移到用户目录 `~/.dsh/`，仓库内不留 agent 运行时与耦合模块。
2. **清理临时文件**：激进清理仓库内无用临时文件/缓存/备份。
3. **纯量化系统**：Agent 通过项目提供的**标准化使用手册**（`docs/AGENT_GUIDE.md`）调用
   astock-anayisis 的量化接口（数据/回测/信号/报告），并在**自己的 Web**（小满 Web）展示输出。

### 最终架构（用户确认版）

```
astock-anayisis (仓库) = 纯量化系统
├── etf-strategies/dashboard   → 量化 Dashboard (:8010)  【纯量化展示+API】
│     策略全景 / 持仓 / 信号 / 报告 / 回测 / 权益曲线 / 工单管理
├── etf-strategies/backtest    → 回测引擎
├── etf-strategies/*.py        → CLI 工具（回测/信号/报告/数据）
├── docs/                      → Agent 标准化使用手册（AGENT_GUIDE.md）+ 设计文档
└── my_doc/                    → 报告输出 / 持仓.md / 每日调仓.md（用户数据，保留在仓库）

~/.dsh/ = DSH 用户目录（agent 全部内容收敛于此）
├── skills/                    → 全部技能（已从 .agents/.dsh 合并去重，30 个）
├── profiles/ sessions/ logs/  → dsh 配置与会话（已迁入）
└── workspace/xiaoman/         ← 小满之家（原计划 ~/.dsh/astock，用户 2026-10-15 拍板改名）
    ├── agent/                 → 小满运行时（内嵌 HTTP API :8020，X-Api-Key 鉴权）
    ├── automation/            → ETF 自动化 prompts/config/bugs/steering
    ├── harness/               → 每日复盘 harness（prompts/experience/config/staging/archive + automation）
    ├── scripts/               → 调度基础设施（task_schedule.json/dsh_trigger/start_all.ps1 等）
    ├── evolution/             → DSH 自进化文档
    └── web/                   → 【待建】小满 Web（纯前端 SPA：桌宠/角色页/聊天/工作日程/提示待办/文章）
```

### 数据流

- **量化 Dashboard**（:8010）：独立运行，纯量化展示 + API。
- **小满 Web**（待建）：独立运行，纯前端直连 agent API(:8020)，展示小满的桌宠/角色/聊天/工作日程/
  提示待办/文章；如需展示量化结果，再调 Dashboard API(:8010)。
- **Agent（小满）**：运行在 `~/.dsh/workspace/xiaoman/agent/`，读仓库 `docs/AGENT_GUIDE.md` →
  调量化 API → 在小满 Web 展示输出。**职责分离：量化系统管数据和 API，agent 管执行和展示。**

---

## 二、用户已确认的关键决策（binding）

| # | 决策点 | 结论 | 时间 |
|---|--------|------|------|
| 1 | agent 运行时/自动化层去向 | 迁至 `~/.dsh`（不留在仓库） | 会话早期 |
| 2 | 清理强度 | **激进清理**（临时文件/缓存/备份全删） | 会话早期 |
| 3 | Dashboard 定位 | **纯量化展示+API**，移除角色页/工作日程/桌宠/聊天 | 2026-10-15 |
| 4 | 小满 Web 形态 | **纯前端 SPA + 直连 agent API(:8020)** | 2026-10-15 |
| 5 | 工单管理页 | **保留在 Dashboard**，改用 Dashboard 的 db（云库 tickets 表） | 2026-10-15 |
| 6 | 小满 Web 位置 | `~/.dsh/workspace/xiaoman/`（**不用 astock 目录名**），Dashboard 解耦出的内容也放这里 | 2026-10-15 |
| 7 | astock 目录 | **废弃**：`~/.dsh/astock/*` 全部移入 `~/.dsh/workspace/xiaoman/` 后删除 astock | 2026-10-15 |

> 注：决策 6/7 是最后一轮拍板，**已执行完成**（见 §三.5）。

---

## 三、当前进度（已完成的步骤）

### 3.1 服务停启（✅ 完成）
- 停掉运行中的 dashboard(PID 27756, :8010) 与 agent(PID 33316, :8020)，释放文件锁。
- 验证端口已释放。改造完成后需重启（见 §四.9 验证）。

### 3.2 激进清理（✅ 完成）
**仓库根目录删除**（git rm 已暂存）：
- `_*.py`、`_*.json` 临时脚本/文件（一次性取数脚本按规范 `_*.py` 命名、跑完即删）
- `_dsh_plugin_research/`、`_pet_shots/`、`_tmp_search/`
- `.superpowers/`、`.trae/`、`.npm-cache/`、`node_modules/`、`.pytest_cache/`、`.ruff_cache/`、`__pycache__/`
- `CHAT.md`、`RESPONSE.md`、`signal_tracking_backup_20260914.json`

**etf-strategies/ 下删除**：
- `_tmp_backup_043..058` 系列、`drawdowns.png`、`equity_curves.png`（生成的图表）
- `.coverage`、`_migrate_export.json`、`_tickets_backup_*.json`、缓存目录

**保留**：`docs/`（设计文档）、`my_doc/每日复盘/reports/`（用户分析输出）、`每日调仓.md`（权威交易日志）。

### 3.3 迁移 `.dsh/` + `.agents/` → `~/.dsh/`（✅ 完成）
- `.dsh/skills/`（30 个技能）→ `~/.dsh/skills/`（与既有技能合并去重）
- `.dsh/profiles/`（xiaoman/headless 定义文件）→ `~/.dsh/profiles/`（已验证）
- `.dsh/sessions/`、`logs/`、`backup/`、`trade-entry/`、`.anonymous-user-id` → `~/.dsh/` 对应位置
- `.dsh/.credentials.example.yaml` → `~/.dsh/astock-credentials.example.yaml`
- `scripts/restart-web.ps1`、`task_export.xml` → `~/.dsh/workspace/xiaoman/scripts/`（随 scripts 迁移）
- `.agents/` 技能 → `~/.dsh/skills/`（合并去重）
- 仓库内 `.agents/`、`.dsh/` 已删除（git 已暂存删除，62 个文件）

### 3.4 迁移 agent 运行时 + 自动化层（✅ 完成，后并入 xiaoman）
- `etf-strategies/agent/` → `~/.dsh/workspace/xiaoman/agent/`
  （排除 104MB `data/browser_profile/`；保留代码 + `data/agent.db` + 依赖 `cloud_db.py`/`load_env.py`）
- `etf-strategies/automation/` → `~/.dsh/workspace/xiaoman/automation/`
- `my_doc/每日复盘/harness/` → `~/.dsh/workspace/xiaoman/harness/`
  （`config/持仓.md` **移回仓库** `my_doc/每日复盘/持仓.md`，属用户数据）
- 根 `scripts/` → `~/.dsh/workspace/xiaoman/scripts/`
  （task_scheduler.py、task_schedule.json、dsh_*.py、start_all.ps1、sync_dsh.ps1、config/、logs/ 等）
- `evolution/` → `~/.dsh/workspace/xiaoman/evolution/`
- 仓库内对应目录已删除（git 已暂存）

### 3.5 目录更名：`~/.dsh/astock/` → `~/.dsh/workspace/xiaoman/`（✅ 完成，用户拍板）
- `~/.dsh/workspace/` 原先不存在 → 新建 `workspace/xiaoman/`
- `~/.dsh/astock/{agent,automation,evolution,harness,scripts}` → `~/.dsh/workspace/xiaoman/` 对应目录
- `~/.dsh/astock/` 已删除（空目录移除）
- **验证通过**：`~/.dsh/workspace/xiaoman/` 下 5 个目录齐全，关键文件存在：
  - `agent/api.py`、`agent/__main__.py` ✓
  - `scripts/task_schedule.json`、`scripts/start_all.ps1` ✓
  - `harness/automation/config/trading_calendar.py`、`signal_tracking.json` ✓

### 3.6 Dashboard 解耦 —— 后端（✅ 完成）

**新建 `etf-strategies/dashboard/importer.py`**（量化数据导入器）：
- 从原 `scheduler.py` 提炼纯量化数据导入能力：`import_reports_from_disk`、
  `import_holdings_from_md`、`import_trades_from_md`、`is_trading_day`、`next_trading_day`、
  `_report_type_from_name`、`_weekly_date`、`_HTML_REPORT_TYPES`
- 常量路径已指向新位置：
  - `REPORTS_DIR = <repo>/my_doc/每日复盘/reports`
  - `HOLDINGS_MD = <repo>/my_doc/每日复盘/持仓.md`
  - `TRADES_MD = <repo>/my_doc/每日复盘/每日调仓.md`
  - `TRADING_CALENDAR_PATH = ~/.dsh/workspace/xiaoman/harness/automation/config/trading_calendar.py`

**`etf-strategies/dashboard/portfolio.py`**（✅）：
- `HOLDINGS_MD` → `my_doc/每日复盘/持仓.md`（原 harness/config 路径废弃）
- `SNAPSHOT_DIR` → `~/.dsh/trade-entry/undo`（撤销快照随 .dsh 迁移）
- 文档字符串同步更新

**`etf-strategies/dashboard/app.py`**（✅）：
- 移除 `from dashboard.api_agent import router as agent_router`
- `from dashboard import scheduler as daily_scheduler` → `from dashboard import importer as daily_importer`
- 启动逻辑：移除 `daily_scheduler.start()`（引擎启动），保留报告/持仓/交易导入
- 关闭逻辑：移除 `daily_scheduler.engine.stop()`，保留 notify watcher stop
- 移除 `app.include_router(agent_router)`；保留 `tickets_router`
- ⚠️ **注意**：`from dashboard.api_tickets import router as tickets_router` 保留（工单留 Dashboard）

**`etf-strategies/dashboard/api_daily.py`**（✅）：
- `from dashboard import scheduler` → `from dashboard import importer`
- `/reports/import` 端点改用 `importer.import_reports_from_disk()`
- **删除全部 `/scheduler/*` 路由**（工作日程 API 移除，1360→1175 行）：
  `/scheduler/tasks`、`/status`、`/engine`、`/auto`、`/run/{task_id}`、`/stop/{task_id}`、
  `/runs`、`/runs/{run_id}/log`
- harness 路径引用更新：
  - `signal_tracking.json` 兜底 → `~/.dsh/workspace/xiaoman/harness/automation/config/signal_tracking.json`
  - `_inject_harness_lib()` → `~/.dsh/workspace/xiaoman/harness/automation`
- 补 `import os`

**`etf-strategies/dashboard/api_tickets.py`**（✅ 重写）：
- 移除 `from agent import db as agent_db`（agent 包已外迁，此 import 会导致 Dashboard 起不来）
- 改为直连云库 `tickets` 表（经 `cloud_db`）：`list_tickets` / `get_ticket` / `retrigger_ticket`
- `retrigger` 仍调用 agent API `AGENT_API_URL/api/agent/scheduler/run/{task_id}`（X-Api-Key 鉴权）
- 云库不可用时优雅降级（返回空列表/source=unavailable），不崩 Dashboard
- 字段对齐 agent.db：`id,kind,title,description,severity,status,source_task,assignee,created_at,updated_at,result,log_entries`

---

## 四、待完成任务（按顺序执行）

> ✅ **全部完成（2026-10-16）**：4.1~4.7 已执行完毕，验证通过（Dashboard 导入冒烟 ✓、
> 残留 import grep ✓、测试套件 419 passed ✓、小满 Web SPA 建成 8 tests ✓）。

### 4.1 迁移 agent UI 资产出 Dashboard → 小满 Web（✅ 完成）
**动作**：把以下 Dashboard 前端资产**移动到** `~/.dsh/workspace/xiaoman/web/`（不要删除，小满 Web 要复用）：
```
etf-strategies/dashboard/static/js/agent.js         → web/static/js/agent.js
etf-strategies/dashboard/static/js/pet.js           → web/static/js/pet.js
etf-strategies/dashboard/static/js/_pet_old_0918.js → web/static/js/_pet_old_0918.js
etf-strategies/dashboard/static/css/agent.css       → web/static/css/agent.css
etf-strategies/dashboard/static/css/pet.css         → web/static/css/pet.css
etf-strategies/dashboard/static/live2d/             → web/static/live2d/（模型+vendor 全量）
```
同时把 `dashboard.html` 中以下片段**提取到**小满 Web 页面（作为 SPA 的页面模板参考）：
- 角色 view（`view-agent`，~L522-589 及聊天逻辑）
- 工作日程 view（`view-scheduler`，~L433-485）
- 桌宠 UI（Live2D，~L594-614）
- 相关 script 引用（agent.js、pet.js）

### 4.2 从 dashboard.html 移除 agent 相关 UI（✅ 完成）
在 `etf-strategies/dashboard/templates/dashboard.html` 中删除：
- 顶部导航的「💬 角色」「🗓️ 工作日程」入口（约 L88-89）
- `view-scheduler`、`view-agent`、桌宠 UI 三大块
- `agent.css`/`pet.css` link（约 L9-10）、`agent.js`/`pet.js` script（约 L623-624）
- 保留：策略全景/持仓/信号/报告/回测等纯量化 view + 工单页
- 移除后确认无 JS 引用已删除的 view/元素（避免控制台报错）

### 4.3 删除 dashboard 内 agent 调度引擎残留（✅ 完成）
- **删除** `etf-strategies/dashboard/scheduler.py`（引擎+dsh 运行器，数据导入已由 importer.py 接管）
- **删除** `etf-strategies/dashboard/scheduler_cli.py`（agent CLI 触发工具，属 agent 自动化）
- **删除/迁移** `etf-strategies/scripts/etf_trigger.py`（imports dashboard.scheduler_cli）
  → 迁移到 `~/.dsh/workspace/xiaoman/scripts/`（agent 自动化侧）
- ⚠️ **测试引用需处理**（见 §五.1）

### 4.4 搭建小满 Web（`~/.dsh/workspace/xiaoman/web/`）（✅ 完成）
**形态**：纯前端 SPA（HTML+JS+CSS，无后端；可用 Python `http.server` 或任意静态服务器托管，
或小脚本起个简单服务）。**直连 agent API(:8020)**，请求头带 `X-Api-Key`（`AGENT_API_KEY` 环境变量，
`start_all.ps1` 中为 `xiaoman-secret-key-change-me`）。

**页面清单**（用户确认）：
1. **桌宠**：复用 live2d + pet.js（Live2D 交互）
2. **角色页**：人设/状态（`GET /api/agent/profile`、`/status`）、动态（`/activities`）、
   文章（`/articles`、`/articles/{aid}`）、上下线（`POST /online`、`/offline`）
3. **聊天**：会话列表（`GET/POST /api/agent/sessions`、`DELETE /sessions/{sid}`）、
   消息（`GET/POST /sessions/{sid}/messages`）、素材源（`/sources`）
4. **工作日程**：任务列表+运行日志（`GET /api/agent/scheduler/status`、
   `POST /api/agent/scheduler/run/{task_id}`、`POST /stop/{task_id}`）
5. **提示待办**：通知（`GET /api/agent/notices`、`/notices/unread-count`、
   `POST /notices/{nid}/read`、`/read-all`、`/{nid}/dismiss`、`/{nid}/reply`）
6. （可选）量化数据展示：调 Dashboard API(:8010) 展示信号/报告

**agent API 端点速查**（`~/.dsh/workspace/xiaoman/agent/api.py`，全部需 X-Api-Key）：
`/api/agent/status`、`/profile`、`/activities`、`/online`、`/offline`、`/state`、
`/notices`、`/notices/unread-count`、`/notices/{nid}/read`、`/notices/read-all`、
`/notices/{nid}/dismiss`、`/notices/{nid}/reply`、`/reachability/refresh`、
`/browser/open-login`、`/sessions`(GET/POST)、`/sessions/{sid}`(DELETE)、
`/sessions/{sid}/messages`(GET/POST)、`/sources`(GET/POST/DELETE/toggle)、
`/articles`、`/articles/{aid}`、`/scheduler/run/{task_id}`、`/scheduler/stop/{task_id}`、
`/scheduler/status`。

### 4.5 更新 .gitignore / README / CLAUDE.md / 开发手册（✅ 完成）
- `.gitignore`：移除 `.dsh/*` 白名单规则（.dsh 已不在仓库）；`_*.py` 规则保留（开发规范）；
  `_*.json` 规则可留可删（临时 json 已清）；新增忽略说明（如有）
- 根 `README.md`：从「Agent+Web 糅合系统」改为**纯量化系统说明**（数据/回测/API/Dashboard 使用方式，
  指向 `docs/AGENT_GUIDE.md`）
- `CLAUDE.md`：§7 自动化迭代系统路径更新（`scripts/` → `~/.dsh/workspace/xiaoman/scripts/`、
  `etf-strategies/automation/` → `~/.dsh/workspace/xiaoman/automation/`、
  `my_doc/每日复盘/harness/` → `~/.dsh/workspace/xiaoman/harness/`）；§六 harness 路径同步；
  注明「仓库已无 agent 运行时，自动化由 ~/.dsh/workspace/xiaoman 驱动」
- `my_doc/每日复盘/开发手册.md`：同步路径说明

### 4.6 编写 `docs/AGENT_GUIDE.md`（Agent 标准化使用手册）（✅ 完成）
内容（给 Agent 读的量化系统说明书）：
- 系统定位：纯量化系统，提供数据/回测/信号/报告 API 与 CLI
- 快速开始：仓库结构、环境变量（`.env`：SUPABASE/ANTHROPIC/DASHBOARD_SCHEDULER_*）、
  依赖安装、如何启动 Dashboard(:8010)
- **量化 API 清单**（Dashboard :8010，JWT 认证）：
  - `/api/signals/*` 每日信号、`/api/daily-signals/*` 每日信号列表
  - `/api/strategies/*` 策略指标、`/api/backtest/*` 回测
  - `/api/reports/*`、`/api/reports/import` 报告查询/导入
  - `/api/holdings/*`、`/api/portfolio/*` 持仓/资产/调仓、`/api/trades/*`
  - `/api/notify/*` 企业微信通知状态
  - `/api/tickets/*` 工单
- **CLI 工具**：`python -m backtest.cli ...`（回测）、信号生成脚本、`sync_kline` 等
- **数据时点约定**：报告须标注数据时点 + 来源端点；区分实测值与判断
- **调用示例**：curl / Python 示例（取信号、取持仓、触发报告导入）
- **数据源纪律**：取数走 `a-stock-data` skill（mootdx/腾讯优先，东财限流）
- 附：小满 Web 地址、agent API 地址（供 Agent 回写展示）

### 4.7 验证（最终）（✅ 完成）
1. `cd etf-strategies && python -c "import dashboard.app"` 导入冒烟（无 agent import 报错）
2. 启动 Dashboard：`python app.py`（或 `DASHBOARD_PORT=8010 python app.py`），
   访问 `http://localhost:8010`，确认登录后：策略全景/持仓/信号/报告/工单正常，**无角色/工作日程/桌宠**
3. 确认 `POST /api/reports/import` 可用（导入报告）
4. 确认 `/api/tickets` 列表可用（云库 tickets 表有数据则返回，无则空列表不报错）
5. 启动 agent：`~/.dsh/workspace/xiaoman/scripts/start_all.ps1`（或
   `python -m agent` in `~/.dsh/workspace/xiaoman/agent`），确认 :8020 起来
6. 启动小满 Web 静态服务，访问桌宠/角色/聊天/工作日程/提示待办页
7. `~/.dsh/workspace/xiaoman/` 结构完整（§一 目录树）
8. 跑相关测试（见 §五.1 处理后的测试套件）
9. `git status` 复核：105+ 删除已暂存、未提交；确认无遗漏的 agent 残留 import

---

## 五、已知注意事项与风险

### 5.1 测试引用（必须处理，否则 pytest 报 ImportError）
以下测试 import 已删除/将删除的模块，需**删除或改写**：
- `tests/test_scheduler_ratelimit.py` → `from dashboard import scheduler`（删除测试，逻辑已随引擎外迁）
- `tests/test_scheduler_status.py` → `from dashboard import scheduler as sched`（删除）
- `tests/test_test_isolation.py` L74 → `from dashboard import scheduler as sched_mod`（改写：改 import importer 或删除该断言）
- `tests/test_daily_review_sync.py` L21 → `from dashboard import scheduler_cli as cli`（删除/改写）
- `tests/test_agent_api.py`、`tests/test_agent_browser_cookies.py` → `from dashboard import api_agent`（删除，agent 代理已移除；agent 侧测试随 agent 外迁）
- `tests/test_throttle_goal.py`、`tests/test_agent_api.py` → `from agent.core import scheduler_agent`（随 agent 外迁，删除）

### 5.2 残留 import 检查
Dashboard 可运行的前提：**无任何 `from agent import ...` / `import agent` / `from dashboard import scheduler`**。
已清：app.py、api_daily.py、api_tickets.py。执行 4.3 删除 scheduler.py/scheduler_cli.py 后再 grep 一遍：
```
grep -rn "from agent import\|import agent\|from dashboard import scheduler" etf-strategies/
```

### 5.3 环境变量（Dashboard 启动依赖）
`.env`（etf-strategies/.env，gitignored）含：`ANTHROPIC_AUTH_TOKEN`、SUPABASE 配置、
`DASHBOARD_SCHEDULER_ENABLED=1`、`DASHBOARD_SCHEDULER_ENGINE=auto`、`AGENT_API_URL`、`AGENT_API_KEY`。
`DASHBOARD_SCHEDULER_*` 已不再被 Dashboard 使用（引擎已移除），可留可清，不影响启动。

### 5.4 云库 tickets 表
工单数据由 agent 进程写入云库 `public.tickets` 表（supabase），Dashboard 直读。
若 agent 未运行，工单列表为空属正常（不是 bug）。

### 5.5 git 状态
- 大量删除已 `git add` 暂存（.agents/.dsh/automation/harness/scripts/evolution/agent 等，105+ 文件）
- **尚未 commit**：新对话续跑时可先 commit 一批（迁移+清理），再 commit Dashboard 解耦，最后 docs
- 未跟踪文件：每日报告（20261012-20261015，正常用户数据，不应删除）、
  `docs/2026-10-14-小满做T研究能力升级方案.md`（用户设计文档，保留）

### 5.6 小满 Web 鉴权
agent API 所有端点要求 `X-Api-Key` 头 = `AGENT_API_KEY`。小满 Web 前端需让用户配置该 key
（如 localStorage 或启动参数），否则 401。

### 5.7 桌面宠物资源体积
`live2d/` 模型目录较大（Haru/Natori/Senko/koharu + vendor），迁移时整个目录搬走即可，
不要在仓库留副本。

---

## 六、变更记录

| 时间 | 事件 |
|------|------|
| 2026-10-15 | 会话启动：停服务、激进清理、迁移 .dsh/.agents/agent 运行时/自动化层到 ~/.dsh |
| 2026-10-15 | 用户拍板：小满 Web 放 `~/.dsh/workspace/xiaoman/`（纯前端 SPA 直连 agent API）；工单留 Dashboard 改用 Dashboard db；Dashboard 纯量化 |
| 2026-10-15 | 用户拍板：废弃 `~/.dsh/astock`，全部并入 `~/.dsh/workspace/xiaoman/`（已执行） |
| 2026-10-15 | Dashboard 后端解耦：importer.py 新建、portfolio.py/app.py/api_daily.py/api_tickets.py 改造完成 |
| 2026-10-16 | §四.1 迁移 agent UI 资产 → `~/.dsh/workspace/xiaoman/web/static/`（agent.js/pet.js/agent.css/pet.css/live2d 全量） |
| 2026-10-16 | §四.2 dashboard.html 移除角色/工作日程/桌宠 view + agent.css/pet.css + agent.js/pet.js；daily.js/dashboard.js 删相关分支 |
| 2026-10-16 | §四.3 删除 scheduler.py/scheduler_cli.py/api_agent.py、scripts/etf_trigger.py、setup_etf_scheduled_tasks.ps1、etf-strategies/agent 目录 |
| 2026-10-16 | §四.4 搭建小满 Web SPA（`~/.dsh/workspace/xiaoman/web/`）：index.html + api.js(直连:8020/X-Api-Key) + app.js，6 视图，8 测试通过 |
| 2026-10-16 | §四.5 更新 .gitignore / README / CLAUDE.md / 开发手册.md / DEPLOY.md / start_dashboard.sh |
| 2026-10-16 | §四.6 新增 docs/AGENT_GUIDE.md（Agent 标准化使用手册：量化 API/CLI/调用示例/数据纪律） |
| 2026-10-16 | §四.7 验证通过：Dashboard 导入冒烟 ✓、残留 import grep ✓（修复 notify.py scheduler→importer）、测试 419 passed ✓ |
| 2026-10-16 | §五.5 分批 commit 完成（3 个 commit：迁移清理 / Dashboard 解耦 / docs），工作树 clean |
