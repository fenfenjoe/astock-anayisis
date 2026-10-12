"""
req_evolution.py 测试 — REQ 对照验证（P2，自进化框架"对照验证"环节）

覆盖: parse_evolution_fields / extract_window / evaluate_improvement / suggest_action
"""

import sys
from pathlib import Path

import pytest

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from req_evolution import (
    parse_evolution_fields,
    extract_window,
    evaluate_improvement,
    suggest_action,
    track_feedback,
    due_for_verification,
)


REQ_MD_FULL = '''
# REQ-015: 提升信号命中率

- **创建时间**: 2026-09-24 12:30
- **优先级**: P0
- **影响范围**: 收盘复盘
- **状态**: IMPLEMENTED
- **关联指标**: G-A: dims.overall.target_hit_rate
- **基线值**: 33.3（实施前 4 周均值）
- **预期改善**: 45.0
- **观察期**: 4 周

## 需求描述
（略）
'''


def _sq_history():
    """8 周信号质量快照：前 4 周命中率 30/33/35/35（基线 33.25），后 4 周 40/42/45/48（after 43.75）。"""
    def mk(wk, rate):
        return {'week_key': wk, 'dims': {'overall': {'target_hit_rate': rate}}}
    weeks = ['2026-W31', '2026-W32', '2026-W33', '2026-W34',
             '2026-W35', '2026-W36', '2026-W37', '2026-W38']
    rates = [30.0, 33.0, 35.0, 35.0, 40.0, 42.0, 45.0, 48.0]
    return [mk(w, r) for w, r in zip(weeks, rates)]


class TestParseEvolutionFields:
    def test_full(self):
        f = parse_evolution_fields(REQ_MD_FULL)
        assert f['metric'] == 'G-A'
        assert f['field'] == 'dims.overall.target_hit_rate'
        assert f['baseline'] == 33.3
        assert f['expected'] == 45.0
        assert f['observation_weeks'] == 4

    def test_missing_fields(self):
        md = '# REQ-016: 无进化字段\n- **状态**: OPEN\n'
        f = parse_evolution_fields(md)
        assert f['metric'] is None
        assert f['field'] is None
        assert f['baseline'] is None

    def test_empty(self):
        assert parse_evolution_fields('')['metric'] is None


class TestExtractWindow:
    def test_avg_last_n(self):
        assert extract_window(_sq_history(), 'dims.overall.target_hit_rate', 4) == pytest.approx(43.75)

    def test_insufficient_uses_available(self):
        h = _sq_history()[:2]  # 只有 2 周
        assert extract_window(h, 'dims.overall.target_hit_rate', 4) == pytest.approx(31.5)

    def test_empty_history(self):
        assert extract_window([], 'dims.overall.target_hit_rate', 4) is None

    def test_missing_field(self):
        assert extract_window(_sq_history(), 'dims.overall.nonexist', 4) is None


class TestEvaluateImprovement:
    def test_improved_higher(self):
        assert evaluate_improvement(33.25, 43.75, 'higher') == 'improved'

    def test_no_change_higher(self):
        assert evaluate_improvement(40.0, 38.0, 'higher') == 'no_change'

    def test_lower_direction(self):
        # direction='lower'：after 更小 = 改善（如错误数下降）
        assert evaluate_improvement(5.0, 2.0, 'lower') == 'improved'
        assert evaluate_improvement(2.0, 5.0, 'lower') == 'no_change'

    def test_expected_constraint_met(self):
        assert evaluate_improvement(33.25, 43.75, 'higher', expected=45.0) == 'no_change'  # 43.75 < 45

    def test_expected_constraint_unmet_but_improved(self):
        # expected 达到才算 improved；未达但改善了 → no_change（需延长观察）
        assert evaluate_improvement(33.25, 46.0, 'higher', expected=45.0) == 'improved'

    def test_insufficient(self):
        assert evaluate_improvement(None, 43.75, 'higher') == 'insufficient'
        assert evaluate_improvement(33.25, None, 'higher') == 'insufficient'


