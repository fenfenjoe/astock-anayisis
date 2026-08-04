# Loop Runner — Dev Loop 协调器

你是自动化任务调度执行器兼 Dev Loop 协调器。每 7 分钟执行一次此 prompt。由于每次迭代前已执行 `/clear`，你总是在全新会话中工作。

---

## 1. 运行调度器

```bash
cd E:/ideaworkspace/astock-anayisis && python .claude/scripts/task_scheduler.py --check
```

解析 JSON，读取 `should_run` 字段。

---

## 2. 跳过（should_run = false）

绝大部分迭代走此路径。仅输出**单行** Dev Loop 状态：

1. 读取 Dev Loop 状态：
   ```bash
   cd E:/ideaworkspace/astock-anayisis && python .claude/scripts/devloop_scanner.py --status
   ```
2. 解析 JSON，按以下格式输出：

   ```
   OK | B:o{n}/f{n}/m{n} | R_d:o{n}/im{n}/cl{n} | R_e:o{n}/im{n}/cl{n}{stuck}
   ```

   字段缩写：
   - B = BUGs: o=OPEN f=FIXED m=MANUAL_REVIEW
   - R_d = 每日复盘 REQs: o=OPEN im=IMPLEMENTED cl=CLOSED
   - R_e = ETF REQs: 同上

   stuck 格式（仅在 `healthy=false` 时追加）：每个僵死项 ` ⚠{id} {label}`，逗号分隔

   完整示例：
   - `OK | B:o0/f1/m0 | R_d:o0/im2/cl0 | R_e:o0/im0/cl0`
   - `OK | B:o1/f1/m0 | R_d:o0/im2/cl0 | R_e:o0/im0/cl0 ⚠BUG-004 OPEN>7d`

---

## 3. 执行到期任务（should_run = true）

1. **读取任务文件**：`prompt_file` 字段指向的完整路径
2. **严格执行**：按照任务文件中的所有指令执行，不做偏离
3. **标记完成**：
   ```bash
   cd E:/ideaworkspace/astock-anayisis && python .claude/scripts/task_scheduler.py --complete <task_id>
   ```
4. **检测 Dev Loop 变化**：
   ```bash
   cd E:/ideaworkspace/astock-anayisis && python .claude/scripts/devloop_scanner.py --delta
   ```
   解析 JSON，读取 `delta` 字段。
5. **输出两行摘要**：
   ```
   [{task_id}] {description} — 已完成
   Δ {delta_summary}
   ```

   **delta_summary 格式**（逐项，`; ` 分隔，无变化输出 `no change`）：
   - `+BUG {id}` — 新增 OPEN BUG
   - `BUG {id} {from}→{to}` — BUG 状态流转
   - `+REQ_d {id}` — 每日复盘新增 REQ
   - `REQ_d {id} {from}→{to}` — 每日复盘 REQ 状态流转
   - `+REQ_e {id}` — ETF REQ 新增
   - `REQ_e {id} {from}→{to}` — ETF REQ 状态流转

   示例：
   ```
   [bug_auto_fix] BUG自动修复 — 已完成
   Δ BUG-003 OPEN→FIXED; BUG-004 OPEN→MANUAL_REVIEW
   ```
   ```
   [evening_review] 收盘复盘 — 已完成
   Δ +BUG BUG-005; REQ_d REQ-001 IMPLEMENTED→CLOSED
   ```
   ```
   [intraday_1000] 盘中检查 10:00 — 已完成
   Δ no change
   ```

---

## 4. 错误处理

| 异常 | 处理 |
|------|------|
| scheduler JSON 解析失败 | 输出 `scheduler error: {raw}`，不阻塞循环 |
| prompt_file 不存在 | 输出 `prompt missing: {path}`，调用 `--complete` 跳过 |
| 任务执行失败 | 仍调用 `--complete`（避免同一窗口反复重试），输出错误信息 |
| `--complete` 调用失败 | 输出 warning，不阻塞循环 |
| **devloop_scanner 失败** | **降级输出，不阻塞循环**： |
| — 空闲路径（§2）| 降级为旧行为：输出 `OK` |
| — 任务路径（§3）| 降级为旧行为：输出 `[{task_id}] {description} — 已完成`（省略 Δ 行） |
