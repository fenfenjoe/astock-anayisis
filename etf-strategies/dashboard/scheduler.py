"""每日复盘 + ETF 自动化调度器 — 线程引擎 + 双引擎运行器（dsh/claude）+ 报告/持仓/交易导入器.

范围规则：接管 prompt_file 以 "my_doc/每日复盘/" 或 "etf-strategies/automation/" 开头的任务
（每日复盘 16 个 + ETF 自动化 5 个：bug_auto_fix / bug_inspect_data / bug_inspect_code /
bug_inspect_logic / strategy_scan_weekly，2026-08-27 用户决策全部随 Web 启停）。

架构：
- 引擎 = threading.Thread(daemon=True)，每 20s tick 一次；随 Web 进程启动/停止
  （app.py lifespan start/stop；Docker 即随容器生命周期），零 token 轮询
- auto 触发：时间窗口 + 交易日门控 + window_key 幂等（语义复用 task_scheduler.py）
- manual 触发：POST /api/scheduler/run/{task_id}，绕过时间/交易日门控，
  window_key 用 manual:{task_id}:{iso}，永不与 auto 冲突
- 双引擎运行器：dsh headless（主，本地）/ claude -p（辅，Docker/兜底），
  见 DASHBOARD_SCHEDULER_ENGINE 与 resolve_engine()
- 无论退出码都跑导入器（agent 可能部分完成也写了文件）
"""
import hashlib
import json

# 云端存储（严格零本地报告源；未配置云置 None → 降级本地扫描）
try:
    from cloud_store import (get_text as _cs_get, put_text as _cs_put,
                             list_objects as _cs_list)
except ImportError:
    _cs_get = _cs_put = _cs_list = None
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
CLAUDE_TIMEOUT_SECONDS = 3600          # dsh/claude 最长 1 小时
OUTPUT_TAIL_CHARS = 8000               # scheduler_runs.output 只存尾部
# 引擎接管范围：每日复盘 + ETF 自动化（2026-08-27 用户决策：全部随 Web 启停）
SCOPE_PREFIXES = ("my_doc/每日复盘/", "etf-strategies/automation/")
REPORT_RESCAN_SECONDS = 60             # 报告增量重扫间隔（mtime 守卫，开销≈0）
# 同一时间窗内 auto 失败重试上限（2026-08-31 重试风暴修复）：
# 失败任务不在 scheduler_window_done 的完成状态（success/timeout）里，
# 引擎每 20s tick 会在窗口内无限重试 → 7 分钟窗口可触发 20+ 次。
# 达到上限后该窗口视为"已消耗"，不再自动重试（手动触发不受限）。
MAX_AUTO_FAILURES_PER_WINDOW = 2

# ── DeepSeek API 429 限流退避（2026-09-02 事故修复）──
# 事故：morning_analysis 手动补跑时，dsh agent 在取数阶段撞上 429
# （AccountRateLimitExceeded）直接失败（run#195），或陷入无限重试循环
# （run#198 重复同一动作 996s）。修复两层：
#   1) _exec_dsh 检测 429 特征 → 指数退避重试（有上限），降低瞬时限流直接失败；
#   2) 全局信号量限制同时运行的 dsh 进程数 → 避免多任务并发打爆 API。
RATE_LIMIT_MARKERS = (
    "rate_limit",                # dsh: RATE_LIMIT: 429 {...}
    "rate limit",                # 空格变体
    "accountratelimitexceeded",  # code 字段
    "requests are too frequent", # message
    "reduce your request frequency",
)
RATE_LIMIT_RETRY_BACKOFF_BASE_SECONDS = 30   # 30s → 60s → 120s（指数）
MAX_RATE_LIMIT_RETRIES = 3                   # 最多重试 3 次（共 4 次尝试）
DSH_MAX_CONCURRENT = 2                       # 同时最多运行 2 个 dsh 进程
DSH_SEM_ACQUIRE_TIMEOUT = 30                 # 信号量获取超时（s），超时放弃本次运行

# dsh 执行并发信号量（全局，跨任务共享）
_dsh_sem = threading.BoundedSemaphore(DSH_MAX_CONCURRENT)

