# 策略扫描报告 — 2026-09-15

> 数据时点：2026-09-15 12:37（定时任务窗口，周二 12:37）
> 数据来源：WebSearch 各平台搜索快照（JoinQuant/BigQuant/GitHub/知乎/CSDN）——本次 web_search 工具余额不足，改用**火山引擎豆包搜索 API**（byted-web-search）完成全部平台搜索
> 说明：平台回测指标直接转录自原文/摘要；未披露字段如实标注，不估算填充。标注"估算"的为折算值。

## 摘要
- 搜索平台: 5（聚宽/BigQuant/GitHub/知乎/CSDN）
- 发现候选: 10
- 🟢 绿灯（可转化）: 1
- 🟡 黄灯（队列）: 6
- 🔴 红灯（跳过）: 3
- 重复（跳过）: 3
- 数据不足/参考: 10（不计入候选，见搜索执行日志）

## 🟢 绿灯候选

### 1. 多品种ETF动量轮动+EPO优化（openhe，聚宽）
```yaml
source:
  platform: joinquant
  url: "https://caifuhao.eastmoney.com/news/20260627124449897326090"
  author: "openhe（聚宽原创，获赞125）/ 东方财富财富号复现"
  title: "多品种ETF动量轮动+EPO优化"
  clone_count: 125  # 聚宽获赞数
strategy:
  name: "动量×R²+EPO权重优化"
  type: etf_rotation
  etf_pool: [518880, 159985, 513100, 510300, 511010]  # 美林时钟构建：黄金/豆粕/纳指/沪深300/国债等
  max_assets: 3
  rebalance: monthly
metrics:
  annual_return: 0.4099   # 聚宽口径；QMT复现 0.3103
  sharpe: 1.600           # QMT复现 1.559
  max_drawdown: -0.2005   # QMT复现 -0.1794
  backtest_start: "2020-04-28"
  backtest_end: "2026-04-28"
  benchmark: "沪深300"
logic:
  core_formula: "动量分数=年化收益×R²（34日log-price OLS），选Top-3后EPO优化权重：收缩相关矩阵 shrunk_cor=(1-w)×corr+w×I（w=0.2）+ 锚定逆方差 + 信号向量求解，负权重置零归一化"
  factors: [动量×R², EPO权重优化, 相关性收缩]
  params: {lookback: 34, top_n: 3, shrink_w: 0.2, risk_aversion: 10}
  risk_control: "EPO收缩相关矩阵分散化 + 动量×R²趋势质量过滤"
code:
  available: true
  language: python
  completeness: full
```
**绿灯原因**：年化40.99%（15-50%区间）、夏普1.600（0.8-2.0）、回撤-20.05%（<30%）、回测6年（≥5年）、逻辑清晰可解释、参数4个（lookback/top_n/shrink_w/risk_aversion）、完整源码（聚宽+QMT双框架复现）。

> ⚠️ **与队列候选同源提示**：09-08 黄灯 `2026-09-08-09`（综合评分+EPO权重，29.8%，知乎 p/25912734294）与本次 openhe 策略疑似同源（均为 EPO 权重优化家族）。本次发现的 openhe 为**最早来源**（聚宽原帖 2024 年发布）且指标更完整（40.99%/1.60/-20.05%/6年），转化时应以 openhe 原版为准，合并评估。

## 🟡 黄灯候选

