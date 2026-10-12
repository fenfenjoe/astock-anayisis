# 策略扫描报告 — 2026-09-22

> 数据时点：2026-09-22 12:41（定时任务窗口，周二 12:37；本周实际于 12:41 手动触发执行）
> 数据来源：WebSearch 各平台搜索快照（JoinQuant/BigQuant/GitHub/知乎/CSDN）——web_search 工具余额仍不足（Insufficient Balance），沿用上轮先例改用**火山引擎豆包搜索 API**（byted-web-search）完成全部 7+2 次平台搜索
> 说明：平台回测指标直接转录自原文/摘要；未披露字段如实标注，不估算填充。标注"估算"的为折算值。

## 摘要
- 搜索平台: 5（聚宽/BigQuant/GitHub/知乎/CSDN）
- 发现候选: 11
- 🟢 绿灯（可转化）: 0
- 🟡 黄灯（队列）: 6
- 🔴 红灯（跳过）: 5
- 重复（跳过）: 5
- 数据不足/参考: 12（不计入候选，见搜索执行日志）

> 本轮无新增绿灯：上轮绿灯候选「多品种ETF动量轮动+EPO优化（openhe）」对应 **REQ-003 仍为 OPEN 状态（未实施）**，建议优先推进 REQ-003 实施，本轮 6 个黄灯候选入队观察。

## 🟢 绿灯候选

（本轮无新增绿灯）

## 🟡 黄灯候选

### 1. 趋势增强因子ETF策略（BigQuant AI量化）
```yaml
source:
  platform: bigquant
  url: "https://bigquant.com/square/ai/926df6df-eb57-0354-80bd-967dd101159e"
  author: "BigQuant AI策略广场（更新2026-08-25）"
  title: "趋势增强因子ETF策略（年化收益率36.97%）"
  clone_count: 0
strategy:
  name: "岭回归趋势增强+止盈轮动"
  type: etf_rotation
  etf_pool: [518880, 512100, 513500, 513060, 513030, 159321, 517520, 159628]  # 20只指定ETF（黄金/1000/标普/恒生医疗/德国等，部分示例）
  max_assets: 3
  rebalance: daily
metrics:
  annual_return: 0.3734
  sharpe: 1.23
  max_drawdown: -0.2057
  backtest_start: "2021-01-04"
  backtest_end: "2026-08-31"
  benchmark: "沪深300"
logic:
  core_formula: "25天趋势增强评分=岭回归（线性时间项+二次项+三角函数表征趋势强度与波动），21日涨跌幅(roc_21)>25%触发止盈清仓，每日从剩余标的中选评分Top-3"
  factors: [岭回归趋势增强, 21日止盈, 三角函数波动项]
  params: {lookback: 25, top_n: 3, take_profit: 0.25, ridge_features: [linear, quadratic, trig]}
  risk_control: "21日涨幅>25%止盈清仓 + 每日调仓"
code:
  available: true
  language: python
  completeness: full
```
**黄灯原因**：年化37.34%（绿灯）、夏普1.23（绿灯）、回撤-20.57%（绿灯）、**回测5.7年（2021-01~2026-08，≥5年绿灯）**、源码可用（BigQuant 源码）。但**岭回归特征工程（线性+二次+三角函数）逻辑可解释性中等**（黄灯），参数约4-5个（lookback/top_n/止盈/岭回归特征集）处于绿灯-黄灯边界；且与 KB S4 的"25日×R²"趋势评分家族部分同源（趋势质量加权思想），但叠加岭回归趋势增强构成差异化扩展。

