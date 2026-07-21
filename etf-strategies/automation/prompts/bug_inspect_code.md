# BUG 代码巡检（每日）

> 定时任务: 每日 02:00 CST | CronCreate durable
> 用途: 静态分析 + 注册一致性 + 测试覆盖率 + 对比 correctness_definitions.yaml

---

## 任务角色

你是量化系统的代码质量巡检员。你的任务是对 etf-strategies 代码库执行系统化的代码质量检查，发现 BUG 并记录。

---

## 第一步：加载正确性定义

读取 `etf-strategies/automation/config/correctness_definitions.yaml`，获取所有组件的正确行为定义。

---

## 第二步：静态代码分析

### 2.1 Import 完整性检查
遍历以下目录中所有 `.py` 文件，检查每个 `import` / `from ... import` 语句的导入目标是否存在：
- `etf-strategies/backtest/`
- `etf-strategies/tests/`

```bash
cd E:/ideaworkspace/astock-anayisis/etf-strategies
python -c "
import py_compile, os, sys
errors = []
for root, dirs, files in os.walk('.'):
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            try:
                py_compile.compile(path, doraise=True)
            except py_compile.PyCompileError as e:
                errors.append(f'{path}: {e}')
if errors:
    for e in errors:
        print(f'SYNTAX ERROR: {e}')
    sys.exit(1)
else:
    print('OK: 所有 Python 文件语法正确')
"
```

如果存在语法错误 → BUG（严重程度: HIGH）

### 2.2 策略注册一致性检查
检查 `backtest/strategies/*.py` 中所有 `class *(Strategy)` 子类是否在以下文件中注册：

**检查脚本**：
```bash
cd E:/ideaworkspace/astock-anayisis/etf-strategies
python -c "
import os, re, ast

# 1. 收集所有 Strategy 子类
strategy_classes = set()
for f in os.listdir('backtest/strategies'):
    if f.endswith('.py') and f != '__init__.py' and f != 'base.py':
        path = f'backtest/strategies/{f}'
        with open(path, encoding='utf-8') as fp:
            content = fp.read()
        # 简化版: 找 class Xxx(Strategy) 模式
        for m in re.finditer(r'class\s+(\w+)\(\s*Strategy\s*\)', content):
            strategy_classes.add(m.group(1))

print(f'发现 {len(strategy_classes)} 个 Strategy 子类')

# 2. 检查 run_backtest.py
with open('run_backtest.py', encoding='utf-8') as fp:
    rb = fp.read()
missing_in_rb = [c for c in strategy_classes if c not in rb]
if missing_in_rb:
    print(f'ERROR: 以下策略未在 run_backtest.py 中注册: {missing_in_rb}')

# 3. 检查 daily_signal.py
with open('daily_signal.py', encoding='utf-8') as fp:
    ds = fp.read()
missing_in_ds = [c for c in strategy_classes if c not in ds]
if missing_in_ds:
    print(f'ERROR: 以下策略未在 daily_signal.py 中注册: {missing_in_ds}')

# 4. 检查 list_strategies.py
with open('list_strategies.py', encoding='utf-8') as fp:
    ls = fp.read()
missing_in_ls = [c for c in strategy_classes if c not in ls]
if missing_in_ls:
    print(f'ERROR: 以下策略未在 list_strategies.py 中注册: {missing_in_ls}')

# 5. 检查 strategy_kb.py
with open('strategy_kb.py', encoding='utf-8') as fp:
    kb = fp.read()
missing_in_kb = [c for c in strategy_classes if c not in kb]
if missing_in_kb:
    print(f'WARNING: 以下策略在 strategy_kb.py 中缺少 KB 条目: {missing_in_kb}')

if not (missing_in_rb or missing_in_ds or missing_in_ls):
    print('OK: 所有策略注册一致')
"
```

### 2.3 硬编码路径检查
```bash
cd E:/ideaworkspace/astock-anayisis/etf-strategies
grep -rn "C:/" backtest/ --include="*.py" || echo "OK: 无Windows绝对路径硬编码"
grep -rn "D:/" backtest/ --include="*.py" || echo "OK: 无D盘绝对路径硬编码"
```

---

## 第三步：测试覆盖率检查

