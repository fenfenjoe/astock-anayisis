# Logic Inspection Scheduled Tasks — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a daily logic inspection task (17:07) and a bi-hourly pending confirmation reminder to the /loop automation system, covering 14 inspection items across 5 groups.

**Architecture:** Pure prompt-driven (方案 A). Two new prompt files drive all logic. No Python code changes needed — `task_scheduler.py` and `loop_runner.md` already support the required schedule patterns. BUG creation and PENDING_CONFIRMATION management happen inline within the prompt execution.

**Tech Stack:** Markdown prompts, JSON schedule config, existing Python scheduler (task_scheduler.py), existing /loop architecture.

## Global Constraints

- `{today}` format throughout: `yyyyMMdd` (e.g. `20260730`), use `date.today().strftime("%Y%m%d")` in Python code
- File existence checks must use `bash test -f`, never rely on LLM reasoning
- BUG creation follows `my_doc/每日复盘/harness/automation/bugs/BUG_TEMPLATE.md`
- `bugs/open/` directory must exist (create if missing)
- All prompts must follow existing auto_*.md conventions (role description, steps, bash blocks, error handling table)

---

### Task 1: Create `auto_pending_remind.md` — Bi-Hourly Pending Confirmation Reminder

**Files:**
- Create: `my_doc/每日复盘/harness/automation/prompts/auto_pending_remind.md`

**Interfaces:**
- Produces: Prompt file referenced by `task_schedule.json` task `pending_remind`
- Reads: `my_doc/每日复盘/harness/automation/PENDING_CONFIRMATION.md`

- [ ] **Step 1: Create the prompt file**

```markdown
# 待确认事项提醒

> 定时任务: 每天 9:13, 11:13, 13:13, 15:13, 17:13, 19:13, 21:13 | /loop 调度
> 用途: 扫描 PENDING_CONFIRMATION.md 中待用户确认的事项，有则醒目提醒，无则静默跳过

---

## 任务角色

你是待确认事项提醒 Agent。每 2 小时检查一次是否有待用户确认的事项。

---

## 第一步：扫描待确认事项

```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import re, os

pending_file = 'my_doc/每日复盘/harness/automation/PENDING_CONFIRMATION.md'
if not os.path.exists(pending_file):
    print('PENDING_FILE_MISSING')
    exit(0)

with open(pending_file, 'r', encoding='utf-8') as f:
    content = f.read()

# 提取 ## 待确认 表中的数据行（非表头/分隔行）
section = content.split('## 待确认')
if len(section) < 2:
    print('PENDING_COUNT:0')
    exit(0)

section_text = section[1].split('## ')[0] if '## ' in section[1] else section[1]
lines = [l for l in section_text.split('\n') if l.strip().startswith('|') and not l.strip().startswith('|--') and not l.strip().startswith('|---')]
# 排除表头行
data_rows = [l for l in lines if '日期' not in l and '来源BUG' not in l and '事项' not in l and '优先级' not in l]
count = len(data_rows)
print(f'PENDING_COUNT:{count}')
if count > 0:
    for row in data_rows:
        print(f'  {row.strip()}')
" 2>&1
```

---

## 第二步：判断

解析 Python 输出的 `PENDING_COUNT` 值：

- **`PENDING_COUNT:0` 或 `PENDING_FILE_MISSING`** → 静默跳过：
  ```
  OK | 无待确认事项
  ```

- **`PENDING_COUNT:N` (N > 0)** → 醒目输出：
  ```
  ⚠️ {N} 项待确认事项，请查看 PENDING_CONFIRMATION.md
  {逐行列出事项}
  ```

---

## 异常处理

| 异常 | 处理 |
|------|------|
| PENDING_CONFIRMATION.md 不存在 | 输出 `PENDING_FILE_MISSING`，静默跳过（首次运行前可能不存在） |
| Python 脚本执行失败 | 输出 `pending_remind error: {raw}`，不阻塞循环 |
```

- [ ] **Step 2: Verify file created successfully**

Run: `bash -c 'test -f "my_doc/每日复盘/harness/automation/prompts/auto_pending_remind.md" && echo "EXISTS" || echo "MISSING"'`
Expected: `EXISTS`

---

### Task 2: Create `auto_logic_inspect.md` — Daily Logic Inspection (Core)

**Files:**
- Create: `my_doc/每日复盘/harness/automation/prompts/auto_logic_inspect.md`

**Interfaces:**
- Produces: Prompt file referenced by `task_schedule.json` task `logic_inspect`
- Reads: `harness/staging/`, `harness/archive/{today}/`, `reports/{today}/`, `harness/config/持仓.md`, `每日调仓.md`, `task_state.json`, `signal_tracking.json`, `experience/`, `BUG_INDEX.md`
- Writes: `bugs/open/BUG-{NNN}.md`, `PENDING_CONFIRMATION.md`, execution log

- [ ] **Step 1: Write header and role description**

```markdown
# 逻辑巡检自动执行

> 定时任务: 每天 17:07 CST | /loop 调度
> 用途: 系统性检查每日复盘项目的文件内容合理性和一致性
> 产出: BUG 报告 + PENDING_CONFIRMATION 更新 + 执行日志
> **{today} 格式**: `yyyyMMdd`（如 `20260730`），所有 Python 代码中必须用 `date.today().strftime("%Y%m%d")`，禁用 `date.today().isoformat()`

---

## 你是什么

你是每日复盘 Harness 的逻辑巡检 Agent。你的任务是每天 17:07 系统性地检查 Harness 层文件的完整性、一致性和内容质量，在问题被用户"使用中发现"之前主动捕获。

**核心原则**:
- **文件存在性必须用 bash 验证，禁止凭推理判断**
- **FAIL → BUG 单**，WARN → 日志记录，PASS → 静默通过
- **去重**：创建 BUG 前检查 BUG_INDEX.md 中是否已有相同问题
- **非交易日降级**：非交易日不因"没有做交易日本该做的事"而报 FAIL

---

## 第〇步：环境准备

### 0.1 判断交易日

```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import json, subprocess, sys
from datetime import date
today = date.today().isoformat()
try:
    result = subprocess.run(['python', 'my_doc/每日复盘/harness/automation/config/trading_calendar.py', today],
                          capture_output=True, text=True, timeout=10)
    data = json.loads(result.stdout)
    is_td = data.get('is_trading_day', False)
    print(f'TRADING_DAY={is_td}')
except:
    print('TRADING_DAY=True')  # fail open
