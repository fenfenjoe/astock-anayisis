"""
REQ-006 TDD 门禁测试 — 信号质量统计区分"已执行样本"与"未执行模拟样本"

被测模块: lib/signal_tracking.py（is_simulated / settle_due_signals / update_aggregation）
          lib/signal_quality.py（split_executed_simulated / generate_quality_dashboard）

覆盖:
  - is_simulated: 显式 simulated 字段优先；status_history 含 executed/partial_executed → False；
    仅 triggered → True；status 字段推断
  - settle_due_signals: triggered 且无执行记录 → simulated=true；triggered 且有 executed → simulated=false；
    executed → simulated=false；P0 不结算不变
  - update_aggregation: simulated P&L 入 simulated_pnl_amount 不入 total_pnl_amount；
    win_rate 仅基于已执行样本；历史记录（无 simulated 字段）兼容推断
  - generate_quality_dashboard: 账户级指标仅基于已执行样本；simulated 单独披露
"""

import sys
from pathlib import Path

import pytest

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from signal_tracking import (
    is_simulated,
    settle_due_signals,
    update_aggregation,
)
from signal_quality import (
    split_executed_simulated,
    generate_quality_dashboard,
)


# ============================================================
# is_simulated（核心推断函数）
# ============================================================

class TestIsSimulated:
    def test_explicit_simulated_true(self):
        """显式 simulated=True → True（覆盖推断）。"""
        sig = {'status': 'executed', 'simulated': True}
        assert is_simulated(sig) is True

    def test_explicit_simulated_false(self):
        """显式 simulated=False → False。"""
        sig = {'status': 'triggered', 'simulated': False}
        assert is_simulated(sig) is False

    def test_history_has_executed_false(self):
        """status_history 含 executed → 已执行，非模拟。"""
        sig = {'status': 'settled', 'status_history': [
            {'status': 'triggered'}, {'status': 'executed'}, {'status': 'settled'},
        ]}
        assert is_simulated(sig) is False

    def test_history_has_partial_executed_false(self):
        """status_history 含 partial_executed → 已执行，非模拟。"""
        sig = {'status': 'settled', 'status_history': [
            {'status': 'triggered'}, {'status': 'partial_executed'}, {'status': 'settled'},
        ]}
        assert is_simulated(sig) is False

    def test_history_only_triggered_true(self):
        """status_history 仅 triggered+settled（无执行）→ 未执行模拟。"""
        sig = {'status': 'settled', 'status_history': [
            {'status': 'triggered'}, {'status': 'settled'},
        ]}
        assert is_simulated(sig) is True

    def test_status_executed_infers_false(self):
        """status=executed（无 status_history）→ 已执行。"""
        sig = {'status': 'executed'}
        assert is_simulated(sig) is False

    def test_status_partial_executed_infers_false(self):
        """status=partial_executed → 已执行。"""
        sig = {'status': 'partial_executed'}
        assert is_simulated(sig) is False

    def test_status_triggered_no_history_infers_true(self):
        """status=triggered 且无 status_history → 未执行模拟（旧记录推断）。"""
        sig = {'status': 'triggered'}
        assert is_simulated(sig) is True

    def test_status_settled_no_history_infers_true(self):
        """status=settled 且无 status_history（旧记录）→ 未执行模拟（保守推断）。"""
        sig = {'status': 'settled'}
        assert is_simulated(sig) is True

    def test_missing_all_infers_true(self):
        """无 status/status_history → 视为未执行模拟。"""
        assert is_simulated({}) is True


# ============================================================
# settle_due_signals：结算时标注 simulated
# ============================================================

def _mk_signal(sid, status='triggered', history=None, priority='P1',
               trade_type='buy', entry=1.00, shares=1000, target_price=1.10,
               trigger_date='2026-07-27'):
    return {
        'signal_id': sid, 'ticker': '512800', 'trade_type': trade_type,
        'urgency': 'high', 'priority': priority, 'entry_price': entry,
        'shares': shares, 'target_price': target_price,
        'trigger_date': trigger_date, 'status': status,
        'status_history': history or [{'date': trigger_date, 'status': 'triggered', 'note': ''}],
    }


_HIST = {'512800': {'2026-07-27': 1.02, '2026-07-28': 1.04, '2026-07-29': 1.03}}


