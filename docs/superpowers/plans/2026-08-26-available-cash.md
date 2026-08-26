# 可用金额引入（建仓份额计算）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 让建仓（未持仓标的）信号能依据 `每日调仓.md` 的可用金额计算出具体份额，沿持仓同步全链路传递。

**Architecture:** 逻辑下沉 `lib/position_sync.py`（3 个纯函数 + 分级比例常量），prompt 只调用渲染。同步链路（auto_evening_review §10.1/10.2、复盘分析-模板 4.5/6、D1）负责把可用金额从 `每日调仓.md` 同步进 `config/持仓.md` 顶部行并交叉验证；消费链路（早盘分析 4.1、信号生成模板）负责读取并计算建仓份额。

**Tech Stack:** Python 3.11（pytest 9.1，现有 harness 测试框架）、Markdown 模板（prompt 嵌入式 Python）。

**Spec:** `docs/superpowers/specs/2026-08-26-available-cash-design.md`

## Global Constraints

- 逻辑必须下沉 `my_doc/每日复盘/harness/automation/lib/position_sync.py`，prompt 不得内联实现（只调用）。
- 测试必须通过 TDD 门禁：先写失败测试，再实现。
- 测试运行方式：`cd my_doc/每日复盘/harness/automation && python -m pytest tests/`
- config/持仓.md 是持仓与可用金额的唯一权威来源（`> 最后更新` 注释下方、持仓表上方为 `可用金额: N 元` 行）。
- 可用金额缺失/非数字 → 告警不中止（持仓同步必须完成），config 保留旧值。
- 交叉验证偏差 > 容差（默认 1.0 元）→ 告警不阻塞。
- 建仓份额 = floor(可用金额×比例/价格/100)×100（100 份整数）；不足 100 份 → 0。
- 分级比例：`open_high=1/3`、`upgrade=1/4`、`probe=1/5`。
- 所有校验脚本（代码-名称、D1、staging 校验）只认 6 位代码表格行，可用金额行不得破坏它们。

---

### Task 1: lib/position_sync.py — 三个纯函数（TDD）

**Files:**
- Create: `my_doc/每日复盘/harness/automation/lib/position_sync.py`
- Create: `my_doc/每日复盘/harness/automation/tests/test_position_sync.py`

**Interfaces:**
- Consumes: 无（标准库 `re`）
- Produces（后续任务依赖的精确签名）:
  - `parse_available_cash(md_text: str) -> int | None`
  - `verify_cash_change(old_cash: float, new_cash: float, trades: list, tolerance: float = 1.0) -> list[str]`
  - `calc_position_shares(available_cash: float, price: float, ratio: float) -> int`
  - `POSITION_RATIOS: dict = {'open_high': 1/3, 'upgrade': 1/4, 'probe': 1/5}`

- [x] **Step 1: 写失败测试**

创建 `tests/test_position_sync.py`：

