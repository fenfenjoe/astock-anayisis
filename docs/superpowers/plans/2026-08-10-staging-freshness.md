# Staging 过期检测与自动重建 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在早盘分析执行时检测 staging 是否过期（执行日期早于今天），过期则自动轻量重建，避免用失效 staging 生成错误报告。

**Architecture:** 新增纯函数库 `lib/staging_freshness.py`（解析执行日期 / 过期判定 / 定位最近复盘 / 综合健康检查），配 pytest 测试；自动入口（`auto_morning_analysis.md`）与手动入口（`daily-review-harness` skill）复用同一套函数；过期时按"轻量重建"流程（基于最近一次复盘报告 + 当前持仓 + 模板）重建 staging 后继续早盘。

**Tech Stack:** Python 3（`datetime`/`pathlib`/`re`，无第三方依赖）、pytest。

## Global Constraints

- 工作目录固定为 `E:/ideaworkspace/astock-anayisis`；测试须 `cd my_doc/每日复盘/harness/automation` 后运行
- 日期格式：报告/文件用 `yyyyMMdd`（如 `20260810`），staging 头部日期用 `YYYY-MM-DD`；Python 用 `date.today().strftime("%Y%m%d")`，禁用 `isoformat()`
- **兼容新旧两种 staging 格式**：
  - 旧格式：`> 本文件由 2026-08-10 收盘复盘自动生成。执行日期：**2026-08-11（周二）早盘前/收盘后**`
  - 新格式（早盘）：`# 今日早盘分析 — 2026-08-11（周二）` + `<!-- 本文件由 ... 自动生成，供 2026-08-11 早盘分析使用 -->`
- 持仓数据唯一权威来源是 `config/持仓.md`；重建时绝不用 staging 旧持仓
- 纯函数库不调用外部 API，不读写生产数据文件（仅 `find_latest_review_report` 扫描目录结构）
- 所有 commit 使用规范信息结尾（`Co-Authored-By: Claude <noreply@anthropic.com>`）

---

### Task 1: 创建 `lib/staging_freshness.py` — 执行日期解析

**Files:**
- Create: `my_doc/每日复盘/harness/automation/lib/staging_freshness.py`
- Test: `my_doc/每日复盘/harness/automation/tests/test_staging_freshness.py`

**Interfaces:**
- Produces: `parse_staging_execution_date(text: str | None) -> date | None`
  - 兼容新旧格式，返回执行日期；解析失败/空输入返回 `None`

- [ ] **Step 1: 写失败测试**（仅测 parse 函数）

创建 `tests/test_staging_freshness.py`：

```python
"""
Staging 执行日期解析 测试套件

被测源码:
  - lib/staging_freshness.py — parse_staging_execution_date
"""

import pytest
from datetime import date
from lib.staging_freshness import parse_staging_execution_date


# ============================================================
# parse_staging_execution_date
# ============================================================

class TestParseStagingExecutionDate:
    def test_old_format_morning(self):
        """旧格式：执行日期：**YYYY-MM-DD（周X）早盘前**"""
        text = (
            '# 每日复盘上下文\n\n'
            '> 本文件由 2026-08-07 收盘复盘（补跑，2026-08-10 早盘前生成）自动生成。'
            '执行日期：**2026-08-10（周一）早盘前**\n'
        )
        assert parse_staging_execution_date(text) == date(2026, 8, 10)

    def test_old_format_review(self):
        """旧格式：执行日期：**YYYY-MM-DD（周X）收盘后**"""
        text = (
            '# 每日复盘上下文\n\n'
            '> 本文件由 2026-08-10 收盘复盘自动生成。'
            '执行日期：**2026-08-11（周二）收盘后**\n'
        )
        assert parse_staging_execution_date(text) == date(2026, 8, 11)

    def test_new_format_morning_title(self):
        """新格式：标题 # 今日早盘分析 — YYYY-MM-DD（周X）"""
        text = (
            '# 今日早盘分析 — 2026-08-11（周二）\n\n'
            '<!-- 本文件由 2026-08-10 收盘复盘自动生成，供 2026-08-11 早盘分析使用 -->\n'
        )
        assert parse_staging_execution_date(text) == date(2026, 8, 11)

    def test_new_format_comment(self):
        """新格式：仅注释 供 YYYY-MM-DD 早盘分析使用（不被生成日干扰）"""
        text = (
            '# 其他标题\n\n'
            '<!-- 本文件由 2026-08-10 收盘复盘自动生成，供 2026-08-11 早盘分析使用 -->\n'
        )
        assert parse_staging_execution_date(text) == date(2026, 8, 11)

    def test_no_date(self):
        """无日期 → None"""
        assert parse_staging_execution_date('# 无日期文件\n正文') is None

    def test_empty_text(self):
        """空文本 → None"""
        assert parse_staging_execution_date('') is None
        assert parse_staging_execution_date(None) is None
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd E:/ideaworkspace/astock-anayisis/my_doc/每日复盘/harness/automation && python -m pytest tests/test_staging_freshness.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'lib.staging_freshness'`

