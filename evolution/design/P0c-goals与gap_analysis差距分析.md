# P0c 设计：goals.md + gap_analysis 差距分析任务

> 自进化框架 P0c（第一阶段第三步）
> 依据：《基于 DeepSeek Harness 的 Agent 自进化框架研究.md》第 7 节「可定制层」+ 第 5 节「改进回路」
> 目标：闭合"结算 → 差距 → 定向 REQ"——让进化从"随机发现"变成"数据定向打击"。
> 日期：2026-09-24 | 状态：**已实施（代码+测试+端到端通过）**

## 一、背景

P0a/P0b 已经产出分维度指标快照（signal_quality_history / report_quality_history），但**没有消费者**——指标算出来没人读，REQ 仍靠复盘随机发现。P0c 补上"差距分析器"：目标(goals.md) − 现状(历史快照) → 差距排序 → 定向 REQ。

## 二、设计

### 2.1 `evolution/config/goals.md`（可定制层入口，已实例化）

- 从 `goals.example.md` 实例化，含 **```json 机器结算块**（gap_analysis 唯一机器输入，勿删）
- 4 个指标：G-A 信号命中率（45）/ G-A2 P0 执行数（3）/ G-A3 早盘触发率（40）/ G-B 报告质量（16）
- 基线依据 P0a（2026-W38 快照）+ P0b（首条质量分）真实数据
- 含愿景/目标/边界红线/节奏/处理记录

### 2.2 `lib/gap_analysis.py`（纯函数）

| 函数 | 职责 |
|------|------|
| `parse_goals(md)` | 解析 goals.md 机器结算块（容忍无块/坏 JSON → 空 metrics） |
| `current_value(metric, sq, rq)` | 从历史快照算近 N 周均值（field 点路径取值） |
| `compute_gaps(goals, sq, rq)` | 算差距（gap=target−current），排序（缺口大前、no_data 后） |
| `gen_req_suggestion(gap, min_gap)` | 显著缺口 → 定向 REQ 建议（缺口≥min_gap；高权重 no_data → 数据缺口提示） |
| `build_gap_report(...)` | 汇总报告 {gaps, suggestions} |

### 2.3 `prompts/auto_gap_analysis.md`（每周一 12:27）

1. 读 goals + 历史快照 → build_gap_report
2. 解读（shortfall/met/no_data 三态）
3. **归因**：拉 4 周趋势 + 参考周报结论；持续短板（≥2 周）才建 REQ（防噪音）
4. 生成定向 REQ（REQ_TEMPLATE 格式 + 关联指标/基线/预期改善字段）→ steering/open/ + REQ_INDEX
5. 输出差距周报 reports/weekly/差距分析周报.md

### 2.4 调度：`task_schedule.json` 新增 `gap_analysis`（周一 12:27，无冲突）

## 三、测试（TDD，17 项）

- parse_goals：解析 / 无块 / 坏 JSON
- current_value：signal 均值 / report avg_total / 单维 / 嵌套维度 / 无数据
- compute_gaps：shortfall 排序 / met / no_data 排后（修复排序逻辑 bug：`!=` → `==`）
- gen_req_suggestion：大缺口建单 / 小缺口 None / 高权重 no_data 建单 / 低权重 no_data None / met None
- build_gap_report：结构完整

## 四、验收（已达成）

1. 全量测试 **574 passed, 1 skipped**（+17 项）✅
2. **端到端真实数据跑通**：goals.md（4 指标）+ 真实历史快照 → 差距报告 ✅
3. **进化闭环首次闭合**：结算→差距→定向 REQ 建议全链路 ✅

**端到端真实输出（2026-09-24）：**
```
G-A  信号T+3命中率  目标=45.0 当前=0.0  缺口=45.0  shortfall → [GAP] REQ 建议
G-A3 早盘信号触发率  目标=40.0 当前=0.0  缺口=40.0  shortfall → [GAP] REQ 建议
G-A2 P0信号执行数   目标=3.0  当前=0.0  缺口=3.0   shortfall（<min_gap 观察）
G-B  报告质量总分   目标=16.0 当前=15.0 缺口=1.0   shortfall（<min_gap 观察）
```
首条定向 REQ 直指"信号命中率缺口 45"（根因=P0 不执行+早盘 0 触发）。

**关键修复**：goals.md field 需带 `dims.` 前缀（快照结构 `dims.overall.*` / `dims.dimensions.*`）。

## 五、后续衔接

- **P2**：REQ 加"关联指标/基线/观察期"——gap_analysis 生成的 REQ 已带这些字段，P2 补"前后对比验证"闭环
- **数据积累**：快照 ≥4 周后，gap_analysis 的"持续短板判定"与"4 周均值"才完全生效
- 云库化：`gap_reports` 表（本地周报先行）

## 六、风险与回滚

- 全为新增（goals.md / gap_analysis.py / prompt / 调度项）→ 回滚 = 删除新增
- goals.md 机器块是 gap_analysis 唯一输入：格式错 → 返回空 metrics（fail-safe，不崩溃）
- 建单有去重铁律（同主题 OPEN 已存在 → 追加记录不重复建单）
