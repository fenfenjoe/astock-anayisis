# AStock Analysis — A股ETF量化策略回测系统

A 股 ETF 策略研发与回测框架。内置 13 个覆盖动量/趋势/配置/风控/多因子/量价情绪的 ETF 轮动策略，提供**零依赖交互式 CLI**（箭头键选择菜单），支持每日信号、策略学习、一年回测 HTML 报告。内置 Dashboard 与拟人 Agent「小满」。

---

## 快速开始

```bash
# 克隆仓库
git clone https://github.com/fenfenjoe/astock-anayisis.git
cd astock-anayisis/etf-strategies

# 安装 Python 依赖
pip install -r requirements.txt
# 可选：云备份/严格零本地需要 boto3
python -m pip install --user boto3
```

---

## 启动指南（含拟人 Agent「小满」）

本项目有 **2 个必跑组件**：Dashboard（web 界面）、小满 Agent（常驻进程）。记忆组件 **OpenViking 已接入火山云版**（无需本地服务）。小满 Agent 内部通过 `dsh --profile xiaoman` 调用 LLM。

### 启动前准备

| # | 项 | 说明 / 命令 |
|---|----|------------|
| 1 | **Node.js + dsh CLI** | 小满与调度引擎的大脑，必须。先装 Node.js（Windows 推荐 nvm4w，npm 随自带）；**dsh 与 pnpm 无需手动装**，第 3 步 sync 脚本检测到缺失会自动安装（手动装：`npm i -g @deepseek-ai/dsh@0.1.0-rc.6`） |
| 2 | **dsh 凭据** | `~/.dsh/.credentials.yaml` 填 `DEEPSEEK_API_KEY`（key 单点，Dashboard 与小满共用）；验证：`dsh --profile xiaoman "在吗"` |
| 3 | **dsh 环境同步（一键）** | `powershell -ExecutionPolicy Bypass -File scripts/sync_dsh.ps1`：自动检测/安装 pnpm、dsh（缺失时），同步仓库 `.dsh/profiles`（xiaoman）到本机，并为每个 profile 自动安装插件依赖（`dsh plugin --profile <name> install`），最后校验凭据与版本 |
| 4 | **Python 依赖** | `pip install -r etf-strategies/requirements.txt` |
| 5 | **`.env` 配置（可选）** | 复制 `etf-strategies/.env.example` → `.env`。云端权威库：`DASHBOARD_DB_BACKEND=cloud` + `AGENT_DB_BACKEND=cloud` + `SUPABASE_URL` + `SUPABASE_SERVICE_KEY`（见 `docs/2026-09-07-云端数据库迁移方案.md`）；用 claude 兜底才需填 `ANTHROPIC_AUTH_TOKEN`（默认走 dsh 不需要） |
| 6 | **OpenViking 记忆（可选）** | 已接入**火山云版**（`~/.openviking/ovcli.conf` 指向 `api.vikingdb.cn-beijing.volces.com/openviking`，含云 API Key，敏感不入 git）；无需本地跑 `openviking-server`，见 `docs/DEPLOYMENT.md` §4.1 |
| 7 | ~~云备份 TOS（已下线）~~ | **2026-09-07 移除**：TOS 对象存储停用（`cloud_sync.py`/`cloud.json` 已删/清空），权威数据在 Supabase 云库；删桶步骤见 `docs/DEPLOYMENT.md` §5 |

### 启动方式

#### 方式 A：一键启动所有服务（推荐）

```powershell
cd astock-anayisis
# 前置：先跑一次同步/校验
powershell -ExecutionPolicy Bypass -File scripts\sync_dsh.ps1

# 启动（dashboard + agent；OpenViking 云版已配置时自动跳过本地 server）
powershell -ExecutionPolicy Bypass -File scripts\start_all.ps1
# 查看 / 停止
powershell -ExecutionPolicy Bypass -File scripts\start_all.ps1 -Action status
powershell -ExecutionPolicy Bypass -File scripts\start_all.ps1 -Action stop
```

#### 方式 B：分别启动

```bash
# 终端 1：Dashboard（web 界面 + 工作日程 + 聊天 API）
cd etf-strategies
python dashboard/app.py
# → http://localhost:8000

# 终端 2：小满 Agent 常驻进程（素材采集 / 每日发文 / 动态）
python -m agent

# （可选）终端 3：OpenViking 记忆服务
openviking-server   # 或 start_all.ps1 管理的 openviking
```

### 启动后的使用

- 访问 **http://localhost:8000**，顶部导航：
  - **💬 角色**：和小满聊天、浏览她的文章/动态；顶部状态栏显示 **请假中 / 摸鱼中 / 正在做XXX**
  - **🗓️ 工作日程**：小满的定时任务表；「👔 上班」= 按日程执行，点「🏖️ 请假」= 暂停定时任务
- 首次启动 Dashboard 会自动初始化 SQLite、同步策略、预热信号，约 10~30 秒
- 可设环境变量 `DASHBOARD_PORT` 自定义端口

### 常用运维

| 操作 | 命令 |
|------|------|
| 小满常驻进程启动/停止 | `start_all.ps1` 或 `python -m agent` |
| 上班/请假（定时任务开关） | Dashboard「🗓️ 工作日程」页即可，无需重启 |
| 云备份上传/恢复 | `python scripts\cloud_sync.py` / `--download` |
| 严格零本地模式 | `.env` 设 `DB_MODE=memory` + `CLOUD_RESTORE_ON_START=1`（见 `docs/DEPLOYMENT.md`） |

