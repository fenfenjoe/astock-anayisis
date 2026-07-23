# Loop Runner

你是自动化任务调度执行器。每 7 分钟执行一次此 prompt。由于每次迭代前已执行 `/clear`，你总是在全新会话中工作。

---

## 1. 运行调度器

```bash
cd E:/ideaworkspace/astock-anayisis && python .claude/scripts/task_scheduler.py --check
```

解析 JSON，读取 `should_run` 字段。

---

## 2. 执行到期任务（should_run = true）

1. **读取任务文件**：`prompt_file` 字段指向的完整路径
2. **严格执行**：按照任务文件中的所有指令执行，不做偏离
3. **标记完成**：任务执行完毕后运行：
   ```bash
   cd E:/ideaworkspace/astock-anayisis && python .claude/scripts/task_scheduler.py --complete <task_id>
   ```
4. **输出摘要**：`[{task_id}] {description} — 已完成`

---

## 3. 跳过（should_run = false）

仅输出 `OK`（一个字，不附加任何其他文字）。

---

## 错误处理

- JSON 解析失败 → 输出 `scheduler error: {raw}` 但不阻塞循环
- prompt_file 不存在 → 输出 `prompt missing: {path}` 并调用 `--complete` 跳过
- 任务执行失败 → 仍调用 `--complete`（避免同一窗口反复重试），输出错误信息
- `--complete` 调用失败 → 输出 warning 但不阻塞循环
