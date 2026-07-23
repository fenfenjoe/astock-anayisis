#!/usr/bin/env python3
"""Task scheduler for /loop architecture.

Determines which automated task (if any) should run at the current time.
Used by the /loop meta-prompt (loop_runner.md) each 7-minute iteration.

Usage:
    python task_scheduler.py --check              # Check if any task is due
    python task_scheduler.py --complete <task_id> # Mark task as done
    python task_scheduler.py --status             # Show today's execution state
"""

import json
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

# --- Paths ---
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEDULE_PATH = Path(__file__).resolve().parent / "task_schedule.json"
STATE_PATH = Path(__file__).resolve().parent / "scheduler_state.json"
TRADING_CALENDAR = (
    REPO_ROOT / "my_doc" / "每日复盘" / "harness" / "automation" / "config" / "trading_calendar.py"
)


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_PATH.exists():
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"executed": {}}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def purge_old_entries(state: dict, today_str: str) -> dict:
    """Remove execution entries from previous days."""
    if "executed" not in state:
        state["executed"] = {}
    state["executed"] = {
        k: v for k, v in state["executed"].items()
        if today_str in k  # key format: "task_id:YYYY-MM-DD" or "task_id:YYYY-MM-DD:HH"
    }
    return state


# ---------------------------------------------------------------------------
# Trading calendar
# ---------------------------------------------------------------------------

def is_trading_day(check_date: date | None = None) -> bool:
    """Check via the project's existing trading_calendar.py."""
    if check_date is None:
        check_date = date.today()
    try:
        result = subprocess.run(
            ["python", str(TRADING_CALENDAR), check_date.isoformat()],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(result.stdout)
        return data.get("is_trading_day", False)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        # If calendar is unreachable, assume trading day (fail open for ETF tasks)
        return True


# ---------------------------------------------------------------------------
# Window helpers
# ---------------------------------------------------------------------------

def time_in_window(current: time, target: time, window_minutes: int) -> bool:
    """Return True if *current* is within [target, target + window_minutes)."""
    today = date.today()
    start = datetime.combine(today, target)
    end = start + timedelta(minutes=window_minutes)
    now = datetime.combine(today, current)
    return start <= now < end


def make_window_key(task: dict, now: datetime) -> str:
    """Generate an idempotency key for *task* at *now*."""
    if task.get("hourly"):
        return f"{task['task_id']}:{now.date().isoformat()}:{now.hour:02d}"
    return f"{task['task_id']}:{now.date().isoformat()}"


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def check() -> dict:
    """Return the first due task, or {"should_run": false}."""
    with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
        schedule = json.load(f)

    state = load_state()
    now = datetime.now()
    today_str = now.date().isoformat()

    # Cross-day cleanup
    state = purge_old_entries(state, today_str)
    state["last_check"] = now.isoformat()
    save_state(state)

    for task in schedule["tasks"]:
        # --- Day-of-week ---
        if task.get("days_of_week") is not None:
            if now.weekday() not in task["days_of_week"]:
                continue

        # --- Trading day ---
        if task.get("trading_day_required", False):
            if not is_trading_day(now.date()):
                continue

        # --- Idempotency ---
        window_key = make_window_key(task, now)
        if window_key in state.get("executed", {}):
            continue

        # --- Time window ---
        window_minutes = task.get("window_minutes", 7)

        if task.get("hourly"):
            target_minute = task["target_minute"]
            hour_range = task.get("hourly_range", [])
            if now.hour not in hour_range:
                continue
            target = time(now.hour, target_minute)
            if not time_in_window(now.time(), target, window_minutes):
                continue
        else:
            parts = task["target_time"].split(":")
            target = time(int(parts[0]), int(parts[1]))
            if not time_in_window(now.time(), target, window_minutes):
                continue

        # --- Match ---
        return {
            "should_run": True,
            "task_id": task["task_id"],
            "prompt_file": task["prompt_file"],
            "window": window_key,
            "description": task.get("description", ""),
            "target_time": task.get("target_time", f"hourly :{task.get('target_minute', '?')}"),
        }

    return {
        "should_run": False,
        "current_time": now.isoformat(),
        "checked_tasks": len(schedule["tasks"]),
    }


def complete(task_id: str) -> dict:
    """Mark *task_id* as executed for the current window."""
    with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
        schedule = json.load(f)

    task_def = next((t for t in schedule["tasks"] if t["task_id"] == task_id), None)
    if not task_def:
        return {"completed": False, "error": f"Unknown task_id: {task_id}"}

    state = load_state()
    now = datetime.now()
    window_key = make_window_key(task_def, now)

    if "executed" not in state:
        state["executed"] = {}
    state["executed"][window_key] = now.isoformat()
    save_state(state)

    return {"completed": True, "task_id": task_id, "window_key": window_key}


def status() -> dict:
    """Return current execution state."""
    state = load_state()
    with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
        schedule = json.load(f)
    return {
        "date": date.today().isoformat(),
        "weekday": date.today().strftime("%A"),
        "total_tasks": len(schedule["tasks"]),
        "executed_today": len(state.get("executed", {})),
        "executed": state.get("executed", {}),
        "last_check": state.get("last_check"),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--check" in sys.argv:
        result = check()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif "--complete" in sys.argv:
        idx = sys.argv.index("--complete")
        task_id = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None
        if not task_id:
            print(json.dumps({"completed": False, "error": "Missing task_id"}, ensure_ascii=False))
            sys.exit(1)
        result = complete(task_id)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif "--status" in sys.argv:
        result = status()
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Usage: task_scheduler.py --check | --complete <task_id> | --status", file=sys.stderr)
        sys.exit(1)
