"""
REQ-001: 信号收益追踪系统 测试套件

被测源码:
  - lib/signal_tracking.py    — P&L计算 / 结算规则 / 聚合统计
  - lib/state_machine.py      — REQ状态转换合法性验证

覆盖要点:
  - 买入/卖出信号 P&L 计算正确性
  - 避免的损失计算（卖出独有）
  - 高/低紧急度结算日判定
  - 90天归档逻辑
  - 聚合统计维度完整性
  - Schema 校验
"""

import pytest
from datetime import date, timedelta
from lib.signal_tracking import (
    calc_buy_pnl,
    calc_sell_pnl,
    calc_avoided_loss,
    calc_settlement_date,
    is_archived,
    update_aggregation,
    settle_signal,
    validate_signal_record,
)


# ============================================================
# calc_buy_pnl
# ============================================================

class TestCalcBuyPnl:
    def test_positive_return(self):
        """正收益: 买入价4.50，卖出价5.00，10000股 => 收益5000"""
        assert calc_buy_pnl(4.50, 5.00, 10000) == 5000.0

    def test_negative_return(self):
        """负收益: 买入价5.00，卖出价4.50，10000股 => 亏损-5000"""
        assert calc_buy_pnl(5.00, 4.50, 10000) == -5000.0

    def test_zero_return(self):
        """零收益: 价格不变"""
        assert calc_buy_pnl(4.50, 4.50, 10000) == 0.0

    def test_large_shares(self):
        """大额份额"""
        assert calc_buy_pnl(3.00, 3.01, 1000000) == pytest.approx(10000.0)


# ============================================================
# calc_sell_pnl
# ============================================================

class TestCalcSellPnl:
    def test_profitable_sell(self):
        """赚钱卖出: 卖价2.80，成本2.60，5000股 => 收益1000"""
        assert calc_sell_pnl(2.80, 2.60, 5000) == pytest.approx(1000.0)

    def test_loss_sell(self):
        """亏损卖出: 卖价2.40，成本2.60，5000股 => 亏损-1000"""
        assert calc_sell_pnl(2.40, 2.60, 5000) == pytest.approx(-1000.0)


# ============================================================
# calc_avoided_loss
# ============================================================

class TestCalcAvoidedLoss:
    def test_price_dropped_after_sell(self):
        """卖出后下跌: 卖价2.80，N日后2.50 => 避免了1500损失"""
        assert calc_avoided_loss(2.80, 2.50, 5000) == pytest.approx(1500.0)

    def test_price_rose_after_sell(self):
        """卖出后上涨: 卖价2.80，N日后3.00 => 卖早了，避免的损失为负"""
        assert calc_avoided_loss(2.80, 3.00, 5000) == pytest.approx(-1000.0)


# ============================================================
# calc_settlement_date
# ============================================================

class TestCalcSettlementDate:
    def test_high_urgency_settlement(self):
        """高紧急度 = 2个交易日后结算"""
        # 2026-07-27 Monday => 2 trading days => 2026-07-29 Wednesday
        trigger = date(2026, 7, 27)
        result = calc_settlement_date(trigger, 'high')
        assert result == date(2026, 7, 29)

    def test_low_urgency_settlement(self):
        """低紧急度 = 5个交易日后结算"""
        # 2026-07-27 Monday => 5 trading days => 2026-08-03 Monday
        trigger = date(2026, 7, 27)
        result = calc_settlement_date(trigger, 'low')
        assert result == date(2026, 8, 3)

    def test_cross_weekend(self):
        """跨周末: 周五触发，高紧急度 => 周二结算"""
        # 2026-07-24 Friday => 2 trading days => 2026-07-28 Tuesday
        trigger = date(2026, 7, 24)
        result = calc_settlement_date(trigger, 'high')
        assert result == date(2026, 7, 28)

    def test_invalid_urgency(self):
        """非法紧急度值应抛出 ValueError"""
        with pytest.raises(ValueError, match="Invalid urgency"):
            calc_settlement_date(date(2026, 7, 27), 'medium')


# ============================================================
# is_archived
# ============================================================

