# AStock Analysis — A股ETF量化策略回测系统

A 股 ETF 策略研发与回测框架。内置 13 个覆盖动量/趋势/配置/风控/多因子/量价情绪的 ETF 轮动策略，提供**零依赖交互式 CLI**（箭头键选择菜单），支持每日信号、策略学习、一年回测 HTML 报告。

---

## 快速开始

```bash
# 克隆仓库
git clone https://github.com/fenfenjoe/astock-anayisis.git
cd astock-anayisis/etf-strategies

# 安装依赖
pip install pandas numpy matplotlib requests

# 交互式 CLI（推荐）— 箭头键选择功能，回车执行
python cli.py

# 也可以直接调用独立脚本或命令行参数
python list_strategies.py           # 列出所有策略
python daily_signal.py S4           # 查看 S4 今日信号
python cli.py learn S4              # 查看 S4 策略详细介绍
python cli.py report S4             # 生成 S4 一年回测HTML报告
python run_backtest.py              # 运行全量回测
```

---

## 交互式 CLI 使用说明

```bash
python cli.py
```

运行后进入全屏交互界面：

```
  🏦 AStock ETF 策略管理
  ==================================================

  ▶  📋 列出所有策略       — 查看已维护的 13 个策略
     📊 查看每日信号       — 查看策略今日买卖操作
     🚀 运行全量回测       — 生成回测报告+图表
     🚪 退出

  ↑↓ 选择  Enter 确认  Esc 返回
```

**操作方式：**
- `↑↓` 箭头键：切换菜单选项
- `Enter`：确认选择
- `Esc`：返回上一级 / 退出

**功能流程：**
1. **列出所有策略** → 直接展示策略表格，按任意键返回
2. **查看每日信号** → 弹出策略列表（含"全部策略"选项）→ 选中后拉取实时数据展示信号
3. **运行全量回测** → 执行 13 个策略的历史回测，生成报告和图表
4. **退出** → 清除屏幕退出

### 新增功能

在 `cli.py` 中添加一个函数 + 在主菜单加一行选项即可：

```python
# 1) 实现功能函数
def _fn_xxx():
    ...

# 2) 加到 MAIN_MENU
MAIN_MENU = [
    ...,
    ("🆕 新功能说明", _fn_xxx),
]
```

新功能会自动出现在交互菜单中，无需修改参数解析逻辑。

> 也可以命令行传参调用（兼容旧用法）：`python cli.py list` / `python cli.py signal S4` / `python cli.py learn S4` / `python cli.py report S4` / `python cli.py backtest`

---

## 策略学习 (`learn`)

查看任意策略的详细介绍：择股逻辑、择时方法、使用因子、优势劣势、回测参数（滑点/佣金/信号滞后等）。

```bash
python cli.py learn S4       # 查看 S4 多资产动量轮动的完整介绍
python cli.py learn S10      # 查看 S10 低波动因子的完整介绍
```

知识库覆盖全部 13 个策略，详见 `strategy_kb.py`。

---

## 一年回测报告 (`report`)

选择策略，拉取近一年真实行情，运行回测，生成包含以下内容的 HTML 报告：

- **回测指标**：年化收益、波动率、夏普、最大回撤、日胜率
- **收盘价走势图**：每个 ETF 的收盘价折线，**持仓期间标为红色线段**，非持仓为灰色
- **调仓历史表**：每次权重变动 >1% 的日期、操作、持仓变化

```bash
python cli.py report S4      # 生成 S4 的一年回测HTML报告
python cli.py report --all   # 生成全部 13 个策略的报告
```

报告输出到 `etf-strategies/report/{策略名}-{时间戳}.html`，用浏览器打开即可查看。

---

## 命令说明

### 1. 策略列表 — `list_strategies.py`

列出项目中所有已维护的策略，包括编号、资产池、默认参数和策略说明。

```bash
python list_strategies.py
```

输出示例：

```
| 编号 | 策略名称 | 资产池 | 默认参数 | 说明 |
|------|---------|--------|---------|------|
| S1_买入持有 | BuyHold | 510300 | code=510300 | 恒满仓，不调仓。作基准 benchmark |
| S2_双动量 | DualMomentum | 510300, 511260, 511880 | lookback=250 | 绝对+相对动量，月末调仓 |
| S3_均线趋势 | MATrend | 510300, 511880 | short=20, long=60 | MA金叉持股，死叉切货币 |
| S4_多资产动量轮动 | MomentumRotation | 518880, 513100, 159915, 510180 | lookback=25 | 年化收益×R²打分轮动 |
| ... | ... | ... | ... | ... |

共 13 个策略
```

