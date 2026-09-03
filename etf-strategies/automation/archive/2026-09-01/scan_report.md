# 策略扫描报告 — 2026-09-01

> 数据时点：2026-09-01 12:37（定时任务窗口，周二 12:37）
> 数据来源：WebSearch 各平台搜索快照（JoinQuant/BigQuant/GitHub/知乎/CSDN）
> 说明：平台回测指标直接转录自原文/摘要；未披露字段如实标注，不估算填充。标注"估算"的为折算值。

## 摘要
- 搜索平台: 5（聚宽/BigQuant/GitHub/知乎/CSDN）
- 发现候选: 9
- 🟢 绿灯（可转化）: 0
- 🟡 黄灯（队列）: 5
- 🔴 红灯（跳过）: 4
- 重复（跳过）: 5
- 数据不足/参考: 11（不计入候选，见搜索执行日志）

## 🟢 绿灯候选

（无 — 本次未发现满足全部绿灯维度的候选）

## 🟡 黄灯候选

### 1. PT 59% ETF动量轮动策略
```yaml
source:
  platform: joinquant
  url: "https://joinquant.com/community/post/detailMobile?postId=5d2a8544ca2ecaa412964bab37458c5b"
  author: "PT"
  title: "PT 59% ETF动量轮动策略"
  clone_count: 未披露
strategy:
  name: "ETF动量轮动(58%)"
  type: etf_rotation
  etf_pool: []  # 未披露
  max_assets: 1  # 推测，未披露
  rebalance: 未披露
metrics:
  annual_return: 0.58  # 标题转录
  sharpe: 未披露
  max_drawdown: 未披露
  backtest_start: 未披露
  backtest_end: 未披露
  benchmark: 未披露
logic:
  core_formula: "ETF动量打分轮动（具体公式未披露，疑似年化收益xR^2类）"
  factors: [动量]
  params: {}
  risk_control: "未披露"
code:
  available: true
  language: python
  completeness: partial
```
**黄灯原因**：年化 58% 落在 50%-100% 黄灯区间；夏普/回撤/回测周期均未披露，无法确认其余维度。

### 2. 年化54.2%，夏普1.97的策略诞生记
```yaml
source:
  platform: zhihu
  url: "https://zhuanlan.zhihu.com/p/668359228"
  author: "未披露（知乎专栏）"
  title: "年化54.2%，夏普1.97的策略诞生记"
  clone_count: 0
strategy:
  name: "动量轮动(54.2%)"
  type: momentum
  etf_pool: []  # 未披露
  max_assets: 未披露
  rebalance: 未披露
metrics:
  annual_return: 0.542
  sharpe: 1.97
  max_drawdown: 未披露
  backtest_start: 未披露
  backtest_end: 未披露
  benchmark: 未披露
logic:
  core_formula: "未披露（策略诞生记录，疑似ETF动量轮动）"
  factors: []
  params: {}
  risk_control: "未披露"
code:
  available: false
  language: other
  completeness: pseudocode
```
**黄灯原因**：年化 54.2% 落在 50%-100% 黄灯区间（夏普 1.97 在绿灯上限边缘）；策略细节/代码未披露。

### 3. 复现聚宽策略，年化31%，夏普1.22，附代码
```yaml
source:
  platform: csdn
  url: "https://quant.csdn.net/6874aa31bb9d8e0ecec22b4c.html"
  author: "未披露（CSDN转载/复现）"
  title: "复现一个聚宽策略，年化31%，夏普比1.22，附代码"
  clone_count: 0
strategy:
  name: "聚宽动量策略复现(31%)"
  type: momentum
  etf_pool: []  # 未披露
  max_assets: 未披露
  rebalance: 未披露
metrics:
  annual_return: 0.31
  sharpe: 1.22
  max_drawdown: 未披露
  backtest_start: 未披露
  backtest_end: 未披露
  benchmark: "沪深300（推测）"
logic:
  core_formula: "未披露（复现自聚宽，年化31%/夏普1.22）"
  factors: []
  params: {}
  risk_control: "未披露"
code:
  available: true
  language: python
  completeness: full
```
**黄灯原因**：年化/夏普在绿灯区间且附完整代码，但**回测周期未披露**（需≥5年方可绿灯）、回撤未披露。

### 4. Risk Parity + Momentum ETF（Schwoerer RPM 变体）
```yaml
source:
  platform: github
  url: "https://github.com/huyukun662-crypto/RiskParity-Momentum-ETF"
  author: "huyukun662-crypto"
  title: "RiskParity-Momentum-ETF（v5e_capped，WF锁定版）"
  clone_count: 0
strategy:
  name: "风险平价+动量(RPM)"
  type: risk_parity
  etf_pool: []  # 未披露具体A股ETF
  max_assets: 未披露
  rebalance: 未披露（RPM经典为年度/季度）
metrics:
  annual_return: 未披露
  sharpe: 未披露
  max_drawdown: 未披露
  backtest_start: 未披露
  backtest_end: 未披露
  benchmark: 未披露
logic:
  core_formula: "风险平价权重分配 x 时间序列动量（RPM，Martin Schwoerer 经典框架），杠杆设上限(capped)。文档含walk-forward锁定版。"
  factors: [风险平价, 时间序列动量]
  params: {leverage_cap: 未披露}
  risk_control: "杠杆上限 + 风险平价天然分散"
code:
  available: true
  language: python
  completeness: full
```
**黄灯原因**：**风险平价类型为 KB 缺失类别**（现有仅目标波动率 S7），逻辑经典清晰、源码完整，但 A 股回测指标未披露，需补跑验证。