" 2>&1
```

解析 `TRADING_DAY` 值，决定后续检查范围。

### 0.2 确保 bugs/open/ 目录存在

```bash
mkdir -p my_doc/每日复盘/harness/automation/bugs/open
mkdir -p my_doc/每日复盘/harness/automation/bugs/closed
```

### 0.3 初始化执行日志

创建 `my_doc/每日复盘/harness/automation/logs/logic_inspect_{today}.log`：
```
[{ISO时间戳}] LOGIC_INSPECT 开始 | 交易日={是/否}
```

---

## A 组：归档完整性（2 条）

### A1: archive/{today}/早盘分析-staging.md 存在

```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import os
from datetime import date
today = date.today().strftime('%Y%m%d')
f = f'my_doc/每日复盘/harness/archive/{today}/早盘分析-staging.md'
if os.path.exists(f):
    size = os.path.getsize(f)
    print(f'A1:PASS: {f} ({size} bytes)')
else:
    print(f'A1:FAIL: {f} 不存在')
" 2>&1
```

### A2: archive/{today}/复盘分析-staging.md 存在

```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import os
from datetime import date
today = date.today().strftime('%Y%m%d')
f = f'my_doc/每日复盘/harness/archive/{today}/复盘分析-staging.md'
if os.path.exists(f):
    size = os.path.getsize(f)
    print(f'A2:PASS: {f} ({size} bytes)')
else:
    print(f'A2:FAIL: {f} 不存在')
" 2>&1
```

**非交易日校准**：MISSING → `A2:PASS`（预期行为），EXISTS → `A2:WARN`（非预期文件）。

**处理**：
- PASS → 记录日志，继续
- FAIL → 创建 BUG（`auto_fix_eligible=false`，MANUAL_REVIEW — 需要判断为什么归档缺失）
- WARN → 写入日志，不创建 BUG

---

## B 组：Staging 章节对齐（3 条）

### B1: staging/今日-早盘分析.md 章节完整性

读取文件内容，检查以下 8 个章节全部存在且非空：

1. **一、昨日盘面回顾** — 含指数涨跌数字 + 日内走势描述 + 核心矛盾
2. **二、当前持仓快照** — 每只标的含代码+数量+成本价+前日收盘+浮盈%
3. **三、7维打分（非持仓板块）** — 节存在（数据可由翌日早盘填入）
4. **四、各持仓做T建议** — 逐只给出方向+触发条件+风控，最多允许"今日不做T"
5. **五、跨品种联动约束** — 含已验证规则+校准参数+验证状态
6. **六、前次预测回顾** — 逐条预测vs实际+准确率统计+根因
7. **七、核心聚焦议题** — 3-6条可验证具体假设，禁止泛泛"关注大盘方向"
8. **八、今日信号汇总** — 预定义信号含触发条件+有效时段+仓位

**检查方法**：
```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import os, sys
from datetime import date

f = 'my_doc/每日复盘/harness/staging/今日-早盘分析.md'
if not os.path.exists(f):
    print('B1:FAIL: staging/今日-早盘分析.md 不存在')
    sys.exit(0)

with open(f, 'r', encoding='utf-8') as fh:
    content = fh.read()

required_sections = [
    '昨日盘面回顾',
    '当前持仓快照',
    '7维打分',
    '各持仓做T建议',
    '跨品种联动约束',
    '前次预测回顾',
    '核心聚焦议题',
    '信号汇总'
]

failures = []
for section in required_sections:
    if section not in content:
        failures.append(f'MISSING: 「{section}」')
    else:
        # 检查节后是否有实际内容（至少50字符非空白）
        idx = content.index(section)
        after = content[idx+len(section):idx+len(section)+500]
        if len(after.strip()) < 50:
            failures.append(f'EMPTY: 「{section}」')

# 检查日期是否指向明天
tomorrow = date.today().strftime('%Y-%m-%d')
# 允许 staging 文件日期是明天（由昨天复盘生成）或昨天（如果复盘用了旧 staging）
# 仅检查文件修改时间是否在合理范围内

if failures:
    for f_item in failures:
        print(f'B1:FAIL: {f_item}')
else:
    print('B1:PASS: 所有 8 个章节完整')
" 2>&1
```

### B2: staging/今日-复盘分析.md 章节完整性

读取文件内容，检查以下 5 个章节全部存在且非空：

1. **一、我的持仓（基线快照）** — 含代码+数量+成本价；标注"基线"
2. **二、今日核心回顾** — 含核心特征(1句)+核心教训(≥2条可操作)+明日核心变量(≥3个具体变量)
3. **三、特别关注项** — 3-6条，含触发条件和影响路径
4. **四、跨品种联动约束（最新版）** — 含校准参数和验证状态
5. **五、前次预测评估** — 逐条预测vs实际+准确率+根因

```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import os, sys

f = 'my_doc/每日复盘/harness/staging/今日-复盘分析.md'
if not os.path.exists(f):
    print('B2:FAIL: staging/今日-复盘分析.md 不存在')
    sys.exit(0)

with open(f, 'r', encoding='utf-8') as fh:
    content = fh.read()

required_sections = [
    '我的持仓',
    '核心回顾',
    '特别关注项',
    '跨品种联动约束',
    '前次预测评估'
]

failures = []
for section in required_sections:
    if section not in content:
        failures.append(f'MISSING: 「{section}」')
    else:
        idx = content.index(section)
        after = content[idx+len(section):idx+len(section)+500]
        if len(after.strip()) < 50:
            failures.append(f'EMPTY: 「{section}」')

# 额外检查：核心教训至少2条
import re
lessons = re.findall(r'\d+\.\s*\*\*.*?\*\*', content)
# 在「核心教训」区域至少找到2条
lesson_section = content.split('核心教训')
if len(lesson_section) >= 2:
    lesson_text = lesson_section[1].split('###')[0] if '###' in lesson_section[1] else lesson_section[1][:1000]
    lesson_count = len(re.findall(r'\d+\.\s*\*\*', lesson_text))
    if lesson_count < 2:
        failures.append(f'核心教训不足: 仅{lesson_count}条（需要≥2条）')

# 额外检查：核心变量至少3个
var_section = content.split('核心变量')
if len(var_section) >= 2:
    var_text = var_section[1].split('###')[0] if '###' in var_section[1] else var_section[1][:1500]
    var_count = len(re.findall(r'-\s*\*\*', var_text))
    if var_count < 3:
        failures.append(f'核心变量不足: 仅{var_count}个（需要≥3个）')

if failures:
    for f_item in failures:
        print(f'B2:FAIL: {f_item}')
else:
    print('B2:PASS: 所有 5 个章节完整，核心教训≥2条，核心变量≥3个')
" 2>&1
```

### B3: ETF 代码-名称交叉校验

**必须机械化比对——复制 auto_evening_review.md §9.3 的 Python 校验脚本：**

```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import re, sys

# 1. 读取权威持仓配置
with open('my_doc/每日复盘/harness/config/持仓.md', 'r', encoding='utf-8') as f:
    config = f.read()

code_to_name = {}
for line in config.split('\n'):
    parts = [p.strip() for p in line.split('|')[1:-1]]
    if len(parts) >= 2 and parts[1].isdigit() and len(parts[1]) == 6:
        code_to_name[parts[1]] = parts[0]