# 调度窗口容差（分钟）：None = 用 task_schedule.json 的 window_minutes（默认 7）。
# 迁移自 Windows 计划任务后，如遇夜间休眠恢复错过窗口，可设
# DASHBOARD_SCHEDULER_WINDOW_MINUTES=30 放宽（与 dsh_trigger ±3h 语义对齐）。
_env_window = os.environ.get("DASHBOARD_SCHEDULER_WINDOW_MINUTES")
WINDOW_TOLERANCE_MINUTES: int | None = int(_env_window) if _env_window else None


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
    """本调度器接管 每日复盘 + ETF 自动化 两类的 prompt_file（其余不接管）。"""
    pf = task.get("prompt_file", "")
    return pf.startswith(SCOPE_PREFIXES)


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
    window_minutes = WINDOW_TOLERANCE_MINUTES or task.get("window_minutes", 7)
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

def import_reports_from_disk(force: bool = False) -> dict:
    """导入复盘报告到 daily_reports。

    严格零本地：云模式从 TOS（daily-reports/ 前缀）拉取导入，指纹守卫；
    云未配置时降级扫描本地 reports/（mtime 守卫）。
    """
    from dashboard import db

    raw_state = db.meta_get("reports_scan_state")
    try:
        state = json.loads(raw_state) if raw_state else {}
    except (json.JSONDecodeError, TypeError):
        state = {}

    imported = 0
    scanned = 0
    changed: dict[str, float | str] = {}

    # ── 云源（TOS daily-reports/，内容指纹守卫）──
    cloud_keys = []
    if _cs_list is not None:
        try:
            cloud_keys = _cs_list("daily-reports/")
        except Exception:
            cloud_keys = []
    if cloud_keys:
        for key in sorted(cloud_keys):
            rel = key[len("daily-reports/"):]
            parts = rel.split("/")
            if len(parts) != 2 or not parts[1].endswith(".md"):
                continue
            date_part, fname = parts
            report_type = _report_type_from_name(fname)
            if not report_type:
                continue
            if date_part == "weekly":
                # 周报在 weekly/ 目录，日期从文件名解析（与本地分支 _weekly_date 一致）
                date_part = _weekly_date(fname) or ""
                if not date_part:
                    continue
            elif not (date_part.isdigit() and len(date_part) == 8):
                continue
            try:
                text = _cs_get(key)
            except Exception:
                continue
            if text is None:
                continue
            scanned += 1
            fp = f"tos:{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"
            if not force and state.get(f"tos:{rel}") == fp:
                continue
            db.report_upsert(date_part, report_type, text,
                             source_file=f"tos:{key}")
            imported += 1
            changed[f"tos:{rel}"] = fp
        if changed:
            state.update(changed)
            db.meta_set("reports_scan_state",
                        json.dumps(state, ensure_ascii=False))
        return {"imported": imported, "scanned": scanned, "source": "tos"}

    # ── 降级：本地扫描（mtime 守卫）──
    if not REPORTS_DIR.exists():
        return {"imported": 0, "error": "reports 目录不存在"}

    def _scan_file(f: Path, report_date: str, fallback_type: str = "") -> None:
        """单文件：mtime 未变则跳过；变化/新增则导入并记录。"""
        nonlocal imported, scanned
        scanned += 1
        rel = f.relative_to(REPORTS_DIR).as_posix()
        try:
            mtime = f.stat().st_mtime
        except OSError:
            return
        if not force and state.get(rel) == mtime:
            return
        report_type = _report_type_from_name(f.name, fallback=fallback_type)
        if report_date and report_type:
            db.report_upsert(report_date, report_type,
                             f.read_text(encoding="utf-8"), source_file=str(f))
            imported += 1
        changed[rel] = mtime

    for sub in sorted(REPORTS_DIR.iterdir()):
        if not sub.is_dir():
            continue
        if sub.name == "weekly":
            for f in sorted(sub.glob("*.md")):
                _scan_file(f, _weekly_date(f.name) or "", fallback_type="周报")
            continue
        if not sub.name.isdigit() or len(sub.name) != 8:
            continue
        for f in sorted(sub.glob("*.md")):
            _scan_file(f, sub.name)

    if changed:
        state.update(changed)
        db.meta_set("reports_scan_state", json.dumps(state, ensure_ascii=False))
    return {"imported": imported, "scanned": scanned, "source": "local"}