### 5. A股ETF定投量化策略（S3分数分档+溢价闸门）
```yaml
source:
  platform: github
  url: "https://github.com/NextRemeber/etf-dca-strategy"
  author: "NextRemeber"
  title: "A股ETF定投量化策略：4支组合+S3分数分档+再平衡轮动+溢价闸门，25轮双周期验证，Calmar 1.78→2.55"
  clone_count: 0
strategy:
  name: "定投+轮动+溢价闸门"
  type: etf_rotation
  etf_pool: []  # 4支组合，未披露代码
  max_assets: 4
  rebalance: 未披露（定投+再平衡轮动）
metrics:
  annual_return: 未披露
  sharpe: 未披露
  max_drawdown: 未披露
  calmar: 1.78~2.55  # 原文指标（25轮双周期验证）
  backtest_start: 未披露
  backtest_end: 未披露
  benchmark: 未披露
logic:
  core_formula: "4支ETF组合定投 + S3分数分档 + 再平衡轮动 + 溢价闸门（溢价过高时暂停买入）"
  factors: [S3分数, 溢价率]
  params: {组合数: 4}
  risk_control: "溢价闸门（防止追高溢价ETF）+ 定投摊平"
code:
  available: true
  language: python
  completeness: full
```
**黄灯原因**：Calmar 1.78→2.55 优秀且经 25 轮双周期验证，**溢价闸门与 2026-08-04 扫描趋势观察一致**；但年化/回撤/夏普未披露，且为定投类（与现有轮动框架形态不同），需评估转化路径。

## 🔴 红灯候选

| 策略 | 来源 | 年化 | 红灯原因 |
|------|------|:---:|------|
| 年化108%最大回撤10% ETF动量轮动RSRS择时（续）| 聚宽 @秋天来了 | 108% | 年化>100% 红灯；且与 KB S18（RSRS+动量）核心逻辑重叠 |
| 五福52V2-多ETF（2020至今收益34倍回撤16%）审查报告 | 知乎 | ≈72%（估算）| **第三方审查揭示回测失真、实盘跟单巨亏**，回测可信度红灯 |
| 基于场内ETF预期年化8%的低风险配置策略 | B站 | 8% | 年化<15% 绿灯下限，收益不达标 |
| ETF多因子动量轮动策略 | BigQuant | 0%（疑似页面标题显示异常）| 转录指标年化0%<15%；数据存疑 |

## 重复（跳过）

1. **双动量ETF轮动年化83%**（聚宽 @空空儿）— 2026-08-04 已发现并列为黄灯，历史候选复现，非新策略。
2. **大盘ETF动量轮动RSRS择时策略分析**（聚宽）— 与 KB S18 核心公式重叠（RSRS Beta 过滤 + 动量打分），视为重复。
3. **十年收益率867.83%核心资产轮动策略**（聚宽 @知知）— 年化≈32%（10年867.83%折算，**估算**）；核心资产池+动量轮动疑似与 KB S19（低相关ETF动量轮动）同源变体，**标注人工复核**后再定去留。
4. **简单却有效的ETF均线择时策略**（BigQuant）— 与 KB S3（均线趋势）逻辑重叠。
5. **dao-quant-research 量价引擎行业轮动 M03**（GitHub）— 2026-08-04 已发现绿灯候选（均线能量+过滤），至今未转化，历史复现。

## 搜索执行日志

| 平台 | 状态 | 备注 |
|------|------|------|
| JoinQuant | ✅ 成功 | 命中动量轮动/RSRS/核心资产/定投轮动等多帖 |
| BigQuant | ✅ 成功 | 命中均线择时/动量突破/多因子，具体指标披露少 |
| GitHub | ✅ 成功 | 命中生产级平台（zhangsensen）、RPM、定投轮动、研究仓库等 |
| 知乎 | ✅ 成功 | 命中54.2%策略、五福52审查报告（警示）|
| CSDN | ✅ 成功 | 命中31%/1.22复现（附代码）、回测实战包（教程）|

数据不足/参考（不评级，仅记录）：
- 聚宽 @youngyunxing「ETF轮动止损版V1.0」— 指标未披露
- 聚宽 @JMoock「四个大市值策略组合」— 指标未披露
- BigQuant「高频动量突破ETF择时」— 指标未披露，疑似高频（与日线框架不符）
- GitHub zhangsensen/etf-rotation-strategy — 生产级平台（WFO/VEC/BT 三层验证引擎），无单策略指标，**工程参考价值高**
- GitHub XiyiRao/a-share-quant-research — 研究仓库（HMM状态过滤+行业轮动+LightGBM），参考价值
- GitHub zhuleimed/etf-daily-sync-and-backtest / Robot-Dog/ETF-Strategies / kavanaghpatrick/etf-research-platform — 纯回测框架
- GitHub codemvper/dajitui_etf — ETF网格交易助手（网格类，与轮动框架不兼容）
- CSDN 回测实战包 / AI编程社区教程 — 教学类

## 2025-2026 策略趋势观察（延续 08-04）

1. **溢价闸门成为新常态** — 本次 etf-dca-strategy 再现金溢价风控（溢价过高暂停买入），呼应 08-04 趋势①
2. **风险平价+动量组合**（RPM）— KB 尚无风险平价类策略，值得试点
3. **三层验证引擎**（WFO→VEC→BT）— 生产级平台工程思路，可用于本项目回测框架防过拟合
4. **回测失真警示案例增多** — 五福52 类"回测34倍/实盘亏损"案例，转化前必须独立复测
