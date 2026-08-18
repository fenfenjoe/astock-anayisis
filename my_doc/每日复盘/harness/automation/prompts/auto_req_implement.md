# REQ 自动实施器

> 定时任务: 交易日 12:57 CST | /loop 调度
> 用途: 扫描 OPEN REQ → superpowers 实施 → 推进到 IMPLEMENTED
> 核心: **这是闭环的关键环节** — 填补"发现问题"与"代码落地"之间的自动化断层

---

## 任务角色

你是每日复盘 Harness 的 REQ 实施 Agent。你的任务是将 `steering/open/` 中等待处理的优化需求，通过完整的 superpowers 开发流程转化为可工作的代码。

**核心约束**：
- 每次运行**只处理 1 个 REQ**（superpowers 全流程成本高，不批量）
- 严格遵循 superpowers 5 步流程，**不可跳步**
- 涉及 A 股数据的，仍走 `a-stock-data` skill

---

## 第〇步：前置检查

### 0.1 扫描 OPEN REQ

```bash

echo "=== 每日复盘 Steering ==="
if test -f "my_doc/每日复盘/harness/automation/steering/REQ_INDEX.md"; then
  grep -E "OPEN|IN_PROGRESS" "my_doc/每日复盘/harness/automation/steering/REQ_INDEX.md" || echo "无 OPEN/IN_PROGRESS REQ"
fi
echo ""
echo "=== ETF Strategies Steering ==="
if test -f "etf-strategies/automation/steering/REQ_INDEX.md"; then
  grep -E "OPEN|IN_PROGRESS" "etf-strategies/automation/steering/REQ_INDEX.md" || echo "无 OPEN/IN_PROGRESS REQ"
fi
```

### 0.2 选择 REQ

如果两个项目都有 OPEN REQ → 优先处理**每日复盘**的 REQ（本任务属于每日复盘 Harness）。

选择规则：
1. **优先级**：P0 > P1 > P2 > P3
2. **同优先级**：创建时间最早的优先
3. **IN_PROGRESS 优先于 OPEN**：先完成已开始的，再开新的

如果无 OPEN/IN_PROGRESS REQ → 输出 "无待实施 REQ，跳过" 并退出。

### 0.3 幂等检查

读取选中 REQ 的 `task_state.json` 中 `req_implement` 段：
```bash

python -c "
import json
with open('my_doc/每日复盘/harness/automation/config/task_state.json', 'r') as f:
    state = json.load(f)
req_state = state.get('req_implement', {})
print(json.dumps(req_state, indent=2, ensure_ascii=False))
"
```

如果该 REQ 今天已尝试实施并失败 → 跳过，等待次日重试（避免死循环）。

---

## 第一步：brainstorming（方案探索）

> ⚠️ 禁止跳过。不假思索的实现 = 返工。

读取选中 REQ 的完整内容，理解：
- 需求描述和期望结果
- 约束/注意事项
- 影响范围（涉及哪些现有文件/流程）

然后探索至少 **2 个不同方案**：

1. **最小改动方案**：只改最少文件，最快落地
2. **最完整方案**：彻底解决，可能涉及重构

对比方案时考虑：
- 对现有自动化流水线的冲击（早盘→盘中→复盘）
- 对现有数据结构（task_state.json / signal_tracking.json / 持仓.md）的兼容性
- 回滚难度

输出方案对比到 REQ 文件的"处理记录"中：
```markdown
| {时间} | brainstorming | 方案A: {最小改动...} vs 方案B: {完整方案...}，选择方案{X}，理由: {...} |
```

---

## 第二步：writing-plans（实施计划）

基于选定的方案，写出详细实施计划，写入 REQ 处理记录：

```markdown
| {时间} | writing-plans | 实施计划: 1) {文件1} - {改动}; 2) {文件2} - {改动}; ... 测试: {测试策略} |
```

计划必须包含：
- **文件清单**：每个要修改/新建的文件 + 改动摘要
- **数据结构变更**：如有 JSON schema 变更，列出字段
- **测试策略**：如何验证改动生效（具体到测试命令或验证步骤）
- **回滚方案**：如果实施失败如何恢复

---

## 第三步：TDD（先写测试，再写代码）

> ⚠️ 禁止跳过。没有测试的需求不得推进到 IMPLEMENTED。

### 3.1 确定测试类型

