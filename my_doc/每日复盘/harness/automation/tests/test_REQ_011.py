"""
REQ-011 TDD 门禁测试 — P0 执行通道结构化：条件单参数机械推导 + 连续 4 日 0% 升级人工裁定

被测模块:
  - lib/cond_order.py（新增）: parse_quantity / build_cond_order / build_cond_order_table / parse_cond_order_table
  - lib/p0_tracking.py（扩展）: check_p0_zero_execution_escalation

覆盖 REQ-011 期望结果:
  ① 条件单参数列组/独立"条件单清单"节 — build_cond_order_table 生成 `## 条件单清单`
  ② 可直接照抄的条件单指令 — build_cond_order 的 cond_order_line
  ③ 盘中复用同一条件单参数 — parse_cond_order_table 从 md 解析回参数
  ④ 收盘统计"条件单是否已挂单" — parse_cond_order_table 解析挂单状态列
  ⑤ 连续 4 日 P0 执行率 0% → 自动升级 PENDING_CONFIRMATION — check_p0_zero_execution_escalation

测试覆盖要求（REQ-011 测试交付物）:
  - 每个公开函数至少 1 条正向 + 1 条边界测试
  - build_cond_order: P0 完整推导 / 非 P0 跳过 / 缺必要字段 / 触发价精度 / 有效期默认
  - build_cond_order_table: 有 P0 生成表 / 无 P0 返回空
  - parse_cond_order_table: 正常解析 / 节不存在返回空
  - check_p0_zero_execution_escalation: 连续 4 日 0% 升级 / 3 日不升级 / rate None 中断 / 100% 中断 / 自定义阈值
"""

import sys
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from cond_order import (
    parse_quantity,
    build_cond_order,
    build_cond_order_table,
    parse_cond_order_table,
    DEFAULT_EXPIRY,
)
from p0_tracking import check_p0_zero_execution_escalation


# ============================================================
# 样本构造
# ============================================================

def _mk_signal(signal_id: str = 'SIG-20261008-01', priority: str = 'P0',
               ticker: str = '601398', name: str = '工商银行',
               direction: str = 'sell', trade_price: float | str = 8.05,
               position: str = '500份', valid_window: str = '09:30 - 14:45 CST',
               trigger_condition: str = '破位 8.05 减仓；站回 9.00 + 期金企稳 → 撤销') -> dict:
    """构造 parse_signal_rows_all 风格的信号记录（含 REQ-011 需要的全部键）。"""
    return {
        'signal_id': signal_id,
        'ticker': ticker,
        'name': name,
        'trade_type': 'sell',
        'direction': direction,
        'priority': priority,
        'urgency': 'high',
        'expected_trigger_rate': None,
        'trade_price': trade_price,
        'target_price': None,
        'stop_price': None,
        'target_pct': None,
        'stop_pct': None,
        'expected_return_date': '',
        'trigger_date': '2026-10-08',
        'status': 'open',
        'source': 'morning_analysis',
        'trigger_condition': trigger_condition,
        'valid_window': valid_window,
        'position': position,
    }


def _mk_store(days: list[dict]) -> dict:
    """构造跨日 store：days = [(date, rate), ...]，rate None 表示当日无 P0 触发。"""
    daily = {}
    for date, rate in days:
        entry = {'triggered': 1, 'executed': 1, 'missed': 0, 'rate': rate}
        if rate == 0.0:
            entry = {'triggered': 1, 'executed': 0, 'missed': 1, 'rate': 0.0}
        daily[date] = entry
    return {'_schema': '1.0', '_updated': '', 'daily': daily}


# ============================================================
# parse_quantity — 从仓位文本解析份额
# ============================================================

class TestParseQuantity:
    def test_positive_shares(self):
        assert parse_quantity('+200份') == 200

    def test_negative_with_thousands(self):
        assert parse_quantity('-1,100份（约-25%）') == 1100

    def test_plain_shares(self):
        assert parse_quantity('500份') == 500

    def test_ratio_no_shares(self):
        assert parse_quantity('1/4') == 0

    def test_empty(self):
        assert parse_quantity('') == 0

    def test_bracket_format(self):
        """仓位含括号说明仍能提取份数（REQ-011 生成时格式）。"""
        assert parse_quantity('900份(可用×1/3)') == 900


# ============================================================
# build_cond_order — 从单条 P0 信号机械推导条件单参数
# ============================================================