class TestSettleDueSignalsSimulated:
    def test_triggered_no_execution_marks_simulated(self):
        """status=triggered 且 status_history 无 executed → 结算后 simulated=true。"""
        db = {'signals': [_mk_signal('SIG-A', status='triggered')]}
        settle_due_signals(db, _HIST, '2026-07-29')
        sig = db['signals'][0]
        assert sig['status'] == 'settled'
        assert sig['simulated'] is True

    def test_triggered_with_executed_history_marks_not_simulated(self):
        """status=triggered 但 status_history 含 executed → simulated=false。"""
        db = {'signals': [_mk_signal('SIG-B', status='triggered', history=[
            {'date': '2026-07-27', 'status': 'triggered', 'note': ''},
            {'date': '2026-07-27', 'status': 'executed', 'note': '用户执行'},
        ])]}
        settle_due_signals(db, _HIST, '2026-07-29')
        sig = db['signals'][0]
        assert sig['status'] == 'settled'
        assert sig['simulated'] is False

    def test_status_executed_marks_not_simulated(self):
        """status=executed → simulated=false。"""
        db = {'signals': [_mk_signal('SIG-C', status='executed', history=[
            {'date': '2026-07-27', 'status': 'triggered', 'note': ''},
            {'date': '2026-07-27', 'status': 'executed', 'note': '用户执行'},
        ])]}
        settle_due_signals(db, _HIST, '2026-07-29')
        sig = db['signals'][0]
        assert sig['status'] == 'settled'
        assert sig['simulated'] is False

    def test_p0_not_settled(self):
        """P0 风控信号不结算（纪律无 P&L）→ 状态不变。"""
        db = {'signals': [_mk_signal('SIG-P0', status='triggered', priority='P0',
                                     trade_type='sell', target_price=0.95)]}
        settle_due_signals(db, _HIST, '2026-07-29')
        assert db['signals'][0]['status'] == 'triggered'

    def test_settle_still_computes_pnl_and_outcome(self):
        """模拟结算仍计算 outcome/pnl（用于方向/目标达成率评估），但 pnl 归模拟口径。"""
        db = {'signals': [_mk_signal('SIG-A', status='triggered')]}
        settle_due_signals(db, _HIST, '2026-07-29')
        sig = db['signals'][0]
        assert sig['outcome'] == 'miss'
        assert sig['pnl'] == pytest.approx(30.0)  # (1.03 - 1.00) * 1000


# ============================================================
# update_aggregation：pnl 分流 + win_rate 仅基于已执行
# ============================================================

class TestUpdateAggregationSplit:
    def _build_db(self, signals):
        return update_aggregation({'signals': signals})

    def test_simulated_pnl_goes_to_simulated_amount(self):
        """模拟样本 P&L → simulated_pnl_amount，不入 total_pnl_amount。"""
        sig = _mk_signal('SIG-SIM', status='settled', history=[
            {'date': '2026-07-27', 'status': 'triggered', 'note': ''},
            {'date': '2026-07-29', 'status': 'settled', 'note': ''},
        ])
        sig['pnl'] = -231.8  # 农业 miss 复现样本
        sig['outcome'] = 'miss'
        db = self._build_db([sig])
        agg = db['aggregates']
        assert agg['simulated_pnl_amount'] == pytest.approx(-231.8)
        assert agg['total_pnl_amount'] == pytest.approx(0.0)
        assert agg['win_count'] == 0
        assert agg['lose_count'] == 0  # 未执行不入账户级败绩

    def test_executed_pnl_goes_to_total_amount(self):
        """已执行样本 P&L → total_pnl_amount，win_count/lose_count 计入。"""
        sig = _mk_signal('SIG-EXEC', status='settled', history=[
            {'date': '2026-07-27', 'status': 'triggered', 'note': ''},
            {'date': '2026-07-27', 'status': 'executed', 'note': '用户执行'},
            {'date': '2026-07-29', 'status': 'settled', 'note': ''},
        ])
        sig['pnl'] = 200.0
        sig['outcome'] = 'hit'
        db = self._build_db([sig])
        agg = db['aggregates']
        assert agg['total_pnl_amount'] == pytest.approx(200.0)
        assert agg['simulated_pnl_amount'] == pytest.approx(0.0)
        assert agg['win_count'] == 1
        assert agg['lose_count'] == 0

    def test_mixed_split(self):
        """已执行 + 模拟混合 → 各自归属正确。"""
        exec_sig = _mk_signal('SIG-E', status='settled', history=[
            {'date': '2026-07-27', 'status': 'triggered', 'note': ''},
            {'date': '2026-07-27', 'status': 'executed', 'note': ''},
            {'date': '2026-07-29', 'status': 'settled', 'note': ''},
        ])
        exec_sig['pnl'] = 100.0
        sim_sig = _mk_signal('SIG-S', status='settled', history=[
            {'date': '2026-07-27', 'status': 'triggered', 'note': ''},
            {'date': '2026-07-29', 'status': 'settled', 'note': ''},
        ])
        sim_sig['pnl'] = -50.0
        db = self._build_db([exec_sig, sim_sig])
        agg = db['aggregates']
        assert agg['total_pnl_amount'] == pytest.approx(100.0)
        assert agg['simulated_pnl_amount'] == pytest.approx(-50.0)
        assert agg['win_count'] == 1
        assert agg['lose_count'] == 0  # 模拟亏损不计入账户级败绩

    def test_legacy_record_without_simulated_field_inferred(self):
        """历史记录（无 simulated 字段）：status_history 含 executed → 已执行；仅 triggered → 模拟。"""
        exec_sig = _mk_signal('SIG-LEGACY-EXEC', status='settled', history=[
            {'date': '2026-07-27', 'status': 'triggered', 'note': ''},
            {'date': '2026-07-27', 'status': 'executed', 'note': ''},
            {'date': '2026-07-29', 'status': 'settled', 'note': ''},
        ])
        exec_sig['pnl'] = 50.0
        sim_sig = _mk_signal('SIG-LEGACY-SIM', status='settled', history=[
            {'date': '2026-07-27', 'status': 'triggered', 'note': ''},
            {'date': '2026-07-29', 'status': 'settled', 'note': ''},
        ])
        sim_sig['pnl'] = -80.0
        db = self._build_db([exec_sig, sim_sig])
        agg = db['aggregates']
        assert agg['total_pnl_amount'] == pytest.approx(50.0)
        assert agg['simulated_pnl_amount'] == pytest.approx(-80.0)

    def test_win_rate_only_executed(self):
        """win_rate 仅基于已执行样本（未执行模拟不计入分母/分子）。"""
        exec_win = _mk_signal('SIG-W', status='settled', history=[
            {'date': '2026-07-27', 'status': 'triggered', 'note': ''},
            {'date': '2026-07-27', 'status': 'executed', 'note': ''},
            {'date': '2026-07-29', 'status': 'settled', 'note': ''},
        ])
        exec_win['pnl'] = 100.0
        sim_lose = _mk_signal('SIG-L', status='settled', history=[
            {'date': '2026-07-27', 'status': 'triggered', 'note': ''},
            {'date': '2026-07-29', 'status': 'settled', 'note': ''},
        ])
        sim_lose['pnl'] = -200.0
        db = self._build_db([exec_win, sim_lose])
        # 已执行 1 单全胜 → 胜率 100%；模拟亏损不拖累
        assert db['aggregates']['win_rate'] == pytest.approx(100.0)


