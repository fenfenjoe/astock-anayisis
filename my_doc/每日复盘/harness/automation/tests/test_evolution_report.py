"""
evolution_report.py 测试 — 进化周报生成器（P2，自进化框架周度全景）

覆盖: 六节数据组装（指标概览/目标进度/REQ进展/验证结果/负反馈/建议）
     markdown 渲染（六节齐全 + 负反馈 halt 标红）
"""

import sys
from pathlib import Path

import pytest

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from evolution_report import build_evolution_report, render_markdown


def _goals():
    return {'metrics': [
        {'id': 'G-A', 'name': '信号命中率', 'source': 'signal_quality',
         'field': 'dims.overall.target_hit_rate', 'target': 45.0, 'weight': 30},
        {'id': 'G-B', 'name': '报告质量', 'source': 'report_quality',
         'field': 'avg_total', 'target': 16.0, 'weight': 25},
    ]}


def _sq_history():
    return [{'week_key': f'2026-W{i}', 'dims': {'overall': {'target_hit_rate': r}}}
            for i, r in enumerate([45, 45, 45, 45], start=35)]


def _rq_history():
    return [{'date': '2026-08-27', 'scores': {'a': 4, 'b': 4, 'c': 4, 'd': 4}, 'total': 16},
            {'date': '2026-09-03', 'scores': {'a': 4, 'b': 4, 'c': 4, 'd': 4}, 'total': 16},
            {'date': '2026-09-10', 'scores': {'a': 4, 'b': 4, 'c': 4, 'd': 4}, 'total': 16},
            {'date': '2026-09-17', 'scores': {'a': 4, 'b': 4, 'c': 4, 'd': 4}, 'total': 16}]


def _reqs():
    return [
        {'id': 'REQ-010', 'title': '条件单落地', 'status': 'IMPLEMENTED'},
        {'id': 'REQ-011', 'title': '显式放弃', 'status': 'OPEN'},
    ]


def _verifications():
    return [
        {'req_id': 'REQ-010', 'eval_result': 'no_change', 'date': '2026-09-10'},
        {'req_id': 'REQ-010', 'eval_result': 'no_change', 'date': '2026-09-17'},
        {'req_id': 'REQ-010', 'eval_result': 'no_change', 'date': '2026-09-24'},
    ]


class TestBuildReport:
    def test_full_report_structure(self):
        r = build_evolution_report(
            goals=_goals(), sq_history=_sq_history(), rq_history=_rq_history(),
            reqs=_reqs(), verifications=_verifications(), today='2026-09-24',
        )
        assert r['date'] == '2026-09-24'
        assert 'metrics' in r          # 一、指标概览
        assert 'gaps' in r             # 二、目标进度
        assert 'req_stats' in r        # 三、REQ 进展
        assert 'verifications' in r    # 四、验证结果
        assert 'feedback' in r         # 五、负反馈
        assert 'suggestions' in r      # 六、建议

    def test_goal_gaps_computed(self):
        r = build_evolution_report(_goals(), _sq_history(), _rq_history(),
                                   [], [], today='2026-09-24')
        by_id = {g['id']: g for g in r['gaps']}
        assert by_id['G-A']['status'] == 'met'      # 45 >= 45
        assert by_id['G-B']['status'] == 'met'      # 16 >= 16

    def test_req_stats(self):
        r = build_evolution_report(_goals(), _sq_history(), _rq_history(),
                                   _reqs(), [], today='2026-09-24')
        assert r['req_stats']['total'] == 2
        assert r['req_stats']['by_status']['OPEN'] == 1
        assert r['req_stats']['by_status']['IMPLEMENTED'] == 1

    def test_feedback_halt_detected(self):
        r = build_evolution_report(_goals(), _sq_history(), _rq_history(),
                                   _reqs(), _verifications(), today='2026-09-24')
        # REQ-010 连续 3 轮 no_change → halt
        assert r['feedback']['REQ-010']['status'] == 'halt'

    def test_verifications_included(self):
        r = build_evolution_report(_goals(), _sq_history(), _rq_history(),
                                   _reqs(), _verifications(), today='2026-09-24')
        assert len(r['verifications']) == 3


class TestRenderMarkdown:
    def test_six_sections_present(self):
        r = build_evolution_report(_goals(), _sq_history(), _rq_history(),
                                   _reqs(), _verifications(), today='2026-09-24')
        md = render_markdown(r)
        assert '# 进化周报' in md
        assert '## 一、' in md
        assert '## 二、' in md
        assert '## 三、' in md
        assert '## 四、' in md
        assert '## 五、' in md
        assert '## 六、' in md

    def test_halt_marked_red(self):
        r = build_evolution_report(_goals(), _sq_history(), _rq_history(),
                                   _reqs(), _verifications(), today='2026-09-24')
        md = render_markdown(r)
        assert 'halt' in md.lower() or '暂停' in md

    def test_empty_report_still_renders(self):
        r = build_evolution_report({}, [], [], [], [], today='2026-09-24')
        md = render_markdown(r)
        assert '# 进化周报' in md