class TestBuildCondOrder:
    def test_p0_full_derivation(self):
        """P0 完整信号 → 全部条件单参数机械推导。"""
        sig = _mk_signal()
        co = build_cond_order(sig)
        assert co is not None
        assert co['signal_id'] == 'SIG-20261008-01'
        assert co['ticker'] == '601398'
        assert co['name'] == '工商银行'
        assert co['direction'] == '卖出'
        assert co['trigger_price'] == '8.05'          # 保留原精度
        assert co['quantity'] == 500
        assert co['expiry'] == DEFAULT_EXPIRY          # 默认当日 14:45
        # 可直接照抄的条件单指令
        assert '601398' in co['cond_order_line']
        assert '8.05' in co['cond_order_line']
        assert '卖出' in co['cond_order_line']
        assert '500份' in co['cond_order_line']
        assert '14:45' in co['cond_order_line']

    def test_non_p0_returns_none(self):
        """非 P0 信号（P1）→ 不生成条件单。"""
        sig = _mk_signal(priority='P1')
        assert build_cond_order(sig) is None

    def test_missing_ticker_returns_none(self):
        """缺代码（ticker 空）→ 无法下单，返回 None。"""
        sig = _mk_signal(ticker='')
        assert build_cond_order(sig) is None

    def test_missing_trade_price_returns_none(self):
        """缺触发价（trade_price 空/None）→ 无法下单，返回 None。"""
        sig = _mk_signal(trade_price=None)
        assert build_cond_order(sig) is None

    def test_trade_price_precision_preserved(self):
        """触发价精确到 0.001：'8.055' 保持三位小数不截断。"""
        sig = _mk_signal(trade_price=8.055)
        co = build_cond_order(sig)
        assert co['trigger_price'] == '8.055'

    def test_buy_direction(self):
        """买入方向 → 条件单 direction=买入。"""
        sig = _mk_signal(direction='buy', trade_price=1.70, position='1000份')
        co = build_cond_order(sig)
        assert co['direction'] == '买入'

    def test_zero_quantity_fallback(self):
        """仓位无份数（如 1/4）→ quantity=0，条件单指令中份额标 '—'（无明确份额）。"""
        sig = _mk_signal(position='1/4')
        co = build_cond_order(sig)
        assert co['quantity'] == 0
        assert '—' in co['cond_order_line'] or '份额' in co['cond_order_line']

    def test_cancel_hint_default(self):
        """无触发条件文本 → 默认撤销提示（REQ-010 二选一，禁止自动撤销）。"""
        sig = _mk_signal(trigger_condition='')
        co = build_cond_order(sig)
        assert 'REQ-010' in co['cancel_hint'] or '放弃' in co['cancel_hint']


# ============================================================
# build_cond_order_table — 生成 `## 条件单清单` markdown 节
# ============================================================

class TestBuildCondOrderTable:
    def test_with_p0_generates_table(self):
        """有 P0 信号 → 生成含表头 + 每 P0 一行的条件单清单节。"""
        sigs = [_mk_signal(), _mk_signal(signal_id='SIG-20261008-02', ticker='512800',
                                         name='银行ETF', trade_price=1.15, position='1000份')]
        md = build_cond_order_table(sigs)
        assert '## 条件单清单' in md
        assert '信号ID' in md and '条件单指令' in md
        assert 'SIG-20261008-01' in md
        assert 'SIG-20261008-02' in md
        # 每条指令可直接照抄
        assert '601398 触发价 8.05 卖出 500份' in md
        assert '512800 触发价 1.15 卖出 1000份' in md

    def test_p1_excluded(self):
        """混合 P0/P1 → 仅 P0 入清单。"""
        sigs = [_mk_signal(), _mk_signal(signal_id='SIG-20261008-03', priority='P1')]
        md = build_cond_order_table(sigs)
        assert 'SIG-20261008-01' in md
        assert 'SIG-20261008-03' not in md

    def test_no_p0_returns_empty(self):
        """无 P0 → 返回空字符串（早盘不生成空节）。"""
        assert build_cond_order_table([]) == ''
        assert build_cond_order_table([_mk_signal(priority='P1')]) == ''

    def test_roundtrip_parse(self):
        """生成 → 解析 回环一致（盘中复用/收盘统计的输入源）。"""
        sigs = [_mk_signal(), _mk_signal(signal_id='SIG-20261008-02', ticker='512800',
                                         name='银行ETF', trade_price=1.15, position='1000份')]
        md = build_cond_order_table(sigs)
        parsed = parse_cond_order_table(md)
        assert len(parsed) == 2
        assert parsed[0]['signal_id'] == 'SIG-20261008-01'
        assert parsed[0]['quantity'] == 500
        assert parsed[1]['ticker'] == '512800'


# ============================================================
# parse_cond_order_table — 从 md 解析回条件单参数
# ============================================================

