"""每日复盘调度器 — 线程引擎 + claude 运行器 + 报告/持仓/交易导入器.

范围规则：只接管 prompt_file 以 "my_doc/每日复盘/" 开头的任务
（morning_analysis / intraday_×8 / evening_review / weekly_portfolio /
experience_health / logic_inspect / pending_remind / req_implement /
harness_bug_auto_fix）。etf-strategies/automation/ 的任务继续归 /loop 驱动。

架构：
- 引擎 = threading.Thread(daemon=True)，每 20s tick 一次
- auto 触发：时间窗口 + 交易日门控 + window_key 幂等（语义复用 task_scheduler.py）
- manual 触发：POST /api/scheduler/run/{task_id}，绕过时间/交易日门控，
  window_key 用 manual:{task_id}:{iso}，永不与 auto 冲突
- claude 运行器：subprocess.run(["claude","-p","--output-format","text"], stdin=prompt)
  无论退出码都跑导入器（agent 可能部分完成也写了文件）
- SCHEDULER_ENABLED：默认 auto 关闭、只允许手动触发（过渡期防与 /loop 双跑）
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import date, datetime, time, timedelta
from pathlib import Path

# ── sys.path：让本模块可独立运行（app.py 已插入 etf-strategies 到 sys.path）──
_ETF_DIR = Path(__file__).resolve().parent.parent
if str(_ETF_DIR) not in sys.path:
    sys.path.insert(0, str(_ETF_DIR))

# 仓库根：默认向上三级推导（本地），Docker 里用 DASHBOARD_REPO_ROOT 指向挂载点。
# 调度器读 prompt / 交易日历 / 持仓，claude 子进程也以 REPO_ROOT 为工作目录读写报告。
_env_repo_root = os.environ.get("DASHBOARD_REPO_ROOT")
REPO_ROOT = (Path(_env_repo_root).resolve() if _env_repo_root
             else Path(__file__).resolve().parent.parent.parent)
SCHEDULE_PATH = REPO_ROOT / ".claude" / "scripts" / "task_schedule.json"
REPORTS_DIR = REPO_ROOT / "my_doc" / "每日复盘" / "reports"
HOLDINGS_MD = REPO_ROOT / "my_doc" / "每日复盘" / "harness" / "config" / "持仓.md"
TRADES_MD = REPO_ROOT / "my_doc" / "每日复盘" / "每日调仓.md"
TRADING_CALENDAR_PATH = (
    REPO_ROOT / "my_doc" / "每日复盘" / "harness" / "automation" / "config" / "trading_calendar.py"
)

TICK_SECONDS = 20
CLAUDE_TIMEOUT_SECONDS = 3600          # claude -p 最长 1 小时
OUTPUT_TAIL_CHARS = 8000               # scheduler_runs.output 只存尾部
AUTO_PREFIX = "my_doc/每日复盘/"        # 本调度器接管范围前缀


# ───────────────────────────────────────────────────────────────────
# 交易日历（复用现有 trading_calendar.py，不污染 sys.path）
# ───────────────────────────────────────────────────────────────────

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
        spec = importlib.util.spec_from_file_location("_trading_calendar_loaded",
                                                      TRADING_CALENDAR_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore
        _trading_cal = module
    return _trading_cal


def is_trading_day(check_date: date | None = None) -> bool:
    try:
        return _trading_calendar_module().is_trading_day(check_date)
    except Exception:
        # 日历不可用时 fail-open（与 task_scheduler.py 一致）
        return True


def next_trading_day(from_date: date | None = None) -> date | None:
    """下一个交易日；日历不可用返回 None。"""
    try:
        return _trading_calendar_module().next_trading_day(from_date)
    except Exception:
        return None


# ───────────────────────────────────────────────────────────────────
# 调度定义与窗口语义（照抄 task_scheduler.py）
# ───────────────────────────────────────────────────────────────────

def load_schedule() -> list[dict]:
    """读 task_schedule.json 的 tasks 列表；失败返回空列表。"""
    try:
        with open(SCHEDULE_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("tasks", [])
    except (OSError, json.JSONDecodeError):
        return []


def in_scope(task: dict) -> bool:
    """本调度器只接管 每日复盘 的 prompt_file（其余归 /loop）。"""
    pf = task.get("prompt_file", "")
    return pf.startswith(AUTO_PREFIX)


def scoped_tasks() -> list[dict]:
    return [t for t in load_schedule() if in_scope(t)]


def time_in_window(current: time, target: time, window_minutes: int) -> bool:
    today = date.today()
    start = datetime.combine(today, target)
    end = start + timedelta(minutes=window_minutes)
    now = datetime.combine(today, current)
    return start <= now < end


def make_window_key(task: dict, now: datetime) -> str:
    if task.get("hourly"):
        return f"{task['task_id']}:{now.date().isoformat()}:{now.hour:02d}"
    return f"{task['task_id']}:{now.date().isoformat()}"


def task_due_now(task: dict, now: datetime) -> bool:
    """判断 *task* 是否到了该触发的时间窗口（不含幂等/交易日门控）。"""
    if task.get("days_of_week") is not None and now.weekday() not in task["days_of_week"]:
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


# ───────────────────────────────────────────────────────────────────
# 导入器：磁盘 → DB（幂等 upsert / replace）
# ───────────────────────────────────────────────────────────────────

def import_reports_from_disk() -> dict:
    """扫描 reports/ 全部日期目录与 weekly/，把 *.md 导入 daily_reports。

    report_type 取自文件名（复盘报告/早盘报告/早盘机会/每日信号/周报）。
    幂等：report_upsert 按 (report_date, report_type) 覆盖。
    """
    from dashboard import db

    if not REPORTS_DIR.exists():
        return {"imported": 0, "error": "reports 目录不存在"}
    imported = 0
    for sub in sorted(REPORTS_DIR.iterdir()):
        if not sub.is_dir():
            continue
        if sub.name == "weekly":
            for f in sorted(sub.glob("*.md")):
                report_date = _weekly_date(f.name)
                report_type = _report_type_from_name(f.name, fallback="周报")
                if report_date and report_type:
                    db.report_upsert(report_date, report_type,
                                     f.read_text(encoding="utf-8"), source_file=str(f))
                    imported += 1
            continue
        if not sub.name.isdigit() or len(sub.name) != 8:
            continue
        for f in sorted(sub.glob("*.md")):
            report_type = _report_type_from_name(f.name)
            if report_type:
                db.report_upsert(sub.name, report_type,
                                 f.read_text(encoding="utf-8"), source_file=str(f))
                imported += 1
    return {"imported": imported, "scanned": len(list(REPORTS_DIR.glob("*/")))}


def _report_type_from_name(filename: str, fallback: str = "") -> str | None:
    stem = Path(filename).stem
    for known in ("复盘报告", "早盘报告", "早盘机会", "每日信号", "周报"):
        if known in stem:
            return known
    return fallback or None


def _weekly_date(filename: str) -> str | None:
    """weekly/2026-07-23_周报.md → 20260723；否则返回 None。"""
    import re
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", filename)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    return None


def import_holdings_from_md() -> bool:
    """从 持仓.md 反向解析持仓 → portfolio_holdings（mtime 守卫）。

    仅当 DB 为空 或 文件 mtime 变化时执行，避免覆盖用户页面上的修改。
    """
    from dashboard import db, portfolio

    rows = portfolio.read_holdings_md()
    if rows is None:
        return False
    mtime = portfolio.holdings_md_mtime()
    stored_mtime = db.meta_get("holdings_md_mtime")
    if db.portfolio_holdings_count() > 0 and stored_mtime is not None:
        try:
            if float(stored_mtime) == float(mtime):
                return False  # 未变化，跳过
        except (TypeError, ValueError):
            pass
    db.portfolio_holdings_replace(rows)
    if mtime is not None:
        db.meta_set("holdings_md_mtime", str(mtime))
    return True


def import_trades_from_md() -> bool:
    from dashboard import db, portfolio

    trades = portfolio.read_trades_md()
    if trades is None:
        return False
    db.portfolio_trades_replace_all(trades)
    return True


# ───────────────────────────────────────────────────────────────────
# claude 运行器
# ───────────────────────────────────────────────────────────────────

def _prompt_text(task: dict, now: datetime) -> str:
    """读 prompt_file（相对 REPO_ROOT），替换 {today}→YYYYMMDD。"""
    pf = Path(REPO_ROOT) / task["prompt_file"]
    try:
        text = pf.read_text(encoding="utf-8")
    except OSError as e:
        raise FileNotFoundError(f"prompt_file 缺失: {task['prompt_file']} ({e})")
    return text.replace("{today}", now.strftime("%Y%m%d"))


def _run_prompt(task: dict, run_id: int) -> None:
    """后台线程执行体：claude -p 跑 prompt，结束后导入产物。

    任何情况下（成功/失败/超时）都执行导入器，把 agent 写出的报告收进 DB。
    """
    from dashboard import db

    started = datetime.now()
    claude_bin = shutil.which("claude")
    if not claude_bin:
        db.scheduler_run_update(
            run_id, status="failed", duration_sec=0,
            output="未找到 claude 可执行文件。请先安装 Claude Code（claude login 登录）后重试。",
            completed_at=datetime.now().isoformat(),
        )
        return

    try:
        prompt = _prompt_text(task, started)
    except FileNotFoundError as e:
        db.scheduler_run_update(run_id, status="failed", duration_sec=0,
                                output=str(e), completed_at=datetime.now().isoformat())
        return

    # 输出重定向到临时文件而非管道：claude -p 会派生子会话进程继承管道写端，
    # 在 Windows 上 subprocess.run(capture_output=True) 会因等不到管道 EOF 挂死
    # （父进程已退出但孙进程仍持有管道句柄）。文件重定向则按进程退出即返回，不阻塞。
    out_path = err_path = None
    try:
        fd_out, out_path = tempfile.mkstemp(prefix="claude_run_out_", suffix=".txt")
        fd_err, err_path = tempfile.mkstemp(prefix="claude_run_err_", suffix=".txt")
        try:
            with os.fdopen(fd_out, "w", encoding="utf-8") as fo, \
                    os.fdopen(fd_err, "w", encoding="utf-8") as fe:
                # 非交互 -p 默认自动拒绝需要授权的工具（Write/Bash）。早盘/盘中/
                # 复盘 prompt 依赖 Bash 跑 python 取数（a-stock-data）+ Write 写报告，
                # 必须放行全部权限才能完整跑通。本调度器只跑仓库内受控 prompt，
                # 且用户已于 2026-08-14 明确确认 --dangerously-skip-permissions。
                proc = subprocess.run(
                    [claude_bin, "-p", "--output-format", "text",
                     "--dangerously-skip-permissions"],
                    input=prompt, cwd=str(REPO_ROOT),
                    stdout=fo, stderr=fe, text=True, encoding="utf-8",
                    timeout=CLAUDE_TIMEOUT_SECONDS,
                )
            status = "success" if proc.returncode == 0 else "failed"
            try:
                out = Path(out_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                out = ""
            try:
                err = Path(err_path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                err = ""
            if err and err.strip():
                out = (out + "\n\n[stderr]\n" + err).strip()
        except subprocess.TimeoutExpired:
            status = "timeout"
            out = f"claude -p 超时（>{CLAUDE_TIMEOUT_SECONDS}s），已终止。"
        except Exception as e:
            status = "failed"
            out = f"运行异常: {e}"
    finally:
        for p in (out_path, err_path):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass

    # 无论结果如何，收走 agent 可能已写出的报告/持仓；任一步失败都如实记录，
    # 绝不把运行行留在 running 状态
    try:
        import_reports_from_disk()
        import_holdings_from_md()
    except Exception as e:
        print(f"[scheduler] run#{run_id} importers failed: {e}", file=sys.stderr)

    elapsed = round((datetime.now() - started).total_seconds(), 1)
    try:
        db.scheduler_run_update(
            run_id, status=status, duration_sec=elapsed,
            output=(out or "")[-OUTPUT_TAIL_CHARS:],
            completed_at=datetime.now().isoformat(),
        )
    except Exception as e:
        print(f"[scheduler] run#{run_id} DB update failed: {e}", file=sys.stderr)

    print(f"[scheduler] run#{run_id} {task.get('task_id')} → {status} ({elapsed}s)",
          file=sys.stderr)


# ───────────────────────────────────────────────────────────────────
# 运行入口（auto / manual 共用）
# ───────────────────────────────────────────────────────────────────

_running_tasks: dict[str, bool] = {}
_running_lock = threading.Lock()


def _is_running(task_id: str) -> bool:
    with _running_lock:
        return _running_tasks.get(task_id, False)


def _set_running(task_id: str, running: bool):
    with _running_lock:
        _running_tasks[task_id] = running


def run_task(task: dict, trigger: str = "manual", now: datetime | None = None) -> dict:
    """触发一次任务。auto 传 trigger='auto'。

    返回 {started: bool, run_id, reason}。同任务并发中 → started=False + reason='busy'。
    """
    from dashboard import db

    task_id = task["task_id"]
    if _is_running(task_id):
        return {"started": False, "run_id": None, "reason": "busy", "message": "该任务正在运行中"}

    now = now or datetime.now()
    if trigger == "auto":
        window_key = make_window_key(task, now)
        if db.scheduler_window_done(task_id, window_key):
            return {"started": False, "run_id": None, "reason": "idempotent",
                    "message": "该时间窗已执行过"}
    else:
        window_key = f"manual:{task_id}:{now.strftime('%Y%m%d-%H%M%S%f')}"

    run_id = db.scheduler_run_insert(task_id, window_key, trigger,
                                     now.strftime("%Y-%m-%d %H:%M:%S"))
    _set_running(task_id, True)

    def _worker(tid: str = task_id):
        try:
            _run_prompt(task, run_id)
        finally:
            _set_running(tid, False)

    threading.Thread(target=_worker, daemon=True).start()
    return {"started": True, "run_id": run_id, "reason": "ok", "message": "任务已启动"}


def run_task_by_id(task_id: str, trigger: str = "manual") -> dict:
    """按 task_id 触发（API 用）。找不到任务或超出本调度器范围 → 拒绝。"""
    task = next((t for t in scoped_tasks() if t["task_id"] == task_id), None)
    if task is None:
        return {"started": False, "reason": "unknown",
                "message": f"未找到每日复盘任务 {task_id}（或不在本调度器范围）"}
    return run_task(task, trigger=trigger)


# ───────────────────────────────────────────────────────────────────
# 引擎：daemon 线程每 TICK_SECONDS tick 一次
# ───────────────────────────────────────────────────────────────────

class SchedulerEngine:
    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.last_tick: str | None = None
        self.last_error: str | None = None
        self.auto_enabled_meta_default = False

    # ── 开关 ──
    def auto_enabled(self) -> bool:
        """auto 调度是否开启。meta 优先，其次环境变量，默认关闭（过渡期防双跑）。"""
        from dashboard import db
        meta = db.meta_get("scheduler_auto_enabled")
        if meta is not None:
            return meta in ("1", "true", "True")
        env = __import__("os").environ.get("DASHBOARD_SCHEDULER_ENABLED", "").lower()
        return env in ("1", "true", "yes", "on")

    def set_auto_enabled(self, enabled: bool):
        from dashboard import db
        db.meta_set("scheduler_auto_enabled", "1" if enabled else "0")

    # ── 生命周期 ──
    def start(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name="scheduler-engine")
            self._thread.start()
            print(f"[scheduler] engine started (auto={self.auto_enabled()})")

    def stop(self):
        self._stop.set()

    def status(self) -> dict:
        return {
            "running": self._thread is not None and self._thread.is_alive(),
            "auto_enabled": self.auto_enabled(),
            "last_tick": self.last_tick,
            "last_error": self.last_error,
            "tick_seconds": TICK_SECONDS,
        }

    # ── 主循环 ──
    def _loop(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                self.last_error = str(e)
            self._stop.wait(TICK_SECONDS)

    def _tick(self):
        from dashboard import db

        now = datetime.now()
        self.last_tick = now.strftime("%Y-%m-%d %H:%M:%S")
        if not self.auto_enabled():
            return  # 过渡期：auto 关闭，仅手动触发

        for t in scoped_tasks():
            if t.get("trading_day_required", False) and not is_trading_day(now.date()):
                continue
            if not task_due_now(t, now):
                continue
            wkey = make_window_key(t, now)
            if db.scheduler_window_done(t["task_id"], wkey):
                continue  # 该时间窗已成功/超时执行过（幂等）
            result = run_task(t, trigger="auto", now=now)
            if result.get("started"):
                print(f"[scheduler] auto dispatch {t['task_id']} → run#{result['run_id']}")


engine = SchedulerEngine()


def start() -> None:
    """lifespan 调用：启动引擎（幂等）。"""
    engine.start()
