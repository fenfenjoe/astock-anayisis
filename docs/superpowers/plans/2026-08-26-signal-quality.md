# 每日信号质量闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将每日信号从"低触发率验证雷达"改为"少而精的短线机会信号"，并建立"触发入库 → 目标价结算 → 质量仪表盘 → 周报"的完整监控闭环。

**Architecture:** 混合方案——信号生成靠模板/prompt 优化（保留 LLM 语义判断），监控统计靠 `lib/` 纯函数代码化（可测试、可强制驱动）。复用现有 `signal_tracking.py` 的解析/合并链路，新增目标价结算模式和 `signal_quality.py` 质量指标库。

**Tech Stack:** Python 3.11（纯函数库 + pytest）、Markdown 模板（harness prompts）、JSON（signal_tracking.json / task_schedule.json）

## Global Constraints

- 所有 A 股数据获取走 `a-stock-data`（东财接口必须串行限流 `em_get`）
- 纯计算函数不读写磁盘、不调用外部 API（可测试性约束，沿用 `signal_tracking.py` / `signal_design.py` 现有模式）
- pytest 运行方式：`cd my_doc/每日复盘/harness/automation && python -m pytest tests/ -v`
- 新信号表列结构（12 列）：`| 优先级 | 标的 | 触发条件 | 操作类型 | 状态 | 方向 | 紧急度 | 预期触发率 | 目标/止损 | 有效时段 | 仓位 | 信号ID |`
- 目标/止损列格式：`目标+3%/止损-2%`（百分比）或 `目标1.75/止损1.66`（显式价格），无止损时仅写目标
- P0 信号预期触发率填 `—`（不考核）；P1 必填百分比
- 结算窗口：触发后 T+3 交易日（用 `trading_calendar.next_trading_day` 精确计算）
- 周报时点：每周三收盘后 16:30（task_schedule.json 新增任务）

---

### Task 1: signal_tracking.py 解析层支持新列（预期触发率 + 目标/止损）

**Files:**
- Modify: `my_doc/每日复盘/harness/automation/lib/signal_tracking.py`
- Test: `my_doc/每日复盘/harness/automation/tests/test_signal_tracking_parse.py`

**Interfaces:**
- Consumes: `_parse_table_rows`, `_col`（现有函数，按列名定位，新列自动兼容）
- Produces: `parse_signal_markdown` 的 record 新增字段 `expected_trigger_rate` / `target_pct` / `stop_pct` / `target_price` / `stop_price`；新函数 `_parse_target_stop(raw: str) -> dict`

- [ ] **Step 1: 写失败测试** — 在 `tests/test_signal_tracking_parse.py` 末尾追加：

```python
# ============================================================
# 新列解析（v2.0 信号质量闭环）
# ============================================================

_NEW_COL_HEADER = (
    "| 优先级 | 标的 | 触发条件 | 操作类型 | 状态 | 方向 | 紧急度 | 预期触发率 | 目标/止损 | 有效时段 | 仓位 | 信号ID |\n"
    "|:---:|------|----------|:------:|:---:|:---:|:---:|:---:|--------|:---:|:---:|--------|\n"
)

def _mk_new_md(rows: list[str]) -> str:
    return f"## 信号总表\n\n{_NEW_COL_HEADER + chr(10).join(rows)}\n"


class TestParseNewColumns:
    def test_expected_trigger_rate(self):
        md = _mk_new_md([
            "| P1 | 电网ETF(159326) | 站上1.70 | 正T | 已触发 | 买入 | 高 | 40 | 目标+3%/止损-2% | 10:30-11:30 | 1,975份 | SIG-20260826-06 |",
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        assert records[0]['expected_trigger_rate'] == 40.0

    def test_expected_trigger_rate_dash(self):
        """P0 预期触发率为 — → None"""
        md = _mk_new_md([
            "| P0 | 全持仓 | 普跌否决 | 风控 | 已过期 | 卖出 | 高 | — | — | 9:30-10:00 | 0 | SIG-20260826-01 |",
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        assert len(records) == 0  # 已过期不追踪

    def test_target_pct_parsing(self):
        md = _mk_new_md([
            "| P1 | 电网ETF(159326) | 站上1.70 | 正T | 已触发 | 买入 | 高 | 40 | 目标+3%/止损-2% | 10:30-11:30 | 1,975份 | SIG-20260826-06 |",
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        rec = records[0]
        assert rec['target_pct'] == 3.0
        assert rec['stop_pct'] == -2.0
        assert rec['target_price'] is None
        assert rec['stop_price'] is None

    def test_target_price_parsing(self):
        """显式价格格式"""
        md = _mk_new_md([
            "| P1 | 电网ETF(159326) | 站上1.70 | 正T | 已执行 | 买入 | 高 | 40 | 目标1.75/止损1.66 | 10:30-11:30 | 1,975份 | SIG-20260826-06 |",
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        rec = records[0]
        assert rec['target_price'] == 1.75
        assert rec['stop_price'] == 1.66
        assert rec['target_pct'] is None

    def test_target_only(self):
        """只有目标无止损"""
        md = _mk_new_md([
            "| P1 | 农业ETF(159825) | 放量突破0.74 | 建仓 | 已触发 | 买入 | 低 | 30 | 目标0.76 | 10:30后 | 观察 | SIG-20260826-05 |",
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        rec = records[0]
        assert rec['target_price'] == 0.76
        assert rec['stop_price'] is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd my_doc/每日复盘/harness/automation && python -m pytest tests/test_signal_tracking_parse.py::TestParseNewColumns -v`
Expected: FAIL（`expected_trigger_rate` 等字段不存在 / KeyError）

- [ ] **Step 3: 实现** — 在 `lib/signal_tracking.py` 增加 `_parse_target_stop`，并修改 `parse_signal_markdown`：

```python
import re  # 若文件顶部无此 import 则添加


def _parse_expected_rate(raw: str):
    """解析 '40' / '40%' → 40.0；'—'/空 → None"""
    if not raw or raw == '—':
        return None
    m = re.search(r'(\d+(?:\.\d+)?)', raw)
    return float(m.group(1)) if m else None


def _parse_target_stop(raw: str) -> dict:
    """解析目标/止损列：'目标+3%/止损-2%'（百分比）或 '目标1.75/止损1.66'（显式价）。
    返回 {target_pct, stop_pct, target_price, stop_price}，无值均为 None。"""
    result = {'target_pct': None, 'stop_pct': None, 'target_price': None, 'stop_price': None}
    if not raw or raw == '—':
        return result
    for part in raw.replace('，', '/').split('/'):
        part = part.strip()
        m = re.match(r'目标\s*([+-]?\d+(?:\.\d+)?)\s*%', part)
        if m:
            result['target_pct'] = float(m.group(1)); continue
        m = re.match(r'止损\s*([+-]?\d+(?:\.\d+)?)\s*%', part)
        if m:
            result['stop_pct'] = float(m.group(1)); continue
        m = re.match(r'目标\s*(\d+(?:\.\d+)?)', part)
        if m:
            result['target_price'] = float(m.group(1)); continue
        m = re.match(r'止损\s*(\d+(?:\.\d+)?)', part)
        if m:
            result['stop_price'] = float(m.group(1)); continue
    return result
```

