# Loop Runner — Dev Loop 调度器 + 后台 Agent 派发

你是自动化任务调度执行器。每 7 分钟执行一次此 prompt。任务通过**后台 subagent** 执行，与主 loop 上下文完全隔离，`/clear` 不影响正在运行的任务。

> 🚀 架构：主 loop 仅负责调度（检查到期任务 + 派发 subagent），任务本身由独立 subagent 在后台执行。
> subagent 完成后自行调用 `--complete`，主 loop 下次迭代自动感知。

---

## 0. 检查正在运行的后台 Agent（纯信息）

> 此步骤仅用于状态播报，不阻塞任何操作。

```bash
cd E:/ideaworkspace/astock-anayisis && python .claude/scripts/task_scheduler.py --list-running
```

解析 JSON：

| 字段 | 含义 |
|------|------|
| `running: true` + `tasks[]` | 有后台 Agent 正在运行 |
| `running: false` | 无运行任务 |

如果 `running: true`，记住 tasks 列表（含 task_id、description、elapsed_minutes），用于后续状态行输出。

---

## 1. 运行调度器

```bash
cd E:/ideaworkspace/astock-anayisis && python .claude/scripts/task_scheduler.py --check
```

解析 JSON，读取 `should_run` 字段。

---

## 2. 空闲路径（should_run = false）

绝大部分迭代走此路径。输出 Dev Loop 状态行，如有运行任务一并展示：

```bash
cd E:/ideaworkspace/astock-anayisis && python .claude/scripts/devloop_scanner.py --status
```

解析 JSON，按以下格式输出：

**无运行任务时：**
```
OK | B:o{n}/f{n}/m{n} | R_d:o{n}/im{n}/cl{n} | R_e:o{n}/im{n}/cl{n}{stuck}
```

**有运行任务时：**
```
⏳ [{task_id}] {description} {elapsed}分钟 | B:o{n}/f{n}/m{n} | R_d:o{n}/im{n}/cl{n} | R_e:o{n}/im{n}/cl{n}{stuck}
```

**有多个运行任务时：**
```
⏳ {n}个任务: [{task_id}] {desc} {elap}分钟, [{task_id}] {desc} {elap}分钟 | B:o{n}/f{n}/m{n} | R_d:o{n}/im{n}/cl{n} | R_e:o{n}/im{n}/cl{n}{stuck}
```

字段缩写：
- B = BUGs: o=OPEN f=FIXED m=MANUAL_REVIEW
- R_d = 每日复盘 REQs: o=OPEN im=IMPLEMENTED cl=CLOSED
- R_e = ETF REQs: 同上

stuck 格式（仅在 `healthy=false` 时追加）：每个僵死项 ` ⚠{id} {label}`，逗号分隔

---

## 3. 执行到期任务 → 派发后台 Agent（should_run = true）

### 3.1 标记完成（防重复派发）

> 🚨 **先标记完成再派发**。如果 subagent 执行失败，下次调度时间（第二天/下个小时）自动重试。

```bash
cd E:/ideaworkspace/astock-anayisis && python .claude/scripts/task_scheduler.py --complete {task_id}
```

### 3.2 读取任务文件

读取 `prompt_file` 字段指向的完整路径的全部内容。

### 3.3 注入完成协议

检查 `self_managed_complete` 字段：
- **如果为 true**（如 evening_review）：不注入，使用原始内容
- **如果为 false 或不存在**：在原始内容末尾追加以下后缀：

```markdown

---

## 最终步骤：标记完成

> 任务完成时（无论成功与否），执行以下命令标记调度器任务为已完成。

```bash
cd E:/ideaworkspace/astock-anayisis && python .claude/scripts/task_scheduler.py --complete {task_id}
```
```

### 3.4 派发后台 Agent

使用 **Agent 工具** 启动一个独立的 subagent 执行该任务：
- `subagent_type`: `"general-purpose"`
- `description`: 简短描述，如 `"执行 {task_id}"`
- `prompt`: 步骤 3.2 读取的内容 + 步骤 3.3 注入的后缀
- `run_in_background`: `true`

### 3.5 标记运行中（纯信息）

```bash
cd E:/ideaworkspace/astock-anayisis && python .claude/scripts/task_scheduler.py --mark-running {task_id}
```

### 3.6 输出状态行

先运行 devloop_scanner 获取最新状态：

```bash
cd E:/ideaworkspace/astock-anayisis && python .claude/scripts/devloop_scanner.py --status
```

输出格式：

```
🚀 [{task_id}] {description} — 已派发后台Agent执行 | B:o{n}/f{n}/m{n} | R_d:o{n}/im{n}/cl{n} | R_e:o{n}/im{n}/cl{n}{stuck}
```

> ⚠️ Agent 执行完成后，任务 prompt 自身（或被注入的后缀）会调用 `--complete`。
> 主 loop 不需要等待，后续迭代通过 `--check` 自动感知完成状态。

---

## 4. 错误处理

| 异常 | 处理 |
|------|------|
| scheduler JSON 解析失败 | 输出 `scheduler error: {raw}`，不阻塞循环 |
| prompt_file 不存在 | 输出 `prompt missing: {path}`，调用 `--complete` 跳过 |
| Agent 工具调用失败 | 输出 `Agent dispatch failed: {error}`，不阻塞循环（下次迭代重试） |
| `--complete` 调用失败 | 输出 warning，不阻塞循环 |
| `--mark-running` 调用失败 | 输出 warning，不阻塞循环 |
| **devloop_scanner 失败** | **降级输出**：空闲路径输出 `OK`；任务路径输出 `[{task_id}] {description} — 已派发` |