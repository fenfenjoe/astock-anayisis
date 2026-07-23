# A股投研项目规范

本目录用于 A 股投资研究：估值分析、个股/ETF/板块研判、财报精读、组合管理。

## 一、工具栈与分工（核心）

本项目有两套工具，**职责严格分离**：

| 层 | 工具 | 角色 | 何时用 |
|---|---|---|---|
| **数据层** | `a-stock-data` skill | 取数 — 行情/财务/研报/资金面/公告的**真实数据** | 任何需要 A 股数据时 |
| **分析层** | 投资命令套件（见下表） | 出框架与判断 — Checklist、四大师框架、财报精读等 | 拿到数据后做结构化分析 |

**铁律：数据获取一律走 `a-stock-data`。**
投资命令（如 `investment-checklist`）的"并行数据收集"步骤、或我自行补数据时，必须调用 `a-stock-data` 取真实数据，**禁止用网络泛搜索结果或凭印象"估算"**填核心数据栏（ROE / PE / PB / 资金流 / 研报一致预期等）。这是本项目的首要纪律。

> 上述投资命令为全局 slash command（用户口语称"ai-berkshire 系列"），属价值投资/基本面分析框架：

| 命令 | 用途 |
|---|---|
| `/investment-checklist` | 巴菲特买入前六关 Checklist |
| `/investment-research` | 巴菲特-芒格-段永平-李录四大师综合框架 |
| `/quality-screen` | 7条指标快速去劣筛选 |
| `/earnings-review` `/earnings-team` | 财报精读（单师/四师并行） |
| `/industry-research` `/industry-funnel` | 行业全景 / 漏斗筛选到3家 |
| `/management-deep-dive` | 管理层纵深研究 |
| `/portfolio-review` | 组合管理 |
| `/thesis-tracker` | 买入后投资论文追踪 |
| `/private-company-research` | 未上市公司研究 |
| `/news-pulse` | 股价异动归因 |
| `/dyp-ask` | 段永平式思考 |

### 开发能力：superpowers（按需启用）

本项目主线是 A 股投研分析，**日常的估值/财报/个股研判不调用 superpowers**。仅当出现**开发需求**——写或改 Python 脚本、构建数据工具、调试代码、重构工程——时才启用，按它的流程走（brainstorming → writing-plans → TDD → executing-plans → code-review；调试走 systematic-debugging）。

- **默认不触发**：即便 superpowers 的 `using-superpowers` skill 自身要求"1% 可能适用就调用"，在本项目里该规则**只对开发任务生效**。取数、过投资框架、写投研报告等任务不进 superpowers 流程，按本规范第一/二节执行。
- **铁律不变**：开发脚本里凡需 A 股真实数据的，仍走 `a-stock-data`，不因进入开发流程而豁免数据纪律。
- **临时脚本清理**：开发产生的一次性取数脚本仍用 `_*.py` 命名、跑完即删（见第四节）。

## 二、标准混用流程

分析标的时按"先取数、后过框架"执行：

1. **取数（a-stock-data）**：按需拉实时行情、财务三表、研报一致预期、资金面、龙虎榜、公告等。
2. **分析（投资命令）**：把真实数据喂给框架，过 Checklist / 四大师 / 财报精读等。
3. **输出**：报告必须标注数据时点 + 数据来源端点，区分"实测值"与"判断"。

典型场景：
- "分析 688017 估值" → a-stock-data 取价/PE/EPS一致预期 → 跑 PEG/PE消化 → 结论
- "/investment-checklist 茅台" → 命令触发 → 数据收集步骤切到 a-stock-data 取 ROE/FCF/研报 → 过六关
- "创业板主力资金流" → 直接 a-stock-data（无需投资命令）

## 三、数据源优先级（取数时遵守，详见 a-stock-data skill）

| 优先级 | 数据源 | 用途 | 封IP风险 |
|---|---|---|---|
| 1 | **mootdx** (TCP) | K线/盘口/财务快照/F10 | 极低 |
| 2 | **腾讯财经** | PE/PB/市值/换手率/涨跌停/ETF | 低 |
| 3 | 新浪/巨潮/同花顺 | 财报三表/公告/一致预期 | 低 |
| 4 | **东财** (限流) | 龙虎榜/解禁/融资融券/大宗/资金流/研报/新闻 | 有，必须走 `em_get` |