在 `parse_signal_markdown` 的列定位处（`c_id = _col(...)` 之后）追加：

```python
    c_exp_rate = _col(header, '预期触发率')
    c_target = _col(header, '目标/止损')
```

在 record 构造处（`'shares': _parse_quantity(quantity_raw),` 之后）追加字段：

```python
        ts = _parse_target_stop(g(c_target))
        records.append({
            'signal_id': signal_id,
            'ticker': ticker,
            'name': target.split('(')[0] if '(' in target else target,
            'trade_type': _map_trade_type(op_type, direction),
            'direction': 'sell' if '卖' in direction else 'buy',
            'priority': priority or 'P2',
            'urgency': urgency_val,
            'expected_trigger_rate': _parse_expected_rate(g(c_exp_rate)),
            'target_pct': ts['target_pct'],
            'stop_pct': ts['stop_pct'],
            'target_price': ts['target_price'],
            'stop_price': ts['stop_price'],
            'expected_return_date': expected_date if expected_date and expected_date != '—' else '',
            'trigger_date': today,
            'entry_price': None,   # 需调用方从盘中数据补充
            'shares': _parse_quantity(quantity_raw),
            'status': 'triggered',
            'status_history': [{'date': today, 'status': 'triggered', 'note': '从每日信号.md解析录入'}],
        })
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd my_doc/每日复盘/harness/automation && python -m pytest tests/test_signal_tracking_parse.py -v`
Expected: 全部 PASS（含旧测试 + 新 TestParseNewColumns）

- [ ] **Step 5: Commit**

```bash
git add my_doc/每日复盘/harness/automation/lib/signal_tracking.py my_doc/每日复盘/harness/automation/tests/test_signal_tracking_parse.py
git commit -m "feat: signal_tracking 解析新列（预期触发率+目标/止损）
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: settle_due_signals 目标价结算模式

**Files:**
- Modify: `my_doc/每日复盘/harness/automation/lib/signal_tracking.py`（`settle_due_signals` 替换）
- Modify: `my_doc/每日复盘/harness/automation/tests/test_signal_tracking_parse.py`（更新现有 4 个 settle 测试 + 新增目标价测试）

**Interfaces:**
- Consumes: `next_trading_day`（trading_calendar）、Task 1 的 `target_price`/`stop_price`/`target_pct`/`stop_pct` 字段
- Produces: 新 `settle_due_signals(tracking, price_history: dict, today: str = '') -> dict`；settled 信号新增 `outcome`（'hit'/'stopped'/'miss'）、`settle_price`、`settle_date`、`holding_days`（1-3）
- **BREAKING**: `price_history` 从 `{ticker: float}` 改为 `{ticker: {date_iso: close_float}}`——现有 4 个 settle 测试必须同步更新

- [ ] **Step 1: 更新现有 settle 测试 + 写新失败测试**

更新 `TestSettleDueSignals`（现有 4 个测试改为新签名），并追加目标价测试：

```python
class TestSettleDueSignals:
    def _hist(self, ticker, closes_by_date: dict) -> dict:
        return {ticker: closes_by_date}

    def test_t3_expiry_miss(self):
        """买入信号 T+3 到期未达目标 → 按 T+3 收盘结算，outcome=miss"""
        db = {'_schema': '1.0', 'signals': [{
            'signal_id': 'SIG-01', 'ticker': '512800', 'trade_type': 'buy',
            'urgency': 'high', 'entry_price': 1.00, 'shares': 1000,
            'target_price': 1.10, 'trigger_date': '2026-07-27', 'status': 'triggered',
        }]}
        hist = {'512800': {'2026-07-27': 1.02, '2026-07-28': 1.04, '2026-07-29': 1.03}}
        settle_due_signals(db, hist, '2026-07-29')
        sig = db['signals'][0]
        assert sig['status'] == 'settled'
        assert sig['outcome'] == 'miss'
        assert sig['settle_price'] == pytest.approx(1.03)  # T+3 收盘
        assert sig['pnl'] == pytest.approx(30.0)
        assert sig['holding_days'] == 3

    def test_t3_target_hit(self):
        """窗口内第2天收盘达到目标 → 达标，按目标价结算，持有天数=2"""
        db = {'_schema': '1.0', 'signals': [{
            'signal_id': 'SIG-02', 'ticker': '512800', 'trade_type': 'buy',
            'urgency': 'high', 'entry_price': 1.00, 'shares': 1000,
            'target_price': 1.10, 'trigger_date': '2026-07-27', 'status': 'triggered',
        }]}
        hist = {'512800': {'2026-07-27': 1.02, '2026-07-28': 1.11, '2026-07-29': 1.05}}
        settle_due_signals(db, hist, '2026-07-29')
        sig = db['signals'][0]
        assert sig['outcome'] == 'hit'
        assert sig['settle_price'] == pytest.approx(1.10)
        assert sig['pnl'] == pytest.approx(100.0)
        assert sig['holding_days'] == 2

    def test_t3_stop_hit(self):
        """窗口内触发止损 → outcome=stopped，按止损价结算"""
        db = {'_schema': '1.0', 'signals': [{
            'signal_id': 'SIG-03', 'ticker': '512800', 'trade_type': 'buy',
            'urgency': 'high', 'entry_price': 1.00, 'shares': 1000,
            'target_price': 1.10, 'stop_price': 0.98,
            'trigger_date': '2026-07-27', 'status': 'triggered',
        }]}
        hist = {'512800': {'2026-07-27': 0.97, '2026-07-28': 1.02, '2026-07-29': 1.05}}
        settle_due_signals(db, hist, '2026-07-29')
        sig = db['signals'][0]
        assert sig['outcome'] == 'stopped'
        assert sig['settle_price'] == pytest.approx(0.98)
        assert sig['pnl'] == pytest.approx(-20.0)
        assert sig['holding_days'] == 1

    def test_t3_target_pct_resolve(self):
        """只有 target_pct 时由触发价换算目标价"""
        db = {'_schema': '1.0', 'signals': [{
            'signal_id': 'SIG-04', 'ticker': '518880', 'trade_type': 'buy',
            'urgency': 'high', 'entry_price': 9.00, 'shares': 500,
            'target_pct': 3.0, 'trigger_date': '2026-07-27', 'status': 'triggered',
        }]}
        hist = {'518880': {'2026-07-27': 9.10, '2026-07-28': 9.30, '2026-07-29': 9.20}}  # 9.30 >= 9.27
        settle_due_signals(db, hist, '2026-07-29')
        sig = db['signals'][0]
        assert sig['outcome'] == 'hit'
        assert sig['settle_price'] == pytest.approx(9.27)  # 9.00 * 1.03
        assert sig['pnl'] == pytest.approx(135.0)

    def test_sell_signal_direction(self):
        """卖出信号：窗口内收盘价 <= 目标价 → 达标（卖对了）"""
        db = {'_schema': '1.0', 'signals': [{
            'signal_id': 'SIG-05', 'ticker': '512800', 'trade_type': 'sell',
            'urgency': 'high', 'entry_price': 1.00, 'cost_basis': 0.90, 'shares': 1000,
            'target_price': 0.95, 'trigger_date': '2026-07-27', 'status': 'triggered',
        }]}
        hist = {'512800': {'2026-07-27': 0.99, '2026-07-28': 0.94, '2026-07-29': 0.96}}
        settle_due_signals(db, hist, '2026-07-29')
        sig = db['signals'][0]
        assert sig['outcome'] == 'hit'
        assert sig['pnl'] == pytest.approx(100.0)  # (1.00-0.90)*1000 卖出本身
        assert sig['avoided_loss'] == pytest.approx(50.0)  # (1.00-0.95)*1000

    def test_not_due_not_settled(self):
        """未到 T+3 → 不结算"""
        db = {'_schema': '1.0', 'signals': [{
            'signal_id': 'SIG-06', 'ticker': '512800', 'trade_type': 'buy',
            'urgency': 'high', 'entry_price': 1.00, 'shares': 1000,
            'target_price': 1.10, 'trigger_date': '2026-07-28', 'status': 'triggered',
        }]}
        hist = {'512800': {'2026-07-28': 1.02, '2026-07-29': 1.03, '2026-07-30': 1.04}}
        settle_due_signals(db, hist, '2026-07-28')  # 今天是触发日
        assert db['signals'][0]['status'] == 'triggered'

    def test_no_target_price_falls_back_t3(self):
        """无目标价 → 退化为 T+3 收盘结算"""
        db = {'_schema': '1.0', 'signals': [{
            'signal_id': 'SIG-07', 'ticker': '512800', 'trade_type': 'buy',
            'urgency': 'high', 'entry_price': 1.00, 'shares': 1000,
            'trigger_date': '2026-07-27', 'status': 'triggered',
        }]}
        hist = {'512800': {'2026-07-27': 1.02, '2026-07-28': 1.04, '2026-07-29': 1.03}}
        settle_due_signals(db, hist, '2026-07-29')
        sig = db['signals'][0]
        assert sig['outcome'] == 'miss'
        assert sig['settle_price'] == pytest.approx(1.03)
