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


def _run_dsh_once(cmd: list[str]) -> tuple[str, str]:
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
                proc = subprocess.run(
                    cmd,
                    cwd=str(REPO_ROOT),
                    stdin=subprocess.DEVNULL,
                    stdout=fo,
                    stderr=fe,
                    text=True,
                    encoding="utf-8",
                    timeout=CLAUDE_TIMEOUT_SECONDS,
                    creationflags=flags,
                    startupinfo=startupinfo,
                )
            status = "success" if proc.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            return ("timeout", f"dsh 超时（>{CLAUDE_TIMEOUT_SECONDS}s），已终止。")
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


def _exec_dsh(task: dict) -> tuple[str, str]:
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

    directive = f"执行 {task['prompt_file']} 的全部内容。"
    cmd = [str(node_p), str(dsh_bin), "--profile", "headless", directive]

    if not _dsh_sem.acquire(timeout=DSH_SEM_ACQUIRE_TIMEOUT):
        return ("failed", f"dsh 并发已满，等待 {DSH_SEM_ACQUIRE_TIMEOUT}s 后放弃。")
    try:
        attempts = MAX_RATE_LIMIT_RETRIES + 1
        last_status = "failed"
        last_out = ""
        for attempt in range(1, attempts + 1):
            last_status, last_out = _run_dsh_once(cmd)
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

    status, out = _exec_dsh(task)

    ended = datetime.now()
    try:
        tokens = _extract_tokens_from_output(out) if status == "success" else None
        agent_db.activity_close_open(ended.strftime("%Y-%m-%d %H:%M:%S"), tokens=tokens)
    except Exception:
        pass

    elapsed = (datetime.now() - started).total_seconds()
    return {
        "status": status,
        "output": (out or "")[-OUTPUT_TAIL_CHARS:],
        "duration_sec": elapsed,
        "task_id": task_id,
    }


def execute_task(task_id: str, trigger: str = "manual") -> dict:
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

    threading.Thread(target=worker, daemon=True).start()
    return {"started": True, "reason": "ok", "message": "任务已启动"}


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