class TestSuggestAction:
    def test_close(self):
        assert suggest_action('improved', 4) == 'close'

    def test_extend_when_insufficient(self):
        assert suggest_action('insufficient', 4) == 'extend'

    def test_rollback_when_no_change(self):
        assert suggest_action('no_change', 4) == 'rollback'


class TestTrackFeedback:
    """P2a 负反馈追踪：连续无改善 → halt（自动暂停+回滚建议）。"""

    def test_improved_resets_streak(self):
        log = [
            {'req_id': 'REQ-010', 'eval_result': 'no_change'},
            {'req_id': 'REQ-010', 'eval_result': 'improved'},
        ]
        st = track_feedback(log)
        assert st['REQ-010']['no_improve_streak'] == 0
        assert st['REQ-010']['status'] == 'normal'

    def test_streak_accumulates(self):
        log = [
            {'req_id': 'REQ-010', 'eval_result': 'no_change'},
            {'req_id': 'REQ-010', 'eval_result': 'no_change'},
        ]
        st = track_feedback(log)
        assert st['REQ-010']['no_improve_streak'] == 2
        assert st['REQ-010']['status'] == 'normal'

    def test_halt_at_threshold(self):
        log = [
            {'req_id': 'REQ-010', 'eval_result': 'no_change'},
            {'req_id': 'REQ-010', 'eval_result': 'no_change'},
            {'req_id': 'REQ-010', 'eval_result': 'no_change'},
        ]
        st = track_feedback(log, rounds=3)
        assert st['REQ-010']['status'] == 'halt'

    def test_insufficient_also_counts(self):
        # insufficient（数据不足）也计为"无改善进展"——观察期拉长没意义就应 halt
        log = [
            {'req_id': 'REQ-010', 'eval_result': 'insufficient'},
            {'req_id': 'REQ-010', 'eval_result': 'insufficient'},
            {'req_id': 'REQ-010', 'eval_result': 'insufficient'},
        ]
        st = track_feedback(log, rounds=3)
        assert st['REQ-010']['status'] == 'halt'

    def test_multiple_reqs_independent(self):
        log = [
            {'req_id': 'REQ-010', 'eval_result': 'no_change'},
            {'req_id': 'REQ-010', 'eval_result': 'no_change'},
            {'req_id': 'REQ-010', 'eval_result': 'no_change'},
            {'req_id': 'REQ-011', 'eval_result': 'improved'},
        ]
        st = track_feedback(log, rounds=3)
        assert st['REQ-010']['status'] == 'halt'
        assert st['REQ-011']['status'] == 'normal'
        assert st['REQ-011']['no_improve_streak'] == 0

    def test_empty_log(self):
        assert track_feedback([]) == {}


class TestDueForVerification:
    """P2b 观察期计时：到期才验证。"""

    def test_due_when_past_due(self):
        # implemented 2026-08-01 + 4 周观察期 → due 2026-08-29；today 2026-09-24 已到期
        assert due_for_verification('2026-08-01', 4, '2026-09-24') is True

    def test_not_due_yet(self):
        # implemented 2026-09-24 + 4 周 → due 2026-10-22；today 2026-09-24 未到期
        assert due_for_verification('2026-09-24', 4, '2026-09-24') is False

    def test_due_on_exact_day(self):
        # implemented 2026-08-01 + 4 周 = 2026-08-29；today 恰为到期日 → True
        assert due_for_verification('2026-08-01', 4, '2026-08-29') is True

    def test_zero_weeks_immediately_due(self):
        assert due_for_verification('2026-09-24', 0, '2026-09-24') is True

    def test_invalid_date(self):
        # implemented_date 非法 → False（安全侧：不验证）
        assert due_for_verification('not-a-date', 4, '2026-09-24') is False