```

> 注：`2026-07-27` 是周一，`next_trading_day`×3 = 7/29（周三），trading_calendar 的交易日判定以 `config/trading_calendar.py` 实际逻辑为准；若测试日期恰逢日历节假日，用 `python -c "from config.trading_calendar import next_trading_day; ..."` 核对后调整测试日期。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd my_doc/每日复盘/harness/automation && python -m pytest tests/test_signal_tracking_parse.py::TestSettleDueSignals -v`
Expected: FAIL（旧测试 TypeError：price_lookup 期望 float 却收到 dict；新测试断言失败）

- [ ] **Step 3: 实现** — 替换 `lib/signal_tracking.py` 的 `settle_due_signals`（保留 `calc_buy_pnl`/`calc_sell_pnl`/`calc_avoided_loss`）：

```python
def _resolve_target_price(sig: dict) -> tuple:
    """计算信号目标价/止损价：显式价格优先，否则用百分比×触发价。"""
    entry = sig.get('entry_price') or 0.0
    target = sig.get('target_price')
    if target is None and sig.get('target_pct') is not None and entry:
        target = round(entry * (1 + sig['target_pct'] / 100.0), 4)
    stop = sig.get('stop_price')
    if stop is None and sig.get('stop_pct') is not None and entry:
        stop = round(entry * (1 + sig['stop_pct'] / 100.0), 4)
    return target, stop


def settle_due_signals(tracking: dict, price_history: dict, today: str = '') -> dict:
    """目标价结算：触发后 T+3 交易日内，收盘达到目标价→达标(hit)；触发止损→stopped；
    否则按 T+3 收盘价结算(miss)。返回更新后的 dict（不写磁盘）。

    price_history: {ticker: {date_iso: close_float}} — 触发日至 T+3 的每日收盘价，
    由调用方（复盘 prompt 脚本）用腾讯财经日K填充。
    仅结算 status ∈ {open, triggered, executed, partial_executed} 且已到期的信号。
    """
    if not today:
        today = date.today().isoformat()

    for sig in tracking.get('signals', []):
        if sig.get('status') not in ('open', 'triggered', 'executed', 'partial_executed'):
            continue
        try:
            trigger_date = date.fromisoformat(sig['trigger_date'])
            today_date = date.fromisoformat(today)
        except Exception:
            continue

        # T+3 结算日（3 个交易日）
        settle_date = trigger_date
        for _ in range(3):
            settle_date = next_trading_day(settle_date)
        if today_date < settle_date:
            continue  # 未到期

        ticker = sig.get('ticker', '')
        hist = price_history.get(ticker, {})
        if not hist:
            continue  # 无价格数据，等待下次

        window_dates = sorted(d for d in hist
                              if trigger_date.isoformat() <= d <= settle_date.isoformat())
        closes = [hist[d] for d in window_dates]
        if not closes:
            continue

        target_price, stop_price = _resolve_target_price(sig)
        is_buy = sig.get('trade_type') == 'buy'
        entry = sig.get('entry_price') or 0.0
        shares = sig.get('shares', 0)

        # 达标/止损判定（按日期顺序，取最先发生的）
        outcome = 'miss'
        settle_price = closes[-1]  # 默认 T+3 收盘
        hit_idx = len(window_dates) - 1
        for i, (d, close) in enumerate(zip(window_dates, closes)):
            if target_price is not None:
                if (is_buy and close >= target_price) or (not is_buy and close <= target_price):
                    outcome = 'hit'; settle_price = target_price; hit_idx = i
                    break
            if stop_price is not None:
                if (is_buy and close <= stop_price) or (not is_buy and close >= stop_price):
                    outcome = 'stopped'; settle_price = stop_price; hit_idx = i
                    break

        if is_buy:
            pnl = calc_buy_pnl(entry, settle_price, shares)
            avoided_loss = 0.0
        else:
            sell_price = sig.get('entry_price') or 0.0
            cost = sig.get('cost_basis', sell_price) or sell_price
            pnl = calc_sell_pnl(sell_price, cost, shares)
            avoided_loss = calc_avoided_loss(sell_price, settle_price, shares)

        sig['pnl'] = round(pnl, 2)
        sig['avoided_loss'] = round(avoided_loss, 2)
        sig['outcome'] = outcome
        sig['settle_price'] = settle_price
        sig['settle_date'] = today
        sig['exit_date'] = today
        sig['holding_days'] = hit_idx + 1
        sig['status'] = 'settled'
        sig.setdefault('status_history', []).append({
            'date': today, 'status': 'settled',
            'note': f'T+3目标价结算: {outcome} @{settle_price}',
        })

    return tracking
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd my_doc/每日复盘/harness/automation && python -m pytest tests/test_signal_tracking_parse.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add my_doc/每日复盘/harness/automation/lib/signal_tracking.py my_doc/每日复盘/harness/automation/tests/test_signal_tracking_parse.py
git commit -m "feat: settle_due_signals 目标价结算模式（hit/stopped/miss + T+3窗口）
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 新增 signal_quality.py 质量指标库

**Files:**
- Create: `my_doc/每日复盘/harness/automation/lib/signal_quality.py`
- Create: `my_doc/每日复盘/harness/automation/tests/test_signal_quality.py`

**Interfaces:**
- Consumes: Task 2 的 settled 信号字段（`outcome`/`settle_price`/`holding_days`/`pnl`/`trade_type`/`entry_price`/`status`）
- Produces: 8 个指标函数 + `generate_quality_dashboard(signals, settled, today='') -> dict`（供复盘 prompt 渲染仪表盘）

- [ ] **Step 1: 写失败测试** — 新建 `tests/test_signal_quality.py`：

```python
"""
signal_quality.py 测试 — 信号质量 A 层 8 项指标
覆盖: 触发率/目标达成率/平均达标天数/平均盈亏比/方向准确率/预期vs实际偏差/期望价值/最大亏损
"""

