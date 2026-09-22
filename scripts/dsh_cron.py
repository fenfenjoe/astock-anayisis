#!/usr/bin/env python3
"""DSH 定时任务 cron 表生成器 — 从 task_schedule.json 实时生成，方便随时查看。

用法:
    python .claude/scripts/dsh_cron.py            # 终端打印 markdown 表格
    python .claude/scripts/dsh_cron.py --save     # 同时写入 docs/定时任务cron表.md

cron 格式: 分 时 日 月 周（周: 0/7=周日, 1=周一 … 6=周六）
注: A股节假日由调度器交易日历自动跳过，cron 的周几只表达"计划星期"。
"""

import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
SCHEDULE = REPO_ROOT / ".claude" / "scripts" / "task_schedule.json"
OUT_FILE = REPO_ROOT / "docs" / "定时任务cron表.md"

DOW_CN = {0: "周一", 1: "周二", 2: "周三", 3: "周四", 4: "周五", 5: "周六", 6: "周日"}


def dow_to_cron(days: list | None) -> str:
    """task_schedule.json 的 days_of_week(0=周一..6=周日) → cron 周字段(0/7=周日,1=周一..6=周六)。"""
    if days is None:
        return "*"
    nums = sorted(set(days))
    if nums == list(range(7)):
        return "*"
    cron_days = [str((d + 1) % 7) for d in nums]  # 周一0→1 … 周六5→6, 周日6→0
    return ",".join(cron_days)


def dow_desc(days: list | None) -> str:
    if days is None:
        return "每天"
    if days == list(range(7)):
        return "每天"
    return "、".join(DOW_CN[d] for d in sorted(days))


def to_cron(task: dict) -> str:
    dow = dow_to_cron(task.get("days_of_week"))
    if task.get("hourly"):
        minute = task["target_minute"]
        hrs = sorted(task.get("hourly_range", []))
        if hrs == list(range(hrs[0], hrs[-1] + 1)):
            hour_str = f"{hrs[0]}-{hrs[-1]}"
        else:
            hour_str = ",".join(map(str, hrs))
        return f"{minute:02d} {hour_str} * * {dow}"
    hh, mm = task["target_time"].split(":")
    return f"{mm} {hh} * * {dow}"


def meaning(task: dict) -> str:
    dow = dow_desc(task.get("days_of_week"))
    if task.get("hourly"):
        minute = task["target_minute"]
        hrs = sorted(task.get("hourly_range", []))
        if hrs == list(range(hrs[0], hrs[-1] + 1)):
            when = f"{hrs[0]}-{hrs[-1]} 点每小时 :{minute:02d}"
        else:
            when = "、".join(f"{h}:{minute:02d}" for h in hrs)
        return f"{dow} {when}"
    return f"{dow} {task['target_time']}"


def main() -> int:
    save = "--save" in sys.argv
    with open(SCHEDULE, "r", encoding="utf-8") as f:
        sched = json.load(f)

    rows = []
    for t in sched["tasks"]:
        rows.append({
            "cron": to_cron(t),
            "task": t["task_id"],
            "meaning": meaning(t),
            "trading": "交易日" if t.get("trading_day_required", False) else "",
            "desc": t.get("description", ""),
        })
    rows.sort(key=lambda r: (r["cron"].split()[1], r["cron"].split()[0]))

    gen = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# DSH 定时任务 cron 表",
        "",
        f"> 由 `.claude/scripts/dsh_cron.py` 从 `task_schedule.json` 生成 · {gen}",
        "",
        "cron 格式：`分 时 日 月 周`（周：0/7=周日，1=周一 … 6=周六）",
        "",
        "| cron | task_id | 执行时间 | 交易日 | 说明 |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| `{r['cron']}` | {r['task']} | {r['meaning']} | {r['trading']} | {r['desc']} |")
    lines += [
        "",
        "> [!] 说明：A股节假日由 `dsh_trigger.py` 交易日历自动跳过（cron 周几只表达计划星期）；",
        "> 电脑睡眠错过会唤醒后 ±3h 内补跑，关机错过则当天跳过。",
    ]
    text = "\n".join(lines)

    print(text)
    if save:
        OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
        OUT_FILE.write_text(text, encoding="utf-8")
        print(f"\n已保存: {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
