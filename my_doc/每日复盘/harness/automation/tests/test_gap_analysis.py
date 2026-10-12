"""
gap_analysis.py 测试 — 差距分析（P0c，自进化框架"差距分析器"）

覆盖: parse_goals / current_value / compute_gaps / gen_req_suggestion / build_gap_report
"""

import sys
from pathlib import Path

import pytest

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from gap_analysis import (
    parse_goals,
    current_value,
    compute_gaps,
    gen_req_suggestion,
    build_gap_report,
)


GOALS_MD = '''
# 进化目标定义

```json
{
  "metrics": [
    {"id": "G-A", "name": "信号命中率", "source": "signal_quality",
     "field": "overall.target_hit_rate", "target": 45.0, "weight": 30, "direction": "higher"},
    {"id": "G-B", "name": "报告质量总分", "source": "report_quality",
     "field": "avg_total", "target": 16.0, "weight": 25, "direction": "higher"},
    {"id": "G-C", "name": "P1触发率", "source": "signal_quality",
     "field": "dimensions.priority.P1.trigger_rate", "target": 40.0, "weight": 20, "direction": "higher"}
  ]
}
```
'''


def _sq_history():
    """3 周信号质量快照：命中率 33.3 / 40 / 50 → 均值 41.1"""
    weeks = [
        ('2026-W35', {'overall': {'target_hit_rate': 33.3},
                      'dimensions': {'priority': {'P1': {'trigger_rate': 30.0}}}}),
        ('2026-W36', {'overall': {'target_hit_rate': 40.0},
                      'dimensions': {'priority': {'P1': {'trigger_rate': 35.0}}}}),
        ('2026-W37', {'overall': {'target_hit_rate': 50.0},
                      'dimensions': {'priority': {'P1': {'trigger_rate': 45.0}}}}),
    ]
    return [{'week_key': wk, **dims} for wk, dims in weeks]


def _rq_history():
    """3 条报告质量分：total 14/15/16 → 均值 15.0"""
    return [
        {'date': '2026-09-21', 'scores': {'data_validation': 4, 'logic_consistency': 4,
                                          'completeness': 3, 'format': 3}, 'total': 14},
        {'date': '2026-09-22', 'scores': {'data_validation': 4, 'logic_consistency': 4,
                                          'completeness': 3, 'format': 4}, 'total': 15},
        {'date': '2026-09-23', 'scores': {'data_validation': 4, 'logic_consistency': 4,
                                          'completeness': 4, 'format': 4}, 'total': 16},
    ]


class TestParseGoals:
    def test_parses_metrics(self):
        goals = parse_goals(GOALS_MD)
        assert len(goals['metrics']) == 3
        assert goals['metrics'][0]['id'] == 'G-A'
        assert goals['metrics'][0]['target'] == 45.0

    def test_no_json_block(self):
        assert parse_goals('no json here') == {'metrics': []}

    def test_invalid_json(self):
        assert parse_goals('```json\n{bad\n```') == {'metrics': []}


class TestCurrentValue:
    def test_signal_quality_avg(self):
        g = {'source': 'signal_quality', 'field': 'overall.target_hit_rate'}
        assert current_value(g, _sq_history(), []) == pytest.approx(41.1)

    def test_report_quality_avg_total(self):
        g = {'source': 'report_quality', 'field': 'avg_total'}
        assert current_value(g, [], _rq_history()) == pytest.approx(15.0)

    def test_report_quality_dim(self):
        g = {'source': 'report_quality', 'field': 'completeness'}
        assert current_value(g, [], _rq_history()) == pytest.approx(3.33)

    def test_nested_dim(self):
        g = {'source': 'signal_quality', 'field': 'dimensions.priority.P1.trigger_rate'}
        assert current_value(g, _sq_history(), []) == pytest.approx(36.67)

    def test_no_data(self):
        g = {'source': 'signal_quality', 'field': 'overall.max_loss'}
        assert current_value(g, [], []) is None


class TestComputeGaps:
    def test_shortfall_sorted(self):
        goals = parse_goals(GOALS_MD)
        gaps = compute_gaps(goals, _sq_history(), _rq_history())
        # G-A 缺口 45-41.1=3.9；G-B 缺口 16-15=1.0；G-C 缺口 40-36.67=3.33
        by_id = {g['id']: g for g in gaps}
        assert by_id['G-A']['status'] == 'shortfall'
        assert by_id['G-A']['gap'] == pytest.approx(3.9)
        assert by_id['G-B']['gap'] == pytest.approx(1.0)
        assert by_id['G-C']['gap'] == pytest.approx(3.33)
        # 排序：缺口大的在前
        assert gaps[0]['id'] == 'G-A'

    def test_met(self):
        goals = {'metrics': [{'id': 'X', 'source': 'signal_quality',
                              'field': 'overall.target_hit_rate', 'target': 40.0,
                              'weight': 10, 'direction': 'higher'}]}
        gaps = compute_gaps(goals, _sq_history(), [])
        assert gaps[0]['status'] == 'met'  # 41.1 > 40

    def test_no_data_last(self):
        goals = {'metrics': [
            {'id': 'A', 'source': 'signal_quality', 'field': 'overall.target_hit_rate',
             'target': 50.0, 'weight': 10, 'direction': 'higher'},
            {'id': 'B', 'source': 'signal_quality', 'field': 'overall.nonexist',
             'target': 10.0, 'weight': 30, 'direction': 'higher'},
        ]}
        gaps = compute_gaps(goals, _sq_history(), [])
        assert gaps[0]['id'] == 'A'
        assert gaps[-1]['id'] == 'B'
        assert gaps[-1]['status'] == 'no_data'


class TestGenReqSuggestion:
    def test_big_gap(self):
        gap = {'name': '信号命中率', 'target': 50.0, 'current': 35.0, 'gap': 15.0,
               'weight': 30, 'status': 'shortfall'}
        sug = gen_req_suggestion(gap, min_gap=5.0)
        assert sug is not None
        assert '[GAP]' in sug['title']
        assert '35.0' in sug['body']

    def test_small_gap_none(self):
        gap = {'name': 'X', 'target': 50.0, 'current': 47.0, 'gap': 3.0,
               'weight': 10, 'status': 'shortfall'}
        assert gen_req_suggestion(gap, min_gap=5.0) is None

    def test_no_data_high_weight(self):
        gap = {'name': 'X', 'target': None, 'current': None, 'gap': None,
               'weight': 25, 'status': 'no_data'}
        sug = gen_req_suggestion(gap)
        assert sug is not None and '无结算样本' in sug['title']

    def test_no_data_low_weight_none(self):
        gap = {'name': 'X', 'target': None, 'current': None, 'gap': None,
               'weight': 5, 'status': 'no_data'}
        assert gen_req_suggestion(gap) is None

    def test_met_none(self):
        gap = {'name': 'X', 'target': 10, 'current': 12, 'gap': -2.0,
               'weight': 10, 'status': 'met'}
        assert gen_req_suggestion(gap) is None


class TestBuildGapReport:
    def test_structure(self):
        goals = parse_goals(GOALS_MD)
        report = build_gap_report(goals, _sq_history(), _rq_history(), min_gap=1.0)
        assert 'gaps' in report and 'suggestions' in report
        assert len(report['gaps']) == 3
        assert len(report['suggestions']) == 3  # 三个都有 gap ≥ 1.0
