"""
signal_reconcile.py 测试 — 信号-成交对账（P0 修复：执行统计来源改造）

覆盖: match_trades（严格键匹配+边界） / apply_matches（状态回填+终态保护）
     / summarize_reconcile（对账摘要）
"""

import sys
from pathlib import Path

import pytest

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from signal_reconcile import match_trades, apply_matches, summarize_reconcile


def _sig(sid, ticker='510300', trade_type='buy', date='2026-09-24', status='open'):
    return {'signal_id': sid, 'ticker': ticker, 'trade_type': trade_type,
            'signal_date': date, 'status': status, 'entry_price': None, 'entry_time': None}


def _trade(code='510300', side='买入', date='2026-09-24', price=3.5, quantity=1000, remark=''):
    return {'code': code, 'side': side, 'trade_date': date, 'price': price,
            'quantity': quantity, 'remark': remark}


class TestMatchTrades:
    def test_match_same_day_same_code_same_side(self):
        sigs = [_sig('S1')]
        trades = [_trade()]
        matches = match_trades(sigs, trades)
        assert len(matches) == 1
        assert matches[0]['signal']['signal_id'] == 'S1'
        assert matches[0]['trade']['code'] == '510300'

    def test_trigger_date_fallback(self):
        # 本地信号用 trigger_date（云库列名是 signal_date）——兼容两种字段
        sig = _sig('S1', date='2026-09-24')
        del sig['signal_date']
        sig['trigger_date'] = '2026-09-24'
        matches = match_trades([sig], [_trade()])
        assert len(matches) == 1

    def test_remark_signal_id_priority(self):
        # 成交 remark 带"执行信号 SIG-xxx" → 最精确匹配（优先于代码+日期+方向）
        sigs = [_sig('SIG-20260921-04', ticker='515880', date='2026-09-21')]
        trades = [_trade(code='515880', date='2026-09-21', price=0.712,
                         remark='执行信号 SIG-20260921-04')]
        matches = match_trades(sigs, trades)
        assert len(matches) == 1
        assert matches[0]['match_by'] == 'remark_signal_id'

    def test_remark_id_wins_over_code_collision(self):
        # 同代码多信号：remark 指定了具体信号 → 匹配那个信号
        sigs = [_sig('SIG-A', ticker='515880', date='2026-09-21'),
                _sig('SIG-B', ticker='515880', date='2026-09-21')]
        trades = [_trade(code='515880', date='2026-09-21', remark='执行信号 SIG-B')]
        matches = match_trades(sigs, trades)
        assert len(matches) == 1
        assert matches[0]['signal']['signal_id'] == 'SIG-B'

    def test_direction_mismatch_no_match(self):
        # 信号 buy，成交 卖出 → 不命中
        sigs = [_sig('S1', trade_type='buy')]
        trades = [_trade(side='卖出')]
        assert match_trades(sigs, trades) == []

    def test_diff_day_no_match(self):
        sigs = [_sig('S1', date='2026-09-24')]
        trades = [_trade(date='2026-09-25')]
        assert match_trades(sigs, trades) == []

    def test_diff_code_no_match(self):
        sigs = [_sig('S1', ticker='510300')]
        trades = [_trade(code='159915')]
        assert match_trades(sigs, trades) == []

    def test_terminal_status_not_matched(self):
        # 已 executed 信号不参与匹配（终态保护）
        sigs = [_sig('S1', status='executed')]
        trades = [_trade()]
        assert match_trades(sigs, trades) == []

    def test_multiple_trades_takes_first(self):
        sigs = [_sig('S1')]
        trades = [_trade(price=3.4, remark='第一笔'), _trade(price=3.6, remark='第二笔')]
        matches = match_trades(sigs, trades)
        assert len(matches) == 1
        assert matches[0]['trade']['price'] == 3.4

    def test_sell_signal_matches_sell_trade(self):
        sigs = [_sig('S2', trade_type='sell')]
        trades = [_trade(side='卖出')]
        assert len(match_trades(sigs, trades)) == 1

    def test_same_code_multi_signals(self):
        # 同代码两个信号（buy+sell），各自匹配对应方向
        sigs = [_sig('S1', trade_type='buy'), _sig('S2', trade_type='sell')]
        trades = [_trade(side='买入'), _trade(side='卖出')]
        matches = match_trades(sigs, trades)
        assert len(matches) == 2
        sides = sorted(m['signal']['trade_type'] for m in matches)
        assert sides == ['buy', 'sell']


class TestApplyMatches:
    def test_updates_executed_fields(self):
        sigs = [_sig('S1')]
        trades = [_trade(price=3.5, quantity=1000)]
        matches = match_trades(sigs, trades)
        updated = apply_matches(sigs, matches)
        assert updated[0]['status'] == 'executed'
        assert updated[0]['entry_price'] == 3.5
        assert updated[0]['entry_time']  # 非空

    def test_unmatched_unchanged(self):
        sigs = [_sig('S1')]
        trades = [_trade(side='卖出')]  # 方向不符
        matches = match_trades(sigs, trades)
        updated = apply_matches(sigs, matches)
        assert updated[0]['status'] == 'open'  # 保持不动
        assert updated[0]['entry_price'] is None


class TestSummarize:
    def test_counts(self):
        sigs = [_sig('S1'), _sig('S2', status='executed'), _sig('S3', ticker='159915')]
        trades = [_trade()]  # 只有 510300 的成交 → S1 匹配，S3（159915）无成交
        matches = match_trades(sigs, trades)
        updated = apply_matches(sigs, matches)
        summ = summarize_reconcile(sigs, updated, matches)
        assert summ['matched_count'] == 1
        assert summ['updated_count'] == 1
        # unmatched：当日 open 但无成交的信号 → S3
        assert [u['signal_id'] for u in summ['unmatched']] == ['S3']
