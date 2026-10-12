# Claude Code 相关代码盘点（2026-09-21）

> 目的：全面梳理项目中 Claude Code 相关代码，为"统一改用 dsh 作为 agent、移除 Claude Code"做准备。
> 现状：迁移到 DSH 的工程**已完成 P1-P3**（见 `docs/迁移到DSH方案.md`），DSH 侧已就绪（`.dsh/skills/` 28 个 skill），
> 本次是 **cutover（切换）+ 清理**阶段：把 Claude Code 专属的代码/配置/文档引用清理掉。

## ✅ 执行状态（2026-09-21 已完成）

| 批次 | 内容 | 状态 |
|---|---|---|
| 第一批 | 删除 Claude Code 专属文件（settings/loop_runner/skills/devloop_scanner/sync_claude_skills 等） | ✅ 已完成 |
| 第二批 | dsh 脚本 + 调度基础设施从 `.claude/` 搬到 `scripts/`（含 REPO_ROOT 层级 bug 修复 + 全部引用更新） | ✅ 已完成 |
| 第三批 | 文档改写：CLAUDE.md（第七节 DSH 化 + superpowers→dev-workflow）、两个开发手册、README、迁移方案、cron 表 | ✅ 已完成 |
| 第四批 | `dashboard/scheduler.py` 移除 `_exec_claude` 引擎（resolve_engine 仅 dsh），api_daily/.env/docker-compose/DEPLOY 同步 | ✅ 已完成，全量测试 **650 passed** |
| 重启 | Dashboard + Agent 需重启加载新代码 | ⏳ 待用户确认 |

> 注意：`.claude/` 目录已整体删除（仅剩调度基础设施已迁至 `scripts/`）。

---

## 一、结论速览

| 类别 | 处置 | 数量 |
|---|---|---|
| 🟢 **保留（调度基础设施）** | 被 Agent/Dashboard/dsh 脚本共同依赖 | 3 个文件 + 1 目录 |
| 🔵 **dsh 迁移产物（保留）** | 已是 DSH 体系的一部分 | 5 个脚本 + 1 文档 |
| 🔴 **Claude Code 专属（可删）** | DSH 侧已有等价物或已停用 | ~10 个文件/目录 |
| 🟡 **需改写（文档/注释）** | 内容要保留，措辞从 Claude → DSH | 3 个文档 + 2 处代码 |

---

## 二、🟢 保留：调度基础设施（不是 Claude 专属，只是放在 .claude 目录）

| 文件 | 被谁依赖 | 说明 |
|---|---|---|
| `.claude/scripts/task_schedule.json` | **Agent**（`scheduler_agent.py` L22 `TASK_DEFS_FILE`）、**Dashboard**（`scheduler.py` L44 `SCHEDULE_PATH`）、`dsh_trigger.py`、`dsh_loop_scheduler.py`、`setup_etf_scheduled_tasks.ps1` | 18 条任务定义，**单一事实源，绝对不能删** |
| `.claude/scripts/task_scheduler.py` | `dsh_trigger.py` / `dsh_loop_scheduler.py`（`import task_scheduler as ts` 复用交易日/幂等/窗口逻辑）；Agent 派发的任务完成时调 `--complete`（scheduler.py L470 指令） | 纯 Python 调度器，agent 无关。docstring 写 "for /loop architecture" 是历史描述，实际已是共享基础设施 |
| `.claude/scripts/scheduler_state.json` | `task_scheduler.py`（幂等状态） | 运行时状态，自动生成 |

> **建议**：这三个文件**保留原地不动**。它们虽然路径在 `.claude/` 下，但已被 DSH/Agent 体系复用，删除会直接破坏调度。

---

## 三、🔵 保留：dsh 迁移产物（已经是 DSH 体系的一部分）

| 文件 | 用途 |
|---|---|
| `.claude/scripts/dsh_trigger.py` | **精确时刻触发**（v2 主方案）：Windows 计划任务到点调用，派发 dsh headless 执行任务 |
| `.claude/scripts/dsh_loop_scheduler.py` | 轮询版调度器（备用），每 7 分钟迭代 |
| `.claude/scripts/dsh_cron.py` | 从 task_schedule.json 生成 cron 表（`docs/定时任务cron表.md`） |
| `.claude/scripts/dsh_status.py` | 今日调度状态 + 派发日志一键查看 |
| `.claude/prompts/setup_dsh_loop.md` | DSH 循环管理指南（v2 精确触发版） |

