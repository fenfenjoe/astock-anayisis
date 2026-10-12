"""agent/core/scheduler_agent.py — Agent 进程调度 tick + 云库 scheduler_runs。

架构调整（2026-09-14）：Dashboard 不再主动派发定时任务；
Agent 进程自己检查到点任务并执行，运行记录写云库 scheduler_runs（工作日志同源）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime

import pytest

from agent import db as agent_db
from agent.core import scheduler_agent as sa


# ═════════════════════════════════════════════════════════════════
# tick()：只触发「到点 + 未完成」的任务
# ═════════════════════════════════════════════════════════════════


def _task(task_id="task_a", **kw):
    t = {
        "task_id": task_id,
        "prompt_file": "etf-strategies/automation/prompts/x.md",
        "target_time": "10:00",
        "window_minutes": 7,
        "days_of_week": None,
        "trading_day_required": False,
    }
    t.update(kw)
    return t


def test_tick_starts_due_unstarted_task(monkeypatch):
    due = _task()
    not_due = _task("task_b", target_time="23:59")
    monkeypatch.setattr(sa, "scoped_tasks", lambda: [due, not_due])
    calls = []

    def fake_execute(task_id, trigger="manual"):
        calls.append((task_id, trigger))
        return {"started": True, "reason": "ok"}

    monkeypatch.setattr(sa, "execute_task", fake_execute)
    monkeypatch.setattr(sa, "scheduler_window_done", lambda *a, **k: False)
    now = datetime(2026, 9, 14, 10, 3)  # 周一 10:03，task_a 在 10:00+7min 窗口内
    r = sa.tick(now=now)
    assert r["started"] == ["task_a"]
    assert calls == [("task_a", "auto")]


def test_tick_skips_when_window_done(monkeypatch):
    due = _task()
    monkeypatch.setattr(sa, "scoped_tasks", lambda: [due])
    calls = []

    def fake_execute(task_id, trigger="manual"):
        calls.append(task_id)
        return {"started": True}

    monkeypatch.setattr(sa, "execute_task", fake_execute)
    monkeypatch.setattr(sa, "scheduler_window_done", lambda *a, **k: True)
    now = datetime(2026, 9, 14, 10, 3)
    r = sa.tick(now=now)
    assert r["started"] == []
    assert calls == []


def test_tick_skips_non_trading_day(monkeypatch):
    due = _task(trading_day_required=True)
    monkeypatch.setattr(sa, "scoped_tasks", lambda: [due])
    calls = []

    def fake_execute(task_id, trigger="manual"):
        calls.append(task_id)
        return {"started": True}

    monkeypatch.setattr(sa, "execute_task", fake_execute)
    monkeypatch.setattr(sa, "scheduler_window_done", lambda *a, **k: False)
    monkeypatch.setattr(sa, "is_trading_day", lambda d: False)
    now = datetime(2026, 9, 14, 10, 3)
    r = sa.tick(now=now)
    assert r["started"] == []
    assert calls == []


def test_tick_does_not_trigger_when_execute_rejects(monkeypatch):
    """execute_task 拒绝（如并发 busy）→ 不算 started，但 tick 不抛错。"""
    due = _task()
    monkeypatch.setattr(sa, "scoped_tasks", lambda: [due])
    monkeypatch.setattr(sa, "scheduler_window_done", lambda *a, **k: False)
    monkeypatch.setattr(
        sa, "execute_task",
        lambda task_id, trigger="manual": {"started": False, "reason": "busy"},
    )
    now = datetime(2026, 9, 14, 10, 3)
    r = sa.tick(now=now)
    assert r["started"] == []


# ═════════════════════════════════════════════════════════════════
# 云库 scheduler_runs helpers（file 模式 no-op；cloud 模式走 cloud_db）
# ═════════════════════════════════════════════════════════════════


def test_scheduler_run_insert_noop_in_file_mode(tmp_path, monkeypatch):
    """file 模式（测试默认 AGENT_DB_BACKEND=file）→ 写操作 no-op，不连云库。"""
    monkeypatch.setattr(agent_db, "USE_CLOUD", False)
    assert sa.scheduler_run_insert("t", "t:2026-09-14", "auto", "2026-09-14 10:00") is None
    assert sa.scheduler_run_update(123, status="success") is None
    assert sa.scheduler_window_done("t", "t:2026-09-14") is False


def test_scheduler_run_helpers_call_cloud_in_cloud_mode(monkeypatch):
    """cloud 模式 → 走 cloud_db 的 insert/update/select（mock 验证调用与参数）。"""
    calls = {"insert": [], "update": [], "select_one": [], "select": []}

    def fake_insert(table, row):
        calls["insert"].append((table, row))
        return {"id": 42}

    def fake_update(table, row, filters=None, columns="*"):
        calls["update"].append((table, row, filters))

    def fake_select_one(table, *, columns="*", filters=None, order=None):
        calls["select_one"].append((table, columns, filters))
        return {"id": 42}

    def fake_select(table, *, columns="*", filters=None, order=None, limit=None, offset=None):
        calls["select"].append((table, columns, filters))
        return []

    monkeypatch.setattr(agent_db, "USE_CLOUD", True)
    monkeypatch.setattr(agent_db, "_cd_insert", fake_insert)
    monkeypatch.setattr(agent_db, "_cd_update", fake_update)
    monkeypatch.setattr(agent_db, "_cd_select_one", fake_select_one)
    monkeypatch.setattr(agent_db, "_cd_select", fake_select)

    rid = sa.scheduler_run_insert("t", "t:2026-09-14", "auto", "2026-09-14 10:00")
    assert rid == 42
    assert calls["insert"] == [("scheduler_runs", {
        "task_id": "t", "window_key": "t:2026-09-14", "trigger": "auto",
        "run_time": "2026-09-14 10:00", "status": "running",
    })]

    sa.scheduler_run_update(42, status="success", duration_sec=1.5)
    assert calls["update"][0][0] == "scheduler_runs"
    assert calls["update"][0][1]["status"] == "success"
    assert calls["update"][0][1]["duration_sec"] == 1.5

    assert sa.scheduler_window_done("t", "t:2026-09-14") is True  # select_one 返回 id
    # window_done 命中 success/timeout → 不再查 failed
    assert calls["select_one"][0][0] == "scheduler_runs"


def test_scheduler_window_done_failed_cap(monkeypatch):
    """无 success/timeout，但 failed 达 max_failures → 视为已消耗。"""
    monkeypatch.setattr(agent_db, "USE_CLOUD", True)

    def fake_select_one(table, *, columns="*", filters=None, order=None):
        return None  # 无 success/timeout

    def fake_select(table, *, columns="*", filters=None, order=None, limit=None, offset=None):
        return [{"id": 1}, {"id": 2}]  # 2 条 failed

    monkeypatch.setattr(agent_db, "_cd_select_one", fake_select_one)
    monkeypatch.setattr(agent_db, "_cd_select", fake_select)
    assert sa.scheduler_window_done("t", "w", max_failures=2) is True


# ═════════════════════════════════════════════════════════════════
# _run_task_and_record：写云库 scheduler_runs（running → 终态）
# ═════════════════════════════════════════════════════════════════


def test_run_task_and_record_writes_scheduler_runs(monkeypatch):
    monkeypatch.setattr(agent_db, "USE_CLOUD", True)
    inserts = []
    updates = []

    def fake_insert(table, row):
        inserts.append(row)
        return {"id": 7}

    def fake_update(table, row, filters=None, columns="*"):
        updates.append((table, row, filters))

    monkeypatch.setattr(agent_db, "_cd_insert", fake_insert)
    monkeypatch.setattr(agent_db, "_cd_update", fake_update)
    monkeypatch.setattr(sa, "_exec_dsh", lambda task, task_id=None: ("success", "Tokens: 123 input / 45 output"))
    monkeypatch.setattr(agent_db, "activity_start", lambda *a, **k: None)
    monkeypatch.setattr(agent_db, "activity_close_open", lambda *a, **k: None)

    task = _task(task_id="task_c", hourly=True, hourly_range=[10], target_minute=0)
    # 直接测 auto trigger → window_key = make_window_key（与 dashboard 同口径）
    sa._run_task_and_record(task, trigger="auto")
    assert len(inserts) == 1
    row = inserts[0]
    assert row["task_id"] == "task_c"
    assert row["trigger"] == "auto"
    assert row["window_key"] == "task_c:2026-09-14:10" or row["window_key"].startswith("task_c:")
    assert row["status"] == "running"
    assert len(updates) == 1
    urow = updates[0][1]
    assert urow["status"] == "success"
    assert urow["duration_sec"] >= 0
    assert "input / 45 output" in urow["output"]


def test_run_task_and_record_manual_window_key(monkeypatch):
    """manual trigger → 独立 window_key（manual:{task_id}:{ts}），永不与 auto 冲突。"""
    monkeypatch.setattr(agent_db, "USE_CLOUD", True)
    inserts = []

    def fake_insert(table, row):
        inserts.append(row)
        return {"id": 8}

    monkeypatch.setattr(agent_db, "_cd_insert", fake_insert)
    monkeypatch.setattr(sa, "_exec_dsh", lambda task, task_id=None: ("failed", "boom"))
    monkeypatch.setattr(agent_db, "activity_start", lambda *a, **k: None)
    monkeypatch.setattr(agent_db, "activity_close_open", lambda *a, **k: None)

    sa._run_task_and_record(_task("task_manual"), trigger="manual")
    assert len(inserts) == 1
    assert inserts[0]["trigger"] == "manual"
    assert inserts[0]["window_key"].startswith("manual:task_manual:")


# ═════════════════════════════════════════════════════════════════
# is_trading_day：日历不可用 fail-open
# ═════════════════════════════════════════════════════════════════


def test_is_trading_day_fail_open(monkeypatch):
    def boom(d=None):
        raise RuntimeError("calendar unavailable")

    monkeypatch.setattr(sa, "_trading_calendar_module", boom)
    assert sa.is_trading_day() is True


# ═════════════════════════════════════════════════════════════════
# reconcile_zombies：Agent 启动时回收遗留 running 记录
# ═════════════════════════════════════════════════════════════════


def test_reconcile_zombies_marks_running_failed(monkeypatch):
    """running 记录 → failed + completed_at + 中断说明（file 模式 no-op）。"""
    monkeypatch.setattr(agent_db, "USE_CLOUD", True)
    running_rows = [{"id": 5, "output": "partial"}]

    def fake_select(table, *, columns="*", filters=None, order=None, limit=None, offset=None):
        return running_rows

    updates = []

    def fake_update(table, row, filters=None, columns="*"):
        updates.append((table, row, filters))

    monkeypatch.setattr(agent_db, "_cd_select", fake_select)
    monkeypatch.setattr(agent_db, "_cd_update", fake_update)
    n = sa.reconcile_zombies()
    assert n == 1
    assert len(updates) == 1
    t, row, filt = updates[0]
    assert t == "scheduler_runs"
    assert row["status"] == "failed"
    assert "中断" in row["output"]
    assert filt == [("id", "eq", 5)]


def test_reconcile_zombies_file_mode_noop(monkeypatch):
    monkeypatch.setattr(agent_db, "USE_CLOUD", False)
    assert sa.reconcile_zombies() == 0


# ═════════════════════════════════════════════════════════════════
# stop_task：用户停止正在执行的任务
# ═════════════════════════════════════════════════════════════════


def test_stop_task_kills_proc_and_marks_stopped(monkeypatch):
    """stop_task：kill proc + 标记 stop flag + 写云库 running→failed。"""
    monkeypatch.setattr(agent_db, "USE_CLOUD", True)
    killed = []
    updated = []

    class FakeProc:
        pid = 999

    def fake_kill(proc):
        killed.append(proc)

    monkeypatch.setattr(sa, "_kill_proc", fake_kill)

    def fake_update(table, row, filters=None, columns="*"):
        updated.append((table, row, filters))

    def fake_select_one(table, *, columns="*", filters=None, order=None):
        return {"id": 42}

    monkeypatch.setattr(agent_db, "_cd_update", fake_update)
    monkeypatch.setattr(agent_db, "_cd_select_one", fake_select_one)
    # 造一个"正在运行"的任务
    with sa._running_lock:
        sa._running_tasks["task_x"] = {
            "task_id": "task_x", "name": "X", "started_at": "10:00", "proc": FakeProc()
        }
        sa._stop_flags.discard("task_x")
    try:
        r = sa.stop_task("task_x")
        assert r["stopped"] is True
        assert len(killed) == 1
        assert sa._was_stopped("task_x") is True
        # 云库标记：task_x 的最新 running 记录 → failed + 停止说明
        assert len(updated) == 1
        assert updated[0][0] == "scheduler_runs"
        assert updated[0][1]["status"] == "failed"
        assert "用户停止" in updated[0][1]["output"]
        assert updated[0][2] == [("id", "eq", 42)]
    finally:
        with sa._running_lock:
            sa._running_tasks.pop("task_x", None)
            sa._stop_flags.discard("task_x")


def test_stop_task_not_running(monkeypatch):
    """任务未运行 → stopped=False + reason=not_running。"""
    with sa._running_lock:
        sa._running_tasks.clear()
        sa._stop_flags.clear()
    r = sa.stop_task("ghost_task")
    assert r["stopped"] is False
    assert r["reason"] == "not_running"


def test_was_stopped_flag_lifecycle(monkeypatch):
    """worker 结束时清除 stop flag 与 running 条目（execute_task 的 finally 逻辑）。"""
    sa._mark_stopped("task_y")
    assert sa._was_stopped("task_y") is True
    with sa._running_lock:
        sa._running_tasks["task_y"] = {"task_id": "task_y", "name": "Y", "started_at": "10:00"}
        # 模拟 worker finally 清理
        sa._running_tasks.pop("task_y", None)
        sa._stop_flags.discard("task_y")
    assert sa._was_stopped("task_y") is False
    assert "task_y" not in sa._running_tasks


# ═════════════════════════════════════════════════════════════════
# BUG-FIX(2026-09-21): current_task 泄漏 subprocess proc 对象
# → /api/agent/status 500 ('_thread.lock' object is not iterable)
# ═════════════════════════════════════════════════════════════════

def test_current_task_strips_proc_field(monkeypatch):
    """任务运行中（_running_tasks 条目含 proc=Popen）→ current_task() 返回的
    dict 不含 proc，且可被 json.dumps 序列化（FastAPI 响应不再 500）。"""
    import json

    class FakeProc:
        def __init__(self):
            self._lock = __import__("threading").Lock()
        pid = 999

    with sa._running_lock:
        sa._running_tasks.clear()
        sa._running_tasks["task_x"] = {
            "task_id": "task_x", "name": "X", "started_at": "10:00", "proc": FakeProc(),
        }
    try:
        task = sa.current_task()
        assert task is not None
        assert task["task_id"] == "task_x"
        assert "proc" not in task          # proc 不得泄漏到响应
        assert list(task) == ["task_id", "name", "started_at"]
        json.dumps(task)                   # 必须可序列化
    finally:
        with sa._running_lock:
            sa._running_tasks.pop("task_x", None)


def test_current_task_without_proc_unchanged(monkeypatch):
    """无 proc 的条目（空闲态/旧数据）行为不变——只返回 task_id/name/started_at。"""
    with sa._running_lock:
        sa._running_tasks.clear()
        sa._running_tasks["task_x"] = {"task_id": "task_x", "name": "X", "started_at": "10:00"}
    try:
        task = sa.current_task()
        assert task == {"task_id": "task_x", "name": "X", "started_at": "10:00"}
    finally:
        with sa._running_lock:
            sa._running_tasks.pop("task_x", None)


def test_run_dsh_once_stop_flag_yields_failed(monkeypatch):
    """停止标志已设时，即便子进程退出码为 0，也返回 failed（防止误报成功）。"""
    import subprocess

    captured = {}

    class FakeProc:
        def __init__(self):
            self.returncode = 0

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: FakeProc())
    sa._mark_stopped("task_z")
    try:
        status, _ = sa._run_dsh_once(["echo", "hi"], task_id="task_z")
        assert status == "failed"
    finally:
        with sa._running_lock:
            sa._stop_flags.discard("task_z")


def test_kill_proc_uses_terminate_then_kill(monkeypatch):
    """_kill_proc：先 terminate，未退出再 kill（Windows 上也可靠，不依赖 taskkill）。"""
    killed = []

    class FakeProc:
        def __init__(self):
            self._alive = True

        def poll(self):
            return None if self._alive else 0

        def terminate(self):
            killed.append("terminate")
            self._alive = False

        def kill(self):
            killed.append("kill")

    p = FakeProc()
    sa._kill_proc(p)
    assert killed == ["terminate"]
    # 已退出（poll 非 None）→ 不再 terminate/kill
    killed.clear()
    p._alive = False
    sa._kill_proc(p)
    assert killed == []