print(f'权威映射: {code_to_name}')

# 2. 检查 staging 文件
errors = []
for staging_file in [
    'my_doc/每日复盘/harness/staging/今日-早盘分析.md',
    'my_doc/每日复盘/harness/staging/今日-复盘分析.md'
]:
    try:
        with open(staging_file, 'r', encoding='utf-8') as f:
            content = f.read()
        for line in content.split('\n'):
            parts = [p.strip() for p in line.split('|')[1:-1]]
            if len(parts) >= 2 and parts[1].isdigit() and len(parts[1]) == 6:
                code = parts[1]
                name_in_staging = parts[0]
                name_in_config = code_to_name.get(code)
                if name_in_config and name_in_staging != name_in_config:
                    errors.append(f'{staging_file}: 代码{code} staging=\"{name_in_staging}\" config=\"{name_in_config}\"')
    except FileNotFoundError:
        print(f'WARNING: {staging_file} 不存在，跳过校验')

if errors:
    print(f'B3:FAIL: {len(errors)} code-name mismatches:')
    for e in errors:
        print(f'  {e}')
else:
    print('B3:PASS: All staging code-name mappings match config/持仓.md')
" 2>&1
```

**处理**：
- B1/B2/B3 PASS → 记录日志
- B1/B2/B3 FAIL → 创建 BUG
  - B3（代码名称不匹配）→ `auto_fix_eligible=true`（确定性重命名修复），状态 OPEN
  - B1/B2（章节缺失）→ `auto_fix_eligible=false`（需要判断为什么），状态 MANUAL_REVIEW
- **非交易日**：B1/B2 若章节完整但日期为旧 → WARN（非 FAIL）

---

## C 组：报告章节对齐（4 条，仅交易日执行）

> ⚠️ 如果第〇步判断为非交易日，跳过整个 C 组。

### C1: reports/{today}/早盘报告.md 章节完整性

```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import os, sys
from datetime import date
today = date.today().strftime('%Y%m%d')
f = f'my_doc/每日复盘/reports/{today}/早盘报告.md'

if not os.path.exists(f):
    print('C1:FAIL: 早盘报告.md 不存在')
    sys.exit(0)

with open(f, 'r', encoding='utf-8') as fh:
    content = fh.read()

# Required sections per 早盘分析-模板.md
required = [
    ('我的持仓', '持仓表'),
    ('宏观研判', '大盘方向+核心矛盾+反面情景+数据时区'),
    ('板块机会扫描', 'N≥3个板块+七维评分表+建仓建议'),
    ('持仓映射', '逐只评分+做T建议+做T纪律'),
    ('操作清单', '优先级+时间表+跨品种约束'),
    ('预判回顾', '预测vs实际+根因+今日改进'),
]

failures = []
for keyword, desc in required:
    if keyword not in content:
        failures.append(f'MISSING: 「{desc}」({keyword})')
    else:
        idx = content.index(keyword)
        after = content[idx+len(keyword):idx+len(keyword)+300]
        if len(after.strip()) < 50:
            failures.append(f'EMPTY: 「{desc}」({keyword})')

if failures:
    for f_item in failures:
        print(f'C1:FAIL: {f_item}')
else:
    print('C1:PASS: 所有核心章节完整')
" 2>&1
```

### C2: reports/{today}/每日信号.md 章节完整性

```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import os, sys
from datetime import date
today = date.today().strftime('%Y%m%d')
f = f'my_doc/每日复盘/reports/{today}/每日信号.md'

if not os.path.exists(f):
    print('C2:FAIL: 每日信号.md 不存在')
    sys.exit(0)

with open(f, 'r', encoding='utf-8') as fh:
    content = fh.read()

# Required sections per 早盘分析-模板.md §九
required_sections = [
    '信号总表',
    '信号触发记录',
    '盘中验证记录',
    '信号评价',
    '当日信号统计',
    '信号收益追踪',
    '信号与早盘报告对照'
]

failures = []
for section in required_sections:
    if section not in content:
        failures.append(f'MISSING: 「{section}」')

# 复盘完成后信号评价表不能为空
if '信号评价（复盘时填入）' in content:
    eval_section = content.split('信号评价（复盘时填入）')
    if len(eval_section) >= 2:
        eval_text = eval_section[1].split('## ')[0] if '## ' in eval_section[1] else eval_section[1]
        data_rows = [l for l in eval_text.split('\n') if l.strip().startswith('|') and not l.strip().startswith('|--') and '信号ID' not in l and '决策质量' not in l]
        if len(data_rows) == 0:
            failures.append('信号评价表为空（复盘完成后必须填充）')

# 当日信号统计不能全为 —
if '当日信号统计' in content:
    stat_section = content.split('当日信号统计')
    if len(stat_section) >= 2:
        stat_text = stat_section[1].split('## ')[0] if '## ' in stat_section[1] else stat_section[1]
        dash_count = stat_text.count('—')
        if dash_count > 2:
            failures.append(f'当日信号统计有 {dash_count} 个未填充的占位符(—)')

if failures:
    for f_item in failures:
        print(f'C2:FAIL: {f_item}')
else:
    print('C2:PASS: 所有必需节完整')
" 2>&1
```

### C3: reports/{today}/复盘报告.md 章节完整性

```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import os, sys
from datetime import date
today = date.today().strftime('%Y%m%d')
f = f'my_doc/每日复盘/reports/{today}/复盘报告.md'

if not os.path.exists(f):
    print('C3:FAIL: 复盘报告.md 不存在')
    sys.exit(0)

with open(f, 'r', encoding='utf-8') as fh:
    content = fh.read()

# Required sections per 复盘分析-模板.md §四
required = [
    ('我的持仓', '最新持仓数据+今日操作列'),
    ('大市表现复盘', '三大指数+成交量+北向+涨跌家数'),
    ('持仓复盘', '逐只涨跌幅+开盘缺口+日内波动'),
    ('早盘预判', '方向预测准确率表+错误归因'),
    ('信号遗漏', '五个必答问题'),
    ('经验沉淀', '写入experience/的条目'),
    ('持仓变更', '新增/移除/变更记录'),
    ('Staging', '生成确认+归档+校验'),
    ('信号收益', '本日结算+累计统计'),
]

failures = []
for keyword, desc in required:
    if keyword not in content:
        failures.append(f'MISSING: 「{desc}」({keyword})')
    else:
        idx = content.index(keyword)
        after = content[idx+len(keyword):idx+len(keyword)+300]
        if len(after.strip()) < 50:
            failures.append(f'EMPTY: 「{desc}」({keyword})')

if failures:
    for f_item in failures:
        print(f'C3:FAIL: {f_item}')
else:
    print('C3:PASS: 所有核心章节完整')
" 2>&1
```

### C4: 报告产出与 task_state 一致性

```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import json, os
from datetime import date
today = date.today().strftime('%Y%m%d')

