# A股投研项目：Claude Code → DSH (DeepSeek Harness) 迁移方案

> 状态：方案 v1.0（2026-08 调研稿）
> 前提：本方案基于对当前仓库 `.claude/`、`~/.claude/commands`、自动化调度脚本，以及本机 DSH 安装（`@deepseek-ai/dsh` + `~/.dsh` + `~/.agents`）的实际调研。

---

## 0. 结论：成本高吗？

**不高，属于"低～中低"成本，预计 0.5 ~ 1.5 人日（半天到一天半）。**

原因：这个项目最大的资产恰好是**模型无关**的——

| 资产 | 是否模型相关 | 迁移成本 |
|---|---|---|
| `a-stock-data`（2696 行数据层 skill，含全部取数代码） | ❌ 纯代码+说明 | **复制即用，零改写** |
| 投资分析框架（Checklist / 四大师 / 财报精读等 prompts） | ⚠️ 少量工具名 | 加 frontmatter + 换 2 个工具名 |
| 20 个自动化任务 prompt（早盘/盘中/复盘/巡检/REQ…） | ⚠️ 少量 `--complete` 约定 | 99% 原样，runner 重写 |
| Python 调度器 `task_scheduler.py` / `devloop_scanner.py` / `trading_calendar.py` | ❌ 纯 Python | **零改写** |
| `CLAUDE.md`（项目规范） | ❌ | **DSH 原生读取，零改写** |
| 每日复盘 harness（staging / experience / config / steering） | ❌ 纯 markdown | **零改写** |

真正需要动手的只有三块：**技能搬运（复制）、18 个 slash command 转格式、自动化 loop 的驱动方式重写**。核心逻辑、数据纪律、分析框架全部保留。

---

## 1. 资产盘点

### 1.1 无需迁移（DSH 原生兼容）

| 资产 | 位置 | 说明 |
|---|---|---|
| 项目规范 | `CLAUDE.md` | DSH `dsh-agent-instructions` 默认候选 `['AGENTS.md','CLAUDE.md']`，**原生读取**（本会话已生效，见系统提示"Instructions from: CLAUDE.md"）。可选加一份 `AGENTS.md` 作为同义副本 |
| 任务调度器 | `.claude/scripts/task_scheduler.py` | 纯 Python + JSON 状态，agent 无关 |
| 状态扫描器 | `.claude/scripts/devloop_scanner.py` | 同上 |
| 交易日历 | `my_doc/每日复盘/harness/automation/config/trading_calendar.py` | 同上 |
| 任务 prompt | `my_doc/每日复盘/harness/automation/prompts/*.md`（10 个）<br>`etf-strategies/automation/prompts/*.md`（8 个） | 扫描结果：仅个别文件含 Claude 专用语法（`--complete` 后缀由 runner 注入、个别 "Task 工具" 字样），任务体本身通用 |
| harness 结构 | `my_doc/每日复盘/harness/{prompts,experience,config,staging,archive}` | 纯 markdown |
| 调度表 | `.claude/scripts/task_schedule.json` | 纯 JSON，20 条任务定义 |

### 1.2 需要迁移

| 资产 | 数量 | 迁移动作 | 预估 |
|---|---|---|---|
| Skills | 8 | 复制目录到 DSH skill 根 | ~0.5h |
| Slash Commands | 18 | 转 user-invocable skill | 2~4h |
| superpowers 插件 | 1 | 浓缩为 `dev-workflow` skill | 1~2h |
| 自动化 loop（loop_runner + SessionStart hook） | 2 | 重写 runner + 换调度载体 | 2~4h |
| 迁移验证（试跑） | — | 全链路试跑 2~3 个任务 | 1~2h |

---

## 2. 逐项迁移细节

### 2.1 Skills：直接复制（8 个，零改写）

**DSH skill 发现根**（`dsh-skill-filesystem`，按优先级）：
1. `<项目根>/.dsh/skills`
2. `<项目根>/.agents/skills`
3. `customSkillDirs`（配置文件指定）
4. `~/.dsh/skills`
5. `~/.agents/skills`（本机已有，arkcli-* 即在此）

**格式兼容性**：DSH 要求 `<name>/SKILL.md` + YAML frontmatter（`name`/`description` 必需，kebab-case）。现有 8 个全部符合：