> **建议**：保留。它们属于 DSH 体系，未来可考虑**从 `.claude/` 移到 `.dsh/` 或 `scripts/`**（纯搬家，不改变功能）——可作为可选优化。

---

## 四、🔴 可删：Claude Code 专属（DSH 侧已有等价物或已停用）

### 4.1 `.claude/settings.json` — 可删
```json
{
  "enabledPlugins": { "superpowers@claude-plugins-official": true },   // superpowers 插件（已被 dev-workflow skill 替代）
  "hooks": { "SessionStart": [...] }                                    // 提醒执行 /loop（已被 dsh 计划任务替代）
}
```

### 4.2 `.claude/settings.local.json` — 可删
```json
{ "permissions": { "allow": ["WebSearch"] } }   // Claude 侧权限配置，DSH 不读
```

### 4.3 `.claude/scheduled_tasks.json` — 可删
```json
{ "tasks": [] }   // 空的历史遗留（旧 CronCreate 时代）
```

### 4.4 `.claude/prompts/loop_runner.md` — 可删
Claude `/loop 7m /clear` 的元 prompt（每 7 分钟迭代调度 + 派发 subagent）。已被 `dsh_trigger.py` / `dsh_loop_scheduler.py` 完全替代。

### 4.5 `.claude/prompts/setup_loop.md` — 可删
旧的 `/loop` 设置指南，已被 `setup_dsh_loop.md` 替代。

### 4.6 `.claude/prompts/setup_automation_cron.md.archived` — 可删
已归档（`.archived` 后缀），旧 CronCreate 方案残留。

### 4.7 `.claude/skills/`（9 个目录）— 可删
`a-stock-data / daily-review-harness / design-critique / design-explore / frontend-design / quant-strategy-discovery / testing / ui-ux-pro-max / windows-ps1-scripts`
**已在 `.dsh/skills/` 全部存在**（已核实：仅 .claude 有的集合为空），DSH 侧 28 个 skill 完整。删除后 DSH 不受影响。

### 4.8 `.claude/scripts/devloop_scanner.py` + `devloop_snapshot.json` — 可删
devloop 状态扫描器（读 BUG_INDEX/REQ_INDEX 供 loop_runner.md 消费），**仅 /loop 架构用**。dsh 侧无依赖（dsh 任务不调它）。

### 4.9 `.claude/scripts/sync_claude_skills.py` — 可删（删除 .claude/skills 后失去意义）
作用：`.claude/skills/` → `.dsh/skills/` 单向同步。**删除 .claude/skills 后此脚本无源可同步**，一并删除。

---

## 五、🟡 需改写：文档/代码中的 Claude 措辞（内容保留，改指向 DSH）

| 文件 | 位置 | 改写内容 |
|---|---|---|
| `CLAUDE.md` | 第七节「自动化迭代系统（Claude Code Loop）」整体 | 改为「DSH 自动化循环」：`/loop 7m /clear` → `dsh_trigger.py` 计划任务；loop_runner.md/setup_loop.md → setup_dsh_loop.md；superpowers 引用 → dev-workflow（约 5 处） |
| `etf-strategies/开发手册.md` | L140-177、L453-454 等 | `/loop 7m /clear && 执行 .claude/prompts/loop_runner.md` → dsh 计划任务；setup_loop.md → setup_dsh_loop.md |
| `my_doc/每日复盘/开发手册.md` | L63-83、L169-207、L442-463、L561-562 | 同上 |
| `docs/迁移到DSH方案.md` | L223（风险 6） | 标记 cutover 完成；§2.6 说".claude/settings.json 保留不删" → 更新为已删 |
| `etf-strategies/dashboard/scheduler.py` | L13、L37、L398-399、L459、L615 | 双引擎注释/兜底逻辑：删 `_exec_claude` 或降级为纯 dsh（见下） |

### 5.1 `etf-strategies/dashboard/scheduler.py` 的 claude 引擎 — 建议移除
- `_exec_claude()`（L475-525，约 50 行）：claude -p 执行引擎
- `resolve_engine()`（L453-459）：auto 探测里 claude 兜底分支
- `_run_prompt` L740-742：`_exec_dsh` / `_exec_claude` 二选一
- 相关注释 L13/L37/L398-399/L615

