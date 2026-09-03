"""scheduler 引擎状态化：current_task / attendance（人格化「正在做XXX/摸鱼中」）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from dashboard import scheduler as sched


@pytest.fixture(autouse=True)
def _clean_running(monkeypatch):
    sched._running_tasks = {}
    yield
    sched._running_tasks = {}


def test_current_task_none_when_idle():
    assert sched.current_task() is None  # 摸鱼中


def test_current_task_returns_running():
    from datetime import datetime
    sched._mark_running("morning_analysis", "早盘分析", "09:07:00")
    task = sched.current_task()
    # 含 task_id（桌宠按任务类型细分工作姿态）
    assert task == {"task_id": "morning_analysis",
                    "name": "早盘分析", "started_at": "09:07:00"}
    assert task["task_id"] == "morning_analysis"


def test_current_task_prefers_earliest_on_concurrency():
    sched._mark_running("intraday_1000", "盘中检查10:00", "10:00:00")
    sched._mark_running("morning_analysis", "早盘分析", "09:07:00")
    task = sched.current_task()
    assert task["name"] == "早盘分析"  # 取最先开始的


def test_clear_running_updates_state():
    sched._mark_running("morning_analysis", "早盘分析", "09:07:00")
    sched._clear_running("morning_analysis")
    assert sched.current_task() is None


def test_engine_status_has_attendance_and_current_task(monkeypatch):
    from dashboard import db as db_mod
    monkeypatch.setattr(db_mod, "meta_get",
                        lambda key: "1" if key == "scheduler_auto_enabled" else None)
    sched._mark_running("evening_review", "收盘复盘", "15:52:00")
    st = sched.engine.status()
    assert st["attendance"] == "on"
    assert st["current_task"]["name"] == "收盘复盘"
    assert st["current_task"]["task_id"] == "evening_review"


def test_engine_status_attendance_leave(monkeypatch):
    from dashboard import db as db_mod
    monkeypatch.setattr(db_mod, "meta_get",
                        lambda key: "0" if key == "scheduler_auto_enabled" else None)
    st = sched.engine.status()
    assert st["attendance"] == "leave"