### 1. 波动率过滤后相关性最小ETF轮动（开心果，聚宽）
```yaml
source:
  platform: joinquant
  url: "https://test.demo.joinquant.com/community/post/detailMobile?postId=49615"
  author: "开心果"
  title: "波动率过滤后相关性最小etf轮动"
  clone_count: 141
strategy:
  name: "k-means低相关+波动率过滤轮动"
  type: etf_rotation
  etf_pool: []  # k-means动态聚类，非固定池
  max_assets: 未披露
  rebalance: daily
metrics:
  annual_return: 0.3165
  sharpe: 1.141
  max_drawdown: 未披露
  backtest_start: "2017-01-01"
  backtest_end: "2024-08-23"
  benchmark: "沪深300"
logic:
  core_formula: "k-means聚类自动寻找最优簇（低相关ETF池）→ 波动率过滤 + 动量评分上下限（-0.5<score<4.5）→ 轮动选标的"
  factors: [相关性聚类, 波动率过滤, 动量评分]
  params: {}
  risk_control: "波动率过滤 + 动量评分上下限"
code:
  available: true
  language: python
  completeness: full
```
**黄灯原因**：年化31.65%（绿灯）、夏普1.141（绿灯）、回测7.6年（绿灯）且源码完整，但**评论区指出现有未来函数问题**（用当前数据倒推240天相关性聚类，"从现在眼光看过去"），需修正为滚动窗口；与 KB S19（低相关ETF轮动）概念相关但实现不同（S19人工选池 vs 本策略k-means自动聚类），可作差异化参考。

### 2. 量价共振ETF轮动（BigQuant AI量化）
```yaml
source:
  platform: bigquant
  url: "https://bigquant.com/square/ai/babfacdc-0536-2a4f-3b5d-17e75146ea4f"
  author: "BigQuant 平台策略（更新2026-09-12）"
  title: "量价共振ETF轮动（年化26.22%）"
  clone_count: 0
strategy:
  name: "趋势+反转+量比三因子轮动"
  type: multi_factor
  etf_pool: [510300, 518880]  # 4只特定ETF
  max_assets: 1
  rebalance: "每25交易日"
metrics:
  annual_return: 0.2622
  sharpe: 1.13
  max_drawdown: -0.2084
  backtest_start: 未披露
  backtest_end: 未披露
  benchmark: "沪深300"
logic:
  core_formula: "综合评分 = 0.4×趋势评分(年化×R²) + 0.2×价格反转 + 量比，选Top-1全仓"
  factors: [趋势×R², 价格反转, 成交量比率]
  params: {trend_w: 0.4, reversal_w: 0.2, rebalance: 25}
  risk_control: "多因子分散 + Top-1集中"
code:
  available: true
  language: python
  completeness: full
```
**黄灯原因**：年化26.22%（绿灯）、夏普1.13（绿灯）、回撤-20.84%（绿灯）、源码可用（平台源码），但**回测周期未披露**（需≥5年方可绿灯）；"趋势×R²"因子与 KB S4 部分重叠但叠加反转+量比构成三因子扩展。

### 3. 大类资产ETF轮动组合"重制版"（择时君，东方财富财富号）
```yaml
source:
  platform: other  # 东方财富财富号（研报型文章）
  url: "https://caifuhao.eastmoney.com/news/20260823153633069010210"
  author: "择时君"
  title: "大类资产ETF轮动组合'重制版'正式上线"
  clone_count: 0
strategy:
  name: "低相关5ETF动量+择时轮动"
  type: etf_rotation
  etf_pool: [510300, 513100, 518880, 159949, 588000]
  max_assets: 未披露（动量最强1只为主）
  rebalance: "约10天/两周一次"
metrics:
  annual_return: 0.3757
  sharpe: 1.21
  max_drawdown: -0.1834
  backtest_start: "2013-07-01"
  backtest_end: "2026-08-22"
  benchmark: "沪深300"
logic:
  core_formula: "5只低相关ETF（沪深300/纳指/黄金/创业板/科创板）动量轮动 + 择时信号，只做趋势行情"
  factors: [动量, 择时信号]
  params: {}
  risk_control: "低相关池分散 + 动量择时（右侧仓位）"
code:
  available: false
  language: other
  completeness: pseudocode
```
**黄灯原因**：指标极其优秀——年化37.57%（绿灯）、夏普1.21（绿灯）、回撤-18.34%（绿灯）、**13年长周期回测**（2013-2026，绿灯）且**已有实盘验证**（2026年5月起实盘收益13.75%，跑赢创指+25%，完全躲过7月大跌）。但**代码未披露**（财富号文章为研报型，无完整源码），需自建实现并验证。