### 2. ETF滚动择时优化策略（BigQuant 量化交易）
```yaml
source:
  platform: bigquant
  url: "https://bigquant.com/wiki/doc/ySSnil1iwd"
  author: "xiaoshao / qxiao（BigQuant Wiki）"
  title: "ETF滚动择时优化策略"
  clone_count: 0
strategy:
  name: "趋势评分+均值方差优化轮动"
  type: etf_rotation
  etf_pool: []  # 11只不同大类资产ETF（原油/黄金/纳指/A股宽基/可转债等）
  max_assets: 6
  rebalance: "每5交易日"
metrics:
  annual_return: 0.2715
  sharpe: 1.41
  max_drawdown: -0.11
  backtest_start: "2021-01"
  backtest_end: "2025-10"
  benchmark: "沪深300"
logic:
  core_formula: "综合得分=25日线性回归斜率（年化收益）×R² 趋势评分 + 5日/10日均线比值(ma_ratio_5_10)；每5交易日选综合评分Top-6；20日涨幅>16%触发止盈剔除；权重=均值-方差优化（120日历史收益率，单票权重5%-30%约束，风险厌恶系数），优化失败回退等权"
  factors: [趋势×R², 均线比值, 均值方差优化]
  params: {lookback: 25, ma_ratio: [5, 10], top_n: 6, take_profit: 0.16, mvo_lookback: 120, weight_bounds: [0.05, 0.30]}
  risk_control: "16%止盈剔除 + 均值方差优化 + 5%-30%权重约束 + 等权回退"
code:
  available: true
  language: python
  completeness: full
```
**黄灯原因**：年化27.15%（绿灯）、夏普1.41（绿灯）、回撤-11%（绿灯）、源码可用（BigQuant codeshare）。但**回测周期约4.75年（2021初~2025-10，3-5年黄灯）**、**参数约6-8个（黄灯）**。"25日×R²"趋势评分与 KB S4 / REQ-003（EPO）家族部分重叠，但叠加**经典均值-方差优化**（非EPO收缩法）构成权重层差异化；120日协方差矩阵需要本框架支持协方差计算（当前数据源支持 close/high/low/vol/amount，可计算收益率协方差）。

### 3. JunQuant ETF动量策略 v5.3.2.11（JunQuant 量化研究平台）
```yaml
source:
  platform: other  # JunQuant 产品化策略站
  url: "https://junquant.com/"
  author: "JunQuant（产品化策略，运行中）"
  title: "ETF动量策略（v5.3.2.11，10年回测）"
  clone_count: 0
strategy:
  name: "全市场ETF动量轮动+单仓集中"
  type: etf_rotation
  etf_pool: []  # 全市场ETF扫描
  max_assets: 1
  rebalance: "T日信号/T+1执行"
metrics:
  annual_return: 0.4165
  sharpe: 1.468
  max_drawdown: -0.2206
  backtest_start: "2016-01-04"
  backtest_end: "2025-12-31"
  benchmark: "沪深300"
logic:
  core_formula: "全市场ETF动量轮动+单仓集中持有；T日收盘算信号、T+1开盘执行；10年无负收益年份（2016-2025逐年+17.67%~+100.06%）"
  factors: [全市场动量]
  params: {}  # 具体公式未披露
  risk_control: "单仓集中 + T+1执行 + 全市场扫描"
code:
  available: false
  language: other
  completeness: pseudocode
```
**黄灯原因**：指标极优秀——年化41.65%（绿灯）、夏普1.468（绿灯）、回撤-22.06%（绿灯）、**完整10年回测（2016-2025，绿灯）且10年无负收益年份**、超额+2278% vs 沪深300。但**代码未披露**（产品化策略站，仅展示绩效与信号推送）、**核心公式未披露**（逻辑维度黄灯）。上轮（09-15）记为"数据不足/参考（年化/夏普未披露）"，本轮搜索到完整指标 → **升级为黄灯候选**。

### 4. 扩散指标+RRG行业轮动策略（西部证券研究）
```yaml
source:
  platform: other  # 券商研报（西部证券 2026-05）
  url: "https://www.baogaobox.com/insights/260527000027745.html"
  author: "西部证券研发中心"
  title: "指数化配置系列研究（6）：相对旋转图（RRG）行业轮动策略"
  clone_count: 0
strategy:
  name: "扩散指标+RRG行业轮动映射ETF"
  type: industry_rotation
  etf_pool: []  # 中信一级行业映射到行业主题ETF
  max_assets: 6
  rebalance: monthly
metrics:
  annual_return: 0.206
  sharpe: 0.79
  max_drawdown: -0.2982
  backtest_start: "2018-12-28"
  backtest_end: "2026-03-31"
  benchmark: "中信一级行业等权 / 沪深300"
logic:
  core_formula: "每月末选自由流通市值加权扩散指标最高的6个中信一级行业等权配置，再剔除RRG中处于第三、四象限的行业；通过行业暴露打分将行业轮动信号映射到行业主题ETF"
  factors: [扩散指标, RRG相对旋转图, 行业暴露打分]
  params: {top_n: 6, rrq_quadrant_filter: [3, 4]}
  risk_control: "RRG象限过滤（剔除动能走弱行业）+ 行业分散（6行业）"
code:
  available: false
  language: other
  completeness: pseudocode
```
**黄灯原因**：年化20.60%（绿灯）、回撤-29.82%（绿灯，压-30%线）、**回测7.3年（2018-12~2026-03，绿灯）**、逻辑非常清晰（扩散指标+RRG相对旋转图，**KB 尚无 RRG 机制**）、各年度均正超额（2019/2020/2021/2025 分别 +45.63%/+43.21%/+18.76%/+28.24%）。但**夏普0.79 略低于 0.8 绿灯线（黄灯）**、**机构研报无源码（代码黄灯）**；行业映射到ETF的"行业暴露打分"方法需自研实现，且当前框架以宽基/资产类ETF为主，行业ETF池需扩展数据。