# 读取 task_state
try:
    with open('my_doc/每日复盘/harness/automation/config/task_state.json', 'r') as f:
        state = json.load(f)
except:
    print('C4:WARN: task_state.json 不存在或损坏')
    exit(0)

tasks = state.get('tasks', {})
errors = []

# morning_analysis=completed → 早盘报告 + 每日信号 必须存在
ma = tasks.get('morning_analysis', {})
if ma.get('status') == 'completed':
    for report_file in [f'my_doc/每日复盘/reports/{today}/早盘报告.md', f'my_doc/每日复盘/reports/{today}/每日信号.md']:
        if not os.path.exists(report_file):
            errors.append(f'morning_analysis=completed 但 {report_file} 缺失')

# evening_review=completed → 复盘报告 必须存在
er = tasks.get('evening_review', {})
if er.get('status') == 'completed':
    report_file = f'my_doc/每日复盘/reports/{today}/复盘报告.md'
    if not os.path.exists(report_file):
        errors.append(f'evening_review=completed 但 {report_file} 缺失')
    if not er.get('staging_generated'):
        print('C4:WARN: evening_review=completed 但 staging_generated 字段为空')

if errors:
    for e in errors:
        print(f'C4:FAIL: {e}')
else:
    print('C4:PASS: task_state 与报告产出一致')
" 2>&1
```

**处理**：
- PASS → 记录日志
- FAIL → 创建 BUG（`auto_fix_eligible=false`，MANUAL_REVIEW — 需要判断是复盘未完成还是文件生成失败）

---

## D 组：数据一致性（3 条）

### D1: config/持仓.md 与 每日调仓.md 持仓一致

**复制 auto_evening_review.md §10.2 的验证脚本**（已在生产验证）：

```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import re, sys

with open('my_doc/每日复盘/每日调仓.md', 'r', encoding='utf-8') as f:
    content = f.read()
match = re.search(r'## 1\.\s*当前持仓\s*\n\s*\n(\|.+\|\s*\n(?:\|.+\|\s*\n)+)', content)
if not match:
    print('D1:FAIL: 无法解析每日调仓.md的当前持仓表')
    sys.exit(1)
lines = [l for l in match.group(1).strip().split('\n') if l.strip()]
src_holdings = {}
for line in lines:
    parts = [p.strip() for p in line.split('|')[1:-1]]
    if parts and parts[0] not in ('股票名称','--------','------') and len(parts)>=4 and parts[1].isdigit():
        src_holdings[parts[1]] = (parts[0], parts[2], parts[3])

with open('my_doc/每日复盘/harness/config/持仓.md', 'r', encoding='utf-8') as f:
    cfg = f.read()
cfg_holdings = {}
for line in cfg.split('\n'):
    parts = [p.strip() for p in line.split('|')[1:-1]]
    if parts and parts[0] not in ('股票名称','--------','------','') and len(parts)>=3 and parts[1].isdigit() and len(parts[1])==6:
        cfg_holdings[parts[1]] = (parts[0], parts[2], parts[3])

errors = []
for code, (name, shares, cost) in src_holdings.items():
    if code not in cfg_holdings:
        errors.append(f'MISSING in config: {name}({code}) {shares}份 @{cost}')
    else:
        cn, cs, cc = cfg_holdings[code]
        if cs != shares or cc != cost:
            errors.append(f'MISMATCH: {name}({code}) src={shares}@{cost} config={cs}@{cc}')

for code in cfg_holdings:
    if code not in src_holdings:
        errors.append(f'STALE in config: {cfg_holdings[code][0]}({code})')

if errors:
    print(f'D1:FAIL: {len(errors)} inconsistencies:')
    for e in errors:
        print(f'  {e}')
else:
    print(f'D1:PASS: config/持仓.md 与 每日调仓.md 一致 ({len(src_holdings)} 个持仓)')
" 2>&1
```

### D2: task_state.json 日期与交易日字段正确

```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import json
from datetime import date

today = date.today().strftime('%Y%m%d')
try:
    with open('my_doc/每日复盘/harness/automation/config/task_state.json', 'r') as f:
        state = json.load(f)
    state_date = state.get('date', 'UNKNOWN')
    trading_day = state.get('trading_day', None)
    if state_date != today:
        print(f'D2:WARN: task_state date={state_date} != today={today}')
    else:
        print(f'D2:PASS: task_state date={today}, trading_day={trading_day}')
except Exception as e:
    print(f'D2:FAIL: 读取 task_state.json 失败: {e}')
" 2>&1
```

**非交易日校准**：date 不匹配 → WARN（非 FAIL）。

### D3: signal_tracking.json 无孤立信号

```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import json, os, glob
from datetime import date, timedelta

tracking_file = 'my_doc/每日复盘/harness/automation/config/signal_tracking.json'
if not os.path.exists(tracking_file):
    print('D3:WARN: signal_tracking.json 不存在')
    exit(0)

with open(tracking_file, 'r', encoding='utf-8') as f:
    db = json.load(f)

signals = db.get('signals', [])
if not signals:
    print('D3:PASS: signal_tracking 为空（无追踪中的信号）')
    exit(0)

# 检查 status='open' 超过 30 天的信号（孤立/遗忘信号）
stale_signals = []
for sig in signals:
    if sig.get('status') in ('open',):
        trigger_date = sig.get('trigger_date', '')
        if trigger_date:
            try:
                td = date.fromisoformat(trigger_date)
                days_open = (date.today() - td).days
                if days_open > 30:
                    stale_signals.append(f'{sig[\"signal_id\"]}: {sig.get(\"ticker\",\"?\")} {sig.get(\"trade_type\",\"?\")} open {days_open}天')
            except:
                pass

if stale_signals:
    print(f'D3:WARN: {len(stale_signals)} 个信号 open > 30天（可能已遗忘）:')
    for s in stale_signals:
        print(f'  {s}')
else:
    print(f'D3:PASS: 无孤立信号（{len(signals)} 条追踪中）')
" 2>&1
```

**处理**：
- D1 FAIL → 创建 BUG（`auto_fix_eligible=true`，确定性修复 — 从每日调仓.md 重新同步）
- D2 PASS/WARN → 记录日志（WARN 不创建 BUG）
- D3 WARN → 创建 BUG（`auto_fix_eligible=false`，MANUAL_REVIEW — 需要判断信号是否确实应保持 open）

---

## E 组：经验与元数据健康（2 条）

### E1: experience/ 三份文件无内容矛盾

**LLM 语义审查**（此条必须由 LLM 判断，不能用 Python 脚本替代）：

1. 读取 `harness/experience/投资经验.md`、`harness/experience/短线机会经验.md`、`harness/experience/报告审阅经验.md`
2. 逐对比较，检查是否有逻辑矛盾。重点关注：
   - 投资经验 vs 短线经验：是否存在方向性矛盾（如投资经验说"不追高"但短线经验鼓励"突破追入"而不加条件限定）
   - 报告审阅经验 vs 投资经验：审阅规则是否与投资规则一致
   - 同一文件内部是否存在自相矛盾（如两个条目给出相反建议）
3. 判断标准：如果两个条目给出**不加条件限定的相反建议** → 矛盾；如果加了不同场景的限制条件 → 不矛盾

**输出**：
- `E1:PASS: 经验文件无内容矛盾`
- `E1:WARN: 发现潜在矛盾: {具体描述矛盾点}`

### E2: BUG_INDEX.md 统计数与实际文件一致

```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import os, re