class TestParseCondOrderTable:
    def test_parse_full(self):
        """正常解析：含 信号ID/标的/代码/方向/触发价/数量/有效期/指令/挂单状态。"""
        md = build_cond_order_table([_mk_signal()])
        rows = parse_cond_order_table(md)
        assert len(rows) == 1
        row = rows[0]
        assert row['signal_id'] == 'SIG-20261008-01'
        assert row['name'] == '工商银行'
        assert row['ticker'] == '601398'
        assert row['direction'] == '卖出'
        assert row['trigger_price'] == '8.05'
        assert row['quantity'] == 500
        assert row['expiry'] == '14:45'
        assert row['status'] == '待挂单'          # 初始挂单状态
        assert '8.05' in row['cond_order_line']

    def test_section_missing_returns_empty(self):
        """md 无 `## 条件单清单` 节 → 返回空列表。"""
        assert parse_cond_order_table('# 每日信号\n\n## 信号总表\n\n| x |\n') == []

    def test_parse_hung_status(self):
        """挂单状态列已更新（如 盘中 已挂单）→ 解析保留。"""
        md = build_cond_order_table([_mk_signal()])
        md = md.replace('待挂单', '已挂单')
        rows = parse_cond_order_table(md)
        assert rows[0]['status'] == '已挂单'


# ============================================================
# check_p0_zero_execution_escalation — 连续 4 日 0% 升级人工裁定
# ============================================================

class TestCheckP0ZeroExecutionEscalation:
    def test_four_consecutive_zero_escalates(self):
        """连续 4 日 0% → escalate=True（REQ-011 期望结果⑤触发线）。"""
        store = _mk_store([
            ('2026-09-08', 0.0), ('2026-09-09', 0.0),
            ('2026-09-10', 0.0), ('2026-09-11', 0.0),
        ])
        result = check_p0_zero_execution_escalation(store)
        assert result['escalate'] is True
        assert result['streak'] == 4

    def test_three_days_no_escalate(self):
        """连续 3 日 0% → 不升级（未达 4 日红线）。"""
        store = _mk_store([
            ('2026-09-08', 0.0), ('2026-09-09', 0.0), ('2026-09-10', 0.0),
        ])
        result = check_p0_zero_execution_escalation(store)
        assert result['escalate'] is False
        assert result['streak'] == 3

    def test_rate_none_breaks_streak(self):
        """无 P0 触发日（rate None）→ 中断连续 0% 计数。"""
        store = _mk_store([
            ('2026-09-08', 0.0), ('2026-09-09', 0.0),
            ('2026-09-10', 0.0), ('2026-09-11', None), ('2026-09-14', 0.0),
        ])
        result = check_p0_zero_execution_escalation(store)
        # 最近连续 0% 仅 1 日（09-14），09-11 无触发中断
        assert result['escalate'] is False
        assert result['streak'] == 1

    def test_100pct_breaks_streak(self):
        """执行率 100% 日 → 中断连续 0% 计数。"""
        store = _mk_store([
            ('2026-09-08', 0.0), ('2026-09-09', 0.0),
            ('2026-09-10', 100.0), ('2026-09-11', 0.0),
        ])
        result = check_p0_zero_execution_escalation(store)
        assert result['escalate'] is False
        assert result['streak'] == 1

    def test_custom_threshold(self):
        """自定义阈值=6：4 日不升级，6 日升级。"""
        store = _mk_store([
            ('2026-09-08', 0.0), ('2026-09-09', 0.0),
            ('2026-09-10', 0.0), ('2026-09-11', 0.0),
        ])
        assert check_p0_zero_execution_escalation(store, threshold=6)['escalate'] is False
        store2 = _mk_store([
            ('2026-09-08', 0.0), ('2026-09-09', 0.0), ('2026-09-10', 0.0),
            ('2026-09-11', 0.0), ('2026-09-14', 0.0), ('2026-09-15', 0.0),
        ])
        assert check_p0_zero_execution_escalation(store2, threshold=6)['escalate'] is True

    def test_no_entries(self):
        """store 空 → 不升级。"""
        result = check_p0_zero_execution_escalation({'_schema': '1.0', 'daily': {}})
        assert result['escalate'] is False
        assert result['streak'] == 0

    def test_daily_missing_waived_key_tolerated(self):
        """旧格式 daily 条目缺 waived 键 → 不报错（历史 p0_tracking.json 兼容）。"""
        store = {
            '_schema': '1.0', '_updated': '',
            'daily': {
                '2026-09-08': {'triggered': 1, 'executed': 0, 'rate': 0.0, 'unexecuted_ids': ['SIG-1']},
                '2026-09-09': {'triggered': 2, 'executed': 0, 'rate': 0.0, 'unexecuted_ids': ['SIG-2']},
            },
        }
        result = check_p0_zero_execution_escalation(store)
        assert result['escalate'] is False
        assert result['streak'] == 2
