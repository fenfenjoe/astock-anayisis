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

python -X utf8 -c "
import os, sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.staging_verify import check_sections

f = 'my_doc/每日复盘/harness/staging/今日-早盘分析.md'
if not os.path.exists(f):
    print('B1:FAIL: staging/今日-早盘分析.md 不存在')
    sys.exit(0)

content = open(f, 'r', encoding='utf-8').read()
required = ['我的持仓','事件日历','核心矛盾','数据收集','板块机会扫描',
            '持仓映射','操作清单','上期预判回顾','上期信号回顾','信号生成指令']
failures = check_sections(content, required, path_label=f)
if failures:
    for f_item in failures:
        print(f'B1:FAIL: {f_item}')
else:
    print('B1:PASS: 所有 8 个章节完整')
" 2>&1

### B2: staging/今日-复盘分析.md 章节完整性

读取文件内容，检查以下 5 个章节全部存在且非空：

1. **一、我的持仓（基线快照）** — 含代码+数量+成本价；标注"基线"
2. **二、今日核心回顾** — 含核心特征(1句)+核心教训(≥2条可操作)+明日核心变量(≥3个具体变量)
3. **三、特别关注项** — 3-6条，含触发条件和影响路径
4. **四、跨品种联动约束（最新版）** — 含校准参数和验证状态
5. **五、前次预测评估** — 逐条预测vs实际+准确率+根因

```bash

python -X utf8 -c "
import os, sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.staging_verify import check_sections, check_lessons_and_vars

f = 'my_doc/每日复盘/harness/staging/今日-复盘分析.md'
if not os.path.exists(f):
    print('B2:FAIL: staging/今日-复盘分析.md 不存在')
    sys.exit(0)

content = open(f, 'r', encoding='utf-8').read()
required = ['我的持仓','特别关注项','板块扫描验证','做T验证','信号执行复盘','核心回顾']
failures = check_sections(content, required, path_label=f)
failures += check_lessons_and_vars(content)
if failures:
    for f_item in failures:
        print(f'B2:FAIL: {f_item}')
else:
    print('B2:PASS: 所有 5 个章节完整，核心教训≥2条，核心变量≥3个')
" 2>&1

### B3: ETF 代码-名称交叉校验

**必须机械化比对——复制 auto_evening_review.md §9.3 的 Python 校验脚本：**

```bash

python -X utf8 -c "
import sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.staging_verify import check_etf_code_names

config = open('my_doc/每日复盘/harness/config/持仓.md', encoding='utf-8').read()
errors = []
for staging_file in ['my_doc/每日复盘/harness/staging/今日-早盘分析.md',
                     'my_doc/每日复盘/harness/staging/今日-复盘分析.md']:
    try:
        content = open(staging_file, encoding='utf-8').read()
        errors += check_etf_code_names(config, content, staging_file)
    except FileNotFoundError:
        print(f'WARNING: {staging_file} 不存在，跳过校验')

if errors:
    print(f'B3:FAIL: {len(errors)} code-name mismatches:')
    for e in errors:
        print(f'  {e}')
else:
    print('B3:PASS: All staging code-name mappings match config/持仓.md')
" 2>&1

### B4: Staging 新鲜度 — 复盘后必须刷新为明日可执行 prompt

> **铁律**：`evening_review=completed` → staging 文件必须已覆写为**明日**可执行内容。
> 不可跳过此步骤——复盘的最后一步就是生成次日 staging。上一日 staging 在复盘开始时已归档，
> 当前 staging 必须指向下一个交易日。

**检查方法**：

```bash

python -X utf8 -c "
import os, json, sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from datetime import date, datetime
from lib.staging_verify import check_review_staging

today = date.today().strftime('%Y%m%d')
failures = []

# 1. 读取 task_state 确认 evening_review 是否完成
state_file = 'my_doc/每日复盘/harness/automation/config/task_state.json'
state = {}
if os.path.exists(state_file):
    with open(state_file, 'r') as f:
        state = json.load(f)

# 2. 读取两个 staging 文件信息
staging_files = [
    'my_doc/每日复盘/harness/staging/今日-早盘分析.md',
    'my_doc/每日复盘/harness/staging/今日-复盘分析.md'
]
results = []
for sf in staging_files:
    if not os.path.exists(sf):
        results.append({'path': sf, 'missing': True})
        continue
    with open(sf, 'r', encoding='utf-8') as fh:
        content = fh.read()
    results.append({
        'path': sf, 'content': content, 'missing': False,
        'mtime': datetime.fromtimestamp(os.path.getmtime(sf)),
        'size': os.path.getsize(sf),
    })

# 3. 新鲜度判定（lib 纯函数：豁免/STALE/OUTDATED/TOO_SMALL）
failures = check_review_staging(state, results, date.today().strftime('%Y-%m-%d'))

if failures:
    for f_item in failures:
        print(f'B4:FAIL: {f_item}')
else:
    print('B4:PASS: staging 文件新鲜，指向明日且内容充实')
" 2>&1

**处理**：
- PASS → 记录日志
- FAIL → 创建 BUG（`auto_fix_eligible=false`，MANUAL_REVIEW — **复盘流程违规：staging生成步骤被跳过**）
  - BUG 优先级：P1（影响次日早盘分析执行）
  - BUG 标题示例：`复盘完成但 staging 未刷新为明日可执行 prompt`
  - 修复建议：重新执行 staging 生成步骤（见 `daily-review-harness` skill §Staging Prompt 生成协议）
- **非交易日**：`evening_review=completed` 但同时 `intraday` 任务也未执行 → 标记今日为非交易日，B4 不检查（跳过），避免误报

**处理**：
- B1/B2/B3/B4 PASS → 记录日志
- B1/B2/B3/B4 FAIL → 创建 BUG
  - B3（代码名称不匹配）→ `auto_fix_eligible=true`（确定性重命名修复），状态 OPEN
  - B4（staging未刷新）→ `auto_fix_eligible=false`（复盘流程违规，需人工审视），状态 MANUAL_REVIEW
  - B1/B2（章节缺失）→ `auto_fix_eligible=false`（需要判断为什么），状态 MANUAL_REVIEW
- **非交易日**：B1/B2 若章节完整但日期为旧 → WARN（非 FAIL）

---

## C 组：报告章节对齐（4 条，仅交易日执行）

> ⚠️ 如果第〇步判断为非交易日，跳过整个 C 组。

### C1: reports/{today}/早盘报告.md 章节完整性

```bash