# 统计实际文件
open_bugs = len([f for f in os.listdir('my_doc/每日复盘/harness/automation/bugs/open') if f.endswith('.md')]) if os.path.exists('my_doc/每日复盘/harness/automation/bugs/open') else 0
closed_bugs = len([f for f in os.listdir('my_doc/每日复盘/harness/automation/bugs/closed') if f.endswith('.md')]) if os.path.exists('my_doc/每日复盘/harness/automation/bugs/closed') else 0

# 读取 BUG_INDEX.md 中的统计
try:
    with open('my_doc/每日复盘/harness/automation/bugs/BUG_INDEX.md', 'r', encoding='utf-8') as f:
        index = f.read()
    # 提取统计表数据
    open_match = re.search(r'OPEN\s*\|\s*(\d+)', index)
    fixed_match = re.search(r'FIXED\s*\|\s*(\d+)', index)
    idx_open = int(open_match.group(1)) if open_match else -1
    idx_fixed = int(fixed_match.group(1)) if fixed_match else -1

    if idx_open == open_bugs and idx_fixed == closed_bugs:
        print(f'E2:PASS: BUG_INDEX 统计 (OPEN={idx_open}, FIXED={idx_fixed}) 与实际文件一致 (open={open_bugs}, closed={closed_bugs})')
    else:
        print(f'E2:FAIL: BUG_INDEX 统计 (OPEN={idx_open}, FIXED={idx_fixed}) != 实际文件 (open={open_bugs}, closed={closed_bugs})')
except Exception as e:
    print(f'E2:FAIL: 读取 BUG_INDEX.md 失败: {e}')
" 2>&1
```

**处理**：
- E1 WARN → 写入 PENDING_CONFIRMATION.md（需用户判断哪个经验正确）
- E2 FAIL → 创建 BUG（`auto_fix_eligible=true`，确定性修复 — 更新 BUG_INDEX 统计数）

---

## 巡检汇总与 BUG 创建

### 收集所有 FAIL/WARN 结果

汇总上述所有检查的输出，生成结构化的巡检报告。

### 去重检查

对每个 FAIL/WARN，搜索 `BUG_INDEX.md` 中是否已有同名文件+同类问题的 OPEN BUG。若有 → 更新已有 BUG 的处理记录而非新建。

### 创建 BUG

对需要创建 BUG 的 FAIL：
1. 按 `bugs/BUG_TEMPLATE.md` 格式创建 `bugs/open/BUG-{NNN}.md`
2. 更新 `bugs/BUG_INDEX.md`：BUG 列表添加新条目，统计表更新
3. 判断 `auto_fix_eligible`：
   - B3（代码名称不匹配）、D1（持仓不一致）、E2（BUG计数不一致）→ `true`
   - A1/A2/A3（归档缺失）、B1/B2（章节缺失）、C1-C4（报告章节缺失）、E1（经验矛盾）→ `false`（MANUAL_REVIEW）
   - D2（日期偏旧）→ WARN 不创建 BUG
   - D3（孤立信号）→ `false`（MANUAL_REVIEW）

### 更新 PENDING_CONFIRMATION.md

对 MANUAL_REVIEW 且需用户决策的 BUG：
1. 读取 `PENDING_CONFIRMATION.md`（如不存在则创建）
2. 追加新条目到 `## 待确认` 表
3. 每行格式：`| {序号} | {MM-DD} | {BUG-ID} | {问题摘要} | {P1/P2/P3} | +{N}天 |`

### 输出巡检报告

```
=== 逻辑巡检报告 {today} ===
交易日: {是/否}
执行时间: {ISO时间戳}

A 组 (归档完整性):
  A1: {PASS/FAIL/WARN} — {详情}
  A2: {PASS/FAIL/WARN} — {详情}

B 组 (Staging 章节对齐):
  B1: {PASS/FAIL/WARN} — {详情}
  B2: {PASS/FAIL/WARN} — {详情}
  B3: {PASS/FAIL/WARN} — {详情}

C 组 (报告章节对齐):
  C1: {PASS/FAIL/WARN/skipped} — {详情}
  ...

D 组 (数据一致性):
  ...

E 组 (经验与元数据):
  ...

总计: {PASS} PASS, {FAIL} FAIL, {WARN} WARN
新增 BUG: {N} | PENDING_CONFIRMATION: {M} 项
```

### 写入执行日志

追加到 `my_doc/每日复盘/harness/automation/logs/logic_inspect_{today}.log`

---

## 异常处理

| 异常 | 处理 |
|------|------|
| Python 脚本执行失败 | 记录错误，跳过该条检查，标记为 ERROR |
| BUG_INDEX.md 不存在 | 创建初始化的 BUG_INDEX.md |
| bugs/open/ 目录不存在 | mkdir -p 创建 |
| PENDING_CONFIRMATION.md 不存在 | 创建含表头的空模板 |
| 非交易日但 staging 不存在 | 预期的正常情况，WARN 不 FAIL |
| 交易日但 reports/{today}/ 目录不存在 | FAIL — 创建 BUG（复盘可能未执行） |
```

- [ ] **Step 2: Verify file created and has expected size**

Run: `bash -c 'wc -c < "my_doc/每日复盘/harness/automation/prompts/auto_logic_inspect.md"'`
Expected: file size > 5000 bytes (substantial prompt with all 14 checks)

- [ ] **Step 3: Commit Task 1 + Task 2 prompts**

```bash
git add my_doc/每日复盘/harness/automation/prompts/auto_pending_remind.md my_doc/每日复盘/harness/automation/prompts/auto_logic_inspect.md
git commit -m "feat(harness): add logic_inspect and pending_remind automation prompts

- auto_logic_inspect.md: 14 inspection items across 5 groups (A-E)
  - A: archive completeness (2 items)
  - B: staging chapter alignment (3 items)
  - C: report chapter alignment (4 items, trading days only)
  - D: data consistency (3 items)
  - E: experience & metadata health (2 items)
- auto_pending_remind.md: bi-hourly scan of PENDING_CONFIRMATION.md

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Update `task_schedule.json` — Add 2 New Schedule Entries

**Files:**
- Modify: `.claude/scripts/task_schedule.json`

- [ ] **Step 1: Add `logic_inspect` task entry**

Insert after the `evening_review` task entry (line 86 in current file). Add:

