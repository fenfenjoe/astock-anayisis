# AStock Analysis — A股ETF量化策略回测系统（纯量化系统）

A 股 ETF 策略研发与回测框架。内置 13+ 覆盖动量/趋势/配置/风控/多因子/量价情绪的 ETF 轮动策略，提供**零依赖交互式 CLI**（箭头键选择菜单），支持每日信号、策略学习、一年回测 HTML 报告。内置**量化 Dashboard**（策略全景/持仓/信号/报告/回测/工单管理）。

> **2026-10-15 解耦改造后**：本仓库是**纯量化系统**（数据 + 回测 + 信号 + API + Dashboard）。
> 拟人 Agent「小满」及其运行时、技能、自动化调度已整体外迁至 `~/.dsh/workspace/xiaoman/`，
> 仓库内不再包含任何 agent 运行时与耦合模块。Agent 通过 `docs/AGENT_GUIDE.md` 调用本系统的量化接口。

---

## 架构总览（解耦后）

```
astock-anayisis (本仓库) = 纯量化系统
├── etf-strategies/dashboard   → 量化 Dashboard (:8010)   【纯量化展示 + API】
│     策略全景 / 持仓 / 信号 / 报告 / 回测 / 权益曲线 / 工单管理
├── etf-strategies/backtest    → 回测引擎
├── etf-strategies/*.py        → CLI 工具（回测/信号/报告/数据）
├── docs/                      → 设计文档 + AGENT_GUIDE.md（Agent 标准化使用手册）
└── my_doc/                    → 报告输出 / 持仓.md / 每日调仓.md（用户数据，保留在仓库）

~/.dsh/ = DSH 用户目录（agent 全部内容收敛于此）
└── workspace/xiaoman/         ← 小满之家
    ├── agent/                 → 小满运行时（内嵌 HTTP API :8020，X-Api-Key 鉴权）
    ├── automation/            → ETF 自动化 prompts/config/bugs/steering
    ├── harness/               → 每日复盘 harness
    ├── scripts/               → 调度基础设施（task_schedule.json / dsh_trigger / start_all.ps1 等）
    ├── evolution/             → DSH 自进化文档
    └── web/                   → 小满 Web（纯前端 SPA：桌宠/角色/聊天/工作日程/提示待办/文章）
```

**数据流**：量化 Dashboard(:8010) 独立运行，纯量化展示 + API；小满 Web 独立运行，纯前端直连
agent API(:8020) 展示小满的桌宠/角色/聊天/工作日程；如需展示量化结果，再调 Dashboard API(:8010)。
**职责分离：量化系统管数据和 API，agent 管执行和展示。**

---

## 快速开始（量化侧）

```bash
# 克隆仓库
git clone https://github.com/fenfenjoe/astock-anayisis.git
cd astock-anayisis/etf-strategies

# 安装 Python 依赖
pip install -r requirements.txt
```

### 启动量化 Dashboard

```bash
cd etf-strategies
python dashboard/app.py          # → http://localhost:8010（可设 DASHBOARD_PORT 自定义端口）
```

Windows 也可用 `etf-strategies/scripts/start_local.ps1`（支持 `-DryRun` / `-Port`）。

首次启动 Dashboard 会自动初始化 SQLite、同步策略、预热信号，约 10~30 秒。

---

## Agent 侧接入（小满 / 外部 Agent）

Agent 使用本系统的标准化手册：**`docs/AGENT_GUIDE.md`**（数据/回测/信号/报告 API 一览 + 调用示例）。

- 小满运行时与 Web 在 `~/.dsh/workspace/xiaoman/`（详见该目录 README 与 `scripts/start_all.ps1`）。
- 小满 Web（纯前端 SPA）：`~/.dsh/workspace/xiaoman/web/`，直连 agent API(:8020)。
- Dashboard API 鉴权：登录后 JWT；Agent API 鉴权：`X-Api-Key` 头。

---

## 功能概览（量化 Dashboard）

| 模块 | 功能 | 说明 |
|------|------|------|
| **策略全景表** | 策略的绩效指标对比 | 年化收益 / 夏普 / 最大回撤 / Calmar / 日胜率 / 换手率 / 超额收益，支持点击排序 |
| **策略详情** | 策略知识库 + 绩效指标 | 择股逻辑 / 择时方法 / 因子说明 / 优劣势 / 来源链接 |
| **每日信号** | 各策略今日买卖建议 | 🟢买入 / 🔴卖出 / ⚪持有，含目标权重和变动幅度 |
| **权益曲线** | 全量回测净值对比图 | ECharts 交互式多策略叠加折线图 + 回撤曲线 |
| **调仓历史** | 最近调仓明细 | 每次调仓的 ETF 权重变动一览 |
| **打分曲线** | 动量/多因子打分过程可视化 | 策略打分因子动态曲线，展示策略内部决策过程 |
| **策略源码** | 在线查看策略 Python 源代码 | 无需切换编辑器即可了解策略实现细节 |
| **单策略回测** | 按需运行单个策略回测 | 结果即时写入数据库并刷新全景表指标 |
| **HTML 报告** | 一键生成一年回测 HTML 报告 | 含收盘价走势图（持仓标红）+ 调仓历史表 |
| **K线同步** | 增量刷新 ETF K线数据 | 自动检测缺失日期，仅拉取增量，写入 SQLite 缓存 |
| **工单管理** | 自动化发现问题的 BUG/REQ 工单 | 使用 Dashboard 自身 db（云库 tickets 表） |

> 小满的桌宠 / 角色页 / 聊天 / 工作日程 / 提示待办 / 文章已移出 Dashboard，见小满 Web。

---

## 架构

```
etf-strategies/
├── dashboard/
│   ├── app.py                  # FastAPI 后端 (:8010)
│   ├── db.py                   # SQLite 持久化层（权威表走 cloud，可重建缓存本地）
│   ├── importer.py             # 持仓/调仓/报告导入（原 scheduler 导入逻辑解耦而来）
│   ├── portfolio.py            # 持仓/调仓（本地 md 文件工作副本）
│   ├── api_daily.py            # 信号/报告 API
│   ├── api_tickets.py          # 工单 API（云库 tickets 表）
│   ├── templates/dashboard.html
│   └── static/                 # CSS/JS（量化视图；agent 相关 UI 已外迁）
├── backtest/                   # 回测核心包
├── tests/                      # Pytest 测试套件
├── report/                     # 生成的 HTML 回测报告
├── scripts/                    # 云库迁移/运维脚本（migrate/pg_exec/aidap 等）
└── *.py                        # CLI 工具（run_backtest / daily_signal / html_report 等）
```

**数据流**：启动时自动种子化策略定义 → K线增量同步至 SQLite → 信号/回测结果写入 SQLite →
API 从 SQLite 读取 → 前端 ECharts 渲染图表。权威数据（用户/持仓/报告/工单）存火山 Supabase 云库
（`cloud_db.py`），本地仅留可重建缓存（K线/NAV）。

---

## 数据来源

East Money (push2his) 前复权日K线，经 `em_get` 限流（≥1s间隔+抖动）防封，本地 parquet 缓存。
更多数据端点与取数规范见 `a-stock-data` skill 与 `etf-strategies/docs/`。

---

## 相关文档

- `docs/AGENT_GUIDE.md` — Agent 标准化使用手册（量化接口调用指南）
- `docs/2026-10-15-AStock与Agent解耦方案与进度.md` — 本次解耦改造的方案与进度
- `etf-strategies/开发手册.md` — 量化侧开发手册
- `docs/DEPLOYMENT.md` / `docs/SECURITY.md` — 部署与安全