def _report_type_from_name(filename: str, fallback: str = "") -> str | None:
    stem = Path(filename).stem
    # 影子/中间产物不导入：降级执行（沙箱/权限故障）时 agent 无法原位写，
    # 生成 "每日信号-复盘填充版.md" 等影子文件——误匹配会覆盖正式报告。
    if "填充版" in stem or "影子" in stem:
        return None
    for known in ("复盘报告", "早盘报告", "早盘机会", "每日信号", "周报", "周度组合回顾"):
        if known in stem:
            return known
    return fallback or None


def upload_reports_to_cloud(force: bool = False) -> dict:
    """本地 reports/ 新报告 → TOS daily-reports/（mtime 守卫，幂等）。

    设计（2026-08-31 用户确认）：导入器保持"只扫云"不变（云上有对象就不扫
    本地）。因此定时任务产出后必须先把本地新报告上传云，云优先导入才能拉到。
    上传与 cloud_sync.py 的 SYNC_MAP 映射一致（reports/ → daily-reports/）：
      reports/20260831/早盘报告.md → daily-reports/20260831/早盘报告.md
      reports/weekly/xxx.md        → daily-reports/weekly/xxx.md
    影子文件（-填充版/-影子 后缀）不上传（与 _report_type_from_name 一致）。
    云未配置（_cs_put is None）→ 返回 0 上传不报错（降级，引擎重扫照常）。
    """
    from dashboard import db

    if _cs_put is None:
        return {"uploaded": 0, "scanned": 0, "source": "local_only"}

    raw_state = db.meta_get("reports_upload_state")
    try:
        state = json.loads(raw_state) if raw_state else {}
    except (json.JSONDecodeError, TypeError):
        state = {}

    if not REPORTS_DIR.exists():
        return {"uploaded": 0, "scanned": 0, "error": "reports 目录不存在"}

    uploaded = 0
    scanned = 0
    changed: dict[str, float] = {}

    def _upload_file(f: Path, key: str) -> None:
        """单文件：mtime 未变则跳过；变化/新增则上传并记录。失败不阻断整体。"""
        nonlocal uploaded, scanned
        scanned += 1
        try:
            mtime = f.stat().st_mtime
        except OSError:
            return
        if not force and state.get(key) == mtime:
            return
        try:
            _cs_put(key, f.read_text(encoding="utf-8"))
        except Exception:
            return  # 单文件失败跳过（下次重扫再试）
        uploaded += 1
        changed[key] = mtime

    for sub in sorted(REPORTS_DIR.iterdir()):
        if not sub.is_dir():
            continue
        if sub.name == "weekly":
            for f in sorted(sub.glob("*.md")):
                if _report_type_from_name(f.name) is None:
                    continue
                _upload_file(f, f"daily-reports/weekly/{f.name}")
            continue
        if not sub.name.isdigit() or len(sub.name) != 8:
            continue
        for f in sorted(sub.glob("*.md")):
            if _report_type_from_name(f.name) is None:
                continue
            _upload_file(f, f"daily-reports/{sub.name}/{f.name}")

    if changed:
        state.update(changed)
        db.meta_set("reports_upload_state", json.dumps(state, ensure_ascii=False))
    return {"uploaded": uploaded, "scanned": scanned, "source": "tos"}


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
    # 可用金额：文件 → DB（每日复盘建仓份额计算的数据源，随持仓一起同步）
    cash = portfolio.read_available_cash_md()
    if cash is not None:
        db.meta_set("available_cash", str(cash))
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
# 执行引擎：dsh headless（主）/ claude -p（辅），可切换
# ───────────────────────────────────────────────────────────────────

def _prompt_text(task: dict, now: datetime) -> str:
    """读 prompt_file（相对 REPO_ROOT），替换 {today}→YYYYMMDD。"""
    pf = Path(REPO_ROOT) / task["prompt_file"]
    try:
        text = pf.read_text(encoding="utf-8")
    except OSError as e:
        raise FileNotFoundError(f"prompt_file 缺失: {task['prompt_file']} ({e})")
    return text.replace("{today}", now.strftime("%Y%m%d"))