```json
    {
      "task_id": "logic_inspect",
      "target_time": "17:07",
      "days_of_week": [0, 1, 2, 3, 4, 5, 6],
      "trading_day_required": false,
      "prompt_file": "my_doc/每日复盘/harness/automation/prompts/auto_logic_inspect.md",
      "window_minutes": 7,
      "description": "逻辑巡检 (每天17:07)"
    },
```

- [ ] **Step 2: Add `pending_remind` task entry**

Insert after the `harness_bug_auto_fix` task entry (last task). Add:

```json
    {
      "task_id": "pending_remind",
      "hourly": true,
      "target_minute": 13,
      "hourly_range": [9, 11, 13, 15, 17, 19, 21],
      "days_of_week": [0, 1, 2, 3, 4, 5, 6],
      "trading_day_required": false,
      "prompt_file": "my_doc/每日复盘/harness/automation/prompts/auto_pending_remind.md",
      "window_minutes": 7,
      "description": "待确认事项提醒 (每2小时 :13)"
    }
```

- [ ] **Step 3: Verify JSON validity**

Run: `python -c "import json; json.load(open('.claude/scripts/task_schedule.json')); print('JSON valid')"`
Expected: `JSON valid`

- [ ] **Step 4: Commit**

```bash
git add .claude/scripts/task_schedule.json
git commit -m "feat(scheduler): add logic_inspect (17:07 daily) and pending_remind (bi-hourly) tasks

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Initialize `PENDING_CONFIRMATION.md`

**Files:**
- Create: `my_doc/每日复盘/harness/automation/PENDING_CONFIRMATION.md`

- [ ] **Step 1: Create empty template**

```markdown
# 待确认事项

> 由逻辑巡检（`auto_logic_inspect`）自动维护。用户确认后在事项行末标注 `✅已确认` 或 `❌驳回`。
> 提醒任务 `auto_pending_remind` 每 2 小时扫描此文件。

## 待确认 (0)

| # | 日期 | 来源BUG | 事项 | 优先级 | 截止时间 |
|---|------|---------|------|:---:|---------|
| (暂无) | — | — | — | — | — |

## 已确认 (0)

| # | 日期 | 来源BUG | 事项 | 结果 | 确认日期 |
|---|------|---------|------|------|---------|
| (暂无) | — | — | — | — | — |
```

- [ ] **Step 2: Commit**

```bash
git add my_doc/每日复盘/harness/automation/PENDING_CONFIRMATION.md
git commit -m "feat(harness): initialize PENDING_CONFIRMATION.md for user notification workflow

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Update `harness/README.md` — Architecture Diagram + New Tasks

**Files:**
- Modify: `my_doc/每日复盘/harness/README.md`

- [ ] **Step 1: Add architecture diagram**

Replace the current "## 每日工作流" section with a comprehensive architecture diagram:

```markdown
## 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                    每日复盘 Harness 层                        │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ 自动化调度层 (.claude/scripts/task_schedule.json)      │   │
│  │                                                       │   │
│  │  morning_analysis 09:07 交易日  ──→ 早盘分析           │   │
│  │  intraday_0940~1430 交易日  ──→ 盘中检查 ×8           │   │
│  │  evening_review    15:52 交易日  ──→ 收盘复盘           │   │
│  │  logic_inspect     17:07 每天    ──→ 逻辑巡检 ★新增    │   │
│  │  pending_remind    :13/2h 每天   ──→ 待确认提醒 ★新增  │   │
│  │  experience_health 12:47 周三   ──→ 经验库健康          │   │
│  │  weekly_portfolio  13:17 周四   ──→ 周度组合回顾        │   │
│  │  req_implement     12:57 交易日 ──→ REQ自动实施          │   │
│  │  harness_bug_auto_fix :17/h 交易日 → BUG自动修复        │   │
│  │                                                       │   │
│  │  + etf-strategies BUG/scan 任务 (并行运行)             │   │
│  └───────────────────────┬───────────────────────────────┘   │
│                          │                                   │
│         ┌────────────────┼────────────────┐                  │
│         ▼                ▼                ▼                  │
│  ┌──────────┐   ┌──────────────┐   ┌──────────────┐        │
│  │ prompts/ │   │ experience/  │   │ automation/  │        │
│  │ 永久模板  │   │ 经验沉淀     │   │ 自动化系统    │        │
│  │          │   │              │   │              │        │
│  │ 早盘分析 │   │ 投资经验     │   │ prompts/     │        │
│  │ 复盘分析 │   │ 短线经验     │   │ config/      │        │
│  │ 盘中分析 │   │ 报告审阅     │   │ bugs/        │        │
│  └──────────┘   └──────────────┘   │ steering/    │        │
│                                     │ logs/        │        │
│  ┌──────────┐   ┌──────────────┐   │ tests/       │        │
│  │ staging/ │   │ archive/     │   │ lib/         │        │
│  │ 今日可执 │   │ 历史归档     │   │ PENDING_     │        │
│  │ 行prompt │   │              │   │ CONFIRMATION │ ★新增  │
│  │ (每日覆盖)│   │ 按日期存放   │   └──────────────┘        │
│  └──────────┘   └──────────────┘                           │
│         │                ▲                                  │
│         └────────────────┘                                  │
│          每日复盘后归档                                       │
└─────────────────────────────────────────────────────────────┘
```

## 目录说明

| 目录 | 用途 | 修改频率 |
|------|------|---------|
| `prompts/` | 永久模板：早盘分析和复盘分析的方法论框架 | 偶有优化，不含日期特定内容 |
| `experience/` | 经验沉淀：投资经验、短线经验、报告审阅标准 | 每次复盘后追加 |
| `config/` | 日度配置：当前持仓快照 | 调仓时更新 |
| `staging/` | 当日可执行 prompt：由昨日复盘生成，每日覆盖 | 每日覆盖 |
| `archive/` | 历史 prompt 归档：按日期保存每日使用的 prompt | 每日追加 |
| `automation/` | 自动化系统：定时任务 prompts、配置、BUG 跟踪、REQ Steering、测试、日志 | 持续演进 |
```

- [ ] **Step 2: Add new tasks to the task table in README**

Add after the existing workfow description:

```markdown
## 自动化任务一览

| 任务 | 时间 | 频率 | 需交易日 | 用途 |
|------|------|------|:---:|------|
| morning_analysis | 09:07 | 交易日 | ✓ | 早盘分析 |
| intraday_* ×8 | 09:40-14:30 | 交易日 | ✓ | 盘中监控 |
| evening_review | 15:52 | 交易日 | ✓ | 收盘复盘 |
| **logic_inspect** | **17:07** | **每天** | **✗** | **逻辑巡检：14条规则检查文件内容合理性和一致性** |
| **pending_remind** | **:13/2h** | **每天** | **✗** | **待确认事项提醒：扫描 PENDING_CONFIRMATION.md** |
| experience_health | 12:47 | 周三 | ✗ | 经验库健康检查 |
| weekly_portfolio | 13:17 | 周四 | ✗ | 周度组合回顾 |
| req_implement | 12:57 | 交易日 | ✗ | REQ 自动实施 |
| harness_bug_auto_fix | :17/h | 交易日 | ✗ | BUG 自动修复 |
```

- [ ] **Step 3: Commit**

```bash
git add my_doc/每日复盘/harness/README.md
git commit -m "docs(harness): add architecture diagram and new task descriptions to README

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Update `CLAUDE.md` — Task Table + Architecture Diagram

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update §7.1 architecture diagram**