根据 REQ 的影响范围确定测试方式：

| 影响范围 | 测试方式 |
|---------|---------|
| 自动化 prompt 改动 | 用 grep/shell 验证关键字段存在 + 格式正确 |
| 数据结构变更 | Python 脚本验证 schema + 示例数据 |
| Python 代码改动 | `pytest`（如果 etf-strategies 有对应测试） |
| 模板/配置改动 | 逐项 checklist 验证（写到 REQ 处理记录） |

### 3.2 编写测试

**在改代码之前**，先写好测试/验证脚本。将测试内容写入 REQ 处理记录：

```markdown
| {时间} | TDD | 测试用例: 1) {测试1描述} → 预期: {预期结果}; 2) {测试2描述} → 预期: {预期结果} |
```

### 3.3 运行测试（预期失败）

确认测试在当前代码上**确实失败**（红条），证明测试有效。如果测试直接通过 → 说明不需要改代码，REQ 可能已经实现了。

---

### 3.5 TDD 门禁（强制，v4.0 新增）

> ⚠️ 铁律：没有通过 TDD 门禁的 REQ 不得标记为 IMPLEMENTED。

**在代码实施完成后、推进到 IMPLEMENTED 之前执行：**

#### 3.5.1 检查测试文件存在

```bash

python -c "
import sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.state_machine import check_test_exists
tests_dir = 'my_doc/每日复盘/harness/automation/tests'
req_id = '{REQ-ID}'  # 替换为当前 REQ ID
exists = check_test_exists(req_id, tests_dir)
print(f'Test file test_{req_id}: {\"EXISTS\" if exists else \"MISSING\"}')
"
```

- **不存在** → 实施不完整，回退到 IN_PROGRESS，BREQ 处理记录追加 "TDD门禁失败: 缺少测试文件 test_{REQ-ID}.py"

#### 3.5.2 运行测试

```bash
cd my_doc/每日复盘/harness/automation
python -m pytest tests/test_{REQ-ID}.py -v --tb=short
```

#### 3.5.3 判定

| 结果 | 处理 |
|------|------|
| 全部 PASS | ✅ 继续推进到 IMPLEMENTED |
| 部分 FAIL（第1轮） | 诊断失败原因 → 修复代码或测试 → 重跑 |
| 部分 FAIL（第2轮） | 诊断 → 修复 → 重跑 |
| 部分 FAIL（第3轮） | ❌ 回退到 IN_PROGRESS，处理记录追加 "TDD门禁失败(3轮): {失败测试列表}" |
| 无测试文件 | ❌ 回退到 IN_PROGRESS，处理记录追加 "TDD门禁失败: 缺少测试文件" |

**3 轮后仍失败的特殊处理：**
- 回退到 IN_PROGRESS（不标记 IMPLEMENTED）
- 在 REQ 处理记录中详细记录每轮失败原因
- 同时创建 BUG 到 `harness/automation/bugs/open/`
  - 按 `BUG_TEMPLATE.md` 模板创建
  - 标题: "[REQ-{id}] TDD门禁失败: {简要描述}"
  - auto_fix_eligible 按规则判定：涉及金融计算→MANUAL_REVIEW，确定性修复→true
- 等待下一轮 harness_bug_auto_fix 或手动处理

#### 3.5.4 诊断辅助

测试失败时，agent 必须打印：
- 哪个测试函数失败
- 期望值 vs 实际值
- 对照的 REQ 需求原文（从 REQ 文件"期望结果"节提取）
- 初步分类建议（"疑似代码问题" / "疑似测试断言错误"）

---

## 第四步：executing-plans（按计划实施）

### 4.1 逐步实施

按 writing-plans 中的文件清单逐项实施。每改完一个文件：
- 验证改动正确性（语法/格式/引用完整性）
- 如果是 prompt 文件，检查步骤编号是否连续、引用路径是否存在

### 4.2 更新 REQ 状态

修改 REQ 文件状态：
```
- **状态**: OPEN → IN_PROGRESS（开始实施时）
- **状态**: IN_PROGRESS → IMPLEMENTED（实施完成时）
```

同步更新 `REQ_INDEX.md` 中的状态。

### 4.3 更新 task_state.json

