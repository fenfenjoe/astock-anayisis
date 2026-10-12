"""
report_quality.py 测试 — 报告质量独立评审（P0b，自进化框架 G6 评估）

覆盖: validate_score / parse_score_markdown / save_report_score+load_scores /
     recent_scores / weekly_report_quality / 损坏容错
"""

import json
import sys
from pathlib import Path

import pytest

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from report_quality import (
    SCORE_DIMENSIONS,
    MAX_PER_DIM,
    validate_score,
    parse_score_markdown,
    save_report_score,
    load_scores,
    recent_scores,
    weekly_report_quality,
)


def _score(date='2026-09-24', data=4, logic=3, completeness=4, fmt=5, issues=None):
    return {
        'date': date,
        'report_path': f'my_doc/每日复盘/reports/{date.replace("-", "")}/复盘报告.md',
        'scores': {
            'data_validation': data,
            'logic_consistency': logic,
            'completeness': completeness,
            'format': fmt,
        },
        'issues': issues or [],
        'reviewer_model': 'deepseek-v4-flash',
        'scored_at': f'{date}T17:20:00',
    }


class TestValidateScore:
    def test_valid(self):
        s = _score()
        out = validate_score(s)
        assert out['total'] == 16  # 4+3+4+5

    def test_missing_dimension_raises(self):
        s = _score()
        del s['scores']['format']
        with pytest.raises(ValueError):
            validate_score(s)

    def test_out_of_range_raises(self):
        s = _score(fmt=6)  # 超过 5
        with pytest.raises(ValueError):
            validate_score(s)

    def test_negative_raises(self):
        s = _score(data=-1)
        with pytest.raises(ValueError):
            validate_score(s)

    def test_dims_constant(self):
        assert SCORE_DIMENSIONS == ['data_validation', 'logic_consistency', 'completeness', 'format']
        assert MAX_PER_DIM == 5


class TestParseScoreMarkdown:
    def test_bare_json(self):
        s = _score()
        text = json.dumps(s, ensure_ascii=False)
        out = parse_score_markdown(text)
        assert out is not None and out['total'] == 16

    def test_fenced_json(self):
        s = _score()
        text = f'评审结果如下：\n```json\n{json.dumps(s, ensure_ascii=False)}\n```\n完毕。'
        out = parse_score_markdown(text)
        assert out is not None and out['date'] == '2026-09-24'

    def test_invalid_json_returns_none(self):
        assert parse_score_markdown('这不是 JSON {{{') is None

    def test_empty_returns_none(self):
        assert parse_score_markdown('') is None


class TestSaveLoad:
    def test_roundtrip(self, tmp_path):
        p = tmp_path / 'history.json'
        save_report_score(_score(), p)
        hist = load_scores(p)
        assert len(hist) == 1
        assert hist[0]['total'] == 16

    def test_same_date_overwrites(self, tmp_path):
        p = tmp_path / 'history.json'
        save_report_score(_score(data=4), p)
        save_report_score(_score(data=5), p)  # 同日期 → 覆盖
        hist = load_scores(p)
        assert len(hist) == 1
        assert hist[0]['scores']['data_validation'] == 5

    def test_append_sorted(self, tmp_path):
        p = tmp_path / 'history.json'
        save_report_score(_score('2026-09-23'), p)
        save_report_score(_score('2026-09-24'), p)
        hist = load_scores(p)
        assert [h['date'] for h in hist] == ['2026-09-23', '2026-09-24']


class TestRecentScores:
    def test_last_n(self, tmp_path):
        p = tmp_path / 'history.json'
        for d in ['2026-09-21', '2026-09-22', '2026-09-23', '2026-09-24']:
            save_report_score(_score(d), p)
        assert [h['date'] for h in recent_scores(2, p)] == ['2026-09-23', '2026-09-24']


class TestWeeklyReportQuality:
    def test_basic(self):
        scores = [
            _score('2026-09-21', data=4, logic=4, completeness=4, fmt=4),  # total 16
            _score('2026-09-22', data=3, logic=4, completeness=5, fmt=4),  # total 16
        ]
        w = weekly_report_quality(scores, '2026-09-21', '2026-09-25')
        assert w['n'] == 2
        assert w['avg_total'] == pytest.approx(16.0)
        assert w['avg_by_dim']['data_validation'] == pytest.approx(3.5)
        assert w['avg_by_dim']['completeness'] == pytest.approx(4.5)

    def test_filters_out_of_week(self):
        scores = [_score('2026-09-14'), _score('2026-09-21')]
        w = weekly_report_quality(scores, '2026-09-21', '2026-09-25')
        assert w['n'] == 1

    def test_empty(self):
        w = weekly_report_quality([], '2026-09-21', '2026-09-25')
        assert w['n'] == 0 and w['avg_total'] is None


class TestCorruption:
    def test_corrupt_file_backs_up(self, tmp_path):
        p = tmp_path / 'history.json'
        p.write_text('{broken', encoding='utf-8')
        assert load_scores(p) == []
        assert (tmp_path / 'history.json.bak').exists()

    def test_missing_file(self, tmp_path):
        assert load_scores(tmp_path / 'nope.json') == []