# 2026-08-27 迁移决策：以 dsh 执行为主（本地 DeepSeek Harness headless，
# 方舟 ARK token 已耗尽），claude -p 为辅（Docker 部署/兜底）。
# 切换方式（优先级：调用方 > DB meta > 环境变量 > auto 探测）：
#   DASHBOARD_SCHEDULER_ENGINE=auto|dsh|claude（默认 auto：
#     本地探测到 dsh CLI → dsh，否则 claude）
_env_engine = os.environ.get("DASHBOARD_SCHEDULER_ENGINE", "auto").strip().lower()
DEFAULT_ENGINE = _env_engine if _env_engine in ("dsh", "claude", "auto") else "auto"


def _find_dsh() -> tuple[Path, Path] | None:
    """定位 (node 可执行, dsh bin.js)；找不到返回 None。

    dsh 装在 node 的 node_modules 下：{node_dir}/node_modules/@deepseek-ai/dsh/lib/bin.js。
    候选：which node 同目录（系统全局）+ nvm 各版本目录（nvm/{ver}/...）。
    """
    candidates: list[tuple[Path, Path]] = []
    node = shutil.which("node")
    if node and Path(node).exists():
        node_p = Path(node)
        candidates.append((node_p, node_p.resolve().parent / "node_modules"
                           / "@deepseek-ai" / "dsh" / "lib" / "bin.js"))
    nvm_dir = Path.home() / "AppData" / "Roaming" / "nvm"
    if nvm_dir.exists():
        for bin_js in sorted(nvm_dir.glob("*/node_modules/@deepseek-ai/dsh/lib/bin.js")):
            ver_dir = bin_js.parents[4]  # .../nvm/{ver}/node_modules/... → {ver}
            node_exe = ver_dir / "node.exe"
            if node_exe.exists():
                candidates.append((node_exe, bin_js))
    for node_exe, bin_js in candidates:
        if node_exe.exists() and bin_js.exists():
            return (node_exe, bin_js)
    return None


def _engine_from_meta() -> str | None:
    """DB meta 覆盖（UI/API 可切换）；无 → None。"""
    try:
        from dashboard import db
        v = db.meta_get("scheduler_engine")
        if v and v.lower() in ("dsh", "claude"):
            return v.lower()
    except Exception:
        pass
    return None


def resolve_engine(preferred: str | None = None) -> str:
    """解析实际执行引擎：preferred > meta > env(DEFAULT_ENGINE) > auto 探测。"""
    for cand in (preferred, _engine_from_meta(), DEFAULT_ENGINE):
        if cand and cand.lower() in ("dsh", "claude"):
            return cand.lower()
    # auto：dsh 可用则 dsh，否则 claude
    return "dsh" if _find_dsh() is not None else "claude"


def _dsh_directive(task: dict) -> str:
    """构造传给 dsh headless 的短指令（与 dsh_loop_scheduler.build_directive 一致）。"""
    prompt_file = task["prompt_file"]
    if task.get("self_managed_complete"):
        suffix = ""
    else:
        suffix = (
            " 任务完成后（无论成功与否），运行："
            f"python .claude/scripts/task_scheduler.py --complete {task['task_id']}"
        )
    return f"执行 {prompt_file} 的全部内容。{suffix}"


def _exec_claude(task: dict, started: datetime) -> tuple[str, str]:
    """claude -p 执行 prompt → (status, output)。"""
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return "failed", "未找到 claude 可执行文件。请安装 Claude Code 或设置 DASHBOARD_SCHEDULER_ENGINE=dsh。"
    try:
        prompt = _prompt_text(task, started)
    except FileNotFoundError as e:
        return "failed", str(e)

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
        except subprocess.TimeoutExpired:
            status = "timeout"
            return status, f"claude -p 超时（>{CLAUDE_TIMEOUT_SECONDS}s），已终止。"
        except Exception as e:
            status = "failed"
            return status, f"运行异常: {e}"
        return status, _read_run_output(out_path, err_path)
    finally:
        for p in (out_path, err_path):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def _is_rate_limited(text: str | None) -> bool:
    """判断输出是否命中 DeepSeek API 429 限流特征。

    用特征子串（小写）而非裸状态码，避免正常输出里的数字"429"误判。
    """
    if not text:
        return False
    low = text.lower()
    return any(m in low for m in RATE_LIMIT_MARKERS)