### 5. Ptrade ETF组合轮动策略（MACD+年度收益+五档仓位）
```yaml
source:
  platform: other  # 搜狐 Ptrade 量化教程
  url: "https://m.sohu.com/a/1003998400_121751103/"
  author: "两融小顾问（Ptrade 教程）"
  title: "Ptrade量化交易教程：ETF组合轮动策略"
  clone_count: 0
strategy:
  name: "MACD多因子+五档仓位管理轮动"
  type: multi_factor
  etf_pool: []  # 股票型ETF（创业板/纳指等）+ 黄金ETF + 国债ETF + 货币ETF
  max_assets: 5
  rebalance: monthly
metrics:
  annual_return: null  # 未披露具体数值
  sharpe: null
  max_drawdown: -0.0984  # 2022年最大回撤9.84%（单年披露）
  backtest_start: "2020-01-01"
  backtest_end: "2025-09-30"
  benchmark: "未披露"
logic:
  core_formula: "多因子决策：MACD（macd_macd_300等指数MACD判断趋势）+年度收益过滤；五档仓位分配（前2档各12.5%进攻=股票ETF，后3档各25%防御=黄金/国债/货币ETF）；红利ETF年度收益<-6%切换国债ETF；每年首日全面再平衡"
  factors: [MACD, 年度收益, 五档仓位]
  params: {position_tiers: [0.125, 0.125, 0.25, 0.25, 0.25], macd_period: 26-12-9, risk_switch: -0.06}
  risk_control: "五档仓位攻守兼备 + 红利ETF年度收益<-6%切国债 + 月度调仓+年度再平衡"
code:
  available: true
  language: python
  completeness: partial
```
**黄灯原因**：回测5.75年（2020-01~2025-09，绿灯）、逻辑非常清晰（MACD趋势+五档仓位管理，**五档动态仓位分配是 KB 尚无的机制**）、2022年熊市最大回撤仅-9.84%（优秀）。但**年化/夏普/整体回撤未披露具体数值（黄灯）**、教程型代码部分披露（代码黄灯）。

### 6. 雪球 ETF动量策略（年化63.87%，含溢价率过滤）
```yaml
source:
  platform: zhihu  # 雪球专栏转载（Zorya-Penta）
  url: "https://xueqiu.com/3057591219/381811152"
  author: "Zorya-Penta（雪球）"
  title: "年化63.87% ETF动量策略"
  clone_count: 0
strategy:
  name: "20日动量+乖离率+溢价率过滤轮动"
  type: etf_rotation
  etf_pool: []  # 基金池（图示，未完全披露）
  max_assets: 未披露
  rebalance: 未披露
metrics:
  annual_return: 0.6387
  sharpe: null
  max_drawdown: -0.2663
  backtest_start: "2021"
  backtest_end: "2026-03"
  benchmark: "未披露"
logic:
  core_formula: "筛选条件：5日乖离率<5% + 溢价率<5% + 20日涨幅>0，按20日涨幅排名轮动；5%收益率止盈，卖出1天内不买回"
  factors: [20日动量, 5日乖离率, 溢价率过滤, 止盈]
  params: {bias_5d: 0.05, premium: 0.05, momentum_20d: 0, take_profit: 0.05, cooldown: 1}
  risk_control: "溢价率<5%过滤（QDII溢价控制）+ 5%止盈 + 卖出1日冷却"
code:
  available: false
  language: other
  completeness: pseudocode
```
**黄灯原因**：年化63.87% 落在 50%-100% 黄灯区间；回撤-26.63% 绿灯；回测约5年（2021至今，接近绿灯线）。**溢价率<5%过滤（针对QDII/跨境ETF溢价控制）与5%止盈+卖出冷却是 KB 尚无的新机制**，20日涨幅轮动与 S4 动量家族部分重叠但叠加乖离率/溢价率过滤构成差异化。但**夏普未披露、代码未披露（黄灯）**。

## 🔴 红灯候选