> 详细：数据上云与严格零本地、多机一致性见 `docs/DEPLOYMENT.md`；凭据安全见 `docs/SECURITY.md`。

### OpenViking 云记忆配置（火山云版）

小满的语义记忆走**火山引擎 OpenViking 云服务**，无需本地跑 `openviking-server`。

**配置位置**：`~/.openviking/ovcli.conf`（机器本地秘密文件，**勿提交/勿公开**）：

```json
{
  "url": "https://api.vikingdb.cn-beijing.volces.com/openviking",
  "api_key": "<你的火山 OpenViking 云 API Key>",
  "account": "default",
  "user": "default"
}
```

> ⚠️ 上面 `api_key` 是**占位符**——真实 Key 只保存在本机 `ovcli.conf`（插件按 `{url}/mcp` 连云端）。请勿把真实 Key 写进 README / 提交到仓库（本项目仓库为 public）。

**接入步骤**（新机器）：
1. `dsh plugin --profile xiaoman add @openviking/dsh-memory-plugin`
2. 按上文写 `~/.openviking/ovcli.conf`（填你的云 Key）
3. 记忆隔离由 `dsh_runner` 自动注入 `OPENVIKING_PEER_ID=xiaoman` + `OPENVIKING_RECALL_PEER_SCOPE=actor`
4. 验证：小满会话里 `viking_remember` / `viking_search` 往返

> 备选：也可用环境变量 `OPENVIKING_URL` / `OPENVIKING_API_KEY` 替代配置文件。详见 `docs/DEPLOYMENT.md` §4.1。

### 功能概览

| 模块 | 功能 | 说明 |
|------|------|------|
| **策略全景表** | 17 个策略的绩效指标对比 | 年化收益 / 夏普 / 最大回撤 / Calmar / 日胜率 / 换手率 / 超额收益，支持点击排序 |
| **策略详情** | 策略知识库 + 绩效指标 | 择股逻辑 / 择时方法 / 因子说明 / 优劣势 / 来源链接 |
| **每日信号** | 各策略今日买卖建议 | 🟢买入 / 🔴卖出 / ⚪持有，含目标权重和变动幅度 |
| **权益曲线** | 全量回测净值对比图 | ECharts 交互式多策略叠加折线图 + 回撤曲线 |
| **调仓历史** | 最近 10 次调仓明细 | 每次调仓的 ETF 权重变动一览 |
| **打分曲线** | 动量/多因子打分过程可视化 | S4/S8/S12~S17 的打分因子动态曲线，展示策略内部决策过程 |
| **策略源码** | 在线查看策略 Python 源代码 | 无需切换编辑器即可了解策略实现细节 |
| **单策略回测** | 按需运行单个策略回测 | 结果即时写入数据库并刷新全景表指标 |
| **HTML 报告** | 一键生成一年回测 HTML 报告 | 含收盘价走势图（持仓标红）+ 调仓历史表 |
| **K线同步** | 增量刷新 ETF K线数据 | 自动检测缺失日期，仅拉取增量，写入 SQLite 缓存 |
| **💬 角色（小满）** | 拟人 Agent | 聊天 + 文章/动态 + 工作日程 + 状态展示（请假/摸鱼/正在做） |
| **🗓️ 工作日程** | 定时任务引擎 | 早盘/盘中/复盘等定时任务，👔上班 / 🏖️请假 |

### 架构

```
etf-strategies/
├── agent/                      # 拟人 Agent「小满」
│   ├── dsh_runner.py           # dsh --profile xiaoman 调用（LLM 大脑）
│   ├── db.py                   # agent.db（会话/文章/观点/知识/素材源）
│   ├── core/                   # persona/memory/knowledge/behavior/lifecycle
│   ├── personas/xiaoman/       # 人设卡
│   └── __main__.py             # 常驻进程入口 (python -m agent)
├── cloud_db.py                 # 云端权威库访问层（火山 Supabase PostgREST）
├── dashboard/
│   ├── app.py                  # FastAPI 后端
│   ├── db.py                   # SQLite 持久化层（权威表走 cloud，可重建缓存本地）
│   ├── scheduler.py            # 定时任务引擎（工作日程/上班请假状态）
│   ├── portfolio.py            # 持仓/调仓（本地 md 文件工作副本）
│   ├── api_agent.py            # 小满 API（聊天/文章/状态）
│   ├── api_daily.py            # 信号/报告/调度 API
│   ├── templates/dashboard.html
│   └── static/                 # CSS/JS（含 agent.js / agent.css）
├── backtest/                   # 回测核心包
├── tests/                      # Pytest 测试套件
└── report/                     # 生成的 HTML 回测报告
```

**数据流：** 启动时自动种子化策略定义 → K线增量同步至 SQLite → 信号/回测结果写入 SQLite → API 从 SQLite 读取 → 前端 ECharts 渲染图表。小满经 dsh 调用 LLM。权威数据（用户/持仓/报告/调度/Agent 会话）存火山 Supabase 云库（`cloud_db.py`），本地仅留可重建缓存（K线/NAV）。

（原「项目结构 / 策略速览 / 数据来源」详表见本仓库 `etf-strategies/README.md` 补充与 `03_ETF策略回测报告.md`。）

---

## 数据来源

East Money (push2his) 前复权日K线，经 `em_get` 限流（≥1s间隔+抖动）防封，本地 parquet 缓存。