import sys
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from signal_quality import (
    calc_trigger_rate,
    calc_target_hit_rate,
    calc_avg_hit_days,
    calc_avg_profit_loss_ratio,
    calc_direction_accuracy,
    calc_expected_vs_actual,
    calc_signal_expected_value,
    calc_max_loss,
    generate_quality_dashboard,
)


def _sig(sid, status='settled', trade_type='buy', entry=1.00, pnl=0.0,
         outcome='miss', holding_days=3, settle_price=1.00,
         priority='P1', expected=None):
    return {
        'signal_id': sid, 'ticker': '512800', 'trade_type': trade_type,
        'priority': priority, 'urgency': 'high', 'status': status,
        'entry_price': entry, 'shares': 1000, 'pnl': pnl,
        'outcome': outcome, 'settle_price': settle_price,
        'holding_days': holding_days, 'expected_trigger_rate': expected,
    }


class TestTriggerRate:
    def test_p1_only(self):
        signals = [
            _sig('A', status='settled', priority='P1'),
            _sig('B', status='triggered', priority='P1'),
            _sig('C', status='expired', priority='P1'),   # 已过期不追踪（但若在库中也不算触发）
            _sig('D', status='settled', priority='P0'),
        ]
        assert calc_trigger_rate(signals, 'P1') == pytest.approx(66.7)

    def test_all(self):
        signals = [_sig('A', status='settled'), _sig('B', status='expired')]
        assert calc_trigger_rate(signals) == pytest.approx(50.0)

    def test_empty(self):
        assert calc_trigger_rate([]) == 0.0


class TestTargetHitRate:
    def test_basic(self):
        settled = [
            _sig('A', outcome='hit', pnl=100.0),
            _sig('B', outcome='miss', pnl=-20.0),
            _sig('C', outcome='stopped', pnl=-30.0),
        ]
        assert calc_target_hit_rate(settled) == pytest.approx(33.3)

    def test_empty(self):
        assert calc_target_hit_rate([]) == 0.0


class TestAvgHitDays:
    def test_basic(self):
        settled = [
            _sig('A', outcome='hit', holding_days=1),
            _sig('B', outcome='hit', holding_days=2),
            _sig('C', outcome='miss', holding_days=3),
        ]
        assert calc_avg_hit_days(settled) == pytest.approx(1.5)  # 只算达标

    def test_no_hit(self):
        settled = [_sig('A', outcome='miss', holding_days=3)]
        assert calc_avg_hit_days(settled) == 0.0


class TestAvgProfitLossRatio:
    def test_basic(self):
        settled = [
            _sig('A', outcome='hit', pnl=200.0),
            _sig('B', outcome='hit', pnl=100.0),
            _sig('C', outcome='miss', pnl=-50.0),
        ]
        # 平均盈 150 / 平均亏 50 = 3.0
        assert calc_avg_profit_loss_ratio(settled) == pytest.approx(3.0)

    def test_no_loss(self):
        settled = [_sig('A', outcome='hit', pnl=100.0)]
        assert calc_avg_profit_loss_ratio(settled) == 0.0


class TestDirectionAccuracy:
    def test_buy_up_correct(self):
        settled = [
            _sig('A', trade_type='buy', entry=1.00, settle_price=1.05),   # 涨 → 对
            _sig('B', trade_type='buy', entry=1.00, settle_price=0.95),   # 跌 → 错
        ]
        assert calc_direction_accuracy(settled) == pytest.approx(50.0)

    def test_sell_down_correct(self):
        settled = [
            _sig('A', trade_type='sell', entry=1.00, settle_price=0.95),  # 跌 → 对
            _sig('B', trade_type='sell', entry=1.00, settle_price=1.05),  # 涨 → 错
        ]
        assert calc_direction_accuracy(settled) == pytest.approx(50.0)


class TestExpectedVsActual:
    def test_basic(self):
        signals = [
            _sig('A', status='settled', expected=40.0),
            _sig('B', status='expired', expected=60.0),
        ]
        res = calc_expected_vs_actual(signals)
        assert len(res['rows']) == 2
        # 实际触发率 50% - 预期均值 50% = 0
        assert res['avg_gap'] == pytest.approx(0.0)

    def test_no_expected(self):
        signals = [_sig('A', status='settled')]  # expected=None
        res = calc_expected_vs_actual(signals)
        assert res['rows'] == []
        assert res['avg_gap'] is None


class TestSignalExpectedValue:
    def test_basic(self):
        settled = [_sig('A', pnl=100.0), _sig('B', pnl=-20.0)]
        assert calc_signal_expected_value(settled) == pytest.approx(40.0)

    def test_empty(self):
        assert calc_signal_expected_value([]) == 0.0


class TestMaxLoss:
    def test_basic(self):
        settled = [_sig('A', pnl=100.0), _sig('B', pnl=-50.0), _sig('C', pnl=-80.0)]
        assert calc_max_loss(settled) == pytest.approx(-80.0)

    def test_empty(self):
        assert calc_max_loss([]) == 0.0


