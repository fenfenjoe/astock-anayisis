"""agent/core/scheduler_agent.py — 小满进程内的调度任务执行器。

接管 Dashboard scheduler.py 的全部定时任务（每日复盘 + ETF 自动化），
由 Agent 的 tick loop 驱动。数据全走云库（Supabase），不再依赖本地 markdown 文件。
"""

import json
import logging
import os
import subprocess
import tempfile
import threading
import time as _time
from datetime import datetime, date, time, timedelta
from pathlib import Path

from agent import config, db as agent_db

logger = logging.getLogger(__name__)

REPO_ROOT = config.REPO_ROOT
TASK_DEFS_FILE = REPO_ROOT / ".claude" / "scripts" / "task_schedule.json"
SCHEDULE_PATH = TASK_DEFS_FILE
CLAUDE_TIMEOUT_SECONDS = 3600
OUTPUT_TAIL_CHARS = 8000
SCOPE_PREFIXES = ("my_doc/每日复盘/", "etf-strategies/automation/")
TICK_SECONDS = 20
REPORT_RESCAN_SECONDS = 60
MAX_AUTO_FAILURES_PER_WINDOW = 2
# 交易日历（与 dashboard/scheduler.py 同源：每日复盘 harness 的 trading_calendar.py）
TRADING_CALENDAR_PATH = (
    REPO_ROOT
    / "my_doc"
    / "每日复盘"
    / "harness"
    / "automation"
    / "config"
    / "trading_calendar.py"
)

_trading_cal = None
_trading_cal_lock = threading.Lock()


def _trading_calendar_module():
    global _trading_cal
    if _trading_cal is not None:
        return _trading_cal
    with _trading_cal_lock:
        if _trading_cal is not None:
            return _trading_cal
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_trading_calendar_loaded", TRADING_CALENDAR_PATH
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore
        _trading_cal = module
    return _trading_cal


def is_trading_day(check_date=None) -> bool:
    """是否为交易日；日历不可用时 fail-open（与 dashboard/scheduler.py 一致）。"""
    try:
        return _trading_calendar_module().is_trading_day(check_date)
    except Exception:
        return True


# ── 云库 scheduler_runs 访问（与 dashboard 共用同一张表，触发/展示同源）──
# Agent 用 AGENT_DB_BACKEND=cloud 时走 cloud_db（同 Supabase）；file 模式（测试）
# 下写操作自动 no-op，读返回空 —— 保证普通测试不连真实云库。


def _cd_enabled() -> bool:
    return agent_db.USE_CLOUD and getattr(agent_db, "_cd_select", None) is not None


def scheduler_run_insert(task_id: str, window_key: str, trigger: str,
                         run_time: str, status: str = "running"):
    """写云库 scheduler_runs（running 初始行）。file 模式返回 None（no-op）。"""
    if not _cd_enabled():
        return None
    try:
        row = agent_db._cd_insert("scheduler_runs", {
            "task_id": task_id, "window_key": window_key, "trigger": trigger,
            "run_time": run_time, "status": status,
        })
        return row["id"] if row else None
    except Exception as exc:
        logger.warning("scheduler_runs 写入失败 (%s): %s", task_id, exc)
        return None


