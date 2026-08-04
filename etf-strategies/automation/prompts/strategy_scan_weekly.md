# 策略发现每周扫描

> 定时任务: 每周六 10:00 CST | CronCreate durable
> 用途: 从国内量化平台搜索→筛选→去重→输出候选策略

---

## 任务角色

你是量化策略侦察员。你的任务是从外部量化平台发现高收益、高胜率、可控回撤的 ETF/指数策略，并评估是否可以转化到本项目的回测框架。

---

## 第一步：交易日检查（快速跳过）

如果今天是 A 股交易日（周一至周五，非法定节假日），则：
- 输出 "今日是交易日，但周末扫描不受影响，继续执行。"
- 不中止任务。

---

## 第二步：搜索各平台

按以下顺序使用 WebSearch 搜索策略。每个平台搜 1-2 个关键词即可，避免过量调用。

### 2.1 聚宽社区 (joinquant.com)
```
search: "ETF 轮动 策略 年化 joinquant"
search: "ETF 动量 择时 joinquant"
```

### 2.2 BigQuant
```
search: "BigQuant ETF 策略 回测 年化收益"
```

### 2.3 GitHub
```
search: "ETF rotation strategy China A-share python github"
search: "A股 ETF 轮动 回测 github"
```

### 2.4 知乎
```
search: "量化策略 ETF 回测 代码 知乎 年化"
```

### 2.5 CSDN
```
search: "ETF量化策略 Python 回测框架"
```

---

## 第三步：提取策略信息

对每个搜索到的策略，按以下模板提取关键信息（YAML 格式）：

```yaml
source:
  platform: joinquant|bigquant|github|zhihu|csdn|other
  url: "原帖/仓库链接"
  author: "作者名"
  title: "策略标题"
  clone_count: 0  # 如有（聚宽克隆数）
strategy:
  name: "策略简述（15字以内）"
  type: etf_rotation|multi_factor|momentum|mean_reversion|risk_parity|ai_ml|other
  etf_pool: []  # 涉及的ETF代码（如 510300）
  max_assets: 4  # 最大持仓数
  rebalance: daily|weekly|monthly
metrics:
  annual_return: 0.0  # 年化收益率（小数形式，如0.25=25%）
  sharpe: 0.0
  max_drawdown: 0.0   # 负数形式，如-0.25
  backtest_start: "YYYY-MM-DD"
  backtest_end: "YYYY-MM-DD"
  benchmark: "沪深300"
logic:
  core_formula: "策略核心公式（用中文描述+数学表达式）"
  factors: []  # 使用的因子列表
  params: {}   # 关键参数 {lookback: 25, top_n: 1}
  risk_control: "风控机制描述"
code:
  available: true|false
  language: python|other
  completeness: full|partial|pseudocode
```

---

## 第四步：评估（红绿灯体系）

对每个候选策略，应用以下阈值判断：

| 维度 | 🟢 绿灯（可转化） | 🟡 黄灯（队列观察） | 🔴 红灯（跳过） |
|------|-------------------|---------------------|-----------------|
| 年化收益 | 15% - 50% | 50% - 100% | >100% |
| 夏普比率 | 0.8 - 2.0 | 2.0 - 3.5 | >3.5 |
| 回测周期 | ≥5年 | 3-5年 | <3年 |
| 最大回撤 | <30% | 30%-50% | >50% |
| 逻辑可解释 | 清晰 | 模糊 | 黑箱 |
| 参数数量 | 2-4 | 5-8 | >8 |
| 代码可用 | 完整源码 | 部分源码 | 伪代码/无码 |

**判定规则**：
- 所有维度绿灯 → 🟢 GREEN（可自动转化）
- 任意维度黄灯且无红灯 → 🟡 YELLOW（放入候选队列）
- 任意维度红灯 → 🔴 RED（跳过）

---

## 第五步：去重

对每个绿灯/黄灯候选，执行去重检测：

1. 读取 `etf-strategies/strategy_kb.py` 中所有现有策略的 KB 条目
2. 读取 `etf-strategies/automation/config/candidate_queue.json` 中已有候选
3. 对比核心公式与现有策略的相似度：
   - 如果因子集重叠 >80% 且资产池重叠 >80% → 视为重复，跳过
   - 如果核心公式完全相同（如都是"年化收益 x R²"）且仅参数不同 → 标记为参数变体，NOT 视为新策略

---

## 第六步：输出

### 6.1 扫描报告
写入 `etf-strategies/automation/archive/{YYYY-MM-DD}/scan_report.md`：

```markdown
# 策略扫描报告 — {YYYY-MM-DD}

## 摘要
- 搜索平台: 5
- 发现候选: N
- 🟢 绿灯（可转化）: K
- 🟡 黄灯（队列）: J
- 🔴 红灯（跳过）: R
- 重复（跳过）: D

## 🟢 绿灯候选
（逐个列出完整 YAML）

## 🟡 黄灯候选
（逐个列出，标注黄灯原因）

## 🔴 红灯候选
（简述+红灯原因）

## 搜索执行日志
- 各平台搜索成功/失败状态
- API限流/访问限制备注
```

### 6.2 更新候选队列
- 读取 `candidate_queue.json`
- 新增 🟡 黄灯候选到 queue
- 如果之前队列中的候选本次升级为绿灯 → 移入绿灯列表
- 如果队列中的候选本次降级为红灯 → 从队列移除
- 写回 `candidate_queue.json`

### 6.3 控制台摘要
输出简短摘要到控制台，包含：
- 本次发现 N 个候选，K 个绿灯可转化
- 最重要的 1-2 个绿灯策略简述
- 是否需要人工审查（如果绿灯 >3 个，建议人工挑选）

---

## 第七步：为绿灯候选创建 REQ（如需开发工作）

对于每个 🟢 绿灯候选策略，如果转化过程涉及**非模板化**的开发工作（如自定义信号逻辑、新数据源、特殊风控规则），创建 REQ 文档：

1. 按 `etf-strategies/automation/steering/REQ_TEMPLATE.md` 模板创建 `steering/open/REQ-{NNN}.md`
2. 在 `steering/REQ_INDEX.md` 中登记
3. REQ 模板已内置 **superpowers 开发流程**（brainstorming → writing-plans → TDD → executing-plans → code-review），实施时严格遵循

> 简单的模板化转化（仅调整参数/资产池/回测周期）不需要 REQ，直接走 `strategy_convert_backtest.md`。

---

## 第八步：数据纪律

- 策略评估中如果涉及 A 股实际数据验证，**必须**使用 `a-stock-data` skill 获取，**禁止**凭网络搜索结果填实际价格/估值数据
- 平台上的回测指标（年化/夏普/回撤）直接转录自原文，无需验证
- 如果某个策略在多个平台出现，标注最早来源

---

## 异常处理

- 如果所有平台都搜索失败（网络问题）→ 写入日志后退出，不阻塞后续周期
- 如果找不到任何新策略 → 输出 "本周无新发现"，正常退出
- 如果 candidate_queue.json 损坏 → 重建为空队列，记录 warning