要点：
- **能用 mootdx/腾讯就别用东财**；东财仅用于其独有数据，且必须串行限流（间隔≥1s + 抖动），批量场景调大到 1.5~2s。
- mootdx 用 `tdx_client()` 创建客户端（规避 0.11.x BESTIP 空串 bug）；**海外/受限网络下 mootdx TCP 7709 会超时**，改用腾讯/百度/东财 HTTP 源。
- push2/push2his 对部分大陆住宅 IP 间歇风控（HTTP 000/空），非代码问题，隔几分钟重试或换网络。
- 全部代码、端点、字段索引都在 `a-stock-data/SKILL.md`，直接抄用即可，勿另造轮子。

## 四、输出纪律

- **数据时点**：每份报告开头标注"数据时点：YYYY-MM-DD HH:MM"（盘中注明时间，盘后注明收盘）。
- **区分实测与判断**：实测值标来源端点（如"东财 push2his"），推算值标"估算"并附置信度。
- **诚实标注不确定性**：数据不足时写"数据不足无法判断"，不为填满表格而编造。
- **临时脚本清理**：一次性取数脚本用临时文件名（`_*.py`），跑完即删，不污染目录。
- **口径提示**：东财"主力净流入"按主动成交单分类，有口径争议，资金面结论需结合量价/北向交叉验证，不单独作为买卖依据。

## 五、前端开发与 UI 设计能力（跨项目通用）

本项目配备了 4 个前端设计 Skills，覆盖从**美学方向选择 → 设计系统工程化 → 评审打磨 → 变体探索**的完整链路。

### 5.1 技能清单与触发时机

| 技能 | 角色 | 触发条件 | 典型用户语句 |
|------|------|---------|------------|
| `frontend-design` | **美学方向定调** — 选方向、定Token、阻断AI塑料味 | 任何涉及 UI/前端/页面/样式/CSS/组件/Dashboard 的需求 | "帮我做个Dashboard""设计一个落地页""美化这个界面""这个页面太丑了" |
| `ui-ux-pro-max` | **设计系统工程化** — 产品类型→完整Token系统，含无障碍和响应式 | 需要完整设计系统、建立产品视觉语言、明说"设计系统"/"design system" | "建立设计系统""生成Design Token""制定设计规范" |
| `design-critique` | **评审与打磨** — /critique /audit /polish /animate /typeset /colorize /delight /overdrive /harden + 44条反模式检测 | 评审/检查/打磨/美化已有UI，或完成前端代码后需要质量把关 | "帮我看看这个设计怎么样""Audit一下这个页面""打磨一下UI" |
| `design-explore` | **变体探索** — 5套主题配方 + 3个参数旋钮（变异度/动效/密度） | 需要多个方案对比、换个风格、调节设计参数 | "给几个不同风格的方案""太保守了大胆一点""太花哨了收敛些" |

### 5.2 协作流程（设计铁律）

前端需求按以下优先级链式调用：

```
用户提UI需求
  → 1. frontend-design（必须先确定美学方向，禁止跳过直接写CSS）
  → 2. ui-ux-pro-max（若是新产品/新系统，生成完整设计Token）
  → 3. 编写前端代码
  → 4. design-critique（/audit + /critique 自动检查 + 44条反模式扫描）
  → 5. design-explore（可选：若用户不满意，用参数旋钮调节或换主题）
```

**关键纪律：**
- **方向优先**：任何 UI 需求先过 `frontend-design` 定方向，**禁止不选方向就写 CSS**。
- **反模式必检**：完成前端代码后必须用 `design-critique` 的 44 条规则自检。
- **Token 不走捷径**：禁止用 `#333`/`#666`/`#999` 等硬编码灰色；禁止 Inter 作为唯一字体；禁止紫色渐变。
- **投资主线不受影响**：前端 Skills 仅在涉及 UI/前端开发时触发，A 股投研分析流程（第一节）不受干扰。

