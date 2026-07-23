# 自动化 Loop 设置指南

本项目使用 `/loop` + `/clear` 架构替代 CronCreate 定时任务。

## 对比 CronCreate

| 特性 | CronCreate (旧) | /loop + /clear (新) |
|------|----------------|---------------------|
| 上下文 | 每次累积，越跑越长 | 每次 /clear 重置，零累积 |
| Token 费用 | 越晚任务越贵 | 每次固定开销 ~400 tokens |
| 持久化 | durable=true 写磁盘 | session-only，重启手动启动 |
| 管理 | 13 个独立 CronCreate | 1 个 task_schedule.json |
| 过期 | 7 天自动过期需重建 | 无过期概念 |

## 启动

在 Claude Code 会话中输入：

```
/loop 7m /clear && 执行 .claude/prompts/loop_runner.md
```

启动后会持续运行，每 7 分钟检查一次是否有到期任务。

**建议**：每个交易日早上启动 Claude Code 后执行此命令。

## 停止

- 发送 `Ctrl+C` 终止
- 或在 loop 提示中回复 `stop`

## 管理

- **查看状态**：`python .claude/scripts/task_scheduler.py --status`
- **修改调度**：编辑 `.claude/scripts/task_schedule.json`（下次迭代即生效）
- **添删任务**：编辑 `task_schedule.json` 的 `tasks` 数组
- **强制重跑**：删除 `.claude/scripts/scheduler_state.json` 中对应 key，等下一轮
- **手动触发**：`python .claude/scripts/task_scheduler.py --check` 查看当前应执行的任务

## 调度文件位置

- 任务定义：`.claude/scripts/task_schedule.json`（13 条任务）
- 调度器：`.claude/scripts/task_scheduler.py`
- 运行时状态：`.claude/scripts/scheduler_state.json`（自动创建）
- Loop prompt：`.claude/prompts/loop_runner.md`
