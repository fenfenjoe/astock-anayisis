"""
signal_quality.py 测试 — 信号质量 A 层 8 项指标
覆盖: 触发率/目标达成率/平均达标天数/平均盈亏比/方向准确率/预期vs实际偏差/期望价值/最大亏损
"""

import sys
from pathlib import Path

import pytest

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