class TestGenerateDashboard:
    def test_all_fields(self):
        signals = [_sig('A', status='settled', priority='P1', expected=50.0)]
        settled = [_sig('A', outcome='hit', pnl=100.0, holding_days=2, settle_price=1.05)]
        d = generate_quality_dashboard(signals, settled, '2026-08-26')
        assert d['date'] == '2026-08-26'
        assert 'trigger_rate_p1' in d and 'trigger_rate_all' in d
        assert 'target_hit_rate' in d and 'avg_hit_days' in d
        assert 'avg_profit_loss_ratio' in d and 'direction_accuracy' in d
        assert 'expected_vs_actual' in d
        assert 'signal_expected_value' in d and 'max_loss' in d
```

> 注意：文件顶部需 `import pytest`。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd my_doc/每日复盘/harness/automation && python -m pytest tests/test_signal_quality.py -v`
Expected: FAIL（ModuleNotFoundError: signal_quality）

- [ ] **Step 3: 实现** — 新建 `lib/signal_quality.py`：

```python
"""
信号质量统计核心逻辑 — 每日信号模块优化（spec: docs/superpowers/specs/2026-08-26-signal-quality-design.md）

从 signal_tracking.json 的 signals 计算 A 层 8 项质量指标。
纯计算函数，不读写磁盘，不调用外部 API。

指标（A 层全自动）:
  触发率 / 目标达成率 / 平均达标天数 / 平均盈亏比 / 方向准确率 /
  预期vs实际触发率偏差 / 信号期望价值 / 单笔最大亏损
"""

_TRIGGERED_STATUSES = ('triggered', 'executed', 'partial_executed', 'settled')


def _is_triggered(sig: dict) -> bool:
    return sig.get('status') in _TRIGGERED_STATUSES


def calc_trigger_rate(signals: list, priority: str = None) -> float:
    """触发率 = 已触发 / 总数。priority 为 None 时统计全部（百分比）。"""
    pool = [s for s in signals if priority is None or s.get('priority') == priority]
    if not pool:
        return 0.0
    hit = sum(1 for s in pool if _is_triggered(s))
    return round(hit / len(pool) * 100, 1)


def calc_target_hit_rate(settled: list) -> float:
    """目标达成率 = outcome=='hit' / 已结算数（百分比）。"""
    if not settled:
        return 0.0
    hits = sum(1 for s in settled if s.get('outcome') == 'hit')
    return round(hits / len(settled) * 100, 1)


def calc_avg_hit_days(settled: list) -> float:
    """平均达标天数 = 达标信号 holding_days 平均（快进快出验证，目标 1-2 天）。"""
    hits = [s.get('holding_days') for s in settled
            if s.get('outcome') == 'hit' and s.get('holding_days') is not None]
    if not hits:
        return 0.0
    return round(sum(hits) / len(hits), 1)


def calc_avg_profit_loss_ratio(settled: list) -> float:
    """平均盈亏比 = 平均盈利单金额 / 平均亏损单金额（按 pnl 绝对值）。"""
    wins = [s.get('pnl', 0.0) for s in settled if (s.get('pnl') or 0) > 0]
    losses = [s.get('pnl', 0.0) for s in settled if (s.get('pnl') or 0) < 0]
    if not wins or not losses:
        return 0.0
    avg_win = sum(wins) / len(wins)
    avg_loss = abs(sum(losses) / len(losses))
    if avg_loss == 0:
        return 0.0
    return round(avg_win / avg_loss, 2)


def calc_direction_accuracy(settled: list) -> float:
    """方向准确率 = 信号方向与结算方向一致比例（百分比）。
    buy: settle_price >= entry_price → 正确；sell: settle_price <= entry_price → 正确。"""
    if not settled:
        return 0.0
    correct = 0
    for s in settled:
        is_buy = s.get('trade_type') == 'buy'
        entry = s.get('entry_price') or 0.0
        settle_p = s.get('settle_price') or 0.0
        if (is_buy and settle_p >= entry) or (not is_buy and settle_p <= entry):
            correct += 1
    return round(correct / len(settled) * 100, 1)


def calc_expected_vs_actual(signals: list) -> dict:
    """预期触发率 vs 实际触发率（生成者校准）。
    返回 {rows: [{signal_id, expected, triggered}], avg_gap: float|None}
    avg_gap = 实际触发率 − 预期均值（百分点），正值=生成者偏保守，负值=偏乐观。"""
    rows = []
    for s in signals:
        exp = s.get('expected_trigger_rate')
        if exp is None:
            continue
        rows.append({
            'signal_id': s.get('signal_id', ''),
            'expected': exp,
            'triggered': _is_triggered(s),
        })
    if not rows:
        return {'rows': [], 'avg_gap': None}
    actual_rate = sum(1 for r in rows if r['triggered']) / len(rows) * 100
    avg_exp = sum(r['expected'] for r in rows) / len(rows)
    return {'rows': rows, 'avg_gap': round(actual_rate - avg_exp, 1)}


def calc_signal_expected_value(settled: list) -> float:
    """信号期望价值 = 平均单次 P&L（已结算信号）。"""
    if not settled:
        return 0.0
    return round(sum(s.get('pnl', 0.0) for s in settled) / len(settled), 2)


def calc_max_loss(settled: list) -> float:
    """单笔最大亏损 = min(pnl)（短线风控）。"""
    pnls = [s.get('pnl', 0.0) for s in settled]
    if not pnls:
        return 0.0
    return round(min(pnls), 2)


def generate_quality_dashboard(signals: list, settled: list, today: str = '') -> dict:
    """汇总 A 层 8 项指标为仪表盘数据 dict（复盘 prompt 渲染为表格）。"""
    return {
        'date': today,
        'trigger_rate_p1': calc_trigger_rate(signals, 'P1'),
        'trigger_rate_all': calc_trigger_rate(signals),
        'target_hit_rate': calc_target_hit_rate(settled),
        'avg_hit_days': calc_avg_hit_days(settled),
        'avg_profit_loss_ratio': calc_avg_profit_loss_ratio(settled),
        'direction_accuracy': calc_direction_accuracy(settled),
        'expected_vs_actual': calc_expected_vs_actual(signals),
        'signal_expected_value': calc_signal_expected_value(settled),
        'max_loss': calc_max_loss(settled),
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd my_doc/每日复盘/harness/automation && python -m pytest tests/test_signal_quality.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add my_doc/每日复盘/harness/automation/lib/signal_quality.py my_doc/每日复盘/harness/automation/tests/test_signal_quality.py
git commit -m "feat: 新增 signal_quality 信号质量指标库（A层8项）
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 早盘分析模板第九节重写 + 新增关注列表

**Files:**
- Modify: `my_doc/每日复盘/harness/prompts/早盘分析-模板.md`

**Interfaces:**
- Consumes: Task 1/2/3 定义的字段格式（12 列信号表、`目标+3%/止损-2%`、预期触发率）
- Produces: 新信号生成规则（供每日早盘执行时遵循）；`报告审阅经验.md` 无需改动

- [ ] **Step 1: 重写第九节信号生成规则**

将 `早盘分析-模板.md` 第九节（`## 九、每日信号生成`，当前约 249-415 行）整体替换为：

