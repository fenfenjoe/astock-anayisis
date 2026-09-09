# 策略扫描报告 — 2026-09-08

> 数据时点：2026-09-08 12:37（定时任务窗口，周二 12:37）
> 数据来源：WebSearch 各平台搜索快照（JoinQuant/BigQuant/GitHub/知乎/CSDN）
> 说明：平台回测指标直接转录自原文/摘要；未披露字段如实标注，不估算填充。标注"估算"的为折算值。

## 摘要
- 搜索平台: 5（聚宽/BigQuant/GitHub/知乎/CSDN）
- 发现候选: 13
- 🟢 绿灯（可转化）: 0
- 🟡 黄灯（队列）: 10
- 🔴 红灯（跳过）: 2
- 重复（跳过）: 1
- 数据不足/参考: 10（不计入候选，见搜索执行日志）

## 🟢 绿灯候选

（无 — 本次未发现满足全部绿灯维度的候选）

## 🟡 黄灯候选

### 1. 年化38.4%，回撤不到20%，夏普1.45的ETF动量策略（附代码）
```yaml
source:
  platform: zhihu
  url: "https://zhuanlan.zhihu.com/p/635005704"
  author: "未披露（知乎专栏）"
  title: "年化38.4%,回撤不到20%,夏普比1.45的ETF动量策略(附代码)"
  clone_count: 0
strategy:
  name: "ETF动量(38.4%)"
  type: momentum
  etf_pool: []  # 未披露
  max_assets: 未披露
  rebalance: 未披露
metrics:
  annual_return: 0.384
  sharpe: 1.45
  max_drawdown: -0.20  # 标题"回撤不到20%"
  backtest_start: 未披露
  backtest_end: 未披露
  benchmark: 未披露
logic:
  core_formula: "未披露（ETF动量策略，附代码，具体打分公式未详述）"
  factors: [动量]
  params: {}
  risk_control: "未披露"
code:
  available: true
  language: python
  completeness: full
```
**黄灯原因**：年化 38.4%/夏普 1.45/回撤<20% 均落在绿灯区间且附完整代码，但**回测周期未披露**（需≥5年方可绿灯），核心打分公式未详述。

### 2. Quantlab5.12 源码发布：年化61.9%，最大回撤-13.3%
```yaml
source:
  platform: zhihu
  url: "https://zhuanlan.zhihu.com/p/721058059"
  author: "未披露（Quantlab）"
  title: "Quantlab5.12源码发布:策略优化至年化收益61.9%,最大回撤-13.3%(python代码+数据)"
  clone_count: 0
strategy:
  name: "Quantlab优化(61.9%)"
  type: etf_rotation
  etf_pool: []  # 未披露
  max_assets: 未披露
  rebalance: 未披露
metrics:
  annual_return: 0.619
  sharpe: 未披露
  max_drawdown: -0.133
  backtest_start: 未披露
  backtest_end: 未披露
  benchmark: 未披露
logic:
  core_formula: "未披露（Quantlab平台策略优化，源码发布）"
  factors: []
  params: {}
  risk_control: "未披露"
code:
  available: true
  language: python
  completeness: full
```
**黄灯原因**：年化 61.9% 落在 50%-100% 黄灯区间；回撤 -13.3% 优秀，但夏普/回测周期/核心逻辑未披露。

### 3. 次方量化 ETF动量轮动策略，年化60%，回撤14%
```yaml
source:
  platform: zhihu
  url: "https://zhuanlan.zhihu.com/p/2036063884918924086"
  author: "次方量化"
  title: "ETF动量轮动策略,年化60%回撤14%"
  clone_count: 0
strategy:
  name: "ETF动量轮动(60%)"
  type: etf_rotation
  etf_pool: []  # 未披露
  max_assets: 未披露
  rebalance: 未披露
metrics:
  annual_return: 0.60
  sharpe: 未披露
  max_drawdown: -0.14
  backtest_start: 未披露
  backtest_end: 未披露
  benchmark: 未披露
logic:
  core_formula: "未披露（ETF动量轮动）"
  factors: [动量]
  params: {}
  risk_control: "未披露"
code:
  available: false
  language: other
  completeness: pseudocode
```
**黄灯原因**：年化 60% 落在 50%-100% 黄灯区间；回撤 -14% 优秀，但夏普/回测周期/代码未披露。