python -X utf8 -c "
import os, sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from datetime import date
from lib.staging_verify import check_sections
today = date.today().strftime('%Y%m%d')
f = 'f'my_doc/每日复盘/reports/{today}/早盘报告.md''
if not os.path.exists(f):
    print('C1:FAIL: 文件不存在 ' + f)
    sys.exit(0)
content = open(f, 'r', encoding='utf-8').read()
required = [('隔夜外盘','外盘总结'),('事件验证','日历核实'),('宏观研判','方向+矛盾'),
            ('板块机会扫描','评分表'),('持仓映射','逐只评分'),('操作清单','优先级'),('上期预判回顾','vs实际')]
failures = check_sections(content, required, path_label=f)
if failures:
    for f_item in failures:
        print(f'C1:FAIL: {f_item}')
else:
    print('C1:PASS: 所有核心章节完整')
" 2>&1

### C2: reports/{today}/每日信号.md 章节完整性

```bash

python -X utf8 -c "
import os, sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from datetime import date
from lib.staging_verify import check_sections
today = date.today().strftime('%Y%m%d')
f = 'f'my_doc/每日复盘/reports/{today}/每日信号.md''
if not os.path.exists(f):
    print('C2:FAIL: 文件不存在 ' + f)
    sys.exit(0)
content = open(f, 'r', encoding='utf-8').read()
required = [('信号总表','12列信号表'),('信号触发记录','触发记录'),('盘中验证记录','验证记录'),
            ('信号评价','决策/执行质量'),('当日信号统计','统计表'),('信号收益追踪','结算统计'),
            ('信号与早盘报告对照','对照表')]
failures = check_sections(content, required, path_label=f)
if failures:
    for f_item in failures:
        print(f'C2:FAIL: {f_item}')
else:
    print('C2:PASS: 所有核心章节完整')
" 2>&1

### C3: reports/{today}/复盘报告.md 章节完整性

```bash

python -X utf8 -c "
import os, sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from datetime import date
from lib.staging_verify import check_sections
today = date.today().strftime('%Y%m%d')
f = 'f'my_doc/每日复盘/reports/{today}/复盘报告.md''
if not os.path.exists(f):
    print('C3:FAIL: 文件不存在 ' + f)
    sys.exit(0)
content = open(f, 'r', encoding='utf-8').read()
required = [('我的持仓','持仓表'),('大市表现复盘','指数+成交量'),('早盘预判复盘','方向对比'),
            ('持仓复盘','逐只'),('做T建议复盘','做T对比'),('信号执行复盘','决策/执行'),
            ('核心回顾','经验教训'),('操作预案','次日预案')]
failures = check_sections(content, required, path_label=f)
if failures:
    for f_item in failures:
        print(f'C3:FAIL: {f_item}')
else:
    print('C3:PASS: 所有核心章节完整')
" 2>&1

### C4: 报告产出与 task_state 一致性

```bash

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

### D4: 信号模型一致性（模板/自动化/编排层无漂移）— v2.0 架构防漂移

> 背景：同一套信号规则曾在 手动模板 + 自动化 prompt + SKILL.md 三处各写一份，
> v2.0 同步时自动化层曾被漏掉（A 区修复）。本检查让漂移可被自动发现。

```bash

python -X utf8 -c "
import sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.consistency_check import check_consistency, render_report, CHECK_TARGETS

contents = {}
errors = []
for label, path in CHECK_TARGETS:
    try:
        contents[label] = open(path, encoding='utf-8').read()
    except FileNotFoundError:
        errors.append(f'{label}: 文件不存在 {path}')

if errors:
    print('D4:WARN: 文件读取失败:')
    for e in errors:
        print(f'  {e}')
    exit(0)

res = check_consistency(contents)
print('D4:' + ('PASS' if res['overall'] else 'FAIL') + ': 信号模型一致性')
print(render_report(res))
" 2>&1
```

**处理**：
- D4 FAIL → 创建 BUG（`auto_fix_eligible=true`，确定性修复 — 按缺失标记同步对应文件；参照 `harness/prompts/早盘分析-模板.md` 第九节为单一事实源）
- D4 PASS → 记录日志

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