In `CLAUDE.md` §7.1, add the two new tasks to the architecture overview. Find the existing ASCII diagram and add the new tasks:

The existing diagram shows the automation layer. Add `auto_logic_inspect.md` and `auto_pending_remind.md` under the prompts directory. Also add `PENDING_CONFIRMATION.md` mention.

- [ ] **Step 2: Update §7.2 task table**

Add two new rows to the task table in §7.2:

```markdown
| logic_inspect | 17:07 | 每天 | ✗ | `auto_logic_inspect.md` |
| pending_remind | 每2h:13 (9-21) | 每天 | ✗ | `auto_pending_remind.md` |
```

Insert them after the `evening_review` row (or in logical order — after evening_review since 17:07 > 15:52).

- [ ] **Step 3: Update the total task count**

Change "14 条任务" to "16 条任务" in the section header and any other references.

- [ ] **Step 4: Update §7.5 关键纪律 — add PENDING_CONFIRMATION mention**

Add to the key disciplines:
```markdown
- **用户通知不静默**：逻辑巡检发现的需用户确认事项写入 `PENDING_CONFIRMATION.md`，`auto_pending_remind` 每 2 小时提醒
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(CLAUDE.md): add logic_inspect and pending_remind tasks to automation system docs

Co-Authored-By: Claude <noreply@anthropic.com>"
```
```

<｜｜DSML｜｜parameter name="new_string" string="true">## 异常处理

| 异常 | 处理 |
|------|------|
| Python 脚本执行失败 | 记录错误，跳过该条检查，标记为 ERROR |
| BUG_INDEX.md 不存在 | 创建初始化的 BUG_INDEX.md |
| bugs/open/ 目录不存在 | mkdir -p 创建 |
| PENDING_CONFIRMATION.md 不存在 | 创建含表头的空模板 |
| 非交易日但 staging 不存在 | 预期的正常情况，WARN 不 FAIL |
| 交易日但 reports/{today}/ 目录不存在 | FAIL — 创建 BUG（复盘可能未执行） |
```

- [ ] **Step 2: Verify file created and has expected size**

Run: `bash -c 'wc -c < "my_doc/每日复盘/harness/automation/prompts/auto_logic_inspect.md"'`
Expected: file size > 5000 bytes (substantial prompt with all 14 checks)

- [ ] **Step 3: Commit Task 1 + Task 2 prompts**

```bash
git add my_doc/每日复盘/harness/automation/prompts/auto_pending_remind.md my_doc/每日复盘/harness/automation/prompts/auto_logic_inspect.md
git commit -m "feat(harness): add logic_inspect and pending_remind automation prompts

- auto_logic_inspect.md: 14 inspection items across 5 groups (A-E)
  - A: archive completeness (2 items)
  - B: staging chapter alignment (3 items)  
  - C: report chapter alignment (4 items, trading days only)
  - D: data consistency (3 items)
  - E: experience & metadata health (2 items)
- auto_pending_remind.md: bi-hourly scan of PENDING_CONFIRMATION.md

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Update `task_schedule.json` — Add 2 New Schedule Entries

**Files:**
- Modify: `.claude/scripts/task_schedule.json`

**Interfaces:**
- Consumes: Prompt file paths from Task 1 (`auto_pending_remind.md`) and Task 2 (`auto_logic_inspect.md`)
- Produces: Updated schedule with 16 tasks (from 14)

- [ ] **Step 1: Add `logic_inspect` task entry**

Insert after the `evening_review` task entry. In the current file, this is after line 86 (the closing `}` of the evening_review task object). Add:

```json
    {
      "task_id": "logic_inspect",
      "target_time": "17:07",
      "days_of_week": [0, 1, 2, 3, 4, 5, 6],
      "trading_day_required": false,
      "prompt_file": "my_doc/每日复盘/harness/automation/prompts/auto_logic_inspect.md",
      "window_minutes": 7,
      "description": "逻辑巡检 (每天17:07)"
    },
```

- [ ] **Step 2: Add `pending_remind` task entry**

Insert after the `harness_bug_auto_fix` task entry (currently the last task). Add:

```json
    {
      "task_id": "pending_remind",
      "hourly": true,
      "target_minute": 13,
      "hourly_range": [9, 11, 13, 15, 17, 19, 21],
      "days_of_week": [0, 1, 2, 3, 4, 5, 6],
      "trading_day_required": false,
      "prompt_file": "my_doc/每日复盘/harness/automation/prompts/auto_pending_remind.md",
      "window_minutes": 7,
      "description": "待确认事项提醒 (每2小时 :13)"
    }
```

- [ ] **Step 3: Verify JSON validity**

Run: `python -c "import json; json.load(open('.claude/scripts/task_schedule.json')); print('JSON valid')"`
Expected: `JSON valid`

- [ ] **Step 4: Commit**

```bash
git add .claude/scripts/task_schedule.json
git commit -m "feat(scheduler): add logic_inspect (17:07 daily) and pending_remind (bi-hourly) tasks

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Initialize `PENDING_CONFIRMATION.md`

**Files:**
- Create: `my_doc/每日复盘/harness/automation/PENDING_CONFIRMATION.md`

**Interfaces:**
- Produces: File read by `auto_pending_remind.md` (Task 1) and written to by `auto_logic_inspect.md` (Task 2)

- [ ] **Step 1: Create empty template**

```markdown
# 待确认事项

> 由逻辑巡检（`auto_logic_inspect`）自动维护。用户确认后在事项行末标注 `✅已确认` 或 `❌驳回`。
> 提醒任务 `auto_pending_remind` 每 2 小时扫描此文件。

## 待确认 (0)

| # | 日期 | 来源BUG | 事项 | 优先级 | 截止时间 |
|---|------|---------|------|:---:|---------|
| (暂无) | — | — | — | — | — |

## 已确认 (0)

| # | 日期 | 来源BUG | 事项 | 结果 | 确认日期 |
|---|------|---------|------|------|---------|
| (暂无) | — | — | — | — | — |
```

- [ ] **Step 2: Commit**