### 4. ETF动量轮动策略，带止盈，年化65%
```yaml
source:
  platform: zhihu
  url: "https://zhuanlan.zhihu.com/p/1925582485137384667"
  author: "未披露（知乎专栏）"
  title: "ETF动量轮动策略,带止盈:年化65%"
  clone_count: 0
strategy:
  name: "ETF动量轮动带止盈(65%)"
  type: etf_rotation
  etf_pool: []  # 未披露
  max_assets: 未披露
  rebalance: 未披露
metrics:
  annual_return: 0.65
  sharpe: 未披露
  max_drawdown: 未披露
  backtest_start: 未披露
  backtest_end: 未披露
  benchmark: 未披露
logic:
  core_formula: "ETF动量轮动 + 止盈机制（具体公式未披露）"
  factors: [动量, 止盈]
  params: {}
  risk_control: "止盈机制"
code:
  available: false
  language: other
  completeness: pseudocode
```
**黄灯原因**：年化 65% 落在 50%-100% 黄灯区间；止盈机制是差异化点，但夏普/回撤/周期/代码均未披露。

### 5. 十年年化42.4%（不止损55.7%）：ETF动量轮动+卡曼滤波+RSRS择时止损
```yaml
source:
  platform: zhihu
  url: "https://zhuanlan.zhihu.com/p/665264886"
  author: "未披露（知乎专栏）"
  title: "十年年化42.4%(不止损版本55.7%):ETF动量轮动+卡曼滤波+RSRS择时止损(代码+数据)"
  clone_count: 0
strategy:
  name: "动量轮动+卡曼滤波+RSRS"
  type: momentum
  etf_pool: []  # 未披露
  max_assets: 未披露
  rebalance: 未披露
metrics:
  annual_return: 0.424  # 止损版；不止损 0.557
  sharpe: 未披露
  max_drawdown: 未披露
  backtest_start: "约2015"  # 十年窗口
  backtest_end: "约2025"
  benchmark: 未披露
logic:
  core_formula: "ETF动量轮动 + 卡曼滤波(Kalman)信号平滑 + RSRS择时止损（与KB S18 RSRS相关但叠加卡曼滤波）"
  factors: [动量, 卡曼滤波, RSRS]
  params: {}
  risk_control: "RSRS择时止损 + 卡曼滤波降噪"
code:
  available: true
  language: python
  completeness: full
```
**黄灯原因**：年化 42.4% 落在绿灯区间、十年长周期回测，但含**卡曼滤波**新元素 + 与 KB S18（RSRS增强反转动量）因子集部分重叠（RSRS），参数复杂度高、夏普/回撤未披露，需评估是否构成新类型。

### 6. 一套跑通 2012–2025 的 ETF 多因子策略：年化15%，最大回撤16%
```yaml
source:
  platform: zhihu
  url: "https://zhuanlan.zhihu.com/p/1949885278463460837"
  author: "未披露（知乎专栏）"
  title: "一套跑通 2012–2025 的 ETF 多因子策略:年化 15%,最大回撤 16%,我做了哪些权衡"
  clone_count: 0
strategy:
  name: "ETF多因子(15%)"
  type: multi_factor
  etf_pool: []  # 未披露
  max_assets: 未披露
  rebalance: 未披露
metrics:
  annual_return: 0.15
  sharpe: 未披露
  max_drawdown: -0.16
  backtest_start: "2012"
  backtest_end: "2025"
  benchmark: 未披露
logic:
  core_formula: "ETF多因子轮动（具体因子组合未披露）"
  factors: [未披露]
  params: {}
  risk_control: "未披露"
code:
  available: false
  language: other
  completeness: pseudocode
```
**黄灯原因**：年化 15% 恰好压在绿灯下限、13 年长周期回测（2012-2025）非常有价值，但因子组合/夏普/代码未披露，仅年化+回撤。

