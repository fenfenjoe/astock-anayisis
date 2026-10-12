"""
signal_quality_history.py 测试 — 周度信号质量快照存档（P0a，自进化框架 G8）

覆盖: save_weekly_snapshot 幂等覆盖 / load_history 往返 / recent_weeks /
     损坏文件备份 .bak + 返回 [] 不崩溃
"""

import json
import sys
from pathlib import Path

import pytest

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from signal_quality_history import (
    DEFAULT_HISTORY_PATH,
    save_weekly_snapshot,
    load_history,
    recent_weeks,
)


def _snapshot(week_key, cohort_start, cohort_end, n=3):
    return {
        'week_key': week_key,
        'cohort_start': cohort_start,
        'cohort_end': cohort_end,
        'dashboard': {'date': cohort_end, 'n': n},
        'dims': {'dimensions': {'priority': {'P1': {'n_signals': n}}}},
        'saved_at': f'{cohort_end}T16:30:00',
    }


class TestSaveAndLoad:
    def test_roundtrip(self, tmp_path):
        p = tmp_path / 'history.json'
        snap = _snapshot('2026-W37', '2026-09-07', '2026-09-11')
        save_weekly_snapshot(snap, p)
        hist = load_history(p)
        assert len(hist) == 1
        assert hist[0]['week_key'] == '2026-W37'
        assert hist[0]['dashboard']['n'] == 3

    def test_idempotent_same_week_overwrites(self, tmp_path):
        p = tmp_path / 'history.json'
        save_weekly_snapshot(_snapshot('2026-W37', '2026-09-07', '2026-09-11', n=3), p)
        # 同周重跑（n 变为 5）→ 覆盖，不产生重复周
        save_weekly_snapshot(_snapshot('2026-W37', '2026-09-07', '2026-09-11', n=5), p)
        hist = load_history(p)
        assert len(hist) == 1
        assert hist[0]['dashboard']['n'] == 5

    def test_append_different_weeks_sorted(self, tmp_path):
        p = tmp_path / 'history.json'
        save_weekly_snapshot(_snapshot('2026-W38', '2026-09-14', '2026-09-18'), p)
        save_weekly_snapshot(_snapshot('2026-W37', '2026-09-07', '2026-09-11'), p)
        hist = load_history(p)
        assert [h['week_key'] for h in hist] == ['2026-W37', '2026-W38']  # 排序


class TestRecentWeeks:
    def test_last_n(self, tmp_path):
        p = tmp_path / 'history.json'
        for i, wk in enumerate(['2026-W35', '2026-W36', '2026-W37', '2026-W38']):
            save_weekly_snapshot(_snapshot(wk, wk, wk), p)
        hist = recent_weeks(2, p)
        assert [h['week_key'] for h in hist] == ['2026-W37', '2026-W38']

    def test_n_larger_than_all(self, tmp_path):
        p = tmp_path / 'history.json'
        save_weekly_snapshot(_snapshot('2026-W37', '2026-09-07', '2026-09-11'), p)
        assert len(recent_weeks(10, p)) == 1


class TestCorruption:
    def test_corrupt_file_backs_up_and_returns_empty(self, tmp_path):
        p = tmp_path / 'history.json'
        p.write_text('{broken json', encoding='utf-8')
        hist = load_history(p)  # 不应崩溃
        assert hist == []
        assert (tmp_path / 'history.json.bak').exists()  # 备份损坏文件

    def test_missing_file_returns_empty(self, tmp_path):
        p = tmp_path / 'nope.json'
        assert load_history(p) == []


class TestDefaultPath:
    def test_default_is_under_config(self):
        assert 'config' in str(DEFAULT_HISTORY_PATH)
        assert DEFAULT_HISTORY_PATH.name == 'signal_quality_history.json'
