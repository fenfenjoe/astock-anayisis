# REQ-{NNN}: {标题}

- **创建时间**: YYYY-MM-DD HH:MM
- **优先级**: P0(紧急) | P1(高) | P2(中) | P3(低)
- **影响范围**: 早盘分析 | 盘中检查 | 收盘复盘 | 周度回顾 | 经验健康 | 其他
- **状态**: OPEN

## 进化契约（P2，gap_analysis 生成定向 REQ 时必填；普通 REQ 可留 N/A）

> 对照验证依据：IMPLEMENTED 后进入观察期，观察期结束对比"实施前 vs 实施后"指标均值。
> 改善 → CLOSED；无改善 → 标记"无效进化" + 回滚建议（人工确认）。

- **关联指标**: {metric_id}: {field}（如 G-A: dims.overall.target_hit_rate；无则 N/A）
- **基线值**: {before}（实施前 N 周均值；无则 N/A）
- **预期改善**: {target}（目标值，通常=goals.md 目标；无则 N/A）
- **观察期**: {4} 周（IMPLEMENTED 后等待周数再对比）

## 开发流程（强制）

> 本需求实施**必须走 superpowers 流程**。不要在生成需求后直接裸写代码。

实施时严格按以下顺序执行：

```
1. brainstorming   — 探索方案空间，不跳入单一实现
2. writing-plans   — 写出详细实施计划（含文件清单、API/数据结构变更）
3. TDD             — 先写测试，再写代码
4. executing-plans — 按计划逐步实施
5. code-review     — 自查 + 修复
```

**铁律：**
- 禁止跳过 TDD — 没有测试的需求不得推进到 IMPLEMENTED
- 禁止跳过 brainstorming — 不假思索的实现 = 返工
- 涉及 A 股数据的，仍走 `a-stock-data` skill

## 需求描述

（详细描述优化需求的内容，越具体越好）

## 期望结果

（描述期望达到的效果，尽量可衡量）

## 测试交付物

> 以下清单在 TDD 步骤（auto_req_implement 第 3 步）中填写，在第 3.5 步门禁中验证。

- [ ] 测试文件: `harness/automation/tests/test_REQ-{NNN}.py`
- [ ] 被测模块: `harness/automation/lib/{模块名}.py`（如涉及 lib/ 新增或修改）
- [ ] TDD 门禁通过: `python -m pytest harness/automation/tests/test_REQ-{NNN}.py -v`
- [ ] 回归测试: 全量 `python -m pytest harness/automation/tests/ -v` 通过

**测试覆盖要求：**
- 每个公开函数至少 1 条正向测试 + 1 条边界测试
- 涉及计算的函数需测试正/负/零三种情况
- 涉及状态转换的函数需测试全部合法路径 + 至少 1 条非法路径

## 约束/注意事项

（如有特殊约束，在此说明）

## 处理记录

| 时间 | 操作 | 备注 |
|------|------|------|
| YYYY-MM-DD | 创建 | - |