- [ ] **Step 3: 最小实现**

创建 `lib/staging_freshness.py`：

```python
"""
Staging 新鲜度检测 — 早盘分析前判断 staging 是否过期

纯计算 + 目录扫描，不调用外部 API，不读写生产数据文件。
判断依据：staging 头部的"执行日期"，兼容新旧两种格式：
  旧格式: `> 本文件由 ... 执行日期：**YYYY-MM-DD（周X）早盘前/收盘后**`
  新格式: `# 今日早盘分析 — YYYY-MM-DD（周X）` + `<!-- ... 供 YYYY-MM-DD 早盘分析使用 -->`
"""

import re
from datetime import date
from typing import Optional


# 三种格式的匹配模式，按优先级排列（执行日期字段 > 供X使用注释 > 标题）
_DATE_PATTERNS = [
    # 旧格式：执行日期：**YYYY-MM-DD（周X）早盘前/收盘后**
    re.compile(r'执行日期[:：]\s*\*{0,2}(\d{4}-\d{2}-\d{2})'),
    # 新格式注释：供 YYYY-MM-DD 早盘分析使用
    re.compile(r'供\s*(\d{4}-\d{2}-\d{2})\s*早盘分析使用'),
    # 新格式标题：# 今日早盘分析 — YYYY-MM-DD（周X）
    re.compile(r'^#\s*今日早盘分析\s*[—\-–]\s*(\d{4}-\d{2}-\d{2})', re.MULTILINE),
]


def parse_staging_execution_date(text: Optional[str]) -> Optional[date]:
    """解析 staging 中的执行日期。

    Args:
        text: staging 文件全文；None/空串返回 None

    Returns:
        执行日期；解析失败返回 None
    """
    if not text:
        return None
    for pat in _DATE_PATTERNS:
        m = pat.search(text)
        if m:
            return date.fromisoformat(m.group(1))
    return None
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd E:/ideaworkspace/astock-anayisis/my_doc/每日复盘/harness/automation && python -m pytest tests/test_staging_freshness.py -v
```

Expected: PASS (6 passed)

- [ ] **Step 5: 提交**

```bash
cd E:/ideaworkspace/astock-anayisis && git add my_doc/每日复盘/harness/automation/lib/staging_freshness.py my_doc/每日复盘/harness/automation/tests/test_staging_freshness.py && git commit -m "feat(morning): add staging execution-date parser

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 添加过期判定 + 最近复盘定位

**Files:**
- Modify: `my_doc/每日复盘/harness/automation/lib/staging_freshness.py`
- Modify: `my_doc/每日复盘/harness/automation/tests/test_staging_freshness.py`

**Interfaces:**
- Consumes: `parse_staging_execution_date`（Task 1）
- Produces:
  - `is_staging_stale(exec_date: date | None, today: date) -> tuple[bool, dict]`
    - `exec_date == None` → `(True, {'exec_date': None, 'days_old': None, 'reason': '无法解析执行日期，保守判为过期'})`
    - `exec_date < today` → `(True, {'exec_date': iso, 'days_old': n, 'reason': '执行日 X 早于今日'})`
    - 否则 → `(False, {...})`
  - `find_latest_review_report(reports_root: str | Path) -> date | None`
    - 扫 `reports/{yyyyMMdd}/` 目录，取含 `复盘报告.md` 的最大日期；无则 None；跳过非日期目录（如 `weekly`）

- [ ] **Step 1: 追加失败测试**（在 `test_staging_freshness.py` 末尾追加）

```python
from lib.staging_freshness import parse_staging_execution_date, is_staging_stale, find_latest_review_report


# ============================================================
# is_staging_stale
# ============================================================

class TestIsStagingStale:
    def test_stale_when_exec_before_today(self):
        """执行日 < 今天 → 过期"""
        stale, diag = is_staging_stale(date(2026, 8, 7), date(2026, 8, 10))
        assert stale is True
        assert diag['days_old'] == 3

    def test_fresh_when_exec_today(self):
        """执行日 == 今天 → 新鲜"""
        stale, diag = is_staging_stale(date(2026, 8, 10), date(2026, 8, 10))
        assert stale is False
        assert diag['days_old'] == 0

    def test_fresh_when_exec_future(self):
        """执行日 > 今天（提前生成）→ 新鲜"""
        stale, diag = is_staging_stale(date(2026, 8, 11), date(2026, 8, 10))
        assert stale is False

    def test_stale_when_none(self):
        """执行日 None → 保守判过期"""
        stale, diag = is_staging_stale(None, date(2026, 8, 10))
        assert stale is True
        assert diag['reason'] is not None


# ============================================================
# find_latest_review_report
# ============================================================

class TestFindLatestReviewReport:
    def test_finds_latest(self, tmp_path):
        """多个日期目录，取含复盘报告的最大日期"""
        (tmp_path / '20260805').mkdir()
        (tmp_path / '20260805' / '复盘报告.md').write_text('x', encoding='utf-8')
        (tmp_path / '20260807').mkdir()
        (tmp_path / '20260807' / '复盘报告.md').write_text('x', encoding='utf-8')
        (tmp_path / '20260810').mkdir()  # 无复盘报告
        assert find_latest_review_report(tmp_path) == date(2026, 8, 7)

    def test_skips_non_date_dirs(self, tmp_path):
        """跳过 weekly 等非日期目录"""
        (tmp_path / 'weekly').mkdir()
        (tmp_path / '20260805').mkdir()
        (tmp_path / '20260805' / '复盘报告.md').write_text('x', encoding='utf-8')
        assert find_latest_review_report(tmp_path) == date(2026, 8, 5)

    def test_none_when_empty(self, tmp_path):
        """空目录 → None"""
        assert find_latest_review_report(tmp_path) is None

    def test_none_when_no_review(self, tmp_path):
        """有日期目录但无复盘报告 → None"""
        (tmp_path / '20260810').mkdir()
        assert find_latest_review_report(tmp_path) is None

    def test_none_when_root_missing(self, tmp_path):
        """目录不存在 → None"""
        assert find_latest_review_report(tmp_path / 'nope') is None
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd E:/ideaworkspace/astock-anayisis/my_doc/每日复盘/harness/automation && python -m pytest tests/test_staging_freshness.py -v
```

Expected: FAIL — `ImportError: cannot import name 'is_staging_stale'`

- [ ] **Step 3: 追加实现**

在 `lib/staging_freshness.py` 末尾追加：

```python
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Tuple, Union


def is_staging_stale(exec_date: Optional[date], today: date) -> Tuple[bool, dict]:
    """判定 staging 是否过期。

    Args:
        exec_date: staging 执行日期；None 表示无法解析
        today: 今天日期

    Returns:
        (is_stale, diag) 其中 diag = {exec_date, days_old, reason}
    """
    if exec_date is None:
        return (True, {
            'exec_date': None,
            'days_old': None,
            'reason': '无法解析执行日期，保守判为过期',
        })
    days_old = (today - exec_date).days
    if exec_date < today:
        return (True, {
            'exec_date': exec_date.isoformat(),
            'days_old': days_old,
            'reason': f'执行日 {exec_date} 早于今日 {today}',
        })
    return (False, {
        'exec_date': exec_date.isoformat(),
        'days_old': days_old,
        'reason': f'执行日 {exec_date} 为今日或未来',
    })


def find_latest_review_report(reports_root: Union[str, Path]) -> Optional[date]:
    """定位最近一次含 复盘报告.md 的 reports/{yyyyMMdd}/ 目录日期。

    Args:
        reports_root: reports/ 目录路径

    Returns:
        最近复盘日期；无则 None
    """
    root = Path(reports_root)
    if not root.is_dir():
        return None
    latest = None
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            d = datetime.strptime(child.name, '%Y%m%d').date()
        except ValueError:
            continue  # 跳过 weekly 等非日期目录
        if (child / '复盘报告.md').is_file():
            if latest is None or d > latest:
                latest = d
    return latest
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd E:/ideaworkspace/astock-anayisis/my_doc/每日复盘/harness/automation && python -m pytest tests/test_staging_freshness.py -v
```

Expected: PASS (15 passed)

- [ ] **Step 5: 提交**

```bash
cd E:/ideaworkspace/astock-anayisis && git add my_doc/每日复盘/harness/automation/lib/staging_freshness.py my_doc/每日复盘/harness/automation/tests/test_staging_freshness.py && git commit -m "feat(morning): add staging staleness check and latest-review locator

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 综合健康检查入口 `staging_health_check`

**Files:**
- Modify: `my_doc/每日复盘/harness/automation/lib/staging_freshness.py`
- Modify: `my_doc/每日复盘/harness/automation/tests/test_staging_freshness.py`

**Interfaces:**
- Consumes: `parse_staging_execution_date`, `is_staging_stale`, `find_latest_review_report`（Task 1/2）
- Produces:
  - `staging_health_check(staging_text: str | None, today: date, reports_root: str | Path) -> dict`
    - 返回 `{exists, exec_date, stale, latest_review_date, action}`，其中 `action ∈ {'use', 'rebuild', 'missing'}`
    - 判定：缺失 → `missing`；执行日解析失败 → `rebuild`（保守）；`exec_date >= today` → `use`；否则 → `rebuild`

- [ ] **Step 1: 追加失败测试**

```python
from lib.staging_freshness import staging_health_check


class TestStagingHealthCheck:
    def test_missing_when_none(self, tmp_path):
        """staging 缺失 → action=missing"""
        r = staging_health_check(None, date(2026, 8, 10), tmp_path)
        assert r['exists'] is False
        assert r['action'] == 'missing'

    def test_use_when_fresh(self, tmp_path):
        """执行日 == 今天 → use"""
        text = '# 今日早盘分析 — 2026-08-10（周一）\n\n供 2026-08-10 早盘分析使用\n'
        r = staging_health_check(text, date(2026, 8, 10), tmp_path)
        assert r['exists'] is True
        assert r['stale'] is False
        assert r['action'] == 'use'

    def test_rebuild_when_stale(self, tmp_path):
        """执行日 < 今天 → rebuild"""
        text = '# 今日早盘分析 — 2026-08-07（周五）\n\n供 2026-08-07 早盘分析使用\n'
        r = staging_health_check(text, date(2026, 8, 10), tmp_path)
        assert r['action'] == 'rebuild'
        assert r['stale'] is True

    def test_rebuild_when_unparseable(self, tmp_path):
        """执行日解析失败 → 保守 rebuild"""
        r = staging_health_check('# 无日期文件', date(2026, 8, 10), tmp_path)
        assert r['action'] == 'rebuild'
        assert r['stale'] is True

    def test_reports_latest_date_populated(self, tmp_path):
        """latest_review_date 从 reports_root 定位"""
        (tmp_path / '20260805').mkdir()
        (tmp_path / '20260805' / '复盘报告.md').write_text('x', encoding='utf-8')
        text = '# 今日早盘分析 — 2026-08-10（周一）\n'
        r = staging_health_check(text, date(2026, 8, 10), tmp_path)
        assert r['latest_review_date'] == date(2026, 8, 5)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd E:/ideaworkspace/astock-anayisis/my_doc/每日复盘/harness/automation && python -m pytest tests/test_staging_freshness.py -v
```

Expected: FAIL — `ImportError: cannot import name 'staging_health_check'`

- [ ] **Step 3: 追加实现**

在 `lib/staging_freshness.py` 末尾追加：

```python
def staging_health_check(
    staging_text: Optional[str],
    today: date,
    reports_root: Union[str, Path],
) -> dict:
    """早盘前的 staging 综合健康检查。

    Args:
        staging_text: staging 文件全文；None 表示文件缺失
        today: 今天日期
        reports_root: reports/ 目录路径（用于定位最近复盘）

    Returns:
        {
            'exists': bool,
            'exec_date': date | None,
            'stale': bool,
            'latest_review_date': date | None,
            'action': 'use' | 'rebuild' | 'missing',
        }
    """
    if not staging_text:
        return {
            'exists': False,
            'exec_date': None,
            'stale': True,
            'latest_review_date': find_latest_review_report(reports_root),
            'action': 'missing',
        }
    exec_date = parse_staging_execution_date(staging_text)
    stale, _diag = is_staging_stale(exec_date, today)
    if exec_date is None or stale:
        action = 'rebuild'
    else:
        action = 'use'
    return {
        'exists': True,
        'exec_date': exec_date,
        'stale': stale,
        'latest_review_date': find_latest_review_report(reports_root),
        'action': action,
    }
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd E:/ideaworkspace/astock-anayisis/my_doc/每日复盘/harness/automation && python -m pytest tests/test_staging_freshness.py -v
```

Expected: PASS (20 passed)

- [ ] **Step 5: 全量回归（确认不破坏既有测试）**

```bash
cd E:/ideaworkspace/astock-anayisis/my_doc/每日复盘/harness/automation && python -m pytest tests/ -v
```

Expected: 全部 PASS（含既有 test_state_machine.py / test_signal_tracking_parse.py / test_data_source_probe.py / test_REQ_*.py）

- [ ] **Step 6: 提交**

```bash
cd E:/ideaworkspace/astock-anayisis && git add my_doc/每日复盘/harness/automation/lib/staging_freshness.py my_doc/每日复盘/harness/automation/tests/test_staging_freshness.py && git commit -m "feat(morning): add staging health check entrypoint

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 修改 `auto_morning_analysis.md` — 修复 1.3c + 新增 1.3d 过期检测与重建

**Files:**
- Modify: `my_doc/每日复盘/harness/automation/prompts/auto_morning_analysis.md`

**Interfaces:**
- Consumes: `staging_health_check`（Task 3）
- Produces: 早盘自动执行流程的"1.3d Staging 过期检测与重建"步骤

**背景**：现有 1.3c 用 `re.search(r'(\d{4}-\d{2}-\d{2})', staging.split('\n')[0])` 只匹配第一行（无日期），导致 STALE DATE 检测从未生效。需删除该失效日期逻辑（保留持仓比对），由新的 1.3d 全权负责新鲜度。

- [ ] **Step 1: 删除 1.3c 中失效的日期提取与判断**

定位 `### 1.3c Staging 持仓新鲜度校验` 节的 `# 2. 检查 staging 文件的日期新鲜度` 部分（约 line 133-141）和 `if staging_date:` 块（约 line 194-201）。

将 `# 2. 检查 staging 文件的日期新鲜度` 整段（从 `staging_file = '...'` 到 `# 提取 staging 中的持仓` 之前的日期提取代码）替换为精简版（保留 staging 读取，去掉日期提取）：

```python
# 2. 读取 staging 内容（日期新鲜度由 1.3d 统一判定）
staging_file = 'my_doc/每日复盘/harness/staging/今日-早盘分析.md'
staging_holdings = {}

if os.path.exists(staging_file):
    with open(staging_file, 'r', encoding='utf-8') as f:
        staging = f.read()
    
    # 提取 staging 中的持仓
```

将 `if staging_date:` 整块（line 194-201）删除：

```python
    if staging_date:
        try:
            sd = datetime.strptime(staging_date, '%Y-%m-%d').date()
            days_old = (date.today() - sd).days
            if days_old > 1:
                errors.append(f'STALE DATE: staging生成于{staging_date}，距今{days_old}天，已过期')
        except:
            pass
```

同时删除 `# 1.3c` 开头 import 中不再需要的 `re`（若其它部分还用则保留）与 `date`（若仅此处用则保留，1.3c 其余代码仍用 `datetime.strptime`，`date.today()` 仅在删除块中——检查后删除不再使用的 import，保留仍用的）。

> 校验要点：编辑后 `# 3. 比较` 的持仓比对逻辑保持不变；`[PASS]`/`[FAIL]` 分支保持不变（FAIL 仅因持仓差异触发，不再因日期）。

- [ ] **Step 2: 验证 1.3c 编辑后语法正确**

```bash
cd E:/ideaworkspace/astock-anayisis && python -c "
# 从 prompt 中提取 1.3c 的 bash 代码块做语法检查
import re
text = open('my_doc/每日复盘/harness/automation/prompts/auto_morning_analysis.md', encoding='utf-8').read()
m = re.search(r'### 1.3c.*?```bash\n(.*?)```', text, re.DOTALL)
code = m.group(1)
# 去掉 bash 引导的 cd 行
lines = [l for l in code.split('\n') if not l.startswith('cd ')]
compile('\n'.join(lines), '<1.3c>', 'exec')
print('1.3c code block: syntax OK')
"
```

Expected: `1.3c code block: syntax OK`

- [ ] **Step 3: 在 1.4 幂等性检查之前插入 1.3d**

在 `### 1.4 幂等性检查` 之前（即 1.3c 的"校验结果处理"段之后）插入新节：

```markdown
### 1.3d Staging 过期检测与自动重建（🚨 防止隔多日使用失效 staging）

> ⚠️ 系统可能隔几天才使用（如节假日/遗漏执行），此时 staging 仍是为旧日期生成的，内容已过期。
> 必须检测 staging 的执行日期，过期则自动重建，绝不用失效 staging 生成早盘报告。

执行健康检查：

```bash
cd E:/ideaworkspace/astock-anayisis
python -X utf8 -c "
import json, sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from datetime import date
from lib.staging_freshness import staging_health_check

try:
    with open('my_doc/每日复盘/harness/staging/今日-早盘分析.md', 'r', encoding='utf-8') as f:
        text = f.read()
except FileNotFoundError:
    text = None

result = staging_health_check(text, date.today(), 'my_doc/每日复盘/reports')
print(json.dumps(result, ensure_ascii=False, default=str))
"
```

**按 `action` 分支处理：**

- **`use`** → staging 为今日执行日，正常继续
- **`missing`** → 已在 1.3 处理（降级为模板早盘），继续走 1.3 的降级逻辑
- **`rebuild`** → 触发**轻量重建流程**（见下方），重建后重新读取 staging 继续早盘

**🚨 轻量重建流程（当 action=rebuild 时执行）：**

1. 从健康检查结果取 `latest_review_date`（记为 Y，若无则降级为模板早盘，标注"无历史复盘可参考"）
2. 读取 `reports/{Y}/复盘报告.md` → 提取"核心矛盾 / 核心教训 / 上期预判回顾"
3. 生成新 staging：
   - 执行日期更新为今天
   - 持仓表从 `config/持仓.md` 权威读取（铁律：绝不用旧 staging 持仓）
   - "前次预测回顾 / 上期信号回顾" ← 基于复盘报告 Y 的内容（标注"基于 Y 日复盘"）
   - 核心矛盾 / 特别关注 ← 基于复盘 Y + 今日市场状态
   - 事件日历 ← 今日数据（解禁 / 宏观 / 海外映射，走 1.3 的降级取数路径）
4. 覆写 `my_doc/每日复盘/harness/staging/今日-早盘分析.md` + `今日-复盘分析.md`
5. 新 staging 头部标注：`> ⚠️ 补生成（原 staging 执行日 {原日期} 已过期，基于 {Y} 日复盘重建）`
6. 重建完成后，重新执行 1.3d 的健康检查确认 action=use，然后继续早盘流程

**重建后必做**：重新跑 1.3b 代码-名称校验 + 1.3c 持仓比对，确保重建的 staging 持仓与 config 一致。
```

> 注意：上述 markdown 中嵌套的 ```bash 代码块在插入时需要保留缩进/原样；实际编辑时直接在 1.3d 标题下写入该 bash 块（块内代码用 4 空格缩进，符合 markdown 代码块语法）。

- [ ] **Step 4: 验证 1.3d 健康检查命令可运行**

用真实 staging 验证健康检查（当前 staging 是 8/10 生成给 8/11 用——执行日 2026-08-11 > 今天 2026-08-10，应返回 action=use）：

```bash
cd E:/ideaworkspace/astock-anayisis && python -X utf8 -c "
import json, sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from datetime import date
from lib.staging_freshness import staging_health_check
text = open('my_doc/每日复盘/harness/staging/今日-早盘分析.md', encoding='utf-8').read()
r = staging_health_check(text, date.today(), 'my_doc/每日复盘/reports')
print(json.dumps(r, ensure_ascii=False, default=str))
"
```

Expected: `action=use`（执行日 2026-08-11 > today 2026-08-10）且 `latest_review_date=2026-08-10`

- [ ] **Step 5: 提交**

```bash
cd E:/ideaworkspace/astock-anayisis && git add my_doc/每日复盘/harness/automation/prompts/auto_morning_analysis.md && git commit -m "feat(morning): add staging staleness detection and auto-rebuild

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 修改 `daily-review-harness` SKILL.md — 手动早盘入口补新鲜度检查

**Files:**
- Modify: `E:/ideaworkspace/astock-anayisis/.claude/skills/daily-review-harness/SKILL.md`

**Interfaces:**
- Consumes: `staging_health_check`（Task 3）
- Produces: 手动早盘模式流程中的"staging 新鲜度检查与重建"步骤

- [ ] **Step 1: 修改早盘模式流程**

定位 `### 早盘模式（盘前 8:00-9:15）` 的流程编号列表（第 1 步"读取 staging"之前）。将流程改为：

```markdown
**流程：**
1. **staging 新鲜度检查**：读取 `harness/staging/今日-早盘分析.md` 全文，执行以下命令判断是否过期：
   ```bash
   cd E:/ideaworkspace/astock-anayisis
   python -X utf8 -c "
   import json, sys
   sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
   from datetime import date
   from lib.staging_freshness import staging_health_check
   try:
       text = open('my_doc/每日复盘/harness/staging/今日-早盘分析.md', encoding='utf-8').read()
   except FileNotFoundError:
       text = None
   print(json.dumps(staging_health_check(text, date.today(), 'my_doc/每日复盘/reports'), ensure_ascii=False, default=str))
   "
   ```
   - `action=use` → 正常使用
   - `action=missing` → 降级为模板早盘（跳过 staging，标注"staging 缺失"）
   - `action=rebuild` → 执行**轻量重建**：读 `reports/{latest_review_date}/复盘报告.md` 提取核心矛盾/预判回顾 → 用 `config/持仓.md` 持仓 + 模板重建两份 staging（执行日=今天）→ 头部标注"⚠️ 补生成（基于 Y 日复盘重建）" → 重新读 staging
2. 读取 `harness/staging/今日-早盘分析.md`（完整可执行 prompt，由昨日复盘已填充日期特定内容）
3. 调用 `a-stock-data` 按四步并行取数（隔夜外盘 → 板块催化 → 资金面 → 事件日历）
4. 执行宏观研判 → 非持仓板块七维评分（第五节）→ 持仓板块评分+做T建议（第六节）→ 操作清单
5. 产出 `reports/{today}/早盘报告.md`
6. **生成每日信号**：从持仓映射分析和操作清单中提取结构化信号，按 `harness/prompts/早盘分析-模板.md` 第九节每日信号生成的规则，输出 `reports/{today}/每日信号.md`
   - 信号必须可量化、可验证、有时效
   - P0信号 ≤ 3条（风险控制信号精而不多）
   - 总信号 5-10 条
   - 信号总表按"优先级→标的→触发条件"排序（重要信息前置），信号ID在末尾便于盘中追加
7. 若执行交易操作，更新 `harness/config/持仓.md`
```

- [ ] **Step 2: 验证修改已生效**

```bash
cd E:/ideaworkspace/astock-anayisis && grep -n "staging_health_check\|新鲜度检查\|action=rebuild" .claude/skills/daily-review-harness/SKILL.md
```

Expected: 至少 3 处匹配（命令、分支处理说明）

- [ ] **Step 3: 提交**

```bash
cd E:/ideaworkspace/astock-anayisis && git add .claude/skills/daily-review-harness/SKILL.md && git commit -m "feat(skill): add staging freshness check to manual morning flow

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 端到端验证

**Files:**（无代码修改，仅验证）

- [ ] **Step 1: 全量测试**

```bash
cd E:/ideaworkspace/astock-anayisis/my_doc/每日复盘/harness/automation && python -m pytest tests/ -v
```

Expected: 全部 PASS

- [ ] **Step 2: 真实场景模拟（过期 → 重建）**

用归档的旧 staging（执行日 2026-08-07 < 今天）验证 health check 返回 rebuild：

```bash
cd E:/ideaworkspace/astock-anayisis && python -X utf8 -c "
import json, sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from datetime import date
from lib.staging_freshness import staging_health_check
text = open('my_doc/每日复盘/harness/archive/20260807/今日-早盘分析.md', encoding='utf-8').read()
r = staging_health_check(text, date.today(), 'my_doc/每日复盘/reports')
print(json.dumps(r, ensure_ascii=False, default=str))
"
```

Expected: `action=rebuild`，`exec_date=2026-08-07`，`latest_review_date=2026-08-10`

- [ ] **Step 3: 真实场景模拟（新鲜 → use）**

```bash
cd E:/ideaworkspace/astock-anayisis && python -X utf8 -c "
import json, sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from datetime import date
from lib.staging_freshness import staging_health_check
text = open('my_doc/每日复盘/harness/staging/今日-早盘分析.md', encoding='utf-8').read()
r = staging_health_check(text, date.today(), 'my_doc/每日复盘/reports')
print(json.dumps(r, ensure_ascii=False, default=str))
"
```

Expected: `action=use`

- [ ] **Step 4: 确认 git 状态干净（仅本 feature 改动未提交前）**

```bash
cd E:/ideaworkspace/astock-anayisis && git status --short
```

Expected: 仅显示本 feature 相关文件的修改（lib / tests / 两个 prompt / skill）；不包含意外的 staging/reports 改动（这些可能由盘中/复盘自动化产生，属正常）。

- [ ] **Step 5: 收尾提交（若 Step 4 有未提交的 feature 文件）**

```bash
cd E:/ideaworkspace/astock-anayisis && git add my_doc/每日复盘/harness/automation/lib/staging_freshness.py my_doc/每日复盘/harness/automation/tests/test_staging_freshness.py my_doc/每日复盘/harness/automation/prompts/auto_morning_analysis.md .claude/skills/daily-review-harness/SKILL.md && git commit -m "feat(morning): staging freshness detection and auto-rebuild (complete)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage 核对：**
- ✅ `parse_staging_execution_date` — Task 1（spec §4.1，兼容新旧格式）
- ✅ `is_staging_stale` — Task 2（spec §4.1，含 None 保守判过期）
- ✅ `find_latest_review_report` — Task 2（spec §4.1，重建输入定位）
- ✅ `staging_health_check` — Task 3（spec §4.1，返回 use/rebuild/missing）
- ✅ 自动入口 1.3d + 修复 1.3c bug — Task 4（spec §5.1）
- ✅ 手动入口 skill — Task 5（spec §5.2）
- ✅ 轻量重建流程 — Task 4 Step 3 + Task 5 Step 1（spec §6，标注补生成/基于Y日复盘/持仓走config）
- ✅ 错误处理 — 缺 staging→missing、解析失败→rebuild、无复盘→降级模板（Task 3 判定 + Task 4 分支）
- ✅ 测试计划 — Task 1/2/3 的 pytest + Task 6 端到端

**Placeholder 扫描：** 无 TBD/TODO；每步含完整代码与预期输出。

**类型一致性：** `staging_health_check(staging_text, today, reports_root) -> dict` 在 Task 3/4/5/6 中签名一致；`find_latest_review_report(reports_root)` 在 Task 2/3 一致；`is_staging_stale` 返回 `tuple[bool, dict]` 在 Task 2/3 一致。