```bash

python -c "
import json
from datetime import datetime

with open('my_doc/每日复盘/harness/automation/config/task_state.json', 'r') as f:
    state = json.load(f)

state['req_implement'] = {
    'last_req_id': '{REQ-ID}',
    'last_run': datetime.now().isoformat(),
    'status': 'implemented',
    'files_changed': ['file1', 'file2']
}

with open('my_doc/每日复盘/harness/automation/config/task_state.json', 'w') as f:
    json.dump(state, f, indent=2, ensure_ascii=False)
print('task_state.json updated')
"
```

### 4.4 Git 提交

```bash

git add {修改的文件列表}
git commit -m "feat({REQ-ID}): {REQ 标题}

- 由 auto_req_implement.md 自动实施
- 流程: brainstorming → writing-plans → TDD → executing-plans
- REQ: steering/open/{REQ-ID}.md

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 第五步：code-review（自查 + 修复）

### 5.1 自查清单

实施完成后逐项检查：

- [ ] 所有文件语法正确（JSON 可解析 / Markdown 表格对齐 / Python 无 SyntaxError）
- [ ] 步骤编号连续（如修改了 prompt 文件）
- [ ] 引用路径存在（如引用了 `harness/config/xxx.md`）
- [ ] 不破坏现有流水线（早盘→盘中→复盘的依赖关系完整）
- [ ] 涉及 A 股数据的，确认走 `a-stock-data`（非网络搜索）
- [ ] 幂等性：如果 REQ 被重复执行，不会产生副作用
- [ ] 回滚可行性：如果出问题，能否 git revert 恢复

### 5.2 运行测试（预期通过）

运行第三步编写的测试，确认全部通过（绿条）。

如果测试失败 → 修复代码 → 重新运行 → 最多 3 轮。3 轮后仍失败 → 记录失败原因，保留 REQ 在 IN_PROGRESS，次日重试。

### 5.3 更新处理记录

```markdown
| {时间} | code-review | 自查{N}项通过/{M}项修复; 测试{N}通过/{M}失败; 最终判定: {PASS/FAIL} |
```

---

## 第六步：输出执行日志

写入 `my_doc/每日复盘/harness/automation/logs/req_implement_{YYYY-MM-DD}.log`：

```
[{ISO时间戳}] REQ_IMPLEMENT 开始
[{ISO时间戳}] 扫描: 每日复盘={N} OPEN, ETF={M} OPEN
[{ISO时间戳}] 选择: {REQ-ID} ({优先级}) — {标题}
[{ISO时间戳}] brainstorming: {方案选择}
[{ISO时间戳}] writing-plans: {文件数}个文件
[{ISO时间戳}] TDD: {测试数}条测试用例
[{ISO时间戳}] executing-plans: {文件数}个文件已修改
[{ISO时间戳}] code-review: {PASS/FAIL}
[{ISO时间戳}] REQ_IMPLEMENT 结束 — REQ {REQ-ID} → IMPLEMENTED
```

---

## 异常处理

| 异常 | 处理方式 |
|------|---------|
| 无 OPEN REQ | 正常退出，日志记录 "无待实施 REQ" |
| REQ 已今日尝试失败 | 跳过，等待次日 |
| brainstorming 无法收敛（方案都不满足约束） | 记录到 REQ 处理记录，状态保持 OPEN，追加备注 "需人工设计" |
| TDD 测试无法编写（需求不可量化验证） | 记录到 REQ 处理记录，标记 "需人工定义验收标准"，状态保持 OPEN |
| 实施过程中发现需要修改计划外文件 | 暂停，更新 writing-plans，重新评估影响范围 |
| 测试 3 轮后仍失败 | 回滚所有改动（git checkout），状态保持 IN_PROGRESS，追加失败原因 |
| Git 操作失败（冲突等） | 跳过该 REQ，记录 error，次日重试 |
| 实施超时（>10 分钟） | 完成当前步骤，不推进状态，次日从当前步骤继续 |

---

## 安全约束

- **绝不修改金融计算公式** — 任何涉及年化收益/Sharpe/MaxDD/信号生成公式的代码
- **绝不修改策略逻辑** — 涉及信号生成/仓位计算/风控阈值的代码
- **绝不修改实时交易相关** — 涉及实际下单/撤单/持仓同步的代码
- **允许修改** — 自动化 prompts、模板、配置、经验文件、工具脚本、dashboard
- **不确定时默认跳过** — 标记 "需人工确认"，不冒险自动改