def scheduler_run_update(run_id, **fields):
    """更新云库 scheduler_runs 行。file 模式 no-op。"""
    if not _cd_enabled() or run_id is None:
        return
    allowed = {"status", "pid", "duration_sec", "output", "completed_at",
               "window_key", "run_time", "trigger", "task_id"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return
    try:
        agent_db._cd_update("scheduler_runs", sets, filters=[("id", "eq", run_id)])
    except Exception as exc:
        logger.warning("scheduler_runs 更新失败 (run#%s): %s", run_id, exc)


def scheduler_window_done(task_id: str, window_key: str,
                          max_failures: int | None = None) -> bool:
    """窗口是否已消耗（与 dashboard/db.py 同口径）。file 模式返回 False（可重试）。"""
    if not _cd_enabled():
        return False
    try:
        done = agent_db._cd_select_one(
            "scheduler_runs", columns="id",
            filters=[("task_id", "eq", task_id), ("window_key", "eq", window_key),
                     ("status", "in", "(success,timeout)")],
        )
        if done:
            return True
        if max_failures is not None:
            failed = agent_db._cd_select(
                "scheduler_runs", columns="id",
                filters=[("task_id", "eq", task_id), ("window_key", "eq", window_key),
                         ("status", "eq", "failed")],
            )
            if len(failed) >= max_failures:
                return True
    except Exception as exc:
        logger.warning("scheduler_window_done 查询失败 (%s): %s", task_id, exc)
    return False


def reconcile_zombies() -> int:
    """把遗留的 running 记录标记为 failed（Agent 进程重启中断）。

    2026-09-14 架构调整：Agent 是定时任务的唯一执行方，running 记录属于
    Agent。进程重启后 _run_task_and_record 的后台线程随旧进程被杀，DB 里的
    running 记录永远收不到终态 —— 成为僵尸记录（UI 一直显示"运行中"）。
    Agent 启动时调用本函数统一回收（等价于原 dashboard 的
    scheduler_mark_zombies_running）。返回被清理的记录数。
    """
    if not _cd_enabled():
        return 0
    note = "\n\n[interrupted] Agent 进程重启，任务被中断（未收到终态，标记为 failed）。"
    try:
        ids = agent_db._cd_select("scheduler_runs", columns="id",
                                  filters=[("status", "eq", "running")])
        if not ids:
            return 0
        now = datetime.now().isoformat()
        for r in ids:
            agent_db._cd_update(
                "scheduler_runs",
                {"status": "failed", "completed_at": now,
                 "output": (r.get("output") or "") + note},
                filters=[("id", "eq", r["id"])],
            )
        return len(ids)
    except Exception as exc:
        logger.warning("reconcile_zombies 失败: %s", exc)
        return 0

RATE_LIMIT_MARKERS = (
    "rate_limit",
    "rate limit",
    "accountratelimitexceeded",
    "requests are too frequent",
    "reduce your request frequency",
)
RATE_LIMIT_RETRY_BACKOFF_BASE_SECONDS = 30
MAX_RATE_LIMIT_RETRIES = 3
DSH_MAX_CONCURRENT = 2
DSH_SEM_ACQUIRE_TIMEOUT = 30

_dsh_sem = threading.BoundedSemaphore(DSH_MAX_CONCURRENT)
_running_tasks: dict[str, dict] = {}
_running_lock = threading.Lock()
_stop_flags: set[str] = set()  # 用户请求停止的任务（worker 轮询检查后清除）
_task_defs_cache = None
_task_defs_mtime = 0.0
_task_defs_ts = 0.0


def load_task_defs() -> list[dict]:
    global _task_defs_cache, _task_defs_mtime, _task_defs_ts
    now = _time.time()
    try:
        mtime = TASK_DEFS_FILE.stat().st_mtime
    except OSError:
        return []
    if _task_defs_mtime == mtime and _task_defs_ts and now - _task_defs_ts < 120:
        return _task_defs_cache
    try:
        with open(TASK_DEFS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f).get("tasks", [])
    except (OSError, json.JSONDecodeError):
        data = []
    _task_defs_mtime = mtime
    _task_defs_ts = now
    _task_defs_cache = data
    return data


def scoped_tasks() -> list[dict]:
    return [
        t
        for t in load_task_defs()
        if t.get("prompt_file", "").startswith(SCOPE_PREFIXES)
    ]


def _prompt_text(task: dict, now: datetime) -> str:
    pf = Path(REPO_ROOT) / task["prompt_file"]
    text = pf.read_text(encoding="utf-8")
    return text.replace("{today}", now.strftime("%Y%m%d"))


def make_window_key(task: dict, now: datetime) -> str:
    if task.get("hourly"):
        return f"{task['task_id']}:{now.date().isoformat()}:{now.hour:02d}"
    return f"{task['task_id']}:{now.date().isoformat()}"


def time_in_window(current, target, window_minutes):
    today = date.today()
    start = datetime.combine(today, target)
    end = start + timedelta(minutes=window_minutes)
    now = datetime.combine(today, current)
    return start <= now < end


def task_due_now(task: dict, now: datetime) -> bool:
    if (
        task.get("days_of_week") is not None
        and now.weekday() not in task["days_of_week"]
    ):
        return False
    window_minutes = task.get("window_minutes", 7)
    if task.get("hourly"):
        if now.hour not in task.get("hourly_range", []):
            return False
        target = time(now.hour, task.get("target_minute", 0))
        return time_in_window(now.time(), target, window_minutes)
    parts = task["target_time"].split(":")
    target = time(int(parts[0]), int(parts[1]))
    return time_in_window(now.time(), target, window_minutes)


def _is_running(task_id: str) -> bool:
    with _running_lock:
        return task_id in _running_tasks


def current_task() -> dict | None:
    with _running_lock:
        active = list(_running_tasks.values())
    if not active:
        return None
    return min(active, key=lambda r: r["started_at"])


def _extract_tokens_from_output(output: str) -> int | None:
    import re

    if not output:
        return None
    patterns = [
        r"(?:tokens|token)\s*[：:=]\s*(\d[\d,]*)\s*(?:input|total|token|\b)",
        r"total_tokens[：:=\s]+(\d[\d,]*)",
        r"(\d[\d,]*)\s*(?:tokens|token)",
    ]
    for pattern in patterns:
        m = re.search(pattern, output[-4096:], re.IGNORECASE)
        if m:
            try:
                return int(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _read_run_output(out_path, err_path):
    out = ""
    try:
        if out_path:
            out = Path(out_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        out = ""
    err = ""
    try:
        if err_path:
            err = Path(err_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        err = ""
    if err and err.strip():
        out = (out + "\n\n[stderr]\n" + err).strip()
    return out


def _is_rate_limited(text: str | None) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(m in low for m in RATE_LIMIT_MARKERS)


def _run_dsh_once(cmd: list[str], task_id: str | None = None) -> tuple[str, str]:
    out_path = err_path = None
    try:
        fd_out, out_path = tempfile.mkstemp(prefix="dsh_run_out_", suffix=".txt")
        fd_err, err_path = tempfile.mkstemp(prefix="dsh_run_err_", suffix=".txt")
        try:
            with (
                os.fdopen(fd_out, "w", encoding="utf-8") as fo,
                os.fdopen(fd_err, "w", encoding="utf-8") as fe,
            ):
                flags = 0
                startupinfo = None
                if os.name == "nt":
                    flags = subprocess.CREATE_NEW_PROCESS_GROUP
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = subprocess.SW_HIDE
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(REPO_ROOT),
                    stdin=subprocess.DEVNULL,
                    stdout=fo,
                    stderr=fe,
                    text=True,
                    encoding="utf-8",
                    creationflags=flags,
                    startupinfo=startupinfo,
                )
                # 注册 proc 句柄供 stop_task 终止（按 task_id 定位）
                if task_id:
                    with _running_lock:
                        if task_id in _running_tasks:
                            _running_tasks[task_id]["proc"] = proc
                try:
                    rc = proc.wait(timeout=CLAUDE_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    _kill_proc(proc)
                    return ("timeout", f"dsh 超时（>{CLAUDE_TIMEOUT_SECONDS}s），已终止。")
                status = "success" if rc == 0 else "failed"
                if _was_stopped(task_id):
                    status = "failed"
        except Exception as e:
            return ("failed", f"运行异常: {e}")
        return status, _read_run_output(out_path, err_path)
    finally:
        for p in (out_path, err_path):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def _kill_proc(proc) -> None:
    """终止 dsh 子进程。

    优先用 Popen 内置 terminate()/kill()（可靠，Windows 下无需管理员即可终止
    同一用户的进程）。随后尽力 taskkill /F /T 补刀（杀进程树，覆盖 dsh 派生的
    孙进程；若环境无权限/被拒则静默忽略 —— 主进程已被 terminate 杀掉即可）。
    """
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
    except Exception:
        pass
    try:
        if proc.poll() is None:
            proc.kill()
    except Exception:
        pass
    # 补刀：杀进程树（best-effort，失败忽略）
    try:
        if os.name == "nt" and proc.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        else:
            proc.kill()
    except Exception:
        pass


def _was_stopped(task_id: str | None) -> bool:
    if not task_id:
        return False
    with _running_lock:
        return task_id in _stop_flags


def _mark_stopped(task_id: str) -> None:
    with _running_lock:
        _stop_flags.add(task_id)


def _exec_dsh(task: dict, task_id: str | None = None) -> tuple[str, str]:
    import shutil

    node = shutil.which("node")
    if not node:
        return ("failed", "未找到 node 可执行文件")
    node_p = Path(node)
    dsh_bin = (
        node_p.resolve().parent
        / "node_modules"
        / "@deepseek-ai"
        / "dsh"
        / "lib"
        / "bin.js"
    )
    if not dsh_bin.exists():
        nvm_dir = Path.home() / "AppData" / "Roaming" / "nvm"
        candidates = sorted(nvm_dir.glob("*/node_modules/@deepseek-ai/dsh/lib/bin.js"))
        if candidates:
            ver_dir = candidates[0].parents[4]
            node_exe = ver_dir / "node.exe"
            if node_exe.exists():
                node_p = node_exe
                dsh_bin = candidates[0]
            else:
                return ("failed", "未找到 dsh CLI")
        else:
            return ("failed", "未找到 dsh CLI")

    task_id = task_id or task.get("task_id")
    directive = f"执行 {task['prompt_file']} 的全部内容。"
    cmd = [str(node_p), str(dsh_bin), "--profile", "headless", directive]

    if not _dsh_sem.acquire(timeout=DSH_SEM_ACQUIRE_TIMEOUT):
        return ("failed", f"dsh 并发已满，等待 {DSH_SEM_ACQUIRE_TIMEOUT}s 后放弃。")
    try:
        attempts = MAX_RATE_LIMIT_RETRIES + 1
        last_status = "failed"
        last_out = ""
        for attempt in range(1, attempts + 1):
            if _was_stopped(task_id):
                return ("failed", "任务已被用户停止")
            last_status, last_out = _run_dsh_once(cmd, task_id=task_id)
            if _was_stopped(task_id):
                return ("failed", "任务已被用户停止")
            if last_status == "success" or not _is_rate_limited(last_out):
                return last_status, last_out
            if attempt >= attempts:
                break
            backoff = RATE_LIMIT_RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            threading.Event().wait(backoff)
        return last_status, last_out
    finally:
        _dsh_sem.release()


def _run_task_and_record(task: dict, trigger: str = "manual") -> dict:
    task_id = task["task_id"]
    task_label = f"📊 {task.get('description') or task.get('name') or task_id}"
    started = datetime.now()

    # 写云库 scheduler_runs（工作日志同源；trigger='auto' 用窗口幂等 key，
    # manual 用独立 key，永不与 auto 冲突）
    if trigger == "auto":
        window_key = make_window_key(task, started)
    else:
        window_key = f"manual:{task_id}:{started.strftime('%Y%m%d-%H%M%S%f')}"
    run_id = scheduler_run_insert(
        task_id, window_key, trigger, started.strftime("%Y-%m-%d %H:%M:%S")
    )

    try:
        agent_db.activity_close_open(started.strftime("%Y-%m-%d %H:%M:%S"), tokens=None)
        agent_db.activity_start(
            "scheduled",
            task_label,
            started.strftime("%Y-%m-%d %H:%M:%S"),
            source="auto",
        )
    except Exception:
        pass

    status, out = _exec_dsh(task, task_id=task_id)

    ended = datetime.now()
    try:
        tokens = _extract_tokens_from_output(out) if status == "success" else None
        agent_db.activity_close_open(ended.strftime("%Y-%m-%d %H:%M:%S"), tokens=tokens)
    except Exception:
        pass

    elapsed = (datetime.now() - started).total_seconds()
    scheduler_run_update(
        run_id,
        status=status,
        duration_sec=elapsed,
        output=(out or "")[-OUTPUT_TAIL_CHARS:],
        completed_at=datetime.now().isoformat(),
    )
    return {
        "status": status,
        "output": (out or "")[-OUTPUT_TAIL_CHARS:],
        "duration_sec": elapsed,
        "task_id": task_id,
    }


def execute_task(task_id: str, trigger: str = "manual") -> dict:
    if agent_db.meta_get("xiaoman_online") != "1":
        return {
            "started": False,
            "reason": "offline",
            "message": "小满现在已下班了，无法执行任务~ 请在页面顶部点击【让小满上线】后再试 💤",
        }
    task = next((t for t in scoped_tasks() if t["task_id"] == task_id), None)
    if task is None:
        return {
            "started": False,
            "reason": "unknown",
            "message": f"未找到任务 {task_id}",
        }
    if _is_running(task_id):
        return {"started": False, "reason": "busy", "message": "该任务正在运行中"}
    with _running_lock:
        _running_tasks[task_id] = {
            "task_id": task_id,
            "name": task.get("name") or task_id,
            "started_at": datetime.now().strftime("%H:%M:%S"),
        }

    def worker():
        try:
            result = _run_task_and_record(task, trigger=trigger)
            _handle_task_result(task, result)
        finally:
            with _running_lock:
                _running_tasks.pop(task_id, None)
                _stop_flags.discard(task_id)

    threading.Thread(target=worker, daemon=True).start()
    return {"started": True, "reason": "ok", "message": "任务已启动"}


def stop_task(task_id: str) -> dict:
    """停止正在执行的任务：终止 dsh 子进程 + 记录状态（用户主动停止）。

    幂等：任务未在运行/已停止 → 返回 not_running。停止后 worker 线程
    自然结束并写入失败状态（含"已被用户停止"说明）。
    """
    with _running_lock:
        entry = _running_tasks.get(task_id)
    if entry is None:
        return {"stopped": False, "reason": "not_running", "message": "该任务未在运行"}
    proc = entry.get("proc")
    _mark_stopped(task_id)
    if proc is not None:
        _kill_proc(proc)
    # 记录停止原因到云库 scheduler_runs（若有正在 running 的行）
    _mark_run_stopped(task_id)
    return {"stopped": True, "reason": "ok", "message": f"已发送停止信号，任务 {task_id} 正在终止"}


def _mark_run_stopped(task_id: str) -> None:
    """把该任务最新的 running 记录标记为 failed（用户停止），并附说明。"""
    if not _cd_enabled():
        return
    try:
        row = agent_db._cd_select_one(
            "scheduler_runs", columns="id",
            filters=[("task_id", "eq", task_id), ("status", "eq", "running")],
            order="id.desc",
        )
        if row:
            agent_db._cd_update(
                "scheduler_runs",
                {"status": "failed", "completed_at": datetime.now().isoformat(),
                 "output": "[stopped] 任务已被用户停止。"},
                filters=[("id", "eq", row["id"])],
            )
    except Exception as exc:
        logger.warning("stop_task 标记 scheduler_runs 失败 (%s): %s", task_id, exc)


def tick(now: datetime | None = None) -> dict:
    """Agent 进程的调度 tick：检查定时任务是否到点，到点则触发并执行。

    由 Agent 主循环（lifecycle.AgentLoop.tick）周期性调用。语义与
    dashboard/scheduler.py 的 auto 派发一致：
    - 交易日门控 + 时间窗口 + window_key 幂等（云库 scheduler_runs 同一张表）
    - 到点且未完成 → execute_task(trigger='auto') 执行
    - 写云库 scheduler_runs（Agent 自己建 running → 完成更新终态），
      与 Dashboard 展示同源，不再需要 Dashboard 派发。
    """
    now = now or datetime.now()
    started: list[str] = []
    for t in scoped_tasks():
        if t.get("trading_day_required", False) and not is_trading_day(now.date()):
            continue
        if not task_due_now(t, now):
            continue
        wkey = make_window_key(t, now)
        if scheduler_window_done(
            t["task_id"], wkey, max_failures=MAX_AUTO_FAILURES_PER_WINDOW
        ):
            continue  # 该时间窗已成功/超时/失败达上限（幂等 + 防重试风暴）
        result = execute_task(t["task_id"], trigger="auto")
        if result.get("started"):
            started.append(t["task_id"])
    return {"started": started, "checked_at": now.strftime("%Y-%m-%d %H:%M:%S")}


def _handle_task_result(task, result):
    status = result["status"]
    if status == "success":
        return
    ticket_id = None
    try:
        ticket_id = _upsert_ticket(task, result)
    except Exception:
        pass
    if status == "failed" and ticket_id:
        try:
            agent_db.notice_create(
                "notice",
                f"调度任务 {task.get('task_id')} 执行失败",
                f"任务 {task.get('name') or task.get('task_id')} 执行失败，工单 {ticket_id} 已创建。",
                source="agent",
            )
        except Exception as exc:  # 通知失败不应影响任务结果处理，但必须留痕
            logger.warning("调度任务失败通知生成失败: %s", exc)


def _upsert_ticket(task, result) -> str | None:
    import uuid

    ticket_id = uuid.uuid4().hex[:12]
    now = datetime.now().isoformat()
    ticket = {
        "id": ticket_id,
        "kind": "bug" if "bug" in task.get("task_id", "") else "req",
        "title": task.get("name") or task.get("description") or task["task_id"],
        "description": f"来源调度任务: {task['task_id']}\nprompt_file: {task.get('prompt_file', '')}",
        "severity": "p2",
        "status": "analyzing",
        "source_task": task["task_id"],
        "assignee": "xiaoman",
        "created_at": now,
        "updated_at": now,
        "result": "",
        "log_entries": json.dumps(
            [{"ts": now, "step": "created", "detail": "任务创建，等待处理"}],
            ensure_ascii=False,
        ),
    }
    try:
        from agent import db as _db

        _db.ticket_upsert(ticket)
    except Exception as exc:  # 建单失败不应中断任务结果处理，但必须留痕
        logger.warning("调度任务工单写入失败 (%s): %s", ticket_id, exc)
    return ticket_id


def status() -> dict:
    return {
        "running": True,
        "auto_enabled": True,
        "current_task": current_task(),
        "tick_seconds": TICK_SECONDS,
    }