### 7. etf-adaptive-rotation-qmt（自适应ETF轮动）
```yaml
source:
  platform: github
  url: "https://github.com/guoyaohua/etf-adaptive-rotation-qmt"
  author: "guoyaohua"
  title: "etf-adaptive-rotation-qmt（自适应ETF轮动，QMT）"
  clone_count: 0
strategy:
  name: "自适应ETF轮动(adaptive)"
  type: etf_rotation
  etf_pool: []  # 未披露
  max_assets: 未披露
  rebalance: 未披露
metrics:
  annual_return: 未披露
  sharpe: 未披露
  max_drawdown: 未披露
  backtest_start: 未披露
  backtest_end: 未披露
  benchmark: 未披露
logic:
  core_formula: "自适应ETF轮动（STRATEGY.md 有完整文档，多次跨平台搜索命中）"
  factors: [自适应, 动量]
  params: {}
  risk_control: "未披露"
code:
  available: true
  language: python
  completeness: full
```
**黄灯原因**：仓库有完整 STRATEGY.md 文档与源码、多次跨平台命中（GitHub/聚宽搜索结果重复出现），但 A 股回测指标未披露需补跑验证；"自适应"概念与 KB S14（动态波动率调整动量）有部分重叠，需确认差异点。

### 8. 年化30% ETF轮动策略 notebook 代码（backtrader）
```yaml
source:
  platform: zhihu
  url: "https://zhuanlan.zhihu.com/p/1936028592686503140"
  author: "未披露（知乎专栏）"
  title: "年化30%ETF轮动策略的notebook代码,基于backtrader通用模板,附python代码"
  clone_count: 0
strategy:
  name: "ETF轮动backtrader(30%)"
  type: etf_rotation
  etf_pool: []  # 未披露
  max_assets: 未披露
  rebalance: 未披露
metrics:
  annual_return: 0.30
  sharpe: 未披露
  max_drawdown: 未披露
  backtest_start: 未披露
  backtest_end: 未披露
  benchmark: 未披露
logic:
  core_formula: "未披露（backtrader通用模板ETF轮动）"
  factors: [动量]
  params: {}
  risk_control: "未披露"
code:
  available: true
  language: python
  completeness: full
```
**黄灯原因**：年化 30% 在绿灯区间且附 backtrader 完整代码，但夏普/回撤/回测周期未披露。

### 9. 年化29.8% 综合评分加 EPO 权重优化
```yaml
source:
  platform: zhihu
  url: "https://zhuanlan.zhihu.com/p/25912734294"
  author: "未披露（知乎专栏）"
  title: "年化29.8%,回撤14.?,比较稳健的策略:综合评分加EPO权重优化(python策略+数据)"
  clone_count: 0
strategy:
  name: "综合评分+EPO权重(29.8%)"
  type: multi_factor
  etf_pool: []  # 未披露
  max_assets: 未披露
  rebalance: 未披露
metrics:
  annual_return: 0.298
  sharpe: 未披露
  max_drawdown: -0.14  # 标题"回撤14.?"截断，约14%
  backtest_start: 未披露
  backtest_end: 未披露
  benchmark: 未披露
logic:
  core_formula: "综合评分 + EPO(Entropy Pooling?)权重优化（具体未披露）"
  factors: [综合评分, EPO权重优化]
  params: {}
  risk_control: "未披露"
code:
  available: true
  language: python
  completeness: full
```
**黄灯原因**：年化 29.8% 在绿灯区间、回撤约14%优秀且附代码，但 EPO 权重优化为新概念需确认可实现性，夏普/回测周期未披露。

### 10. 年化29.6% ETF评分轮动加止损风控
```yaml
source:
  platform: zhihu
  url: "https://zhuanlan.zhihu.com/p/24432537558"
  author: "未披露（知乎专栏）"
  title: "年化29.6%:基于ETF评分的轮动策略加止损风控版本,更稳健(python代码+数据)"
  clone_count: 0
strategy:
  name: "ETF评分轮动+止损(29.6%)"
  type: etf_rotation
  etf_pool: []  # 未披露
  max_assets: 未披露
  rebalance: 未披露
metrics:
  annual_return: 0.296
  sharpe: 未披露
  max_drawdown: 未披露
  backtest_start: 未披露
  backtest_end: 未披露
  benchmark: 未披露
logic:
  core_formula: "ETF评分轮动 + 止损风控（具体未披露）"
  factors: [ETF评分, 止损]
  params: {}
  risk_control: "止损风控"
code:
  available: true
  language: python
  completeness: full
```
**黄灯原因**：年化 29.6% 在绿灯区间且附代码、止损风控有价值，但夏普/回撤/回测周期未披露。