````markdown
## 九、每日信号生成

> 从早盘分析中提取**机会型短线信号**（快进快出），输出到 `reports/{yyyyMMdd}/每日信号.md`。
> 定位：**少而精**——每天 4-6 条（P0 风控 ≤3 + P1 操作 2-4），不做广覆盖雷达。

### 9.1 信号构成（强制）

| 类型 | 数量 | 考核指标 | 说明 |
|------|------|---------|------|
| P0 风控 | ≤3 | 不考核触发率 | 普跌否决/黄金守位/科技回避等纪律。不触发=市场安全，价值在"有备无患" |
| P1 操作 | 2-4 | 触发率 + 目标达成率 | 高置信度短线操作（正T/减仓/建仓/锁利），按 T+3 目标价结算口径设计 |

**验证型判断禁止进信号表**（防御延续/农业延续/反抽观察等）——写入报告正文或关注列表（§9.4），不进信号表。

### 9.2 信号表结构（12 列）

```
| 优先级 | 标的 | 触发条件 | 操作类型 | 状态 | 方向 | 紧急度 | 预期触发率 | 目标/止损 | 有效时段 | 仓位 | 信号ID |
```

- `预期触发率`：P0 填 `—`；**P1 必填百分比**（生成时估计，复盘自动校准）
- `目标/止损`：格式 `目标+3%/止损-2%`（百分比）或 `目标1.75/止损1.66`（显式价）；P1 必填目标，止损推荐
- 信号ID：`SIG-YYYYMMDD-NN`（盘中追加自动顺延）

### 9.3 P1 信号生成规则

1. **双向设计**：每条 P1 = 触发路径（明确价位/量能+仓位+时段）+ 证伪路径（什么情况说明早盘判断错→信号作废）。杜绝"既不触发又无信息量"。
2. **必填预期触发率**：生成时估计（如 40%）。
3. **必填目标/止损**：短线止盈目标（+X% 或显式价）+ 止损线。
4. **短线定位**：目标价按 T+3 交易日口径设计（快进快出），不做中线。

### 9.4 关注列表（观察雷达，非信号）

早盘报告中新增"关注列表"小节（报告正文内），观察雷达全部移入此处，含量化升级条件：

```
| 关注标的 | 观察逻辑 | 升级条件（量化） |
|---------|---------|-----------------|
| 农业159825 | 主线延续验证 | 方向确认>30min+放量突破0.74且涨停≥3只→盘中临时追加信号 |
```

盘中 Tier 1/2 发现升级条件满足 → **临时追加信号**（操作来源="盘中信号"），不预先占信号名额。

### 9.5 输出文件结构

每日信号.md 输出结构（与盘中/复盘共享）：
- 信号总表（12 列，按"优先级→标的→触发条件"排序）
- 信号触发记录（盘中填）
- 盘中验证记录（盘中填）
- 信号评价（复盘填）
- 当日信号统计（复盘填）
- 信号收益追踪（复盘填）
````

- [ ] **Step 2: 验证模板无残留旧引用**

Run: `cd my_doc/每日复盘/harness && grep -n "升级条件\|预期收益日\|操作来源" prompts/早盘分析-模板.md | head -20`
Expected: 输出为空（旧列名不再出现在模板中；若残留则删除）

- [ ] **Step 3: Commit**