```
.claude/skills/a-stock-data/            →  .dsh/skills/a-stock-data/
.claude/skills/daily-review-harness/    →  .dsh/skills/daily-review-harness/
.claude/skills/frontend-design/         →  .dsh/skills/frontend-design/
.claude/skills/ui-ux-pro-max/           →  .dsh/skills/ui-ux-pro-max/
.claude/skills/design-critique/         →  .dsh/skills/design-critique/
.claude/skills/design-explore/          →  .dsh/skills/design-explore/
.claude/skills/quant-strategy-discovery/→  .dsh/skills/quant-strategy-discovery/
.claude/skills/testing/                 →  .dsh/skills/testing/
```

- frontmatter 里的 `origin: custom`、`version: 3.3.0` 等额外字段 DSH 会忽略，无需删。
- **建议放项目 `.dsh/skills/`**（随 Git 走、可复现、对新会话即时生效——skill catalog 热刷新，无需重启）。
- 验证：新开会话看 `<available_skills>` 目录出现 `a-stock-data` 等。

### 2.2 Slash Commands → user-invocable skills（18 个）

**原理**：DSH skill frontmatter 加 `user-invocable: true` 即出现在**人类可调用命令面**（等价于 Claude `/command`；`user-invocable: false` 则隐藏）。

18 个命令（位于 `~/.claude/commands/`，全局）：
`investment-checklist` `investment-research` `quality-screen` `earnings-review` `earnings-team` `industry-research` `industry-funnel` `management-deep-dive` `portfolio-review` `thesis-tracker` `private-company-research` `news-pulse` `dyp-ask` `financial-data` `investment-team` `deep-company-series` `bottleneck-hunter` `wechat-article`

**每个文件的转换步骤**（内容逻辑 100% 保留）：
1. 加 YAML frontmatter：`name`（kebab-case，与命令同名）、`description`（一行为触发条件）、`user-invocable: true`（可再加 `metadata`）。
2. `$ARGUMENTS` 占位符 → 改为指令："从用户本次输入中解析标的/参数（逗号/顿号/空格分隔）"。DSH 无 `$ARGUMENTS` 机制，靠输入解析。
3. 命令体内"使用 Task 工具启动并行后台 Agent 收集数据" → 改为 "使用 `subagent` 工具（`run_in_background: true`）并行派发数据收集"。DSH 的 subagent 与 Claude Task 语义一致。
4. 涉及取数 → 保持引用 `a-stock-data` skill（skill 名相同，无需改）。

> 放置位置建议：命令是"全局方法论"，放 `~/.agents/skills/`（跨项目可用，与现有 arkcli-* 同根）；若想项目内自包含，放项目 `.dsh/skills/` 亦可。
>
> ⚠️ **放置路径注意**：DSH skill 发现**只认一层目录**（`<skill根>/<name>/SKILL.md` 或 `<skill根>/<name>.md`），**不能**放进 `.dsh/skills/commands/` 这类子目录，否则不会被发现。本项目三个子项目（etf-strategies / my_doc）同属一个 git 仓库，放仓库根 `.dsh/skills/` 即可全仓生效。

### 2.3 superpowers 插件 → `dev-workflow` skill

现状：`.claude/settings.json` 里 `enabledPlugins: superpowers@claude-plugins-official`，项目只用它的主线流程（brainstorming → writing-plans → TDD → executing-plans → code-review；调试走 systematic-debugging）。

迁移：写一个精简 skill `dev-workflow`（放 `.dsh/skills/dev-workflow/SKILL.md`）：
- frontmatter：`name: dev-workflow`，`description: 开发任务五步流程（brainstorming→writing-plans→TDD→executing-plans→code-review；调试走 systematic-debugging）`
- 正文：把 5 步流程的触发规则、每步产出、TDD 门禁、代码评审要求浓缩成一份可执行清单（与 CLAUDE.md 第七节现有约定对齐）。
- 同步改 `CLAUDE.md`：把"superpowers 流程"字样替换为"dev-workflow 流程"（约 5 处引用）。

### 2.4 自动化 Loop（重点）

**现状**：`/loop 7m /clear && 执行 .claude/prompts/loop_runner.md`，靠 Claude 内建循环每 7 分钟迭代；loop_runner 内用 Claude 的**后台 Agent 工具**派发任务。

**迁移方案 A（已落地）：Windows 任务计划 + 纯脚本调度器 + `dsh --profile headless`**