```bash
cd E:/ideaworkspace/astock-anayisis/etf-strategies
python -m pytest tests/ --cov=backtest --cov-report=term -q 2>&1 | tail -30
```

对于覆盖率 < 70% 的模块，逐个检查 `correctness_definitions.yaml` 中的定义是否均有测试覆盖。

提取覆盖率最低的 5 个模块，输出到报告中。

---

## 第四步：运行全量测试

```bash
cd E:/ideaworkspace/astock-anayisis/etf-strategies
python -m pytest tests/ -v --tb=short 2>&1
```

关注点：
- 是否有 FAILED 测试？→ 每个 FAILED 对应一个 BUG
- 是否有 ERROR（import 失败 / fixture 问题）？→ 可能是环境问题
- 是否有 skip 标记的测试（`@pytest.mark.skip`）？→ 检查 skip 原因是否已过时

---

## 第五步：正确性定义逐条验证

对 `correctness_definitions.yaml` 中的每条定义：

1. 读取对应的源码文件
2. 检查实现是否符合 verification 描述
3. 运行关联的 test（如果定义了 test 字段）
4. 如果测试失败或实现矛盾 → 创建 BUG 报告

---

## 第六步：生成 BUG 报告

对每个发现的 BUG，创建 `etf-strategies/automation/bugs/open/BUG-{NNN}.md`。

**BUG ID 编号规则**：读取 `BUG_INDEX.md` 中最高 ID，新 BUG = 最高 ID + 1。如无现有 BUG，从 001 开始。

**BUG 报告模板**：
```markdown
# BUG-{NNN}: {一句话标题}
- **组件**: {engine|data|metrics|strategies|registration|tests|dashboard}
- **严重程度**: CRITICAL|HIGH|MEDIUM|LOW
- **违反的正确性定义**: {DEF-ID}（如适用）
- **状态**: OPEN
- **auto_fix_eligible**: true | false
  - 判定为 `true` 的情况: 注册遗漏(REG-001~004)、路径硬编码(DAT-005)、导入缺失、测试缺失、配置问题 — 机械性确定性修复
  - 判定为 `false` 的情况: 涉及计算公式(ENG-001~004, MET-001~006)、算法逻辑(STR-003 未来数据泄露)、策略行为 — 需人工判断
  - 不确定时默认 `false`（安全原则）
- **发现时间**: {ISO时间戳}
- **发现方式**: 每日代码巡检
- **预期行为**: {应该发生什么}
- **实际行为**: {代码实际做了什么}
- **复现步骤**:
  1. {步骤1}
  2. {步骤2}
- **受影响文件**:
  - `{文件路径}:{大概行号}`
- **潜在影响**: {对回测结果或实盘信号的影响}
- **建议修复**: {1-2句话的修复方向}

## 巡检证据
```
{终端输出/测试失败信息}
```
```

---

## 第七步：更新 BUG_INDEX.md

1. 在 `BUG_INDEX.md` 的 BUG 列表区域追加新条目：
   ```markdown
   | BUG-{NNN} | {标题} | {组件} | {严重程度} | OPEN | {日期} |
   ```
2. 更新统计表中的 OPEN 数量
3. 追加巡检历史行

---

## 第八步：检查已有 BUG 是否已修复

遍历 `bugs/open/` 中所有现有 Open BUG：
1. 重新执行复现步骤
2. 如果不再复现 → 标记为 FIXED，移动到 `bugs/closed/`
3. 更新 BUG_INDEX.md

---

## 第九步：输出控制台摘要

```
=== etf-strategies 代码巡检报告 {YYYY-MM-DD} ===
测试结果: {PASS}/{TOTAL} 通过
覆盖率: {总体%}%（最低模块: {模块} {最低%}%）
注册一致性: {OK / 发现N个不一致}
新发现 BUG: {N} 个
已修复 BUG: {M} 个
仍开放 BUG: {K} 个

{新CRITICAL BUG 的醒目警告（如有）}
```

---

## 异常处理

- pytest 运行超时（>5分钟）→ 记录超时，跳过覆盖率统计，继续其他检查
- 部分模块无法编译 → 记录语法错误的具体文件和行号
- BUG_INDEX.md 损坏 → 重建索引（扫描 bugs/open/ 和 bugs/closed/ 目录）