| 策略 | 来源 | 关键指标 | 红灯原因 |
|------|------|:---:|------|
| 大类资产ETF轮动复合排序策略 | BigQuant square/c4c7a45c | 年化35.13%，回撤**-37.76%**，夏普0.83 | 回测仅**423天**<3年 红灯；最大回撤-37.76%>30% 红灯；双红灯 |
| 基于CatBoost模型ETF选基策略 | BigQuant square/a212fc01 | 年化74.53%~83.68%，夏普1.70，回撤-18.27% | 回测仅**2025-01~2026-09（约1.7年）**<3年 红灯；ML黑箱（CatBoost二分类不可解释） |
| 五福ETF动量-多空组合 v5.0 | JoinQuant post/71294（商界观察ETF） | 年化75.07%，回撤-25.86%，夏普1.69 | 参数>8（MOMENTUM_WINDOW/R2_THRESHOLD/SWITCH_BUFFER/GAUSSIAN_SIGMA/EWM_SPAN/RSRS_WINDOW/RSRS_NORM_WINDOW/RSRS_BUY/SELL）红灯；**多空组合需做空基础设施**（A股ETF无法直接做空）与本项目纯多头日线框架不兼容；RSRS因子与KB S17重叠 |
| ETF轮动策略（基于五福改进 V6.4） | 百果量化交流平台 (100apple.net id=837) | 区间80.30%，回测2025-04~2026-05 | 回测仅**13.5个月**<3年 红灯（09-15 已记录红灯，本次再次命中确认）；分钟级止损监控与日线框架不兼容 |
| 基于高频动量突破的ETF择时策略 | BigQuant wiki/GdhZMb5NuJ | 指标未披露，评论称"换一段时间回测持续亏损" | 分钟级高频动量突破（依赖分钟数据，日线框架不兼容）红灯；策略不稳定（跨时段持续亏损） |

## 重复（跳过）

1. **核心资产轮动(带止损):用4只ETF把「动量」做成6倍收益**（财富号 2026-07-07）— 25日动量×R²，4只核心资产（518880/513100/159915/510180），与 **KB S4** 核心公式与资产池高度重叠 → **参数变体**（09-15 已记录重复，本次再次命中确认）。
2. **次方量化 聚宽平台直接运行的ETF轮动**（blog.cifangquant.com/post/21.html）— 克隆自 joinquant post/42673（wywy1995 核心资产轮动），25日动量×R²，7只ETF池 → **与 KB S4 完全重复**（09-15 已记录重复，本次再次命中确认）。
3. **核心资产轮动-每日盘前交易预测**（JoinQuant post/50158，openresearch）— wywy1995 核心资产轮动家族，25日动量×R²，4只ETF（518880/513100/159915/510300），仅改交易时间/费率 → **S4 参数变体，NOT 新策略**。
4. **BigQuant 趋势稳健性动量ETF组合策略**（wiki/BK7xBd9oPp，sywgfuture01）— 年化17.77%/夏普1.06/回撤-17.54%/7.5年回测，但**核心公式即"年化×R²"（25天滚动窗口），ETF池为黄金/纳指/沪深300/创业板4只（与S4池3/4重叠）** → **与 KB S4 参数变体**（仅 Top-2 vs S4 Top-1 与调仓频率差异），NOT 新策略。
5. **多品种ETF动量轮动+EPO优化（openhe）** — 上轮绿灯候选，已创建 **REQ-003**（OPEN，未实施），本次为同一策略（聚宽原帖/QMT复现）再次命中 → **已入库，不重复评估**。

## 搜索执行日志

| 平台 | 状态 | 备注 |
|------|------|------|
| JoinQuant | ✅ 成功 | 命中 openhe EPO（REQ-003，已知）、核心资产轮动家族（重复）、五福多空（红灯，参数>8）、帮忙写个ETF轮动（行业ETF+涨幅区间，无指标）等 |
| BigQuant | ✅ 成功 | 命中趋势增强因子（黄灯）、ETF滚动择时优化（黄灯）、趋势稳健性动量（S4重复）、CatBoost（红灯1.7年）、大类资产复合排序（红灯423天+回撤37.76%）、高频动量突破（红灯分钟级）等 |
| GitHub | ✅ 成功 | 命中 jcback（回测框架）、FinLab/TuringTrader（美股不适用）、RRG行业轮动研报（黄灯）等；框架/工具类为主 |
| 知乎 | ⚠️ 部分成功 | 命中雪球63.87%策略（黄灯，溢价率过滤）、Ptrade五档仓位教程（黄灯）、ETFQuest工具等；多为教程/工具/重复内容 |
| CSDN | ⚠️ 部分成功 | 命中 A股实测回测工具包（工具类）、五福改进V6.4（红灯13.5个月）等；多为工程教程 |