```bash
git add my_doc/每日复盘/harness/prompts/早盘分析-模板.md
git commit -m "feat: 早盘模板第九节重写（少而精+预期触发率+目标价+关注列表）
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 复盘模板 2c/2d 扩展（质量仪表盘 + 强制入库 + 目标价结算）

**Files:**
- Modify: `my_doc/每日复盘/harness/prompts/复盘分析-模板.md`

**Interfaces:**
- Consumes: `generate_quality_dashboard`（Task 3）、`settle_due_signals` 新签名（Task 2）、`parse_signal_markdown`/`merge_new_signals`（现有）
- Produces: 复盘 prompt 内的强制入库步骤 + 仪表盘渲染规则

- [ ] **Step 1: 扩展 2c 节（信号执行复盘 → 质量仪表盘）**

在 `复盘分析-模板.md` 2c 节末尾（"信号遗漏与机会盲区检测"表格之后、"### 2d" 之前）插入：

````markdown
**信号质量仪表盘（v2.0 自动生成，调用 lib/signal_quality.py）**：

> 前置：确认 `config/signal_tracking.json` 已入库今日触发信号并结算到期信号（入库步骤见 2d）。
> 运行：`python -X utf8 -c "import json,sys; sys.path.insert(0,'my_doc/每日复盘/harness/automation'); from lib.signal_quality import generate_quality_dashboard; db=json.load(open('my_doc/每日复盘/harness/automation/config/signal_tracking.json',encoding='utf-8')); settled=[s for s in db['signals'] if s.get('status')=='settled']; print(json.dumps(generate_quality_dashboard(db['signals'], settled, '{today}'), ensure_ascii=False, indent=1))"`
> 将输出渲染为下表：

| 维度 | 指标 | 数值 | 阈值/目标 | 状态 |
|------|------|------|----------|:---:|
| 触达 | P1 触发率（累计）| {trigger_rate_p1}% | ≥40% | ✅/⚠️ |
| 触达 | 全量触发率 | {trigger_rate_all}% | — | — |
| 结果 | 目标达成率 | {target_hit_rate}% | ≥50% | ✅/⚠️ |
| 结果 | 平均达标天数 | {avg_hit_days} 天 | 1-2 天 | ✅/⚠️ |
| 结果 | 平均盈亏比 | {avg_profit_loss_ratio} | ≥1.5 | ✅/⚠️ |
| 结果 | 单笔最大亏损 | {max_loss} 元 | 风控线内 | ✅/⚠️ |
| 方向 | 方向准确率 | {direction_accuracy}% | ≥60% | ✅/⚠️ |
| 校准 | 预期vs实际偏差 | {expected_vs_actual.avg_gap}pp | ±20pp 内 | ✅/⚠️ |
| 价值 | 信号期望价值 | {signal_expected_value} 元/单 | 为正 | ✅/⚠️ |

**预警与校准（必答）**：
- P1 周触发率 <40% → ⚠️ 预警：触发条件过严或信号类型需调整（给出具体建议）
- 目标达成率 <50% → 检查目标价设定是否过高（对照实际 T+3 走势）
- 预期触发率系统性高估（avg_gap < −20）→ 生成者偏乐观，建议下调预期
- 将校准结论沉淀到 `harness/experience/投资经验.md` 信号设计章节
````

- [ ] **Step 2: 扩展 2d 节（强制入库 + 目标价结算）**

在 `复盘分析-模板.md` 2d 节开头（"### 2d. 信号收益追踪" 标题下、现有读取说明之前）插入：

````markdown
**强制入库与结算步骤（v2.0，禁止跳过）**：

1. **解析入库**：从 `reports/{today}/每日信号.md` 解析已触发信号并合并入追踪库：
   ```bash
   python -X utf8 -c "
   import json, sys
   sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
   from lib.signal_tracking import parse_signal_markdown, merge_new_signals
   md = open('my_doc/每日复盘/reports/{today}/每日信号.md', encoding='utf-8').read()
   db_path = 'my_doc/每日复盘/harness/automation/config/signal_tracking.json'
   db = json.load(open(db_path, encoding='utf-8'))
   recs = parse_signal_markdown(md, '{today}')
   db = merge_new_signals(db, recs)
   json.dump(db, open(db_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
   print(f'入库 {len(recs)} 条, 库内信号总数 {len(db[\"signals\"])}')"
   ```
2. **拉取 T+3 收盘价并结算**：对到期信号（触发日+3交易日 ≤ 今日），用腾讯财经日K拉取触发日至 T+3 的每日收盘价（`a-stock-data` §1.2 或腾讯日K），构造 `{ticker: {date: close}}` 后调用 `settle_due_signals(db, price_history, today)` 并写回。
3. **更新聚合**：`update_aggregation(db)` 后写回 `signal_tracking.json`。
4. **本日结算信号表**：从 `db['signals']` 中 `settle_date == today` 的记录渲染下表。
````

- [ ] **Step 3: 更新 2d 节现有表格口径**

将 2d 节"累计追踪统计"表替换为：

```markdown
| 指标 | 数值 |
|------|:---:|
| 累计追踪信号数 | N |
| 已结算 | N（持仓中: N） |
| 累计已实现P&L | ±XXX.XX元 |
| 累计避免损失 | XXX.XX元 |
| 总胜率（目标达成率） | XX%（W/L） |
| P1信号: 目标达成率 / 平均达标天数 | XX% / X.X天 |
| 低紧急度信号: 目标达成率 | XX% |
```

- [ ] **Step 4: Commit**

```bash
git add my_doc/每日复盘/harness/prompts/复盘分析-模板.md
git commit -m "feat: 复盘模板2c/2d扩展（质量仪表盘+强制入库+目标价结算）
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 盘中模板 Tier 调整（观察信号改临时追加）

**Files:**
- Modify: `my_doc/每日复盘/harness/prompts/盘中分析-模板.md`

**Interfaces:**
- Consumes: 无代码接口（纯 prompt 文本）
- Produces: 盘中验证逻辑与"临时追加"规则

- [ ] **Step 1: 更新信号验证规则**

在 `盘中分析-模板.md` "### 3.1 读取信号清单" 处追加说明，并在"盘中追加信号生成"节调整：

````markdown
### 3.1 读取信号清单（v2.0）

从 `reports/{yyyyMMdd}/每日信号.md` 的信号总表中提取：
- 所有状态为 **"待执行"** 的信号（P0 风控 + P1 操作）
- 跳过状态为"已执行""已过期""已取消"的信号
- 从信号触发记录表检查用户操作列是否已有填写（防止重复触发）

> ⚠️ **v2.0 变更**：早盘信号表已无 P2 观察信号（观察雷达移入早盘报告"关注列表"）。
> 观察类机会通过**盘中临时追加**（3.4 节 Tier 1/2）发现后生成，不预先占信号名额。
````

并在盘中追加信号生成节（Tier 逻辑所在处）开头追加：

````markdown
> **v2.0 临时追加规则**：Tier 1/2 发现新机会时，对照早盘报告"关注列表"的升级条件（量化阈值满足）→ 追加信号；
> Tier 3 无新机会 → 强制输出"当前无新增信号机会"。追加信号必须符合 12 列格式，操作来源="盘中信号"。
````

- [ ] **Step 2: 验证**

Run: `cd my_doc/每日复盘/harness && grep -n "v2.0" prompts/盘中分析-模板.md`
Expected: 输出两处 v2.0 标注

- [ ] **Step 3: Commit**

```bash
git add my_doc/每日复盘/harness/prompts/盘中分析-模板.md
git commit -m "feat: 盘中模板信号验证规则更新（P2移除+临时追加）
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: 调度新增 signal_quality_weekly + 周报 prompt

**Files:**
- Modify: `.claude/scripts/task_schedule.json`
- Create: `my_doc/每日复盘/harness/automation/prompts/auto_signal_quality_weekly.md`

**Interfaces:**
- Consumes: `generate_quality_dashboard`（Task 3）
- Produces: 周报任务（每周三 16:30，`trading_day_required: false`）

- [ ] **Step 1: task_schedule.json 添加任务**

在 `.claude/scripts/task_schedule.json` 的 `tasks` 数组末尾（`pending_remind` 任务对象之后、数组闭合 `]` 之前）追加：

```json
    ,
    {
      "task_id": "signal_quality_weekly",
      "target_time": "16:30",
      "days_of_week": [2],
      "trading_day_required": false,
      "prompt_file": "my_doc/每日复盘/harness/automation/prompts/auto_signal_quality_weekly.md",
      "window_minutes": 7,
      "description": "信号质量周报 (每周三收盘后)"
    }
```

- [ ] **Step 2: 验证 JSON 合法性 + 调度器可解析**

Run:
```bash
python -X utf8 -c "import json; d=json.load(open('.claude/scripts/task_schedule.json',encoding='utf-8')); print([t['task_id'] for t in d['tasks']][-3:])"
python .claude/scripts/task_scheduler.py --status 2>&1 | head -5
```
Expected: 输出含 `signal_quality_weekly`；调度器 --status 正常输出（无 JSON 解析错误）

- [ ] **Step 3: 创建周报 prompt** — 新建 `my_doc/每日复盘/harness/automation/prompts/auto_signal_quality_weekly.md`：

````markdown
# 信号质量周报（每周三收盘后）

> 触发：每周三 16:30（task_schedule.json: signal_quality_weekly）| 上周五触发的信号 T+3=本周三，上周数据完整

## 一、数据读取

读取 `config/signal_tracking.json`，统计**上周一至上周五触发**的信号（`trigger_date` 在上周区间）。

## 二、周度指标（调用 lib/signal_quality.py）

```bash
python -X utf8 -c "
import json, sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.signal_quality import generate_quality_dashboard
from datetime import date
db = json.load(open('my_doc/每日复盘/harness/automation/config/signal_tracking.json', encoding='utf-8'))
# 上周信号（按 trigger_date 过滤，上周一~周五）
import datetime
today = date.today()
last_mon = today - datetime.timedelta(days=today.weekday() + 7)
last_fri = last_mon + datetime.timedelta(days=4)
week = [s for s in db['signals'] if last_mon.isoformat() <= s.get('trigger_date','') <= last_fri.isoformat()]
settled = [s for s in week if s.get('status') == 'settled']
print(json.dumps(generate_quality_dashboard(week, settled, today.isoformat()), ensure_ascii=False, indent=1))
print('上周信号数:', len(week), '已结算:', len(settled))
" 2>&1
```

## 三、周报输出（reports/weekly/信号质量周报.md）

1. **本周指标表**（同复盘仪表盘：触发率/达成率/盈亏比/方向准确率/持有天数/偏差/期望价值/最大亏损）
2. **信号价值排名**：按 `pnl` 排序已结算信号，标记 TOP 值得保留的信号类型 vs 该淘汰的
3. **环比上周**：与上周周报指标对比（读上一份周报或累计值）
4. **校准建议**：
   - P1 周触发率 <40% → 条件过严/类型需调整的具体建议
   - 目标达成率 <50% → 目标价设定校准
   - 预期vs实际偏差 → 生成者校准
   - 保留/淘汰/调整信号类型决策（如"农业延续验证类信号已连续 N 周 0 触发，建议移除"）
5. **沉淀经验**：将可复用结论追加到 `harness/experience/投资经验.md` 信号设计章节
````

- [ ] **Step 4: 创建 reports/weekly 目录**

Run: `mkdir -p my_doc/每日复盘/reports/weekly && echo created`
Expected: created

- [ ] **Step 5: Commit**

```bash
git add .claude/scripts/task_schedule.json my_doc/每日复盘/harness/automation/prompts/auto_signal_quality_weekly.md
git commit -m "feat: 新增 signal_quality_weekly 周报任务（周三16:30）
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: skill 同步 + 经验沉淀

**Files:**
- Modify: `.claude/skills/daily-review-harness/SKILL.md`
- Modify: `my_doc/每日复盘/harness/experience/投资经验.md`

**Interfaces:**
- Consumes: 全部前述设计
- Produces: 文档同步（无代码接口）

- [ ] **Step 1: 同步 daily-review-harness SKILL.md**

在 SKILL.md "早盘模式" 流程第 6 步（每日信号生成）处更新，并在"复盘模式"第 5 步（信号执行复盘）处补充仪表盘与入库说明：

````markdown
6. **生成每日信号**：从持仓映射分析和操作清单中提取结构化信号，按 `harness/prompts/早盘分析-模板.md` 第九节规则（**v2.0：少而精——P0 风控≤3 + P1 操作 2-4 条，观察雷达移入关注列表**）输出 `reports/{today}/每日信号.md`
   - 信号必须可量化、可验证、有时效（短线，T+3 目标价结算口径）
   - P1 信号必填预期触发率 + 目标/止损
   - P0信号 ≤ 3条（风险控制信号精而不多）
   - 总信号 4-6 条
   - 信号总表按"优先级→标的→触发条件"排序（重要信息前置），信号ID在末尾便于盘中追加
````

````markdown
5. **信号执行复盘**：读取 `reports/{today}/每日信号.md`，逐条评价决策质量和执行质量，更新信号评价表。**v2.0 新增**：① 强制入库（parse_signal_markdown → merge_new_signals 写入 signal_tracking.json）；② 目标价结算（settle_due_signals 新签名，T+3 窗口 hit/stopped/miss）；③ 质量仪表盘（generate_quality_dashboard 渲染 8 项指标 + 预警）
6. **报告审阅**：参照 `harness/experience/报告审阅经验.md` 进行 2-3 轮审阅
7. **经验沉淀**（见下文协议）——信号设计经验追加到 `harness/experience/投资经验.md`
8. **生成次日 staging prompts**（见下文协议）
9. **归档当日 staging** → `harness/archive/{today}/`
10. **自动同步持仓配置**：读取 `每日调仓.md` "当前持仓"表 → 覆写 `harness/config/持仓.md`。比对上一日持仓，在复盘报告中列出变更
````

在 SKILL.md "自动化调度" 部分（周末任务行前）插入：

````
  周三 16:30 → 信号质量周报（上周信号 T+3 全部结算完成，数据完整）
````

- [ ] **Step 2: 沉淀经验到投资经验.md**

在 `my_doc/每日复盘/harness/experience/投资经验.md` 的"信号设计"章节（`## 信号设计` 标题下）追加：

```markdown
### v2.0 信号质量闭环（2026-08-26 实施）
- 信号定位改为**机会型短线**（快进快出）：P0 风控 ≤3 + P1 操作 2-4，验证型判断移入报告正文/关注列表，不进信号表——根治"触发率低无参考价值"。
- P1 信号必填**预期触发率**与**目标/止损**，结算用**目标价达成判定**（T+3 日内收盘达目标=达标按目标结算），非恒定 T+3 卖出——避免"第2天到目标第3天回落"误判。
- 质量闭环：复盘强制入库 → 目标价结算 → 8 项指标仪表盘（触发率/达成率/盈亏比/方向准确率/持有天数/偏差/期望价值/最大亏损）→ 周三周报。**先看指标校准信号设计，不靠感觉**。
```

- [ ] **Step 3: 验证**

Run: `cd my_doc/每日复盘/harness/automation && python -m pytest tests/ -v 2>&1 | tail -5`
Expected: 全部测试 PASS（全量回归）

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/daily-review-harness/SKILL.md my_doc/每日复盘/harness/experience/投资经验.md
git commit -m "docs: 同步 skill 与经验库（信号质量闭环 v2.0）
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 计划自审（Self-Review）

**1. Spec 覆盖检查**（对照 spec 逐节）：
- §4 信号生成优化 → Task 1（字段）+ Task 4（模板）
- §5 目标价结算 → Task 2
- §6 监控闭环（signal_quality.py + 强制入库）→ Task 3 + Task 5
- §7.1 复盘内嵌仪表盘 → Task 5
- §7.2 周度周报 + 时点 → Task 7
- §8 文件修改清单 → Task 4/5/6/7/8
- §9 测试计划 → Task 1/2/3
- §10 验收标准 → 由 Task 5 仪表盘 + Task 7 周报承载

**2. Placeholder 扫描**：所有代码步骤含完整可执行代码，无 TBD/TODO。

**3. 类型一致性**：
- `settle_due_signals(tracking, price_history: dict, today)` 在 Task 2 定义、Task 5 复用 —— 签名一致
- settled 信号字段 `outcome`/`settle_price`/`holding_days` 在 Task 2 产出、Task 3 消费 —— 一致
- `generate_quality_dashboard(signals, settled, today)` 在 Task 3 定义、Task 5/7 复用 —— 一致
- 12 列信号表结构在 Task 1 测试、Task 4 模板、Task 6 盘中 —— 一致