```
┌──────────────────────────────────────────────────────────────┐
│ Windows 任务计划（dsh-automation-loop，每 7 分钟，当前 Disabled）│
│   python .claude/scripts/dsh_loop_scheduler.py  ← 纯脚本，零 token│
└──────────────────────────┬───────────────────────────────────┘
                           ▼
   dsh_loop_scheduler.py（复用 task_scheduler.py 全部逻辑）
   1. task_scheduler.py --check          ← 到期判定/幂等/交易日，零改动
   2. 到期？→ --complete + --mark-running ← 先标记防重
   3. Start-Process 独立进程派发：          ← 任务隔离，崩溃自愈
      pwsh -NoProfile -Command 'dsh.cmd --profile headless "执行 <prompt_file> ..."'
   4. 未到期 → 静默退出（不消耗任何 token）
└──────────────────────────┬───────────────────────────────────┘
                           ▼
   独立 headless 会话执行任务 → 任务内调用 --complete → 下次迭代感知
```

要点：
- **headless = 一次性持久会话**：每次任务都是全新会话 → **零上下文累积**（等价于 Claude `/clear`），崩溃自愈，比 Claude `/loop` 更稳。
- **空闲迭代 0 token**：原 `/loop` 每次迭代要模型跑一遍 loop_runner（~400 tokens），纯脚本调度器空闲时只做 Python 判断，**不调用模型**。
- **派发方式**：`node <dsh bin.js> --profile headless "<指令>"` 直接调用（CreateProcess UTF-16 参数，最稳）；兜底 `powershell.exe + dsh.cmd`。注意本机**无 pwsh 7**（DSH 的 pwsh 工具实为 Windows PowerShell 5.1），且 `dsh.ps1` 垫片受执行策略限制，故不依赖它们。
- **headless profile 首次使用自动初始化**（需写 `~/.dsh/profiles/headless`；任务计划在沙箱外运行，无权限问题）。
- 幂等双保险（`scheduler_state.json` + 任务内 `task_state.json`）原样复用；`task_scheduler.py`/`task_schedule.json` **零改动**。
- 启动/停止 = 启用/禁用计划任务（详见 `.claude/prompts/setup_dsh_loop.md`）。
- 派发日志：`.dsh/logs/{task_id}-{timestamp}.log`。

**方案 B（补充）：DSH goal 长目标**
DSH 的 goal 工具支持跨轮次自动续跑（create_goal → 自动 continuation rounds）。可以把"今日自动化调度"作为一个 goal 由常驻 web 会话驱动。缺点：节奏按"轮"而非按分钟，7 分钟窗口精度不如方案 A。适合作为 A 的补充/兜底，不建议做主载体。

### 2.5 SessionStart hook 提醒

现状：`.claude/settings.json` 的 SessionStart hook 在启动时提醒执行 `/loop`。
迁移：
- 简单做法：在 `CLAUDE.md`（或新建 `AGENTS.md`）追加一行启动提醒："自动化调度已迁移到 DSH：启用/停用 Windows 计划任务 `dsh-automation-loop`；管理指南见 `.claude/prompts/setup_dsh_loop.md`"。
- 或做一个 `automation-reminder` skill。推荐前者，零额外文件。
- **注意**：CLAUDE.md 被两边读取，此改动在 cutover 时一并做。

### 2.6 配置文件清理

- `.claude/settings.json`（superpowers 插件 + SessionStart hook）：DSH 不读，**保留不删**（回滚用）。
- `.claude/scheduled_tasks.json`（空）：历史遗留，不动。

### 2.7 对 Claude 原有运行的影响（结论：不影响，唯一例外是自动化循环）

**迁移 = 纯新增，零侵入 Claude 侧**：
- 新增 `.dsh/skills/`、`dsh_loop_runner.md`（新文件）、Windows 任务计划，全部是"加"，不改任何 Claude 现有文件。
- `.claude/`（skills / scripts / prompts / settings.json）、`~/.claude/commands/`、`~/.claude/skills/`、全局 `~/.claude/settings.json`（仅 env）**原样保留**。
- `CLAUDE.md` 被两边同时读取：**cutover 之前不改它**（若把 superpowers 措辞改成 dev-workflow，Claude 侧行为也会跟着变）。
- 命令转 user-invocable skill 是"新增文件"，不覆盖原 `~/.claude/commands/*.md`，Claude 的 `/命令` 不受影响。
- Claude 无常驻后台进程（`/loop` 只在手动启动的会话里跑；SessionStart hook 只是提醒），不存在启动冲突。

