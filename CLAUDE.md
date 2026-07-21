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

本项目为 `etf-strategies` 和 `每日复盘` 两个项目构建了自动化迭代层，基于 Claude Code `CronCreate` + prompts 实现。

### 7.1 架构概览

```
自动化层（本section定义）
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

### 7.2 etf-strategies 自动化调度

| 任务 | 频率 | Prompt | 用途 |
|------|------|--------|------|
| 代码巡检 | 每日 02:00 | `bug_inspect_code.md` | 静态分析+注册一致性+测试覆盖率 |
| 逻辑巡检 | 每周日 02:00 | `bug_inspect_logic.md` | KB vs 代码对齐+边界条件+跨策略一致性 |
| 数据质量 | 交易日 08:00 | `bug_inspect_data.md` | 缓存新鲜度+除权检测+跨源验证 |
| 策略发现 | 每周六 10:00 | `strategy_scan_weekly.md` | 各平台搜索→筛选→去重→输出候选 |
| **BUG自动修复** | **每小时 :07** | `bug_auto_fix.md` | 扫描OPEN BUG → AUTO_FIX修复 → MANUAL_REVIEW标记 → 生成报告 |

**BUG 管理**：巡检Prompt负责发现+记录（`bugs/open/BUG-{NNN}.md`），并标记 `auto_fix_eligible`。自动修复任务（`bug_auto_fix.md`，每小时 :07）扫描 OPEN BUG：
- `auto_fix_eligible=true` → 自动修复 → 测试通过则 FIXED，失败则升级为 MANUAL_REVIEW
- `auto_fix_eligible=false` → 标记 MANUAL_REVIEW，展现在 `BUG_INDEX.md` "⚠️ 待人工审核" 区域
- MANUAL_REVIEW BUG 需人工执行 `bug_fix_template.md` 修复流程
- 采用 Git 分支 `bugfix/BUG-{NNN}-{desc}` + 规范commit
- BUG 生命周期：OPEN → (自动修复) → FIXED / MANUAL_REVIEW → IN_PROGRESS → FIXED → VERIFIED

**策略发现**：绿灯候选自动转化 → `strategy_convert_backtest.md` 创建策略文件+测试+注册+回测→报告。黄灯候选进入 `candidate_queue.json` 排队。

**正确性定义**：`etf-strategies/automation/config/correctness_definitions.yaml` 定义了 engine/data/metrics/strategies/registration/dashboard 六组件的预期行为，巡检时逐条验证。

### 7.2.1 优化需求 Steering

用户可通过 `etf-strategies/automation/steering/` 注入优化需求，把控自动化迭代方向。

- **创建需求**：在 `steering/open/` 下按 `REQ_TEMPLATE.md` 模板创建 `REQ-{NNN}.md`，并在 `REQ_INDEX.md` 中登记
- **自动集成**：巡检/修复/发现任务执行时自动读取 `steering/open/` 中待处理需求，纳入工作范围
- **状态管理**：OPEN → IN_PROGRESS (自动化任务自动推进) → ADOPTED/REJECTED/IMPLEMENTED (用户人工确认)

每日复盘项目同样有独立的 steering 目录：`my_doc/每日复盘/harness/automation/steering/`。

### 7.3 每日复盘自动化调度

| 任务 | 频率 | Prompt | 用途 |
|------|------|--------|------|
| 早盘分析 | 交易日 07:55 | `auto_morning_analysis.md` | 取数→研判→信号→早盘报告 |
| 盘中检查 | 交易日 10:30/13:30/14:45 | `auto_intraday_check.md` | 验证信号触发→扫描新信号→更新信号文件 |
| 收盘复盘 | 交易日 15:45 | `auto_evening_review.md` | 盘面复盘→逐仓评估→预测对比→经验沉淀→生成次日staging→归档 |
| 周度回顾 | 周六 10:00 | `auto_weekly_portfolio.md` | 周P&L+预测准确率+量化vs实际对比 |
| 经验健康 | 周日 09:00 | `auto_experience_health.md` | 大小控制+重复检测+矛盾检测+过时检测 |

**流水线协调**：`task_state.json` 是跨任务协调中枢，确保幂等（同一天重复触发自动退出）和流水线感知（早盘→盘中→复盘 共享状态）。

**交易日历**：`trading_calendar.py` 判断是否为交易日，支持节假日/调休/盘中时间窗口检测。

### 7.4 cron 持久化策略

CronCreate `durable: true` 写入 `.claude/scheduled_tasks.json`，重启恢复，但有 **7 天自动过期**限制。

**解决方案**：在 `.claude/settings.json` 配置 `onSessionStart` hook，每次启动 Claude Code 时自动重建所有定时任务。只要中途启动过 Claude Code（基本每天用），定时任务就永远是新鲜的。

### 7.5 关键纪律

- **自动化不替代人类判断**：MANUAL_REVIEW BUG 必须人工确认；策略发现绿灯候选需要人工确认后才转化
- **数据铁律不变**：自动化prompts中涉及A股数据的，必须走 `a-stock-data` skill
- **Generator-Evaluator 分离不变**：自动复盘仍然严格执行"早盘预测 vs 复盘评估"的对抗审查
- **失败透明**：所有自动化任务写入执行日志（`automation/logs/`），失败不静默
- **交易日优先**：所有盘中/盘前/盘后自动化任务首先检查是否为交易日，非交易日自动跳过