```python
"""
position_sync.py 测试 — 可用金额解析/交叉验证/建仓份额计算
"""

import sys
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from position_sync import (
    parse_available_cash,
    verify_cash_change,
    calc_position_shares,
    POSITION_RATIOS,
)


# ============================================================
# parse_available_cash
# ============================================================

class TestParseAvailableCash:
    def test_plain_number(self):
        md = "## 0. 可用金额\n\n25701\n"
        assert parse_available_cash(md) == 25701

    def test_thousand_separator(self):
        md = "## 0. 可用金额\n\n25,701\n"
        assert parse_available_cash(md) == 25701

    def test_trailing_text(self):
        md = "## 0. 可用金额\n\n25701 元\n"
        assert parse_available_cash(md) == 25701

    def test_missing_section(self):
        md = "## 1. 当前持仓\n\n| 股票名称 | 代码 |\n"
        assert parse_available_cash(md) is None

    def test_non_numeric(self):
        md = "## 0. 可用金额\n\n未知\n"
        assert parse_available_cash(md) is None

    def test_real_file_shape(self):
        md = (
            "# 仓位\n\n"
            "## 0. 可用金额\n\n25701\n\n"
            "## 1. 当前持仓\n\n| 股票名称 | 代码 |\n"
        )
        assert parse_available_cash(md) == 25701


# ============================================================
# verify_cash_change
# ============================================================

class TestVerifyCashChange:
    def test_no_trades_no_change(self):
        assert verify_cash_change(10000, 10000, []) == []

    def test_buy_decreases_cash(self):
        trades = [{'direction': '买入', 'qty': 1000, 'price': 2.0}]
        assert verify_cash_change(10000, 8000, trades) == []

    def test_sell_increases_cash(self):
        trades = [{'direction': '卖出', 'qty': 500, 'price': 3.0}]
        assert verify_cash_change(10000, 11500, trades) == []

    def test_mixed_trades(self):
        trades = [
            {'direction': '买入', 'qty': 1000, 'price': 2.0},  # -2000
            {'direction': '卖出', 'qty': 500, 'price': 3.0},   # +1500
        ]
        assert verify_cash_change(10000, 9500, trades) == []

    def test_deviation_warns(self):
        trades = [{'direction': '买入', 'qty': 1000, 'price': 2.0}]
        warnings = verify_cash_change(10000, 7000, trades)  # 期望8000
        assert len(warnings) == 1
        assert '1000' in warnings[0]

    def test_tolerance_parameter(self):
        trades = [{'direction': '买入', 'qty': 1000, 'price': 2.0}]
        assert verify_cash_change(10000, 7999.5, trades, tolerance=1.0) == []
        assert len(verify_cash_change(10000, 7998.5, trades, tolerance=1.0)) == 1


# ============================================================
# calc_position_shares
# ============================================================

class TestCalcPositionShares:
    def test_normal_calc(self):
        # 25701 × 1/3 / 1.70 = 5039.4 → 5000
        assert calc_position_shares(25701, 1.70, 1 / 3) == 5000

    def test_round_to_lot(self):
        # 10000 × 1/3 / 2.0 = 1666.6 → 1600
        assert calc_position_shares(10000, 2.0, 1 / 3) == 1600

    def test_less_than_one_lot(self):
        # 500 × 1/3 / 2.0 = 83.3 → 不足100份 → 0
        assert calc_position_shares(500, 2.0, 1 / 3) == 0

    def test_zero_price(self):
        assert calc_position_shares(10000, 0, 1 / 3) == 0

    def test_zero_cash(self):
        assert calc_position_shares(0, 2.0, 1 / 3) == 0

    def test_ratios_defined(self):
        assert POSITION_RATIOS == {'open_high': 1 / 3, 'upgrade': 1 / 4, 'probe': 1 / 5}
```

- [x] **Step 2: 运行确认失败（RED）**

Run: `cd my_doc/每日复盘/harness/automation && python -m pytest tests/test_position_sync.py -q`
Expected: `ModuleNotFoundError: No module named 'position_sync'`（或全部 FAIL）

- [x] **Step 3: 写最小实现**

创建 `lib/position_sync.py`：

```python
"""
可用金额/建仓份额核心逻辑 — 2026-08-26 可用金额引入
(spec: docs/superpowers/specs/2026-08-26-available-cash-design.md)

纯计算函数，不读写磁盘，不调用外部 API。
  1. parse_available_cash  — 从每日调仓.md 解析可用金额
  2. verify_cash_change    — 与当日调仓交叉验证（漏记/未更新告警）
  3. calc_position_shares  — 建仓信号份额 = 可用金额 × 分级比例 ÷ 价格
"""

import re

# 建仓份额分级比例（信号置信度越高仓位越大）
POSITION_RATIOS = {
    'open_high': 1 / 3,   # P1 直接建仓（高置信）
    'upgrade': 1 / 4,     # 观察→升级建仓（盘中）
    'probe': 1 / 5,       # 试探/低置信
}


def parse_available_cash(md_text: str) -> int | None:
    """解析每日调仓.md 的 `## 0. 可用金额` → int；缺失/非数字 → None。"""
    m = re.search(r'##\s*0\.\s*可用金额\s*\n\s*\n\s*([\d,]+)', md_text)
    if not m:
        return None
    return int(m.group(1).replace(',', ''))


