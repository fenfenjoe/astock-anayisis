#!/usr/bin/env python3
"""DSH 自动化执行状态一览（一键查看）。

用法:
    python .claude/scripts/dsh_status.py           # 今日调度状态 + 最近派发日志
    python .claude/scripts/dsh_status.py --logs 20 # 显示最近 20 条派发日志

输出:
    1) 今日任务状态表（已执行/待执行/已过窗口/非今日）
    2) 最近派发日志（.dsh/logs/，headless stdout/stderr 落盘）
"""

import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import task_scheduler as ts  # noqa: E402

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def task_status(task: dict, now: datetime, executed: set) -> str:
    tid = task["task_id"]
    if task.get("days_of_week") is not None and now.weekday() not in task["days_of_week"]:
        return "非今日"
    if task.get("hourly"):
        # 小时任务：统计今天已执行次数
        n = sum(1 for k in executed if k.startswith(f"{tid}:{now.date().isoformat()}:"))
        if now.hour > max(task.get("hourly_range", [0])):
            return f"今日已结束(执行{n}次)"
        return f"执行{n}次/今天"
    key = f"{tid}:{now.date().isoformat()}"
    if key in executed:
        return "已执行"
    if not task.get("trading_day_required", False) or ts.is_trading_day(now.date()):
        hh, mm = task["target_time"].split(":")
        tgt = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if now < tgt:
            return f"待执行 {task['target_time']}"
        return "已过窗口(今日未执行!)"
    return "非交易日"


def main() -> int:
    now = datetime.now()
    with open(ts.SCHEDULE_PATH, "r", encoding="utf-8") as f:
        sched = json.load(f)
    state = ts.load_state()
    executed = set(state.get("executed", {}))
    trading = ts.is_trading_day(now.date())

    print("=" * 70)
    print(f"DSH 自动化状态 | {now:%Y-%m-%d %H:%M} {WEEKDAY_CN[now.weekday()]} | "
          f"交易日: {'是' if trading else '否'}")
    print("=" * 70)

    print(f"\n[今日任务状态]")
    for t in sorted(sched["tasks"], key=lambda x: x.get("target_time", "")):
        tid = t["task_id"]
        desc = t.get("description", "")
        win = f"每{t.get('target_minute', '?')}分" if t.get("hourly") else t.get("target_time", "?")
        st = task_status(t, now, executed)
        mark = {"已执行": "[x]", "非今日": " - ", "非交易日": " - "}.get(st, "[ ]")
        print(f"  {mark} {tid:24s} {win:8s} {st:16s} {desc}")

    logs_dir = REPO_ROOT / ".dsh" / "logs"
    n_logs = 8
    if "--logs" in sys.argv:
        try:
            n_logs = int(sys.argv[sys.argv.index("--logs") + 1])
        except (ValueError, IndexError):
            pass
    if logs_dir.exists():
        logs = sorted(logs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:n_logs]
        print(f"\n[最近 {len(logs)} 条派发日志 (.dsh/logs/)]")
        for p in logs:
            kb = round(p.stat().st_size / 1024, 1)
            print(f"  {p.name}  ({kb} KB, {datetime.fromtimestamp(p.stat().st_mtime):%m-%d %H:%M})")
    else:
        print("\n[派发日志] 无 (.dsh/logs/ 不存在，尚未派发过任务)")

    print("\n[提示] 计划任务运行结果（LastRunTime/LastTaskResult）在 PowerShell 查看：")
    print("  Get-ScheduledTask -TaskName 'dsh-trigger-*' | Get-ScheduledTaskInfo |")
    print("    Select TaskName, LastRunTime, LastTaskResult | Sort LastRunTime -Descending")
    return 0


if __name__ == "__main__":
    sys.exit(main())
