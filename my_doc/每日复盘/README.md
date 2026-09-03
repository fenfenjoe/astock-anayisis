# 每日复盘项目

> ⚠️ **DEPRECATED（已迁移至 etf-strategies/dashboard）**
>
> 本系统的功能已融入 `etf-strategies/dashboard`（端口 8000）：
> - **持仓/资产 配置** → 页面「💰 持仓/资产」（读写本目录 `harness/config/持仓.md`）
> - **定时任务**（早盘/盘中/盘后分析）→ 页面「⏰ 定时任务」内置调度器 + headless `claude -p` 运行器
> - **报告 / 每日信号展示** → 页面「📄 报告」「📡 每日信号」
>
> 本目录**保留**作为唯一事实源（报告/持仓/经验/交易记录数据），dashboard 直接读写同一份数据，**不做删除**。
> 迁移详情见 `etf-strategies/dashboard` 与 `daily-review-harness` skill。

基于 Harness Engineering 架构的 A 股每日市场报告生成系统。

## 架构

```
每日复盘/
├── harness/          # 厨房 — 报告生成系统（模板/经验/配置/工具）
├── reports/          # 菜 — 每日报告产出（按日期组织）
└── 每日调仓.md       # 调仓历史日志
```

### 厨房与菜分离

- **harness/**：所有"做饭"的东西——提示词模板、投资经验、持仓配置、辅助工具
- **reports/**：所有"菜"——生成的早盘报告、复盘报告，不含任何 prompt 副本

## 快速开始

对 Claude 说：
- "执行早盘分析" — 盘前 8:00-9:15 生成当日早盘报告
- "执行复盘分析" — 收盘后生成复盘报告，并自动生成次日 prompt

## 目录详情

详见 `harness/README.md`。

## 定时任务（DSH 精确触发）

当前自动化由 **Windows 计划任务**驱动（`dsh-trigger-*`，精确时刻触发、空闲零 token），
调度定义见 `.claude/scripts/task_schedule.json`（21 条：早盘/盘中×7/复盘/巡检/REQ 等）。

**查看执行时间（cron 表）**：

```powershell
# 终端打印 + 更新 docs/定时任务cron表.md
python .claude/scripts/dsh_cron.py --save

# 只打印，不写文件
python .claude/scripts/dsh_cron.py
```

cron 表实时生成自 `task_schedule.json`，含每条任务的 cron 表达式（`分 时 日 月 周`）、
执行时间、交易日标记；改过调度后重跑一次即刷新 `docs/定时任务cron表.md`。

管理命令（启用/停用/执行状态/日志）见 `.claude/prompts/setup_dsh_loop.md`。

## 数据纪律

- 所有 A 股数据走 `a-stock-data` skill
- 报告标注数据时点和数据源
- 区分"实测值"和"判断"