## 🔴 红灯候选

| 策略 | 来源 | 年化 | 红灯原因 |
|------|------|:---:|------|
| 年化118%、回撤仅6%：ETF自动运行印钞机 | 知乎 p/2040515217851996119 | 118% | 年化>100% 红灯；超高收益+极低回撤组合疑似过拟合 |
| +505%的ETF轮动策略被质疑过拟合：15组对照实验 | 知乎 p/2078407975023265270 | >100%（505%累计）| 年化>100% 红灯；**原文自身即过拟合审查报告**，揭示回测失真 |

## 重复（跳过）

1. **年化36.93%核心资产轮动策略复现（年化收益*R2拟合度评分）**（知乎 p/21345773251）— 核心公式为"年化收益 × R²"评分，与 KB **S4（多资产动量轮动）核心公式完全相同**（log-price OLS → 年化收益×R²），仅参数/资产池不同 → **参数变体，NOT 新策略**。另与 09-01 扫描标记的"十年867.83%核心资产轮动"同源（核心资产+年化×R²家族）。

## 搜索执行日志

| 平台 | 状态 | 备注 |
|------|------|------|
| JoinQuant | ⚠️ 部分成功 | 定向搜索命中弱（多为 GitHub/知乎镜像内容），未获得新策略 |
| BigQuant | ⚠️ 部分成功 | 命中学术论文（jsjkx.com）与 AI量化研究，平台策略页未直接返回具体指标 |
| GitHub | ✅ 成功 | 命中 etf-adaptive-rotation-qmt（自适应轮动，STRATEGY.md 完整文档）、QuantBot 等 |
| 知乎 | ✅ 成功（高产）| 命中 38.4%/61.9%/60%/65%/42.4%/29.8%/29.6%/30% 等大量具体策略 |
| CSDN | ⚠️ 部分成功 | 命中 Qbot/Qlib/qanat 等框架类项目，无单策略指标 |

数据不足/参考（不评级，仅记录）：
- 知乎「年化20%以上、回撤15%以下如何做ETF多因子轮动」p/2075345873148692260 — 问题帖非成品策略
- 知乎「7只ETF跑赢95%主动基金」p/2067561686840742965 — 无具体指标
- 知乎「全球主要市场ETF动量交易年化23.2%」p/1948684935478116399 — 全球市场，与本项目 A 股框架数据范围不符
- 知乎「ETF动量轮动+卡曼滤波+RSRS」中的不止损变体（55.7%）— 见黄灯#5
- BigQuant 学术论文（jsjkx.com id=19223）— 平台开发方法论文，非策略
- B站「简单因子年化超50%」— 非标准平台，指标披露少
- GitHub QuantBot（jeokeo011212/quantbot）— AI量化机器人桌面前端，工程参考
- GitHub daily_stock_analysis / tick-stock-panel — 股票分析/盘口工具，非轮动策略
- GitHub a-share-quant-research（XiyiRao）— 09-01 已记录的研究仓库，重复命中
- CSDN Qbot / Qlib / qanat — 量化框架（回测/Alpha DAG 引擎），工程参考

## 2025-2026 策略趋势观察（延续 08-04/09-01）

1. **知乎平台策略产出密度明显高于其他平台** — 本次 10 个黄灯候选中有 9 个来自知乎，聚宽/BigQuant 平台策略页对搜索引擎可见性下降
2. **止损/止盈风控成标配** — 带止盈(65%)、止损风控(29.6%)、RSRS择时止损(42.4%)多个候选叠加显式风控
3. **长周期回测案例增多** — 2012-2025（13年）多因子、十年卡曼滤波+RSRS，行业开始强调回测周期可信度
4. **自适应/滤波类新元素** — 自适应轮动（QMT）、卡曼滤波信号平滑，属于本项目 KB 尚无的信号处理层
5. **过拟合审查文化兴起** — +505% 被 15 组对照实验质疑、118%印钞机疑点，转化前必须独立复测（延续 09-01 警示）