def _run_dsh_once(cmd: list[str]) -> tuple[str, str]:
    """执行一次 dsh headless（不重试）→ (status, output)。

    Windows 隐藏控制台防弹窗 + 文件重定向防管道 EOF 挂死（与 claude 侧同理）。
    """
    out_path = err_path = None
    try:
        fd_out, out_path = tempfile.mkstemp(prefix="dsh_run_out_", suffix=".txt")
        fd_err, err_path = tempfile.mkstemp(prefix="dsh_run_err_", suffix=".txt")
        try:
            with os.fdopen(fd_out, "w", encoding="utf-8") as fo, \
                    os.fdopen(fd_err, "w", encoding="utf-8") as fe:
                flags = 0
                startupinfo = None
                if os.name == "nt":
                    # 隐藏控制台（非禁用）：后代取数子进程继承隐藏控制台 → 全程静默
                    flags = subprocess.CREATE_NEW_PROCESS_GROUP
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = subprocess.SW_HIDE
                proc = subprocess.run(
                    cmd, cwd=str(REPO_ROOT), stdin=subprocess.DEVNULL,
                    stdout=fo, stderr=fe, text=True, encoding="utf-8",
                    timeout=CLAUDE_TIMEOUT_SECONDS,
                    creationflags=flags, startupinfo=startupinfo,
                )
            status = "success" if proc.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            return "timeout", f"dsh headless 超时（>{CLAUDE_TIMEOUT_SECONDS}s），已终止。"
        except Exception as e:
            return "failed", f"运行异常: {e}"
        return status, _read_run_output(out_path, err_path)
    finally:
        for p in (out_path, err_path):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def _exec_dsh(task: dict) -> tuple[str, str]:
    """dsh headless 执行 prompt → (status, output)。

    与 dsh_loop_scheduler.dispatch 同构：node dsh bin.js --profile headless
    {directive}，cwd=REPO_ROOT，独立进程。dashboard 侧**等待完成**（非派发即返），
    便于记录 running→success/failed 并导入产物。

    2026-09-02 修复（429 限流）：
    - 全局信号量限制同时运行的 dsh 进程数（错峰，防多任务并发打爆 API）；
    - 命中 429 特征时指数退避重试（有上限），瞬时限流不再直接判死。
    """
    found = _find_dsh()
    if found is None:
        return "failed", ("未找到 dsh CLI（node + @deepseek-ai/dsh/lib/bin.js）。"
                          "请安装 DSH，或设置 DASHBOARD_SCHEDULER_ENGINE=claude 用兜底引擎。")
    node_exe, dsh_bin = found
    directive = _dsh_directive(task)
    cmd = [str(node_exe), str(dsh_bin), "--profile", "headless", directive]

    # 错峰：并发满时等待，超时放弃（快速失败，不无限排队）
    if not _dsh_sem.acquire(timeout=DSH_SEM_ACQUIRE_TIMEOUT):
        return "failed", (
            f"dsh 并发已满（>{DSH_MAX_CONCURRENT} 个运行中），"
            f"等待 {DSH_SEM_ACQUIRE_TIMEOUT}s 后仍无空闲，已放弃本次运行。"
        )
    try:
        attempts = MAX_RATE_LIMIT_RETRIES + 1  # 首次 + 最多 N 次重试
        last_status = "failed"
        last_out = ""
        for attempt in range(1, attempts + 1):
            last_status, last_out = _run_dsh_once(cmd)
            if last_status == "success" or not _is_rate_limited(last_out):
                return last_status, last_out
            if attempt >= attempts:
                break  # 重试耗尽
            backoff = RATE_LIMIT_RETRY_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            print(f"[scheduler] dsh 429 限流，{backoff}s 后退避重试 "
                  f"（{attempt}/{MAX_RATE_LIMIT_RETRIES}）", file=sys.stderr)
            threading.Event().wait(backoff)
        return last_status, last_out
    finally:
        _dsh_sem.release()


