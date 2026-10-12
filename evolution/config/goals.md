# 进化目标定义（goals.md）

> 本文件是自进化框架**可定制层**的入口：用户维护目标/指标/验证器/方向/边界/节奏，
> 通用进化引擎（gap_analysis 等）据此自动运转。
> 实例化自 `goals.example.md`（2026-09-24），基线依据 P0a/P0b 真实数据。

---

## 机器结算定义（gap_analysis 读取，勿删）

> ⚠️ 下方 ```json 块是 gap_analysis 的**唯一机器输入**；修改指标必须同步更新此块与下方文字说明。
> `source`: signal_quality（读 signal_quality_history.json）/ report_quality（读 report_quality_history.json）
> `field`: 快照内点路径（signal: overall.target_hit_rate / dimensions.priority.P1.trigger_rate；report: avg_total 或单维键）
> `direction`: higher=越高越好；lower=越低越好

```json
{
  "metrics": [
    {"id": "G-A", "name": "信号T+3命中率", "source": "signal_quality",
     "field": "dims.overall.target_hit_rate", "target": 45.0, "weight": 30,
     "direction": "higher", "recent_weeks": 4},
    {"id": "G-A2", "name": "P0信号执行数", "source": "signal_quality",
     "field": "dims.dimensions.priority.P0.n_executed", "target": 3.0, "weight": 25,
     "direction": "higher", "recent_weeks": 4},
    {"id": "G-A3", "name": "早盘信号触发率", "source": "signal_quality",
     "field": "dims.dimensions.source.morning_analysis.trigger_rate", "target": 40.0,
     "weight": 20, "direction": "higher", "recent_weeks": 4},
    {"id": "G-B", "name": "报告质量总分", "source": "report_quality",
     "field": "avg_total", "target": 16.0, "weight": 25,
     "direction": "higher", "recent_weeks": 4}
  ]
}
```

---

## 愿景（Vision）

> 一句话：这个 Agent 最终要成为什么。

```
让 A 股投研 Agent 成为"能持续自我进化的私人投研合伙人"：
预测越来越准、报告越来越可靠、经验越攒越值钱、错误越犯越少。
```

---

## 目标（Goals）

### G-A：提升每日信号命中率（P0，权重 30%）

- **指标（Metrics）**：
  - 信号 T+3 命中率（hit/(hit+stopped+miss)）≥ 45%
  - P0 信号执行率 = 100%（**当前基线 0%——P0 信号从不执行，见 2026-W38 快照**）
  - 信号决策质量分（复盘仪表盘 8 项均分）≥ 3.5/5
- **验证器（Verifier）**：`settle_due_signals`（T+3 目标价结算）+ `dimension_dashboard`（P0a 新增分维度切片）
- **进化方向（Direction）**：
  - 优先：**P0 执行机制**（条件单/显式放弃，REQ-010/011 推进中）
  - 其次：信号设计 skill（`投资经验.md` 信号设计章节、盘中三级阈值）
- **当前状态**：**短板**（命中率无已执行样本；执行率 0% 是首要病灶）

### G-A2：P0 信号执行（P0，权重 25%）

- **指标（Metrics）**：P0 信号实际执行数（周度，n_executed）≥ 3（当前基线 **0——P0 从不执行**）
- **验证器（Verifier）**：`dimension_dashboard` by_priority P0 切片（P0a）
- **进化方向（Direction）**：
  - 优先：条件单自动化（REQ-011）+ 显式放弃记录（REQ-010）
  - 其次：P0 触发后的执行提醒机制
- **当前状态**：**严重短板**（连续 ≥6 日 0%，09-16 周报 P1 告警）

### G-A3：早盘信号触发率（P1，权重 20%）

- **指标（Metrics）**：早盘（morning_analysis）信号触发率 ≥ 40%（当前基线 **0%，连续两周**）
- **验证器（Verifier）**：`dimension_dashboard` by_source 切片（P0a）
- **进化方向（Direction）**：
  - 优先：早盘信号生成逻辑（触发条件可量化性、纳入标准）
  - 其次：早盘与盘中信号分层（早盘偏方向、盘中偏执行）
- **当前状态**：**短板**（连续两周 0 触发——gap_analysis 首个定向目标）

### G-B：提升报告质量与可靠性（P1，权重 25%）

- **指标（Metrics）**：报告质量总分（四维 0-5×4，总分 20）≥ 16
- **验证器（Verifier）**：`report_quality_review` 独立只读评审（P0b，交易日 17:20）
- **进化方向（Direction）**：
  - 优先：报告审阅 checklist（`报告审阅经验.md` 锚点 → 评分表）
  - 其次：数据校验脚本库（ETF 代码-名称强校验等）
- **当前状态**：进行中（首条基线 2026-09-24 total 15/20）

---

## 边界（Boundaries，红线）

> 明确"不进化什么"，防止误进化与目标漂移。

```
- 不进化方向：不做短线妖股/打板高频（能力圈之外）；不碰融资杠杆建议
- 不改动：数据层铁律（所有 A 股数据必须走 a-stock-data，不得另造数据通道）
- 不触碰：reports/（产物目录只读）；用户账户/凭证/身份相关配置
- 涉及金钱/金融/安全/删除类变更：必须人工确认（MANUAL_REVIEW 机制）
- 自动化发现问题→REQ：可自动建单，但 REQ CLOSED 必须用户最终确认
```

---

## 节奏（Cadence）

```
- 指标结算：每交易日复盘（T+3 结算随信号到期自动完成）+ 报告质量评审（17:20）
- 差距分析 → 定向 REQ：每周一（gap_analysis，读近 4 周快照）
- 进化候选验证：每周批处理（不用每个小波动都触发，防进化噪音）
- 经验库健康体检：每周三（experience_health）
- 进化周报：每周五（汇总"这周改了什么/为什么/验证了什么/指标怎么变"）
- 连续 3 轮指标无改善的方向：自动暂停 + 回滚最近变更 + 换方向（负反馈）
```

---

## 处理记录

| 时间 | 操作 | 备注 |
|------|------|------|
| 2026-09-24 | 实例化 | 从 goals.example.md 创建；基线依据 P0a（2026-W38 快照）+ P0b（首条质量分）真实数据 |
