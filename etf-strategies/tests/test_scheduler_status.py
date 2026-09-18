"""scheduler 引擎状态化：current_task / attendance（人格化「正在做XXX/摸鱼中」）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from dashboard import scheduler as sched


@pytest.fixture(autouse=True)
def _clean_running(monkeypatch):
    sched._running_tasks = {}
    # 重置 agent_online() 的 5s 短缓存，避免跨用例缓存污染（BUG-031）
    sched._online_cache.ts = 0.0
    sched._online_cache.val = False
    yield
    sched._running_tasks = {}
    sched._online_cache.ts = 0.0
    sched._online_cache.val = False


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


# ═══════════════════════════════════════════════════════════════
# BUG-FIX(2026-09-07): agent_online() 读 agent db 的 xiaoman_online
# （此前 _tick 从 dashboard db 读该 key 永远为空 → auto 调度被永久短路）
# ═══════════════════════════════════════════════════════════════

def test_agent_online_true_when_agent_db_says_1(monkeypatch):
    import agent.db as agent_db_mod
    monkeypatch.setattr(agent_db_mod, "meta_get",
                        lambda key: "1" if key == "xiaoman_online" else None)
    assert sched.agent_online() is True


def test_agent_online_false_when_agent_db_says_0(monkeypatch):
    import agent.db as agent_db_mod
    monkeypatch.setattr(agent_db_mod, "meta_get",
                        lambda key: "0" if key == "xiaoman_online" else None)
    assert sched.agent_online() is False


def test_agent_online_false_when_agent_db_unavailable(monkeypatch):
    # agent db 读取抛异常 → fail-safe 返回 False（宁可不调度，不误触发）
    import agent.db as agent_db_mod
    def _boom(key):
        raise RuntimeError("agent.db unavailable")
    monkeypatch.setattr(agent_db_mod, "meta_get", _boom)
    assert sched.agent_online() is False


# ═══════════════════════════════════════════════════════════════
# 2026-09-14 架构调整：手动「运行」= Dashboard 直接 POST Agent，
# 不再本地建记录、不本地兜底执行（Agent 写云库 scheduler_runs）
# ═══════════════════════════════════════════════════════════════


def test_run_task_by_id_dispatches_to_agent(monkeypatch):
    """手动运行：POST Agent 成功 → started=True，且不写本地 scheduler_runs。"""
    import requests as req
    import agent.db as agent_db_mod
    monkeypatch.setattr(agent_db_mod, "meta_get",
                        lambda key: "1" if key == "xiaoman_online" else None)

    captured = {}

    class FakeResp:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self):
            return {"started": True, "reason": "ok"}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["body"] = json
        return FakeResp()

    monkeypatch.setattr(req, "post", fake_post)
    # 强制走真实 scoped_tasks（morning_analysis 在 task_schedule.json 里）
    task = next(t for t in sched.scoped_tasks() if t["task_id"] == "morning_analysis")
    assert task is not None
    monkeypatch.setattr(sched, "scoped_tasks", lambda: [task])
    monkeypatch.setattr(sched, "_dispatch_to_agent", lambda t, trigger="manual": {
        "started": True, "reason": "ok", "message": "已派发给 Agent 执行", "run": None,
    })
    r = sched.run_task_by_id("morning_analysis", trigger="manual")
    assert r["started"] is True
    assert r["reason"] == "ok"


def test_run_task_by_id_offline_rejected(monkeypatch):
    """小满下线 → 拒绝，message 含上班提示。"""
    import agent.db as agent_db_mod
    monkeypatch.setattr(agent_db_mod, "meta_get",
                        lambda key: "0" if key == "xiaoman_online" else None)
    r = sched.run_task_by_id("morning_analysis")
    assert r["started"] is False
    assert r["reason"] == "offline"
    assert "上线" in r["message"]


def test_run_task_by_id_unknown_task_rejected(monkeypatch):
    import agent.db as agent_db_mod
    monkeypatch.setattr(agent_db_mod, "meta_get",
                        lambda key: "1" if key == "xiaoman_online" else None)
    r = sched.run_task_by_id("no_such_task_xyz")
    assert r["started"] is False
    assert r["reason"] == "unknown"


def test_dispatch_to_agent_unreachable(monkeypatch):
    """Agent 进程不可达 → started=False + reason=agent_unreachable（不本地兜底）。"""
    import requests as req
    def _boom(*a, **k):
        raise ConnectionError("agent down")
    monkeypatch.setattr(req, "post", _boom)
    r = sched._dispatch_to_agent({"task_id": "morning_analysis"})
    assert r["started"] is False
    assert r["reason"] == "agent_unreachable"


def test_dispatch_stop_to_agent_ok(monkeypatch):
    """停止：POST Agent 成功 → stopped=True。"""
    import requests as req

    class FakeResp:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self):
            return {"stopped": True, "message": "已发送停止信号"}

    monkeypatch.setattr(req, "post", lambda *a, **k: FakeResp())
    r = sched.dispatch_stop_to_agent("morning_analysis")
    assert r["stopped"] is True


def test_dispatch_stop_to_agent_not_running(monkeypatch):
    """Agent 返回未运行 → stopped=False + reason=not_running。"""
    import requests as req

    class FakeResp:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self):
            return {"stopped": False, "reason": "not_running", "message": "该任务未在运行"}

    monkeypatch.setattr(req, "post", lambda *a, **k: FakeResp())
    r = sched.dispatch_stop_to_agent("ghost")
    assert r["stopped"] is False
    assert r["reason"] == "not_running"


def test_dispatch_stop_to_agent_unreachable(monkeypatch):
    """Agent 不可达 → stopped=False + reason=agent_unreachable。"""
    import requests as req
    def _boom(*a, **k):
        raise ConnectionError("agent down")
    monkeypatch.setattr(req, "post", _boom)
    r = sched.dispatch_stop_to_agent("morning_analysis")
    assert r["stopped"] is False
    assert r["reason"] == "agent_unreachable"