def verify_cash_change(old_cash: float, new_cash: float,
                       trades: list, tolerance: float = 1.0) -> list:
    """交叉验证：期望新可用金额 = 旧值 + Σ卖出额 - Σ买入额。
    实际与期望偏差 > tolerance → 返回告警（不抛异常）。
    trades: [{'direction': '买入'|'卖出', 'qty': int, 'price': float}]"""
    warnings = []
    net = 0.0
    for t in trades:
        qty = float(t.get('qty', 0))
        price = float(t.get('price', 0.0))
        amount = qty * price
        if t.get('direction') == '卖出':
            net += amount
        else:  # 买入
            net -= amount
    expected = old_cash + net
    deviation = abs(new_cash - expected)
    if deviation > tolerance:
        warnings.append(
            f'可用金额偏差 {deviation:.2f} 元：期望 {expected:.2f}'
            f'（旧值 {old_cash:.2f} + 调仓净额 {net:.2f}），实际 {new_cash:.2f}'
            f'——可能漏记交易或可用金额未更新'
        )
    return warnings


def calc_position_shares(available_cash: float, price: float, ratio: float) -> int:
    """建仓份额 = floor(可用金额×比例/价格/100)×100（ETF 100份整数）。
    价格≤0 / 可用金额≤0 / 比例≤0 / 不足100份 → 0。"""
    if price <= 0 or available_cash <= 0 or ratio <= 0:
        return 0
    raw = available_cash * ratio / price
    return int(raw // 100) * 100
```

- [x] **Step 4: 运行确认通过（GREEN）**

Run: `cd my_doc/每日复盘/harness/automation && python -m pytest tests/test_position_sync.py -q`
Expected: `18 passed`

- [x] **Step 5: 全量回归**

Run: `cd my_doc/每日复盘/harness/automation && python -m pytest tests/ -q`
Expected: 全部通过（原 190 + 新 18 = 208 passed）

- [x] **Step 6: 提交**

```bash
cd E:/ideaworkspace/astock-anayisis
git add my_doc/每日复盘/harness/automation/lib/position_sync.py my_doc/每日复盘/harness/automation/tests/test_position_sync.py
git commit -m "feat: 可用金额解析/交叉验证/建仓份额计算下沉 lib/position_sync.py（18测试）"
```

---

### Task 2: config/持仓.md 加可用金额行 + auto_evening_review.md §10.1/10.2 同步接入

**Files:**
- Modify: `my_doc/每日复盘/harness/config/持仓.md`（插入一行）
- Modify: `my_doc/每日复盘/harness/automation/prompts/auto_evening_review.md`（§10.1 嵌入脚本 4 处 + §10.2 嵌入脚本 1 处）

**Interfaces:**
- Consumes: `parse_available_cash`, `verify_cash_change`（Task 1）
- Produces: config/持仓.md 顶部 `可用金额: N 元` 行；§10.1 同步脚本输出 WARN 告警；§10.2 校验可用金额一致性

- [x] **Step 1: config/持仓.md 插入可用金额行**

在 `> ⚠️ 历史修正记录...` 行（第 5 行）之后、持仓表之前插入：

```
可用金额: 25701 元

```

（结果：注释块后空一行，`可用金额: 25701 元`，再空一行，然后持仓表。）

- [x] **Step 2: §10.1 脚本 — 解析可用金额**

在 `auto_evening_review.md` §10.1 脚本中，`content = f.read()` 之后、`# 提取 ## 1. 当前持仓` 之前插入：

```python
# 1a. 解析可用金额（## 0. 可用金额，v5.0 新增）
sys.path.insert(0, 'my_doc/每日复盘/harness/automation/lib')
from position_sync import parse_available_cash, verify_cash_change
cash = parse_available_cash(content)
print(f'=== 可用金额: {cash} 元 ===' if cash is not None
      else 'WARN: 每日调仓.md 可用金额缺失或非数字（config 将保留旧值）')
```

- [x] **Step 3: §10.1 脚本 — 读取旧 config 可用金额**

将 §10.1 脚本中：

```python
old_config_path = 'my_doc/每日复盘/harness/config/持仓.md'
old_holdings = {}
if os.path.exists(old_config_path):
    with open(old_config_path, 'r', encoding='utf-8') as f:
        old = f.read()
    for line in old.split('\n'):
```

改为：

```python
old_config_path = 'my_doc/每日复盘/harness/config/持仓.md'
old_holdings = {}
old_cash = None
if os.path.exists(old_config_path):
    with open(old_config_path, 'r', encoding='utf-8') as f:
        old = f.read()
    m_cash = re.search(r'可用金额:\s*([\d,]+)', old)
    if m_cash:
        old_cash = float(m_cash.group(1).replace(',', ''))
    for line in old.split('\n'):
```

- [x] **Step 4: §10.1 脚本 — 交叉验证**

在 §10.1 脚本中 `    print('=== 今日无调仓记录 ===')` 之后、`# 1c. 为每个持仓匹配今日操作` 之前插入：

```python
# 1b. 可用金额交叉验证（期望新值 = 旧值 + Σ卖出 − Σ买入，v5.0 新增）
if cash is not None and old_cash is not None and today_trades:
    trade_records = [{'direction': t['direction'],
                      'qty': int(t['qty'].replace(',', '')),
                      'price': float(t['price'])} for t in today_trades]
    for warn in verify_cash_change(old_cash, cash, trade_records):
        print(f'WARN: {warn}')
```

- [x] **Step 5: §10.1 脚本 — 写入 config 时带可用金额行**

将 §10.1 脚本中：

```python
header = '# 当前持仓\n\n> 本文件由每日复盘自动同步自 每日调仓.md，反映最新持仓状态。\n> 最后更新: 自动同步\n\n'
```

改为：

```python
header = '# 当前持仓\n\n> 本文件由每日复盘自动同步自 每日调仓.md，反映最新持仓状态。\n> 最后更新: 自动同步\n'
if cash is not None:
    header += f'可用金额: {cash} 元\n'
elif old_cash is not None:
    header += f'可用金额: {int(old_cash)} 元\n'
else:
    header += '可用金额: 未知 元\n'
header += '\n'
```

- [x] **Step 6: §10.2 校验脚本 — 可用金额一致性**

在 §10.2 脚本中 `        errors.append(f'STALE in config: ...')` 循环之后、`if errors:` 之前插入：

```python
# 可用金额一致性（v5.0 新增）
sys.path.insert(0, 'my_doc/每日复盘/harness/automation/lib')
from position_sync import parse_available_cash
cash_src = parse_available_cash(content)
cash_cfg = re.search(r'可用金额:\s*([\d,]+)', cfg)
if cash_src is not None and (not cash_cfg or int(cash_cfg.group(1).replace(',', '')) != cash_src):
    errors.append(f'可用金额不一致: src={cash_src} config={cash_cfg.group(1) if cash_cfg else "缺失"}')
```

- [x] **Step 7: 验证 — 运行真实文件的可用金额一致性检查**

Run（只读，不写文件）:

```bash
cd E:/ideaworkspace/astock-anayisis && python -X utf8 -c "
import re, sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation/lib')
from position_sync import parse_available_cash
content = open('my_doc/每日复盘/每日调仓.md', encoding='utf-8').read()
cfg = open('my_doc/每日复盘/harness/config/持仓.md', encoding='utf-8').read()
src = parse_available_cash(content)
m = re.search(r'可用金额:\s*([\d,]+)', cfg)
print('src=', src, 'cfg=', m.group(1) if m else None)
assert src == 25701 and m and int(m.group(1).replace(',','')) == 25701
print('PASS: 每日调仓.md 与 config/持仓.md 可用金额一致')
"
```
Expected: `src= 25701 cfg= 25701` 且 `PASS`

- [x] **Step 8: 提交**

```bash
cd E:/ideaworkspace/astock-anayisis
git add my_doc/每日复盘/harness/config/持仓.md my_doc/每日复盘/harness/automation/prompts/auto_evening_review.md
git commit -m "feat: 可用金额同步入 config/持仓.md + §10.1 交叉验证 + §10.2 一致性校验"
```

---

### Task 3: 复盘分析-模板.md 任务4.5/6 + auto_logic_inspect.md D1

**Files:**
- Modify: `my_doc/每日复盘/harness/prompts/复盘分析-模板.md`（任务4.5、任务6）
- Modify: `my_doc/每日复盘/harness/automation/prompts/auto_logic_inspect.md`（D1 脚本）

**Interfaces:**
- Consumes: `parse_available_cash`（Task 1）
- Produces: 手动同步路径携带可用金额；D1 一致性检查覆盖可用金额

- [x] **Step 1: 复盘分析-模板.md 任务4.5 — 读取可用金额**

在任务4.5 步骤 a（`读取 每日调仓.md → 解析"## 1. 当前持仓"表格`）之后插入步骤 a2：

```markdown
a2. 读取 `每日调仓.md` 的 `## 0. 可用金额`（标题后首个数字行，支持千分位）
```

- [x] **Step 2: 复盘分析-模板.md 任务4.5 — 写入 config 时带可用金额**

将步骤 d：

```markdown
d. **记录差异后**再覆写 `harness/config/持仓.md`，保持与 `每日调仓.md` 的当前持仓表完全一致
```

改为：

```markdown
d. **记录差异后**再覆写 `harness/config/持仓.md`，保持与 `每日调仓.md` 的当前持仓表完全一致；并将可用金额写入文件顶部 `可用金额: N 元` 行（缺失则保留旧值并提示用户补充）
```

- [x] **Step 3: 复盘分析-模板.md 任务6 — staging 携带可用金额**

任务6 步骤2（收集次日输入数据）加一行：

```markdown
   - 可用金额：`config/持仓.md` 的 `可用金额` 行
```

任务6 步骤3（生成 `harness/staging/今日-早盘分析.md`）加一行：

```markdown
   - 填入可用金额（持仓快照区顶部）
```

- [x] **Step 4: auto_logic_inspect.md D1 — 可用金额一致性**

在 D1 脚本中 `        errors.append(f'STALE in config: ...')` 循环之后、`if errors:` 之前插入：

```python
# 可用金额一致性（v5.0 新增）
sys.path.insert(0, 'my_doc/每日复盘/harness/automation/lib')
from position_sync import parse_available_cash
cash_src = parse_available_cash(content)
cash_cfg = re.search(r'可用金额:\s*([\d,]+)', cfg)
if cash_src is not None and (not cash_cfg or int(cash_cfg.group(1).replace(',', '')) != cash_src):
    errors.append(f'可用金额不一致: src={cash_src} config={cash_cfg.group(1) if cash_cfg else "缺失"}')
```

（D1 脚本中 `content`=每日调仓.md 内容、`cfg`=config/持仓.md 内容，与 §10.2 一致。）

- [x] **Step 5: 验证 — D1 脚本对真实文件运行**

Run（只读）:

```bash
cd E:/ideaworkspace/astock-anayisis && python -X utf8 -c "
import re, sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation/lib')
from position_sync import parse_available_cash
content = open('my_doc/每日复盘/每日调仓.md', encoding='utf-8').read()
cfg = open('my_doc/每日复盘/harness/config/持仓.md', encoding='utf-8').read()
errors = []
cash_src = parse_available_cash(content)
cash_cfg = re.search(r'可用金额:\s*([\d,]+)', cfg)
if cash_src is not None and (not cash_cfg or int(cash_cfg.group(1).replace(',', '')) != cash_src):
    errors.append(f'可用金额不一致: src={cash_src} config={cash_cfg.group(1) if cash_cfg else \"缺失\"}')
print('D1:', 'FAIL ' + str(errors) if errors else 'PASS 可用金额一致')
assert not errors
"
```
Expected: `D1: PASS 可用金额一致`

- [x] **Step 6: 提交**

```bash
cd E:/ideaworkspace/astock-anayisis
git add my_doc/每日复盘/harness/prompts/复盘分析-模板.md my_doc/每日复盘/harness/automation/prompts/auto_logic_inspect.md
git commit -m "feat: 手动同步路径 + D1 校验接入可用金额"
```

---

### Task 4: 消费链路 — 早盘分析读取 + 信号生成规则

**Files:**
- Modify: `my_doc/每日复盘/harness/automation/prompts/auto_morning_analysis.md`（4.1 持仓快照、第五步信号生成）
- Modify: `my_doc/每日复盘/harness/prompts/早盘分析-模板.md`（§9.3 信号生成规则）
- Modify: `my_doc/每日复盘/harness/prompts/盘中分析-模板.md`（升级建仓信号份额）

**Interfaces:**
- Consumes: `calc_position_shares`, `POSITION_RATIOS`（Task 1，语义引用）
- Produces: 早盘/盘中 prompt 中建仓信号份额计算规则（`N份(可用×X/X)` 格式）

- [x] **Step 1: auto_morning_analysis.md 4.1 — 持仓快照展示可用金额**

在 4.1 节 `读取 my_doc/每日复盘/harness/config/持仓.md，生成完整持仓快照表：` 之后、`- 列：股票名称...` 之前插入：

```markdown
- **可用金额**：读取 config 顶部 `可用金额: N 元` 行，展示在快照最上方；缺失则标"可用金额未知"（建仓信号份额无法计算）
```

- [x] **Step 2: auto_morning_analysis.md 第五步 5.1 — 建仓信号仓位计算规则**

在 5.1 的 `**紧急度分配规则：**` 块之后（`**每条信号字段说明：**` 之前）插入：

```markdown
**建仓信号仓位计算（2026-08-26 新增）**：未持仓标的的建仓信号，份额 = `可用金额 × 分级比例 ÷ 参考价`（100 份整数取整）：
- P1 直接建仓（高置信）= 可用金额 1/3；观察升级建仓 = 1/4；试探/低置信 = 1/5
- 参考价 = 昨收（早盘生成时点可得）
- 份额不足 100 份 → 仓位列写"资金不足"；可用金额缺失 → 写"可用金额未知，暂不定份额"
- 输出格式：`{N}份(可用×1/3)`（追踪收益 `_parse_quantity` 可解析）
```

- [x] **Step 3: 早盘分析-模板.md §9.3 — P1 信号生成规则加建仓份额**

在 §9.3 规则 4（`4. **短线定位**...`）之后追加规则 5：

```markdown
5. **建仓信号份额**：未持仓标的 = `可用金额 × 分级比例 ÷ 昨收`（100份整数）：高置信 P1 建仓=1/3、观察升级=1/4、试探=1/5。资金不足100份→"资金不足"；可用金额未知→"暂不定份额"。输出 `N份(可用×X/X)` 格式。
```

- [x] **Step 4: 盘中分析-模板.md — 升级建仓信号份额**

在盘中追加信号规则（`盘中追加信号直接追加到信号总表末尾...` 附近）之后追加：

```markdown
**升级建仓信号份额（2026-08-26 新增）**：从关注列表升级的建仓信号，读取 `config/持仓.md` 的可用金额，份额 = `可用金额 × 1/4 ÷ 盘中现价`（100份整数），输出 `N份(可用×1/4)`；不足100份→"资金不足"；可用金额缺失→"暂不定份额"。
```

- [x] **Step 5: 验证 — calc_position_shares 示例计算**

Run:

```bash
cd E:/ideaworkspace/astock-anayisis && python -X utf8 -c "
import sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation/lib')
from position_sync import calc_position_shares
# 当前可用金额 25701 × 1/3 ÷ 昨收 1.70 → 5000份
print('P1建仓(1/3):', calc_position_shares(25701, 1.70, 1/3), '份')
# 观察升级(1/4) ÷ 盘中现价 3.50 → 1800份 (25701×0.25/3.5=1835.8→1800)
print('升级(1/4):', calc_position_shares(25701, 3.50, 1/4), '份')
# 试探(1/5)
print('试探(1/5):', calc_position_shares(25701, 9.0, 1/5), '份')
"
```
Expected:
```
P1建仓(1/3): 5000 份
升级(1/4): 1800 份
试探(1/5): 500 份
```

- [x] **Step 6: 全量回归**

Run: `cd my_doc/每日复盘/harness/automation && python -m pytest tests/ -q`
Expected: 全部通过（208 passed）

- [x] **Step 7: 提交**

```bash
cd E:/ideaworkspace/astock-anayisis
git add my_doc/每日复盘/harness/automation/prompts/auto_morning_analysis.md my_doc/每日复盘/harness/prompts/早盘分析-模板.md my_doc/每日复盘/harness/prompts/盘中分析-模板.md
git commit -m "feat: 早盘/盘中建仓信号份额计算规则（可用金额×分级比例）"
```

---

## 验收汇总（对照 spec §9）

1. `python -m pytest tests/` 全绿（含新增 test_position_sync.py）— Task 1/4
2. config/持仓.md 含 `可用金额: 25701 元` 行，B3/D1 不受影响 — Task 2/3
3. 早盘分析生成的建仓信号仓位列输出 `N份(可用×X/X)` — Task 4
4. 改 每日调仓.md 可用金额为错误值 → 同步脚本输出告警 — Task 2（§10.1 交叉验证 WARN）