**新增策略时**，在 `list_strategies.py` 的 `STRATEGIES` 列表中加一行类引用即可自动发现。

---

### 2. 每日信号 — `daily_signal.py`

拉取最新行情数据，运行指定策略，给出当天的具体买卖操作。

```bash
python daily_signal.py              # 列出所有可用策略
python daily_signal.py S4           # 查看 S4 今日信号
python daily_signal.py S8           # 查看 S8 今日信号
python daily_signal.py --all        # 查看全部策略的今日信号
```

输出包含：
- 数据窗口（最近 N 个交易日）
- 每个 ETF 的目标权重、上期权重、变动幅度
- 操作方向：🟢买入 / 🔴卖出 / ⚪持有
- 建议持仓汇总

输出示例：

```
======================================================================
  S4 多资产动量轮动
  资产池: 518880(黄金ETF), 513100(纳指100ETF), 159915(创业板ETF), 510180(上证180ETF)
======================================================================
  数据窗口: 2025-09-04 ~ 2026-07-01 (196 个交易日)

  📅 信号日期: 2026-07-01
  代码       名称                 目标权重     上期权重       变动  操作
  --------------------------------------------------------------
  518880   黄金ETF             0.0%      0.0%     +0.0%   ⚪ 持有
  513100   纳指100ETF          0.0%      0.0%     +0.0%   ⚪ 持有
  159915   创业板ETF          100.0%    100.0%     +0.0%   ⚪ 持有
  510180   上证180ETF          0.0%      0.0%     +0.0%   ⚪ 持有

  ✅ 今日无需操作，维持现有持仓。

  💼 建议持仓:
     159915 创业板ETF: 100.0%
```

---

### 3. 全量回测 — `run_backtest.py`

对所有策略在历史数据上运行完整回测，生成指标对比表和净值/回撤曲线图。

```bash
python run_backtest.py
```

产出文件：
- `03_ETF策略回测报告.md` — Markdown 回测报告（指标表 + 图表）
- `equity_curves.png` — 13条策略净值曲线对比
- `drawdowns.png` — 13条策略回撤曲线对比

---

## Web Dashboard

基于 **FastAPI + SQLite + ECharts** 构建的量化策略 Web Dashboard，提供可视化的策略管理、信号查看和回测分析界面，作为 CLI 工具的图形化补充。

### 启动

```bash
cd etf-strategies

# 安装额外依赖
pip install fastapi uvicorn

# 启动 Dashboard（默认端口 8000）
python dashboard/app.py
```

启动后访问 **http://localhost:8000** 即可打开 Dashboard。

> 首次启动会自动初始化 SQLite 数据库、同步策略定义、预热信号缓存，耗时约 10~30 秒。
> 可通过环境变量 `DASHBOARD_PORT` 自定义端口。

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

### 架构

```
dashboard/
├── app.py                    # FastAPI 后端（30+ API 端点）
├── db.py                     # SQLite 持久化层（6 张表，含完整 Schema 注释）
├── sync.py                   # 数据同步（K线增量/信号生成/回测NAV）
├── templates/
│   └── dashboard.html        # 前端单页应用
├── static/
│   ├── css/dashboard.css     # 样式表
│   └── js/dashboard.js       # 前端逻辑（ECharts 图表渲染 + 状态管理）
└── data/
    └── cache.db              # SQLite 数据库文件（自动创建，WAL 模式）
```

**数据库表设计：**

| 表名 | 用途 | 数据量 |
|------|------|--------|
| `kline_daily` | ETF K线日数据缓存（OHLCV），按 code+date 去重 | ~87,500 行 |
| `strategy_metrics` | 策略回测绩效指标（年化/夏普/回撤/Calmar/胜率/换手） | 17 行 |
| `daily_signals` | 每日交易信号快照（BUY/SELL/HOLD + 权重变动） | ~64 行/天 |
| `strategy_kb` | 策略知识库（择股/择时/因子/优劣势/来源/执行流程） | 17 行 |
| `backtest_nav` | 权益曲线净值数据（周频采样，供 ECharts 渲染） | ~11,200 行 |
| `metadata` | 系统元数据（种子标记等 key-value） | <10 行 |

**数据流：** 启动时自动种子化策略定义 → K线增量同步至 SQLite → 信号/回测结果写入 SQLite → API 从 SQLite 读取 → 前端 ECharts 渲染图表。