def _read_run_output(out_path: str | None, err_path: str | None) -> str:
    """读回执行输出（stdout + stderr 合并）。"""
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


def _run_prompt(task: dict, run_id: int) -> None:
    """后台线程执行体：按当前引擎（dsh/claude）跑 prompt，结束后导入产物。

    任何情况下（成功/失败/超时）都执行导入器，把 agent 写出的报告收进 DB，
    绝不把运行行留在 running 状态。
    """
    from dashboard import db

    started = datetime.now()
    # 2026-08-31 修复：TOS 模式下复盘/早盘/盘中/周报 prompt 读取本地 每日调仓.md/持仓.md，
    # 运行前先把云端权威副本拉回本地，避免复盘读到过期持仓/调仓（dashboard 录入只写云端）。
    try:
        from dashboard import portfolio
        pulled = portfolio.pull_holdings_to_local()
        if pulled.get("pulled"):
            print(f"[scheduler] run#{run_id} cloud→local holdings synced: {pulled['pulled']}")
    except Exception as e:
        print(f"[scheduler] run#{run_id} cloud→local holdings sync failed: {e}", file=sys.stderr)

    engine = resolve_engine()
    if engine == "dsh":
        status, out = _exec_dsh(task)
    else:
        status, out = _exec_claude(task, started)

    # 无论结果如何，收走 agent 可能已写出的报告/持仓
    try:
        # 先上传本地新报告到云（保持"导入只扫云"设计），再云优先导入
        upload_reports_to_cloud()
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

    print(f"[scheduler] run#{run_id} {task.get('task_id')} → {status} "
          f"({elapsed}s, engine={engine})", file=sys.stderr)


# ───────────────────────────────────────────────────────────────────
# 运行入口（auto / manual 共用）
# ───────────────────────────────────────────────────────────────────

_running_tasks: dict[str, dict] = {}   # task_id -> {"name", "started_at"}
_running_lock = threading.Lock()


def _is_running(task_id: str) -> bool:
    with _running_lock:
        return task_id in _running_tasks


def _mark_running(task_id: str, name: str, started_at: str):
    """记录运行中状态（供「正在做XXX」展示）。含 task_id（桌宠按任务类型细分工作姿态）。"""
    with _running_lock:
        _running_tasks[task_id] = {
            "task_id": task_id, "name": name, "started_at": started_at}


def _clear_running(task_id: str):
    with _running_lock:
        _running_tasks.pop(task_id, None)


def current_task() -> dict | None:
    """当前正在执行的任务（人格化状态：小满正在做XXX）。

    多任务并发时取最先开始的；无返回 None（摸鱼中）。
    """
    with _running_lock:
        active = list(_running_tasks.values())
    if not active:
        return None
    return min(active, key=lambda r: r["started_at"])


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
        if db.scheduler_window_done(task_id, window_key,
                                    max_failures=MAX_AUTO_FAILURES_PER_WINDOW):
            return {"started": False, "run_id": None, "reason": "idempotent",
                    "message": "该时间窗已执行过"}
    else:
        window_key = f"manual:{task_id}:{now.strftime('%Y%m%d-%H%M%S%f')}"

    run_id = db.scheduler_run_insert(task_id, window_key, trigger,
                                     now.strftime("%Y-%m-%d %H:%M:%S"))
    task_name = (task.get("description") or task.get("name") or task_id)
    _mark_running(task_id, task_name, now.strftime("%H:%M:%S"))

    def _worker(tid: str = task_id):
        try:
            _run_prompt(task, run_id)
        finally:
            _clear_running(tid)

    threading.Thread(target=_worker, daemon=True).start()
    return {"started": True, "run_id": run_id, "reason": "ok", "message": "任务已启动"}