### 4. PPO算法优化ETF动量轮动（CSDN / FreeRL_trader）
```yaml
source:
  platform: csdn
  url: "https://blog.csdn.net/weixin_56760882/article/details/159689283"
  author: "CSDN 博主 / wild-firefox (github.com/wild-firefox/FreeRL_trader)"
  title: "【量化RL】使用PPO来进行ETF动量轮动（v0.2）"
  clone_count: 0
strategy:
  name: "PPO强化学习ETF轮动"
  type: ai_ml
  etf_pool: [518880, 159915, 513500, 159985]
  max_assets: 1
  rebalance: daily
metrics:
  annual_return: 未披露
  sharpe: 2.41  # 改进后；改进前1.36
  max_drawdown: -0.1822
  backtest_start: "2020"  # 训练2020-2023/验证2023-2026/测试2026后
  backtest_end: "2026"
  benchmark: "沪深300"
logic:
  core_formula: "离散PPO强化学习：状态=多维市场特征（动量/波动率等），动作=8种预定义ETF组合（全仓创业板/黄金:创业板=1:3/...），奖励=当日收益率；离线训练+在线验证双环境"
  factors: [动量, 波动率, RL状态特征]
  params: {动作空间: 8, 训练/验证/测试划分: 2020-2023/2023-2026/2026后}
  risk_control: "RL动作空间约束 + 训练验证测试严格分离防数据窥探"
code:
  available: true
  language: python
  completeness: full
```
**黄灯原因**：夏普2.41 落在 2.0-3.5 黄灯区间；回撤-18.22% 绿灯；回测约6年（2020-2026）；代码完整开源（GitHub FreeRL_trader）。但**RL黑箱逻辑**（动作-状态映射不可直接解释）→ "逻辑可解释"维度黄灯；RL 模型与本项目纯规则回测框架兼容性待评估（需引入训练/推理流程）。

### 5. QMT T0策略（年化66%，回撤6%）
```yaml
source:
  platform: csdn
  url: "https://blog.csdn.net/qq_26742269/article/details/147364019"
  author: "CSDN 博主"
  title: "QMT深夜制作T0策略，年化66，回撤6"
  clone_count: 0
strategy:
  name: "ETF日内T0短波策略"
  type: mean_reversion
  etf_pool: [513100, 159915, 159937]
  max_assets: 未披露
  rebalance: intraday
metrics:
  annual_return: 0.66
  sharpe: 未披露
  max_drawdown: -0.06
  backtest_start: 未披露
  backtest_end: 未披露
  benchmark: 未披露
logic:
  core_formula: "一篮子ETF日内短波收益（T0），盘中高低点波段操作"
  factors: [日内短波]
  params: {}
  risk_control: "日内T0高频 + 一篮子分散"
code:
  available: true
  language: python
  completeness: full
```
**黄灯原因**：年化66% 落在 50%-100% 黄灯区间；回撤-6% 优秀（绿灯）；代码完整（QMT 环境）。但**T0日内策略依赖分钟级数据与高频执行**，与本项目日线回测框架不兼容（数据源仅 close/open/high/low/vol/amount/amp 日线），转化难度极高，需评估是否值得建立分钟数据基础设施。