> **工具备注**：本次 web_search 工具继续返回 "Insufficient Balance"（余额不足），沿用 09-15 先例改用 **byted-web-search**（火山引擎豆包搜索 API）完成全部 7 次平台搜索 + 2 次补充确认搜索，全部成功且命中率高。未触发 A 股实际数据取数需求（本轮策略指标均为平台转录，无本地数据验证步骤）。

数据不足/参考（不评级，仅记录）：
- 腾讯云 60日动量ETF轮动入门（教程，无指标）
- ETF 二八轮动复现（BigQuant wiki，3只ETF 20日涨幅，5年回测但年化未披露）— 经典二八轮动变体，参考
- ETFQuest 量化回测系统（产品工具，轮动策略 47.1%/回撤-31.7% 或 18.5%/-28.6%，非开源）
- jcback 0.2.1（PyPI，A股/ETF/债券/期货事件驱动回测框架）— 工程参考
- QuantStart Momentum TAA / backtrader / BT Package（框架教程，美股）
- FinLab ETF Rotation（美股 QQQ 200日均线+126日动量，30.5% CAGR/-17.9% DD）— 美股不直接适用，可作避险逻辑参考
- TuringTrader ETF-Rotation Report（美股多周期动量 19.79% CAGR）— 美股，参考
- SuperMind 多指数轮动教程 / 二八轮动（同花顺，9指数20日涨幅，无指标）
- JoinQuant post/47077 帮忙写个ETF轮动（12只行业ETF+5/20均线过滤+涨幅5%-20%区间，无回测指标）
- 21天搭建ETF量化交易系统 Day19（Backtrader+Dash 工程教程）
- CSDN A股实测可用Python量化回测工具包（6只ETF轮动+量价双金叉，课程设计向，无回测指标）
- BigQuant《基于动量与风险优化双重视角的ETF行业轮动策略研究》（PDF，夏普0.567 弱，协方差收缩与 REQ-003 EPO 家族同源，参考）

## 2025-2026 策略趋势观察（延续 08-04/09-01/09-08/09-15）

1. **权重/组合优化成为主流方向** — 本轮 2 个黄灯候选（ETF滚动择时=MVO均值方差、趋势增强因子）与 REQ-003（EPO）均属"动量选标的 + 组合优化定权重"框架，从"选什么"深化到"买多少"，权重优化已是聚宽/BigQuant 双平台共识方向。
2. **产品化策略站绩效披露更完整** — JunQuant 完整披露 10 年逐年收益（无负收益年份）、超额、索提诺/信息比率，可信度高于社区回测；但代码封闭仍是转化壁垒。
3. **机构研报持续产出可转化机制** — 西部证券 RRG（扩散指标+相对旋转图）是本轮最有价值的"新机制"，KB 无 RRG 先例，行业映射到 ETF 的落地路径清晰。
4. **风控差异化成为黄灯候选分水岭** — 雪球 63.87% 靠"溢价率过滤+止盈冷却"、Ptrade 靠"五档仓位攻守"、滚动择时靠"16%止盈+权重约束"，单纯动量已无新意，叠加风控机制才有入队资格。
5. **红灯原因高度集中** — 5 个红灯中 3 个因回测周期<3年（423天/1.7年/13.5个月）、2 个因数据/做空基础设施不兼容（分钟级/多空），印证"长周期+可执行"仍是硬门槛。

## 下一步建议

1. **优先推进 REQ-003 实施**（OPEN 状态）：多品种ETF动量轮动+EPO优化仍为本项目唯一绿灯候选，涉及非模板化 EPO 权重优化层，建议本周内进入 dev-workflow 流程。
2. **🟡 队列观察**：6 个黄灯候选已加入 candidate_queue.json。优先关注：
   - **JunQuant 全市场动量**（10年无负收益年份，指标最硬）→ 需联系/挖掘其核心公式；
   - **RRG 行业轮动**（KB 新机制，机构验证 7.3 年）→ 行业ETF数据扩展后可自研实现；
   - **ETF滚动择时优化**（MVO 权重层与 EPO 互补，源码可用）→ 若 REQ-003 落地后可复用协方差计算基础设施。
3. **重复家族持续警戒**：年化×R²核心资产轮动家族（S4变体）连续多周高频命中（本周4处），后续直接跳过不再评估。
4. **候选队列升降级**：本轮无黄灯升级绿灯、无黄灯降级红灯；09-01/09-08/09-15 候选均保持黄灯。
