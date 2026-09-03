#!/usr/bin/env python3
"""精确时刻触发：指定任务到点执行一次（替代 7 分钟轮询架构）。

由 Windows 计划任务在目标时刻调用：
    python .claude/scripts/dsh_trigger.py --task morning_analysis
    python .claude/scripts/dsh_trigger.py --task evening_review

内部复用 task_scheduler.py 的交易日/幂等/窗口逻辑：
- 非交易日自动跳过（交易日历读取失败时按 fail-open 处理，与原架构一致）
- 已执行过则跳过（scheduler_state.json 幂等）
- 到点则：标记完成 → 派发独立 headless 进程执行任务 prompt（零上下文累积）

相比 7 分钟轮询：空闲零 token、零进程；只有真正到点的任务才消耗 token。
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import task_scheduler as ts  # noqa: E402
from dsh_loop_scheduler import dispatch, LOG_DIR  # noqa: E402  (复用派发/日志)

# pythonw.exe（无窗口）下 sys.stdout/stderr 为 None，print 会抛异常；
# 任务计划用 pythonw 运行时把输出重定向到 devnull 即可（日志本就落 .dsh/logs/）。
if os.path.basename(sys.executable).lower().startswith("pythonw"):
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
    sys.stderr = open(os.devnull, "w", encoding="utf-8")


def load_task(task_id: str) -> dict | None:
    with open(ts.SCHEDULE_PATH, "r", encoding="utf-8") as f:
        sched = json.load(f)
    return next((t for t in sched["tasks"] if t["task_id"] == task_id), None)


def should_run(task: dict, now: datetime) -> tuple[bool, str]:
    """触发模式判定：星期 ✓ 交易日 ✓ 幂等 ✓ 时间窗口（宽松容差）✓。"""
    if task.get("days_of_week") is not None and now.weekday() not in task["days_of_week"]:
        return False, "非计划星期"
    if task.get("trading_day_required", False) and not ts.is_trading_day(now.date()):
        return False, "非交易日"
    key = ts.make_window_key(task, now)
    if key in ts.load_state().get("executed", {}):
        return False, f"今日已执行({key})"
    # 时间窗口：目标时刻 ±3 小时（任务计划抖动/机器休眠恢复的容差）
    if task.get("hourly"):
        target = now.replace(minute=task["target_minute"], second=0, microsecond=0)
        if now.hour not in task.get("hourly_range", []):
            return False, "不在小时范围"
    else:
        hh, mm = task["target_time"].split(":")
        target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    if abs((now - target).total_seconds()) > 3 * 3600:
        return False, f"超出触发窗口(目标{target:%H:%M})"
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, help="task_id，如 morning_analysis / evening_review")
    ap.add_argument("--force", action="store_true", help="忽略幂等/窗口判定强制执行（调试用）")
    ap.add_argument("--dry-run", action="store_true", help="只判定不执行")
    args = ap.parse_args()

    task = load_task(args.task)
    if not task:
        print(json.dumps({"error": f"unknown task: {args.task}"}, ensure_ascii=False))
        return 1

    now = datetime.now()
    if not args.force:
        ok, reason = should_run(task, now)
        if not ok:
            print(json.dumps({"skip": args.task, "reason": reason}, ensure_ascii=False))
            return 0

    if args.dry_run:
        print(json.dumps({"would_run": args.task, "prompt_file": task["prompt_file"]},
                         ensure_ascii=False))
        return 0

    task_id = task["task_id"]
    ts.complete(task_id)
    ts.mark_running(task_id)
    result = {
        "task_id": task_id,
        "prompt_file": task["prompt_file"],
        "self_managed_complete": task.get("self_managed_complete", False),
    }
    log = dispatch(result)
    print(json.dumps({"dispatched": task_id, "log": log}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