## 项目结构

```
etf-strategies/
├── cli.py                        # 统一 CLI 入口（推荐）
├── run_backtest.py               # 全量回测入口
├── list_strategies.py            # 策略列表脚本
├── daily_signal.py               # 每日买卖信号脚本
├── strategy_kb.py                # 策略知识库（17个策略详解）
├── html_report.py                # HTML报告生成器（一年回测+走势图）
├── dashboard/                    # Web Dashboard（FastAPI + SQLite + ECharts）
│   ├── app.py                    #   后端 API 服务
│   ├── db.py                     #   SQLite 持久化层
│   ├── sync.py                   #   数据同步模块
│   ├── templates/                #   前端模板
│   ├── static/                   #   静态资源（CSS/JS）
│   └── data/                     #   SQLite 数据库
├── backtest/                     # 回测核心包
│   ├── engine.py                 # 向量化回测引擎（信号滞后+成本）
│   ├── data.py                   # 数据层（东财K线+parquet缓存）
│   ├── em_client.py              # 东财HTTP客户端（限流+重试）
│   ├── cost.py                   # 交易成本模型
│   ├── metrics.py                # 绩效指标（年化/夏普/回撤/Calmar）
│   ├── reporting.py              # 报告生成（matplotlib+markdown）
│   └── strategies/               # 策略实现（17个）
│       ├── base.py               # 策略基类
│       ├── buy_hold.py           # S1 买入持有
│       ├── dual_momentum.py      # S2 双动量
│       ├── ma_trend.py           # S3 均线趋势
│       ├── momentum_rotation.py  # S4 多资产动量轮动
│       ├── equal_weight.py       # S5 等权组合
│       ├── portfolio_6040.py     # S6 60-40股债平衡
│       ├── target_vol.py         # S7 目标波动率
│       ├── three_factor_momentum.py  # S8 三因子动量轮动
│       ├── industry_momentum.py  # S9 行业动量轮动
│       ├── low_vol.py            # S10 低波动因子
│       ├── bollinger.py          # S11 布林带均值回归
│       ├── sentiment_momentum.py # S12 量价情绪多因子
│       ├── multi_factor.py       # S13 多因子综合打分
│       ├── adaptive_momentum.py  # S14 动态波动率调整动量
│       ├── rsrs_momentum.py      # S15 趋势过滤动量增强
│       └── canary_defense.py     # S16/S17 金丝雀防御动量
├── tests/                        # Pytest 测试套件
├── cache/                        # K线数据 parquet 缓存
├── report/                       # 生成的HTML回测报告
└── *.md                          # 回测报告 + 调研报告
```

---

## 策略速览

| 编号 | 策略 | 年化收益 | 夏普 | 最大回撤 | 调仓 |
|------|------|---------|------|---------|------|
| S1 | 买入持有（基准） | 8.19% | 0.30 | -52.97% | — |
| S2 | 双动量 | 5.60% | 0.39 | **-24.58%** | 月末 |
| S3 | 均线趋势 | 6.99% | 0.35 | -50.45% | 月末 |
| S4 | 多资产动量轮动 | 33.62% | 1.21 | -29.73% | 每日 |
| S5 | 等权组合 | 7.70% | 0.44 | -32.93% | 季末 |
| S6 | 60-40股债平衡 | 5.71% | 0.45 | -25.11% | 季末 |
| S7 | 目标波动率 | 9.55% | 0.57 | -40.90% | 月末 |
| S8 | 三因子动量轮动 | **34.82%** | 1.27 | -30.14% | 每日 |
| S9 | 行业动量轮动 | 2.95% | 0.14 | -46.03% | 月末 |
| S10 | 低波动因子 | 10.89% | **1.39** | **-9.68%** | 月末 |
| S11 | 布林带均值回归 | 7.93% | 0.47 | -34.05% | 每周 |
| S12 | 量价情绪多因子 | 14.85% | 0.82 | -30.57% | 每日 |
| S13 | 多因子综合打分 | 2.16% | 0.11 | -40.49% | 月末 |

> 回测窗口：各策略资产对齐后窗口不同（2012~2026），详见 `03_ETF策略回测报告.md`。
> ⚠️ 回测好≠实盘好。上述收益含过拟合风险，不构成投资建议。

---

## 数据来源

East Money (push2his) 前复权日K线，经 `em_get` 限流（≥1s间隔+抖动）防封，本地 parquet 缓存。

---

## 运行测试

```bash
cd etf-strategies
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/ -v
```