**唯一实质冲突点：自动化循环的共享状态，必须二选一**：
- `scheduler_state.json`（幂等标记）、任务内 `task_state.json`、`staging/`（每日覆盖）、`experience/`、`steering/`、`PENDING_CONFIRMATION.md`、`automation/logs/` 都是**同一套文件**，Claude `/loop` 与 DSH 循环同时跑会互相覆盖 → 任务重复执行或互跳。
- 规则：**迁移验证期间停掉 Claude `/loop`；DSH 验证通过后由 DSH 循环接管，Claude `/loop` 不再启动（配置保留作回滚）。**

**skill 放置的可见性提醒**：
- 放项目 `.dsh/skills/` → DSH 专用根，Claude 完全看不见，零影响（推荐）。
- 放 `~/.agents/skills/` → 这是 agent 通用目录，Claude Code 新版也可能扫描 → 可能两边目录都出现（想双端共用才选它）。

**日常分析类使用**：Claude 和 DSH 可并行用（各自出报告），只要不同时写同一份报告文件即可。

### 2.8 成本优化（v2）：轮询 → 精确触发（2026-08-26 落地）

**问题**：原 `/loop` 7 分钟轮询非常耗费 token。实测 `~/.claude/stats-cache.json`（2026-06-29~07-22 活跃期）：缓存读 tokens 高达 **10.9 亿（pro）+ 0.67 亿（flash）**，日均等效消耗 **~900 万 tokens/天**（峰值日 800-970 万），而手工模式（盘前+信号+盘后 3 次/天）仅 ~10-15 万/天。

**根因**（按贡献排序）：
1. **轮询固定开销（80%+）**：205 次/天 × 每次重复读完整前缀（系统提示+工具+CLAUDE.md+loop_runner 148 行+skill 目录 ≈ 2-4 万 tokens/次）——"空转检查"比"干活"贵得多。
2. 任务 prompt 巨大：evening_review 59KB / morning_analysis 38KB / logic_inspect 31KB，每次全量重读。
3. 任务过多：盘中 8 次 + 每小时 2 个 BUG 巡检，大量重复。
4. 子代理放大：每个 subagent 独立上下文重复读前缀 + skill。

**v2 方案（已落地）**：
- `dsh_trigger.py --task <id>`：精确时刻触发单个任务，复用 task_scheduler 的交易日/幂等/±3h 容差逻辑，到点才跑一次 headless。
- 计划任务：`dsh-trigger-morning`(09:07→morning_analysis，产出早盘报告+每日信号)、`dsh-trigger-evening`(15:52→evening_review)。旧 7 分钟轮询任务已删除。
- 效果：空闲零 token；每天仅 2 次任务消耗（≈手工模式同等量级，~10-15 万/天），较轮询省 **90%+**。
- 配套：`sync_claude_skills.py`（Claude skill → DSH 副本一键同步，消除迁移副本分叉风险）；harness 模板/经验/prompts 本就是共享单份文件，Claude 侧优化自动继承。

---

## 3. 分阶段执行计划

| Phase | 内容 | 产出 | 预估 |
|---|---|---|---|
| **P1 技能搬运** | 复制 8 个 skill 到 `.dsh/skills/`；新开会话验证 catalog | 8 个 skill 生效 | 0.5h |
| **P2 命令转换** | 18 个命令转 user-invocable skill（frontmatter + `$ARGUMENTS` 改造 + subagent 替换）；抽查试跑 `investment-checklist`、`earnings-review` | 18 个命令生效 | 2~4h |
| **P3 开发流程 + 自动化** | 写 `dev-workflow` skill；改 CLAUDE.md 引用；写 `dsh_loop_runner.md`；建 Windows 任务计划（7 分钟）；验证一次派发 | 自动化循环可用 | 2~4h |
| **P4 全链路验证** | 试跑：早盘分析 → 盘中检查 → 复盘（Generator-Evaluator）→ REQ 闭环；核对数据纪律（a-stock-data 走通、东财限流生效） | 验收通过 | 1~2h |