```bash
git add my_doc/每日复盘/harness/automation/PENDING_CONFIRMATION.md
git commit -m "feat(harness): initialize PENDING_CONFIRMATION.md for user notification workflow

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Update `harness/README.md` — Architecture Diagram + New Tasks

**Files:**
- Modify: `my_doc/每日复盘/harness/README.md`

**Interfaces:**
- Consumes: Task IDs and descriptions from Task 3 (`logic_inspect`, `pending_remind`)

- [ ] **Step 1: Read current README.md**

The current file is at `my_doc/每日复盘/harness/README.md` (read earlier — 40 lines). We will replace the "每日工作流" section and add new content.

- [ ] **Step 2: Replace "## 设计理念" through "## 如何触发"**

Replace the content between "## 目录说明" and "## 如何触发" with the updated architecture and task descriptions. The new content should be:

```markdown
## 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                    每日复盘 Harness 层                        │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │ 自动化调度层 (.claude/scripts/task_schedule.json)      │   │
│  │                                                       │   │
│  │  morning_analysis 09:07 交易日  ──→ 早盘分析           │   │
│  │  intraday_0940~1430 交易日  ──→ 盘中检查 ×8           │   │
│  │  evening_review    15:52 交易日  ──→ 收盘复盘           │   │
│  │  logic_inspect     17:07 每天    ──→ 逻辑巡检 ★新增    │   │
│  │  pending_remind    :13/2h 每天   ──→ 待确认提醒 ★新增  │   │
│  │  experience_health 12:47 周三   ──→ 经验库健康          │   │
│  │  weekly_portfolio  13:17 周四   ──→ 周度组合回顾        │   │
│  │  req_implement     12:57 交易日 ──→ REQ自动实施          │   │
│  │  harness_bug_auto_fix :17/h 交易日 → BUG自动修复        │   │
│  │                                                       │   │
│  │  + etf-strategies BUG/scan 任务 (并行运行)             │   │
│  └───────────────────────┬───────────────────────────────┘   │
│                          │                                   │
│         ┌────────────────┼────────────────┐                  │
│         ▼                ▼                ▼                  │
│  ┌──────────┐   ┌──────────────┐   ┌──────────────┐        │
│  │ prompts/ │   │ experience/  │   │ automation/  │        │
│  │ 永久模板  │   │ 经验沉淀     │   │ 自动化系统    │        │
│  │          │   │              │   │              │        │
│  │ 早盘分析 │   │ 投资经验     │   │ prompts/     │        │
│  │ 复盘分析 │   │ 短线经验     │   │ config/      │        │
│  │ 盘中分析 │   │ 报告审阅     │   │ bugs/        │        │
│  └──────────┘   └──────────────┘   │ steering/    │        │
│                                     │ logs/        │        │
│  ┌──────────┐   ┌──────────────┐   │ tests/       │        │
│  │ staging/ │   │ archive/     │   │ lib/         │        │
│  │ 今日可执 │   │ 历史归档     │   │ PENDING_     │        │
│  │ 行prompt │   │              │   │ CONFIRMATION │ ★新增  │
│  │ (每日覆盖)│   │ 按日期存放   │   └──────────────┘        │
│  └──────────┘   └──────────────┘                           │
│         │                ▲                                  │
│         └────────────────┘                                  │
│          每日复盘后归档                                       │
└─────────────────────────────────────────────────────────────┘
```

## 设计理念

遵循 **Harness Engineering** 三支柱：

1. **Context Management（上下文管理）**：模板、经验、配置分层存放，按需加载，避免全量注入
2. **Tool Use（工具使用）**：`a-stock-data` 取数 + Skill 流程编排
3. **Evaluation Loop（评估回路）**：复盘 = Generator-Evaluator，报告审阅经验 = 质量门

核心原则：**"信 harness，不信 AI"** — 把流程执行从 LLM 推理中外化到结构化框架中。

## 自动化任务一览

| 任务 | 时间 | 频率 | 需交易日 | 用途 |
|------|------|------|:---:|------|
| morning_analysis | 09:07 | 交易日 | ✓ | 早盘分析 |
| intraday_* ×8 | 09:40-14:30 | 交易日 | ✓ | 盘中监控 |
| evening_review | 15:52 | 交易日 | ✓ | 收盘复盘 |
| **logic_inspect** | **17:07** | **每天** | **✗** | **逻辑巡检：14条规则检查文件内容合理性和一致性** |
| **pending_remind** | **:13/2h** | **每天** | **✗** | **待确认事项提醒：扫描 PENDING_CONFIRMATION.md** |
| experience_health | 12:47 | 周三 | ✗ | 经验库健康检查 |
| weekly_portfolio | 13:17 | 周四 | ✗ | 周度组合回顾 |
| req_implement | 12:57 | 交易日 | ✗ | REQ 自动实施 |
| harness_bug_auto_fix | :17/h | 交易日 | ✗ | BUG 自动修复 |

## 每日工作流

```
盘前: 读 staging/今日-早盘分析.md → 执行早盘分析 → 产出早盘报告
收盘: 读 staging/今日-复盘分析.md → 执行复盘分析 → 产出复盘报告
      → 经验沉淀 → 生成次日 staging → 归档当日 prompt
17:07: 逻辑巡检 → 14条规则 → BUG + PENDING_CONFIRMATION
每2h:  待确认提醒 → 扫描 PENDING_CONFIRMATION → 有则提醒
```

- [ ] **Step 3: Commit**

```bash
git add my_doc/每日复盘/harness/README.md
git commit -m "docs(harness): add architecture diagram and new task descriptions to README

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Update `CLAUDE.md` — Task Table + Architecture

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: Task IDs and descriptions from Task 3

- [ ] **Step 1: Locate §7.2 task table**

The task table is in `CLAUDE.md` §7.2 "全部 14 条任务调度".

- [ ] **Step 2: Add `logic_inspect` row**

Insert after the `evening_review` row:

```markdown
| logic_inspect | 17:07 | 每天 | ✗ | `auto_logic_inspect.md` |
```

- [ ] **Step 3: Add `pending_remind` row**

Insert after `harness_bug_auto_fix` row:

```markdown
| pending_remind | 每2h:13 (9-21) | 每天 | ✗ | `auto_pending_remind.md` |
```

- [ ] **Step 4: Update section header**

Change `### 7.2 全部 14 条任务调度` to `### 7.2 全部 16 条任务调度`

- [ ] **Step 5: Update §7.5 key disciplines**

Add to the bullet list in §7.5 关键纪律:

```markdown
- **用户通知不静默**：逻辑巡检发现的 MANUAL_REVIEW BUG 写入 `PENDING_CONFIRMATION.md`，`auto_pending_remind` 每 2 小时扫描并提醒，确保用户感知待确认事项
```

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(CLAUDE.md): add logic_inspect and pending_remind to task table (14→16)

Co-Authored-By: Claude <noreply@anthropic.com>"
```
```

<｜｜DSML｜｜parameter name="file_path" string="true">E:\ideaworkspace\astock-anayisis\docs\superpowers\plans\2026-07-30-logic-inspect-plan.md