"""每日复盘任务独立触发入口 — 供系统级定时任务（cron / launchd / 计划任务 / 容器 cron）调用.

用法（任意环境，cwd = etf-strategies）:
    python -m dashboard.scheduler_cli --task morning_analysis            # 正常触发
    python -m dashboard.scheduler_cli --task evening_review --force      # 跳过 星期/交易日/幂等 判定
    python -m dashboard.scheduler_cli --task morning_analysis --dry-run  # 只判定不执行

与 dashboard 引擎的关系:
- 本入口**同步执行**（进程内等待 dsh/claude 完成），退出码 = 任务成败（cron 可感知）
- 幂等/交易日判定与引擎一致（scheduler_runs.window_key + trading_calendar）
- 触发类型记 'cron'：window_key 与引擎 auto 相同 → 外部 cron 与 dashboard 引擎互斥防双跑
- 执行引擎与 dashboard 一致（dsh 主 / claude 辅，DASHBOARD_SCHEDULER_ENGINE 可切换）

典型配置:
    # Linux crontab（交易日 09:07 早盘；crontab 无星期-交易日混合，用脚本内判定）
    7 9 * * 1-5  cd /path/to/astock-anayisis/etf-strategies && python -m dashboard.scheduler_cli --task morning_analysis
    # macOS launchd：plist 内 ProgramArguments 同上
    # Windows 计划任务：程序 = python，参数 = -m dashboard.scheduler_cli --task evening_review
    # Docker 容器：容器内 cron（见 DEPLOY.md）或保持 dashboard 引擎轮询（零 token）
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

_ETF_DIR = Path(__file__).resolve().parent.parent
if str(_ETF_DIR) not in sys.path:
    sys.path.insert(0, str(_ETF_DIR))

from dashboard import db, scheduler  # noqa: E402


def decide(task: dict, force: bool, now: datetime | None = None) -> tuple[bool, str, str | None]:
    """触发判定：返回 (should_run, reason, window_key)。

    force=True 跳过 星期/交易日/幂等；否则与引擎语义一致。
    """
    now = now or datetime.now()
    if not force:
        if task.get("days_of_week") is not None and now.weekday() not in task["days_of_week"]:
            return False, f"非计划星期（weekday={now.weekday()}）", None
        if task.get("trading_day_required", False) and not scheduler.is_trading_day(now.date()):
            return False, f"非交易日（{now.date()}）", None
        wkey = scheduler.make_window_key(task, now)
        if db.scheduler_window_done(task["task_id"], wkey):
            return False, f"今日已执行（window_key={wkey}）", wkey
        return True, "", wkey
    wkey = f"manual:{task['task_id']}:{now.strftime('%Y%m%d-%H%M%S%f')}"
    return True, "", wkey


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="dashboard.scheduler_cli",
        description="每日复盘任务独立触发入口（cron/launchd/计划任务/容器 cron）",
    )
    ap.add_argument("--task", required=True, help="task_id，如 morning_analysis / evening_review")
    ap.add_argument("--force", action="store_true", help="跳过 星期/交易日/幂等 判定（调试用）")
    ap.add_argument("--dry-run", action="store_true", help="只判定不执行")
    args = ap.parse_args(argv)

    task = next((t for t in scheduler.scoped_tasks() if t["task_id"] == args.task), None)
    if task is None:
        print(json.dumps({"error": f"未找到任务 {args.task}（或不在本调度器范围）"},
                         ensure_ascii=False))
        return 1

    should_run, reason, wkey = decide(task, args.force)
    if not should_run:
        print(json.dumps({"skip": args.task, "reason": reason}, ensure_ascii=False))
        return 0

    if args.dry_run:
        print(json.dumps({"would_run": args.task, "prompt_file": task["prompt_file"],
                          "window_key": wkey}, ensure_ascii=False))
        return 0

    run = scheduler.run_task_sync(task, trigger="cron")
    status = run.get("status", "unknown")
    print(json.dumps({
        "run_id": run.get("id"),
        "task_id": args.task,
        "status": status,
        "duration_sec": run.get("duration_sec"),
        "trigger": run.get("trigger"),
        "window_key": run.get("window_key"),
    }, ensure_ascii=False))
    return 0 if status == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
