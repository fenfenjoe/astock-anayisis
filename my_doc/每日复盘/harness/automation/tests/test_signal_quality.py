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
    dimension_dashboard,
)


def _sig(sid, status='settled', trade_type='buy', entry=1.00, pnl=0.0,
         outcome='miss', holding_days=3, settle_price=1.00,
         priority='P1', expected=None, source=None, simulated=False,
         status_history=None):
    rec = {
        'signal_id': sid, 'ticker': '512800', 'trade_type': trade_type,
        'priority': priority, 'urgency': 'high', 'status': status,
        'entry_price': entry, 'shares': 1000, 'pnl': pnl,
        'outcome': outcome, 'settle_price': settle_price,
        'holding_days': holding_days, 'expected_trigger_rate': expected,
    }
    if source is not None:
        rec['source'] = source
    # REQ-006 口径：显式声明是否"已执行样本"（默认 False=已执行，避免被推断为模拟）
    rec['simulated'] = simulated
    if status_history is not None:
        rec['status_history'] = status_history
    return rec


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

    def test_all_positive(self):
        """全为盈利 → 无最大亏损，返回 0.0"""
        settled = [_sig('A', pnl=100.0), _sig('B', pnl=50.0)]
        assert calc_max_loss(settled) == 0.0

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


# ============================================================
# P0a: 分维度切片（自进化框架）
# ============================================================

class TestDimensionDashboard:
    """dimension_dashboard — 按 priority/source/trade_type 切片，供 gap_analysis。"""

    def _mk_signals(self):
        """构造混合维度信号集（已结算）：
        - P0×1 hit（工行）
        - P1×2：hit / miss
        - source 覆盖 morning_analysis / evening_review
        - trade_type 覆盖 buy / sell
        """
        return [
            _sig('S1', status='settled', priority='P0', source='morning_analysis',
                 trade_type='buy', outcome='hit', pnl=150.0, holding_days=1,
                 entry=1.00, settle_price=1.08),
            _sig('S2', status='settled', priority='P1', source='evening_review',
                 trade_type='buy', outcome='hit', pnl=100.0, holding_days=2,
                 entry=1.00, settle_price=1.05),
            _sig('S3', status='settled', priority='P1', source='morning_analysis',
                 trade_type='sell', outcome='miss', pnl=-30.0, holding_days=3,
                 entry=1.00, settle_price=0.97),
        ]

    def test_structure(self):
        signals = self._mk_signals()
        settled = signals  # 全部已结算
        d = dimension_dashboard(signals, settled, '2026-09-24')
        assert d['date'] == '2026-09-24'
        assert set(d['dimensions'].keys()) == {'priority', 'source', 'trade_type'}
        assert 'overall' in d

    def test_by_priority_hit_rate(self):
        signals = self._mk_signals()
        settled = signals
        d = dimension_dashboard(signals, settled)
        prio = d['dimensions']['priority']
        assert set(prio.keys()) == {'P0', 'P1'}           # 只含实际出现的值
        assert prio['P0']['n_signals'] == 1
        assert prio['P0']['target_hit_rate'] == 100.0     # 1/1 hit
        assert prio['P1']['n_signals'] == 2
        assert prio['P1']['target_hit_rate'] == 50.0      # 1/2 hit
        assert prio['P1']['signal_expected_value'] == pytest.approx(35.0)  # (100-30)/2

    def test_by_source(self):
        signals = self._mk_signals()
        settled = signals
        d = dimension_dashboard(signals, settled)
        src = d['dimensions']['source']
        assert set(src.keys()) == {'morning_analysis', 'evening_review'}
        assert src['morning_analysis']['n_signals'] == 2
        assert src['evening_review']['n_signals'] == 1

    def test_by_trade_type(self):
        signals = self._mk_signals()
        settled = signals
        d = dimension_dashboard(signals, settled)
        tt = d['dimensions']['trade_type']
        assert set(tt.keys()) == {'buy', 'sell'}
        assert tt['buy']['n_signals'] == 2
        assert tt['sell']['n_signals'] == 1

    def test_simulated_excluded_from_account_metrics(self):
        """账户级指标只算已执行；未执行模拟样本入 simulated_*（REQ-006 口径）。"""
        signals = [
            _sig('E1', status='settled', priority='P1', trade_type='buy',
                 outcome='hit', pnl=200.0),              # 已执行（无 simulated 字段+status settled → 推断已执行?）
            _sig('E2', status='settled', priority='P1', trade_type='buy',
                 outcome='miss', pnl=-50.0, simulated=True),  # 显式模拟
        ]
        d = dimension_dashboard(signals, signals)
        p1 = d['dimensions']['priority']['P1']
        assert p1['n_settled'] == 2
        assert p1['simulated_count'] == 1
        # 账户级期望价值只基于已执行（E1）
        assert p1['signal_expected_value'] == pytest.approx(200.0)

    def test_overall_matches_full_pool(self):
        signals = self._mk_signals()
        settled = signals
        d = dimension_dashboard(signals, settled)
        assert d['overall']['n_signals'] == 3
        assert d['overall']['target_hit_rate'] == pytest.approx(66.7)  # 2/3
        # overall 与按维度求和一致（样本数）
        sum_n = sum(s['n_signals'] for s in d['dimensions']['priority'].values())
        assert sum_n == d['overall']['n_signals']

    def test_empty(self):
        d = dimension_dashboard([], [], '2026-09-24')
        assert d['overall']['n_signals'] == 0
        assert d['dimensions'] == {'priority': {}, 'source': {}, 'trade_type': {}}