class TestIsArchived:
    def test_exactly_90_days(self):
        """恰好90天 => 已归档"""
        sig_date = date(2026, 4, 28)
        current = date(2026, 7, 27)
        assert is_archived(sig_date, current) is True

    def test_91_days(self):
        """91天 => 已归档"""
        sig_date = date(2026, 4, 27)
        current = date(2026, 7, 27)
        assert is_archived(sig_date, current) is True

    def test_89_days(self):
        """89天 => 未归档"""
        sig_date = date(2026, 4, 29)
        current = date(2026, 7, 27)
        assert is_archived(sig_date, current) is False


# ============================================================
# settle_signal
# ============================================================

class TestSettleSignal:
    def test_settle_buy_signal(self, sample_buy_signal):
        """结算买入信号: 应填充 pnl, settled_date, status='settled'"""
        result = settle_signal(sample_buy_signal, 5.00)  # 当前价5.00
        assert result['status'] == 'settled'
        assert result['pnl'] == 5000.0  # (5.00 - 4.50) * 10000
        assert result['avoided_loss'] == 0.0  # 买入信号无此概念
        assert 'settled_date' in result

    def test_settle_sell_signal(self, sample_sell_signal):
        """结算卖出信号: 应填充 pnl + avoided_loss"""
        result = settle_signal(sample_sell_signal, 2.50)  # N日后价格2.50
        assert result['status'] == 'settled'
        assert result['pnl'] == pytest.approx(1000.0)  # (2.80 - 2.60) * 5000
        assert result['avoided_loss'] == pytest.approx(1500.0)  # (2.80 - 2.50) * 5000


# ============================================================
# update_aggregation
# ============================================================

class TestUpdateAggregation:
    def test_empty_db(self):
        """空追踪库 => 聚合全为0"""
        db = {'_schema': '1.0', 'signals': []}
        result = update_aggregation(db)
        agg = result['aggregation']
        assert agg['by_urgency']['high']['count'] == 0
        assert agg['by_urgency']['low']['count'] == 0

    def test_single_signal(self, sample_buy_signal):
        """单条信号 => 聚合计数为1"""
        db = {'_schema': '1.0', 'signals': [sample_buy_signal]}
        result = update_aggregation(db)
        agg = result['aggregation']
        assert agg['by_urgency']['high']['count'] == 1
        assert agg['by_priority']['P1']['count'] == 1

    def test_multi_signal(self, sample_buy_signal, sample_sell_signal):
        """多条信号 => 聚合按维度正确分类"""
        db = {'_schema': '1.0', 'signals': [sample_buy_signal, sample_sell_signal]}
        result = update_aggregation(db)
        agg = result['aggregation']
        assert agg['by_urgency']['high']['count'] == 1  # SIG-001
        assert agg['by_urgency']['low']['count'] == 1   # SIG-002
        assert agg['by_priority']['P1']['count'] == 1   # SIG-001
        assert agg['by_priority']['P2']['count'] == 1   # SIG-002

    def test_total_consistency(self, sample_buy_signal, sample_sell_signal):
        """汇总一致性: P0+P1+P2 count == total signals"""
        db = {'_schema': '1.0', 'signals': [sample_buy_signal, sample_sell_signal]}
        result = update_aggregation(db)
        agg = result['aggregation']
        priority_total = sum(
            agg['by_priority'][p]['count'] for p in ['P0', 'P1', 'P2']
        )
        assert priority_total == len(db['signals'])


# ============================================================
# validate_signal_record
# ============================================================

class TestValidateSignalRecord:
    def test_valid_record(self, sample_buy_signal):
        """完整合法记录 => 无错误"""
        errors = validate_signal_record(sample_buy_signal)
        assert errors == []

    def test_missing_entry_price(self):
        """缺失 entry_price => 报告错误"""
        sig = {'signal_id': 'SIG-003', 'ticker': '510300', 'trade_type': 'buy',
               'urgency': 'high', 'priority': 'P1', 'shares': 1000}
        errors = validate_signal_record(sig)
        assert any('entry_price' in e for e in errors)

    def test_invalid_urgency(self, sample_buy_signal):
        """非法 urgency => 报告错误"""
        sig = dict(sample_buy_signal)
        sig['urgency'] = 'critical'
        errors = validate_signal_record(sig)
        assert any('urgency' in e for e in errors)

    def test_invalid_priority(self, sample_buy_signal):
        """非法 priority => 报告错误"""
        sig = dict(sample_buy_signal)
        sig['priority'] = 'P9'
        errors = validate_signal_record(sig)
        assert any('priority' in e for e in errors)