### 6. 新浪财经 多资产ETF轮动策略（固收+视角）
```yaml
source:
  platform: other  # 新浪财经研报
  url: "https://finance.sina.com.cn/roll/2026-08-13/doc-inincnuy3417599.shtml"
  author: "新浪财经研报（机构）"
  title: "多资产ETF轮动策略：固收+视角下动态组合管理的构建与实践"
  clone_count: 0
strategy:
  name: "趋势质量+市场状态识别轮动"
  type: multi_factor
  etf_pool: []  # 权益/海外/黄金/债券/货币全类资产
  max_assets: 未披露
  rebalance: 未披露
metrics:
  annual_return: 0.2074
  sharpe: 未披露
  max_drawdown: -0.1013
  backtest_start: "2019-01"
  backtest_end: "2026-07"
  benchmark: "未披露"
logic:
  core_formula: "时间加权回归趋势得分（斜率×R²）+ 21/60日动量 + 市场状态识别（强势/震荡/危险三态）+ 反转信号（170日标准化偏离修复）"
  factors: [趋势质量×R², 动量, 市场状态, 反转]
  params: {regression_window: 未披露, momentum: [21, 60]}
  risk_control: "危险状态暂停风险资产 + 反转修复入场 + 状态自适应选券规则"
code:
  available: false
  language: other
  completeness: pseudocode
```
**黄灯原因**：年化20.74%（绿灯）、回撤-10.13%（绿灯）、回测7.5年（绿灯）、Calmar 2.05 优秀、逻辑非常清晰（趋势质量+市场状态自适应+反转）。但为**机构研报**，无源码（代码维度黄灯/未披露）；"市场状态识别（强势/震荡/危险）"是本项目 KB 尚无的新机制，有价值但需自研。

## 🔴 红灯候选

| 策略 | 来源 | 关键指标 | 红灯原因 |
|------|------|:---:|------|
| ETF双池动量轮动（静态+动态双池融合） | GitCode/CSDN stars580 | 年化453%，六年11倍 | 年化>100% 红灯；超高收益+双池动态扫全市场，明显过拟合/幸存者偏差嫌疑 |
| ETF轮动策略（基于五福改进） | 百果量化交流平台 (100apple.net id=837) | 区间80.30%，回测2025-04~2026-05 | 回测仅13个月<3年 红灯；样本不足，且年化约70%+落入黄灯区间 |
| 双阈动量ETF狙击策略 | BigQuant (square/40ab0b13) | 年化26.03%，累计29.31%（418天） | 回测仅418天<3年 红灯；样本不足 |

## 重复（跳过）

1. **次方量化博客 聚宽平台直接运行的ETF轮动**（blog.cifangquant.com/post/21.html）— 克隆自聚宽 post/42673（wywy1995 核心资产轮动），核心公式"年化收益×R²"与 **KB S4** 完全相同，7只ETF池 → **参数变体，NOT 新策略**。且该家族已多次命中（08-04/09-01/09-08 均记录）。
2. **核心资产轮动(带止损):用4只ETF把「动量」做成6倍收益**（财富号 2026-07-07）— 25日动量×R²，4只核心资产（518880/513100/159915/510180），与 **KB S4** 核心公式与资产池高度重叠，仅叠加止损 → **参数变体**（止损可作 S4 风控增强参考，不作为新策略）。
3. **CSDN《QMT量化实战系列》复现聚宽年化30%+ETF轮动策略**（blog.csdn.net/qq_46262068/149083100）— 25日动量×R²，4只ETF与 S4 相同池（518880/513100/159915/510180）→ **与 S4 完全重复**。

## 搜索执行日志

| 平台 | 状态 | 备注 |
|------|------|------|
| JoinQuant | ✅ 成功 | 命中 openhe EPO优化（绿灯）、开心果低相关轮动（黄灯）、二八轮动（经典无指标）等 |
| BigQuant | ✅ 成功 | 命中量价共振ETF轮动（黄灯）、双阈动量狙击（红灯，418天）、海龟ETF轮动（无指标）等 |
| GitHub | ✅ 成功 | 命中 FreeRL_trader（PPO RL）、sencloud/quant-strategies、yingxincui/streametf、PandOvo 等框架/策略 |
| 知乎 | ⚠️ 部分成功 | 命中多为教程/平台文档/重复内容（S4变体），无全新高价值策略 |
| CSDN | ✅ 成功 | 命中 PPO ETF轮动（黄灯）、QMT T0年化66%（黄灯）、ETF双池453%（红灯）等 |