**验收标准（P4，2026-08-26 实测状态）**：
- [x] DSH 会话 `<available_skills>` 含全部 8 个 skill + 18 个命令 skill + dev-workflow（本会话实时可见）
- [x] headless 会话可见 54 个 skill，`investment-checklist` 等可正常加载
- [x] 真实自动化 prompt（auto_pending_remind）在 headless 下完整执行（扫描→判断→静默跳过→--complete 标记）
- [x] 调度器派发链路端到端（node 直调 bin.js → 分离进程 → 日志落盘 → 完成标记）
- [x] a-stock-data 数据层冒烟（腾讯行情 600519 真实报价 1302.80）
- [x] 每日复盘链路只读校验（headless 加载 daily-review-harness：staging/模板/报告三件套/经验配置/数据时点 5 项全过，Generator-Evaluator 分离成立）
- [ ] 任务计划 7 分钟循环常驻运行（任务已建、Disabled，待用户确认 Claude /loop 停止后启用）
- [ ] `/investment-checklist 茅台` 完整试跑（含并行 subagent 取数）
- [ ] Claude 侧配置原样保留（.claude/、~/.claude/commands 未动）

> ✅ **试跑补充（2026-08-26）**：`/investment-checklist 茅台` 已完整执行——六关全过（能力圈/好生意/护城河 5 星、管理层 4 星、安全边际 3 星），报告落盘 `巴菲特Checklist-贵州茅台.md`；数据全部实测（腾讯行情/新浪三表/东财分红限流 + financial_rigor.py 计算）。唯一偏差：并行 subagent 取数超时被中断，改为本会话直连 a-stock-data 取数（建议后续给数据子代理加超时提示）。

---

## 4. 风险与注意事项

1. **模型差异（最大不确定项）**：现有 prompt 为 Claude 调优，DeepSeek 模型行为可能有微差（尤其 Generator-Evaluator 对抗审查、REQ 闭环的纪律性）。对策：P4 必须完整试跑一轮闭环，发现纪律松动就强化 prompt 措辞。
2. **命令参数传递**：user-invocable skill 在 GUI 上如何输入参数（标的）需实测确认；若 GUI 只支持无参触发，需在 skill 正文明确"从对话输入解析"，必要时加一步 `ask_user_question`。
3. **成本**：迁移是**一次性人力成本**（~1 人日）；日常运行成本从 Claude 计费切到 DeepSeek 计费，按 token 通常更低，且 headless 循环每次只花固定小 token（类似原 `/clear` 设计）。
4. **并行/回滚**：`.claude/`、`~/.claude/commands` 全部保留，迁移是纯新增；回滚 = 停任务计划 + 删 `.dsh/skills`，零破坏。**注意：自动化循环必须二选一（见 §2.7），不可两套同时跑。**
5. **编码**：文件均为 UTF-8，无编码迁移问题（部分工具终端显示乱码是控制台代码页问题，与文件无关）。
6. **CLAUDE.md 措辞**：迁移完成后把第七节"Claude Code Loop"改为"DSH 自动化循环"，把 superpowers 引用改为 dev-workflow；数据铁律、输出纪律章节一字不动。

---

## 5. 交付物清单（已落地 ✅ 截至 P3）

| 交付物 | 位置 | 状态 |
|---|---|---|
| 8 个原 skill | `.dsh/skills/<name>/SKILL.md` | ✅ 已生效（daily-review-harness 修复了 YAML 冒号 bug） |
| 18 个命令 skill | `.dsh/skills/<name>/SKILL.md`（user-invocable: true） | ✅ 已生效（WebSearch→web_search 已替换） |
| dev-workflow skill | `.dsh/skills/dev-workflow/SKILL.md` | ✅ 已生效 |
| DSH 自动化调度器 | `.claude/scripts/dsh_trigger.py`（精确触发，v2）+ `dsh_loop_scheduler.py`（轮询版，备用） | ✅ 已就绪（dry-run 通过） |
| skill 同步脚本 | `.claude/scripts/sync_claude_skills.py` | ✅ 已就绪（两侧已一致） |
| 循环管理指南 | `.claude/prompts/setup_dsh_loop.md`（v2 精确触发版） | ✅ 已就绪 |
| Windows 计划任务 | `dsh-trigger-morning`(09:07) / `dsh-trigger-evening`(15:52)，旧轮询任务已删 | ✅ 已注册（Ready） |
| 派发日志目录 | `.dsh/logs/`（已加入 .gitignore） | ✅ |
| 更新后的 CLAUDE.md | 引用替换 + 启动提醒 | ⏳ cutover 时执行 |

---

*附：本方案调研依据——DSH 安装 `@deepseek-ai/dsh`（`dsh-agent-instructions` / `dsh-skill-filesystem` / `dsh-tool-skill` / `dsh-headless` / `dsh-cmdline` 文档）、`~/.dsh` 与 `~/.agents` 现状、仓库 `.claude/` 全量盘点。*
