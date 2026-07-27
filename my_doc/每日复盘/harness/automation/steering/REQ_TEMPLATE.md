# REQ-{NNN}: {标题}

- **创建时间**: YYYY-MM-DD HH:MM
- **优先级**: P0(紧急) | P1(高) | P2(中) | P3(低)
- **影响范围**: 早盘分析 | 盘中检查 | 收盘复盘 | 周度回顾 | 经验健康 | 其他
- **状态**: OPEN

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