> **工具备注**：本次 web_search 工具返回 "Insufficient Balance"（余额不足），改用项目内置 **byted-web-search**（火山引擎豆包搜索 API）完成全部 7 次平台搜索，全部成功且命中率高。未触发 A 股实际数据取数需求（本轮策略指标均为平台转录，无本地数据验证步骤）。

数据不足/参考（不评级，仅记录）：
- easyquant.ai 聚宽ETF动量轮动（均线+成交额+分钟趋势分批建仓）— 教程型，无回测指标
- JunQuant ETF动量策略 v5 — 产品化策略站点，回撤-22.06%（2020），年化/夏普未披露
- 二八轮动（JoinQuant post/45653，Gyron）— 经典大盘/小盘切换，无回测指标
- 海龟交易系统ETF轮动（BigQuant wiki）— 5%止损+20日低点+8%回撤止盈，无回测指标
- 科创50ETF择时（BigQuant）— 年化9.28%表现弱，单ETF
- GitHub sencloud/quant-strategies（ETF-Strategies）— Backtrader回测系统，双均线+市场情绪，框架类
- GitHub yingxincui/streametf — Streamlit ETF回测工具（动量/网格/定投），工具类
- GitHub PandOvo/quant-backtest-portfolio_akshare — 轻量回测框架，双均线30/50（24.82%/1.10/-38.10%）、趋势过滤动量（16.44%回撤-50.34%），学习模板非策略发布
- QSTrader / VeighNa 框架 — 通用回测框架，工程参考
- 21天搭建ETF量化交易系统 Day19（jishuzhan）— 动量轮动Backtrader+Dash，教程
- 掘金/CSDN ETF轮动入门教程（60日动量+空仓阈值）— 入门向
- CSDN 散户量化实战——动量因子（wuji2mol）— 上证50/创业板/国债22日动量，无明确年化
- B站 PTrade ETF轮动策略回测版 — 动量评分Top-1，无回测指标

## 2025-2026 策略趋势观察（延续 08-04/09-01/09-08）

1. **权重优化成为新热点（EPO）** — 本次唯一绿灯策略即"动量×R² + EPO权重优化"，从"选标的"升级到"优化仓位"，呼应 09-08 发现的 EPO 候选。相关性收缩+逆方差锚定是 KB 尚无的权重层方法。
2. **机构研报/财富号加入策略披露** — 新浪固收+多资产（Calmar 2.05）、择时君大类资产（13年回测+实盘）来自研报/财富号而非量化社区，显示策略披露渠道多元化。
3. **RL强化学习策略持续出现** — PPO ETF轮动（夏普2.41）连续两周命中，但黑箱+框架兼容问题是转化门槛。
4. **长周期+实盘验证成为可信度分水岭** — 择时君13年回测+实盘验证（跑赢+25%、躲过7月大跌）显著增强可信度；而453%年化（GitCode）、13个月回测（百果）被直接红灯，行业分化加剧。
5. **T0日内策略开始冒头** — QMT T0年化66%回撤6%虽诱人，但需要分钟级数据基础设施，与本项目日线框架存在结构性差距，短期内难以转化。

## 下一步建议

1. **🟢 绿灯转化**：多品种ETF动量轮动+EPO优化 — 需要**非模板化**开发（EPO权重优化层，KB无先例），已创建 **REQ-003** 进入开发流程（见 steering/open/REQ-003.md）。
2. **🟡 队列观察**：6个黄灯候选已加入 candidate_queue.json，其中"大类资产ETF轮动（择时君）"与"新浪固收+多资产"指标优秀但缺代码，建议优先补源码/自建实现验证；开心果低相关轮动需先修未来函数。
3. **重复家族持续警戒**：年化×R²核心资产轮动家族（S4变体）连续多周高频命中，后续直接跳过不再评估。