### 5.3 与 superpowers 的关系

前端开发需求同样遵循 superpowers 流程（brainstorming → TDD → code-review），但**在 brainstorming 阶段必须先调用 `frontend-design` 定美学方向**，再进入 writing-plans。

```
前端开发需求
  → brainstorming（内嵌 frontend-design 定方向）
  → writing-plans
  → TDD
  → executing-plans
  → design-critique（/audit 44条反模式扫描）
  → code-review
```

## 六、每日复盘 Harness 层

`my_doc/每日复盘/` 采用 Harness Engineering 架构，将"厨房"与"菜"严格分离：

```
每日复盘/
├── harness/          # 厨房 — 模板/经验/配置/工具
│   ├── prompts/      #   永久模板（早盘分析+复盘分析方法论框架）
│   ├── experience/   #   经验沉淀（投资经验/短线经验/报告审阅标准）
│   ├── config/       #   日度配置（当前持仓快照）
│   ├── staging/      #   当日可执行 prompt（每日覆盖，仅 2 个文件）
│   └── archive/      #   历史 prompt 归档
├── reports/          # 菜 — 仅报告产出（不含 prompt 副本）
└── 每日调仓.md       #   调仓历史日志
```

**编排入口**：`daily-review-harness` skill。触发方式：说"执行早盘分析"或"执行复盘分析"。

**核心模式**：
- **Generator-Evaluator 分离**：早盘分析生成预测，复盘分析逐条评估，不允许自产自评
- **Staging 机制**：每日复盘后生成次日 staging prompt（`harness/staging/今日-*.md`），执行时直接读取，每日覆盖，消灭 prompt 副本
- **经验持续积累**：每次复盘后追加 `harness/experience/`，无日期标签，冲突则修正

详见 `my_doc/每日复盘/harness/README.md` 和 `daily-review-harness` skill。

## 七、自动化迭代系统（Claude Code Loop）

本项目为 `etf-strategies` 和 `每日复盘` 两个项目构建了自动化迭代层，基于 Claude Code `/loop` + Python 调度器实现。

### 7.1 架构概览

```
自动化层（本section定义）
├── .claude/scripts/
│   ├── task_schedule.json         #   13条任务调度定义（时间/星期/交易日等）
│   ├── task_scheduler.py          #   Python调度器（时间匹配+幂等+交易日判断）
│   └── scheduler_state.json       #   运行时幂等状态（自动创建）
├── .claude/prompts/
│   ├── loop_runner.md             #   每7分钟迭代的元prompt
│   └── setup_loop.md              #   一次性设置指南
├── etf-strategies/automation/     # ETF策略自动化
│   ├── prompts/                   #   巡检+发现prompts
│   ├── config/                    #   正确性定义+发现源配置
│   ├── bugs/                      #   BUG跟踪（open/closed + INDEX）
│   └── archive/                   #   历史扫描/转化报告
└── 每日复盘/harness/automation/   # 每日复盘自动化
    ├── prompts/                   #   早盘/盘中/复盘/周度/经验健康prompts
    ├── config/                    #   交易日历 + 跨任务状态
    └── logs/                      #   执行日志
```

**核心机制**：一个 `/loop 7m /clear && 执行 loop_runner.md` 替代全部 CronCreate 定时任务。每次迭代先 `/clear` 清空上下文，Python 调度器判断是否有到期任务，有则执行，无则跳过。**零上下文累积**。

**调度精度**：7 分钟间隔 + 7 分钟窗口，每个任务在目标时间后 0~7 分钟内触发。全部 13 条任务定义见 `.claude/scripts/task_schedule.json`。

### 7.2 全部 13 条任务调度

