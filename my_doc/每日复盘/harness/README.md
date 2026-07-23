# Harness 层使用说明

这是每日复盘项目的"厨房"——所有用于生成报告的工具、模板和经验都在这里。

## 目录说明

| 目录 | 用途 | 修改频率 |
|------|------|---------|
| `prompts/` | 永久模板：早盘分析和复盘分析的方法论框架 | 偶有优化，不含日期特定内容 |
| `experience/` | 经验沉淀：投资经验、短线经验、报告审阅标准 | 每次复盘后追加 |
| `config/` | 日度配置：当前持仓快照 | 调仓时更新 |
| `staging/` | 当日可执行 prompt：由昨日复盘生成，每日覆盖 | 每日覆盖 |
| `archive/` | 历史 prompt 归档：按日期保存每日使用的 prompt | 每日追加 |

## 设计理念

遵循 **Harness Engineering** 三支柱：

1. **Context Management（上下文管理）**：模板、经验、配置分层存放，按需加载，避免全量注入
2. **Tool Use（工具使用）**：`a-stock-data` 取数 + Skill 流程编排
3. **Evaluation Loop（评估回路）**：复盘 = Generator-Evaluator，报告审阅经验 = 质量门

核心原则：**"信 harness，不信 AI"** — 把流程执行从 LLM 推理中外化到结构化框架中。

## 每日工作流

```
盘前: 读 staging/今日-早盘分析.md → 执行早盘分析 → 产出早盘报告
收盘: 读 staging/今日-复盘分析.md → 执行复盘分析 → 产出复盘报告
      → 经验沉淀 → 生成次日 staging → 归档当日 prompt
```

## 如何触发

对 Claude 说"执行早盘分析"或"执行复盘分析"，Harness 层会自动编排完整流程。

或直接说"每日复盘"触发 `daily-review-harness` skill。