**改法**：删掉 claude 分支，`resolve_engine` 只返回 "dsh"（或保留 auto 但 fallback 报错）。**注意**：这是对运行中服务的代码改动，需测试 + 重启 Dashboard。

---

## 六、其他引用点（文档/历史记录，无需改动或仅归档）

- `docs/2026-08-27-每日复盘调度迁移设计.md`、`docs/2026-09-07-Dashboard全面BUG审查报告.md`、`docs/CHAT-tasks-design.md`、`docs/superpowers/*`、`etf-strategies/DEPLOY.md`、`etf-strategies/.env.example` 等：**历史设计/记录文档**，引用 task_schedule.json / /loop 是历史事实，保留不动（或作为历史归档）。
- `etf-strategies/automation/bugs/closed/BUG-009.md`、`my_doc/每日复盘/harness/automation/bugs/open/BUG-019.md`：历史 BUG 记录提及 /loop，保留（历史事实）。
- `etf-strategies/scripts/setup_etf_scheduled_tasks.ps1`：从 task_schedule.json 生成 `etf-trigger-*` 计划任务——**保留**（调度基础设施脚本）。

---

## 七、删除后需要验证的闭环

1. `.claude/skills/` 删除后，`dsh_status.py` / `setup_dsh_loop.md` 提到的 skill 同步（`sync_claude_skills.py`）失效 → 该脚本一并删，文档同步改。
2. `loop_runner.md` / `setup_loop.md` 删除后，`CLAUDE.md` / 两个开发手册不再引用（改写）。
3. `devloop_scanner.py` 删除后，确认无脚本调用（grep devloop_scanner 无引用）。
4. `dashboard/scheduler.py` 移除 claude 引擎后，跑 `tests/` 确认无回归 + 重启 Dashboard 验证调度仍正常。
5. 保留的 `task_scheduler.py` docstring 仍写 "for /loop architecture" → 可选更新 docstring 为 "DSH 自动化调度基础设施"。

---

## 八、可选优化（非必须）

- 把 `.claude/scripts/` 下的 dsh 脚本（dsh_trigger.py 等）**搬家到 `scripts/` 或 `.dsh/scripts/`**，彻底摆脱 `.claude/` 命名空间（纯移动，功能不变）。
- `CLAUDE.md` 是否改名 `AGENTS.md`（DSH 默认也读 CLAUDE.md，可选加 AGENTS.md 副本）。

---

## 附：`.claude/` 目录完整文件清单（21 项）

```
.claude/
├── settings.json                    🔴 删（superpowers + SessionStart hook）
├── settings.local.json              🔴 删（权限配置）
├── scheduled_tasks.json             🔴 删（空历史遗留）
├── prompts/
│   ├── loop_runner.md               🔴 删（/loop 元 prompt）
│   ├── setup_loop.md                🔴 删（旧设置指南）
│   ├── setup_automation_cron.md.archived 🔴 删（已归档）
│   └── setup_dsh_loop.md            🔵 留（DSH 管理指南）
├── scripts/
│   ├── task_schedule.json           🟢 留（调度单一事实源，Agent/Dashboard 依赖）
│   ├── task_scheduler.py            🟢 留（调度器，dsh_trigger 复用）
│   ├── scheduler_state.json         🟢 留（幂等状态）
│   ├── dsh_trigger.py               🔵 留（精确触发主方案）
│   ├── dsh_loop_scheduler.py        🔵 留（轮询备用）
│   ├── dsh_cron.py                  🔵 留（cron 表生成）
│   ├── dsh_status.py                🔵 留（状态查看）
│   ├── sync_claude_skills.py        🔴 删（.claude/skills 删后失去意义）
│   ├── devloop_scanner.py           🔴 删（仅 /loop 用）
│   ├── devloop_snapshot.json        🔴 删（devloop 快照）
│   └── __pycache__/                 🔴 删（task_scheduler/dsh_loop_scheduler 的 pyc，自动重建）
└── skills/（9 个目录）              🔴 删（DSH 侧 28 个 skill 已全覆盖）
```

> 注意：`.claude/` 目录**本身不能删**（task_schedule.json 等核心文件还在里面），只删其中的 Claude Code 专属文件。