# ============================================================
# split_executed_simulated + generate_quality_dashboard
# ============================================================

class TestSplitExecutedSimulated:
    def test_splits_by_execution(self):
        settled = [
            {'status': 'settled', 'status_history': [{'status': 'executed'}]},
            {'status': 'settled', 'status_history': [{'status': 'triggered'}]},
            {'status': 'settled', 'simulated': False},
            {'status': 'settled', 'simulated': True},
        ]
        executed, simulated = split_executed_simulated(settled)
        assert len(executed) == 2
        assert len(simulated) == 2

    def test_empty(self):
        executed, simulated = split_executed_simulated([])
        assert executed == [] and simulated == []


class TestGenerateDashboardSimulated:
    def _mk_settled(self, sid, pnl, executed=True, outcome='hit'):
        history = [{'date': '2026-07-27', 'status': 'triggered', 'note': ''}]
        if executed:
            history.append({'date': '2026-07-27', 'status': 'executed', 'note': ''})
        history.append({'date': '2026-07-29', 'status': 'settled', 'note': ''})
        return {
            'signal_id': sid, 'ticker': '512800', 'trade_type': 'buy',
            'priority': 'P1', 'urgency': 'high', 'status': 'settled',
            'entry_price': 1.00, 'shares': 1000, 'pnl': pnl,
            'outcome': outcome, 'settle_price': 1.05, 'holding_days': 2,
            'status_history': history,
        }

    def test_account_level_metrics_use_executed_only(self):
        """账户级指标（期望价值/最大亏损）仅基于已执行样本。"""
        executed = self._mk_settled('SIG-E', pnl=100.0, executed=True)
        simulated = self._mk_settled('SIG-S', pnl=-300.0, executed=False, outcome='miss')
        signals = [executed, simulated]
        settled = [executed, simulated]
        d = generate_quality_dashboard(signals, settled, '2026-07-29')
        # 期望价值仅按已执行：100 / 1 = 100
        assert d['signal_expected_value'] == pytest.approx(100.0)
        # 最大亏损仅看已执行样本（全盈 → 0）
        assert d['max_loss'] == pytest.approx(0.0)
        # simulated 单独披露
        assert d['simulated_count'] == 1
        assert d['simulated_pnl_amount'] == pytest.approx(-300.0)
        assert d['simulated_expected_value'] == pytest.approx(-300.0)

    def test_simulated_target_hit_rate_separate(self):
        """simulated 样本目标达成率单独披露，不影响账户级。"""
        executed_win = self._mk_settled('SIG-E1', pnl=100.0, executed=True, outcome='hit')
        executed_lose = self._mk_settled('SIG-E2', pnl=-50.0, executed=True, outcome='miss')
        simulated_hit = self._mk_settled('SIG-S1', pnl=10.0, executed=False, outcome='hit')
        simulated_lose = self._mk_settled('SIG-S2', pnl=-10.0, executed=False, outcome='miss')
        d = generate_quality_dashboard([], [executed_win, executed_lose, simulated_hit, simulated_lose], '2026-07-29')
        # 账户级目标达成率 = 1/2 = 50%
        assert d['target_hit_rate'] == pytest.approx(50.0)
        # simulated 目标达成率 = 1/2 = 50%
        assert d['simulated_target_hit_rate'] == pytest.approx(50.0)