| task_id | 时间 | 星期 | 需交易日 | Prompt |
|---------|------|------|---------|--------|
| morning_analysis | 09:07 | 一~五 | ✓ | `auto_morning_analysis.md` |
| intraday_0940 | 09:40 | 一~五 | ✓ | `auto_intraday_check.md` |
| intraday_1000 | 10:00 | 一~五 | ✓ | `auto_intraday_check.md` |
| intraday_1030 | 10:30 | 一~五 | ✓ | `auto_intraday_check.md` |
| intraday_1100 | 11:00 | 一~五 | ✓ | `auto_intraday_check.md` |
| intraday_1330 | 13:30 | 一~五 | ✓ | `auto_intraday_check.md` |
| intraday_1400 | 14:00 | 一~五 | ✓ | `auto_intraday_check.md` |
| intraday_1430 | 14:30 | 一~五 | ✓ | `auto_intraday_check.md` |
| evening_review | 15:52 | 一~五 | ✓ | `auto_evening_review.md` |
| bug_auto_fix | 每小时:07 (9-18) | 一~五 | ✗ | `bug_auto_fix.md` |
| bug_inspect_data | 12:07 | 一~五 | ✗ | `bug_inspect_data.md` |
| bug_inspect_code | 12:17 | 一~五 | ✗ | `bug_inspect_code.md` |
| bug_inspect_logic | 12:23 | 周一 | ✗ | `bug_inspect_logic.md` |
| strategy_scan_weekly | 12:37 | 周二 | ✗ | `strategy_scan_weekly.md` |
| experience_health | 12:47 | 周三 | ✗ | `auto_experience_health.md` |
| weekly_portfolio | 13:17 | 周四 | ✗ | `auto_weekly_portfolio.md` |

> 修改调度：编辑 `.claude/scripts/task_schedule.json`，下次迭代即生效。

### 7.3 启动与停止

**启动**（每次 Claude Code 启动后手动执行一次）：

```
/loop 7m /clear && 执行 .claude/prompts/loop_runner.md
```

SessionStart hook 会在启动时提醒此命令。

**停止**：`Ctrl+C` 或回复 `stop`。

**管理**：详见 `.claude/prompts/setup_loop.md`。
- 查看状态：`python .claude/scripts/task_scheduler.py --status`
- 强制重跑：删除 `scheduler_state.json` 中对应 key

### 7.4 与 CronCreate 旧方案的对比

| 特性 | CronCreate (旧) | /loop + /clear (新) |
|------|----------------|---------------------|
| 上下文 | 每次累积，越跑越长 | 每次 /clear 重置，零累积 |
| Token | 越晚任务越贵 | 每次固定 ~400 tokens 开销 |
| 持久化 | durable=true 写磁盘 | session-only，重启手动启动 |
| 管理 | 13 个独立 CronCreate | 1 个 task_schedule.json |
| 过期 | 7 天自动过期需重建 | 无过期概念 |

### 7.5 关键纪律

- **自动化不替代人类判断**：MANUAL_REVIEW BUG 必须人工确认；策略发现绿灯候选需要人工确认后才转化
- **数据铁律不变**：自动化prompts中涉及A股数据的，必须走 `a-stock-data` skill
- **Generator-Evaluator 分离不变**：自动复盘仍然严格执行"早盘预测 vs 复盘评估"的对抗审查
- **失败透明**：所有自动化任务写入执行日志（`automation/logs/`），失败不静默
- **交易日优先**：所有盘中/盘前/盘后自动化任务首先检查是否为交易日，非交易日自动跳过
- **幂等双保险**：调度器 `scheduler_state.json` + 任务 prompt 内部 `task_state.json` 各自独立检查，防止重复执行

### 7.6 优化需求 Steering

用户可通过 `etf-strategies/automation/steering/` 注入优化需求，把控自动化迭代方向。

- **创建需求**：在 `steering/open/` 下按 `REQ_TEMPLATE.md` 模板创建 `REQ-{NNN}.md`，并在 `REQ_INDEX.md` 中登记
- **自动集成**：巡检/修复/发现任务执行时自动读取 `steering/open/` 中待处理需求，纳入工作范围
- **状态管理**：OPEN → IN_PROGRESS (自动化任务自动推进) → ADOPTED/REJECTED/IMPLEMENTED (用户人工确认)

每日复盘项目同样有独立的 steering 目录：`my_doc/每日复盘/harness/automation/steering/`。