def run_task_by_id(task_id: str, trigger: str = "manual") -> dict:
    """按 task_id 触发（API 用）。找不到任务或超出本调度器范围 → 拒绝。"""
    task = next((t for t in scoped_tasks() if t["task_id"] == task_id), None)
    if task is None:
        return {"started": False, "reason": "unknown",
                "message": f"未找到每日复盘任务 {task_id}（或不在本调度器范围）"}
    return run_task(task, trigger=trigger)


def run_task_sync(task: dict, trigger: str = "cron", now: datetime | None = None) -> dict:
    """同步执行一次任务（独立进程 / cron 场景）：建 run 记录 → 等待完成 → 返回结果。

    - trigger='cron'：window_key 与引擎 auto 相同（make_window_key），
      外部 cron 与 dashboard 引擎互斥防双跑（scheduler_runs 幂等一致）
    - trigger='manual'：独立 window_key（不参与 auto 幂等）
    - 同步阻塞：_run_prompt 内部 subprocess 等待执行引擎（dsh/claude）完成，
      适合 cron/计划任务/容器 cron 到点调用后即退出。
    """
    from dashboard import db

    now = now or datetime.now()
    if trigger == "cron":
        wkey = make_window_key(task, now)
    else:
        wkey = f"manual:{task['task_id']}:{now.strftime('%Y%m%d-%H%M%S%f')}"
    run_id = db.scheduler_run_insert(task["task_id"], wkey, trigger,
                                     now.strftime("%Y-%m-%d %H:%M:%S"))
    _run_prompt(task, run_id)
    return db.scheduler_run_get(run_id) or {}


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
        self.last_report_scan: str | None = None
        self._last_report_scan_dt: datetime | None = None
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
            "attendance": "on" if self.auto_enabled() else "leave",
            "engine": resolve_engine(),
            "last_tick": self.last_tick,
            "last_error": self.last_error,
            "last_report_scan": self.last_report_scan,
            "tick_seconds": TICK_SECONDS,
            "current_task": current_task(),
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

        # 报告增量重扫：无论 auto 开关都执行（兼容过渡期外部/Windows 任务
        # 写入 reports/ 的新报告；mtime 守卫，无变化时零 IO 零写库）。
        # 先上传本地新报告到云（保持"导入只扫云"设计），再云优先导入。
        if (self._last_report_scan_dt is None
                or (now - self._last_report_scan_dt).total_seconds() >= REPORT_RESCAN_SECONDS):
            try:
                upload_reports_to_cloud()
                r = import_reports_from_disk()
                self.last_report_scan = now.strftime("%Y-%m-%d %H:%M:%S")
                self._last_report_scan_dt = now
                if r.get("imported", 0):
                    print(f"[scheduler] report rescan imported {r['imported']} new/changed")
            except Exception as e:
                self.last_error = f"report rescan: {e}"

        if not self.auto_enabled():
            return  # 过渡期：auto 关闭，仅手动触发

        for t in scoped_tasks():
            if t.get("trading_day_required", False) and not is_trading_day(now.date()):
                continue
            if not task_due_now(t, now):
                continue
            wkey = make_window_key(t, now)
            if db.scheduler_window_done(t["task_id"], wkey,
                                        max_failures=MAX_AUTO_FAILURES_PER_WINDOW):
                continue  # 该时间窗已成功/超时/失败达上限（幂等 + 防重试风暴）
            result = run_task(t, trigger="auto", now=now)
            if result.get("started"):
                print(f"[scheduler] auto dispatch {t['task_id']} → run#{result['run_id']}")


engine = SchedulerEngine()


def start() -> None:
    """lifespan 调用：启动引擎（幂等）。

    启动前先回收僵尸 running 记录：上次进程被中断时，_run_prompt 的后台线程
    没机会把 running 更新为终态，DB 会遗留永久"运行中"的记录（UI 误导 +
    窗口幂等判断受影响）。重启后进程内任务表必为空，任何 DB running 都是僵尸。
    """
    from dashboard import db
    try:
        n = db.scheduler_mark_zombies_running()
        if n:
            print(f"[scheduler] start: 回收 {n} 条中断遗留的 running 记录 → failed",
                  file=sys.stderr)
    except Exception as e:
        print(f"[scheduler] start: 僵尸 running 清理失败: {e}", file=sys.stderr)
    engine.start()
