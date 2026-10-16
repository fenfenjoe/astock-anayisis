"""dashboard/importer.py — 量化系统数据导入器（磁盘 → DB）.

从 astock-anayisis 仓库的量化数据目录（my_doc/每日复盘/reports、持仓.md、每日调仓.md）
导入报告/持仓/交易到 Dashboard 数据库（幂等 upsert / mtime 守卫）。

2026-10-15 解耦：原 dashboard/scheduler.py 中「调度引擎 + DSH 运行器」属 Agent 自动化内容，
已随自动化层迁至 ~/.dsh/workspace/xiaoman/；本模块仅保留量化系统需要的数据导入能力。
"""

import json
import os
import sys
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

# ── sys.path：让本模块可独立运行（app.py 已插入 etf-strategies 到 sys.path）──
_ETF_DIR = Path(__file__).resolve().parent.parent
if str(_ETF_DIR) not in sys.path:
    sys.path.insert(0, str(_ETF_DIR))

# 仓库根：默认向上三级推导（本地），Docker 里用 DASHBOARD_REPO_ROOT 指向挂载点。
_env_repo_root = os.environ.get("DASHBOARD_REPO_ROOT")
REPO_ROOT = (
    Path(_env_repo_root).resolve()
    if _env_repo_root
    else Path(__file__).resolve().parent.parent.parent
)
REPORTS_DIR = REPO_ROOT / "my_doc" / "每日复盘" / "reports"
HOLDINGS_MD = REPO_ROOT / "my_doc" / "每日复盘" / "持仓.md"
TRADES_MD = REPO_ROOT / "my_doc" / "每日复盘" / "每日调仓.md"

# 交易日历：harness 自动化配置已随自动化层迁至 ~/.dsh/workspace/xiaoman/harness/
_env_home = os.environ.get("USERPROFILE") or os.environ.get("HOME") or str(Path.home())
TRADING_CALENDAR_PATH = (
    Path(_env_home)
    / ".dsh"
    / "workspace"
    / "xiaoman"
    / "harness"
    / "automation"
    / "config"
    / "trading_calendar.py"
)

# ── Markdown 优先的报告类型（2026-10 回退：Dashboard 恢复 markdown 渲染，.html 仅兜底）──
_HTML_REPORT_TYPES = frozenset({"早盘报告", "复盘报告", "进化周报"})

# ───────────────────────────────────────────────────────────────────
# 交易日历（复用 ~/.dsh/workspace/xiaoman/harness/automation/config/trading_calendar.py，不污染 sys.path）
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

        spec = importlib.util.spec_from_file_location(
            "_trading_calendar_loaded", TRADING_CALENDAR_PATH
        )
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
# 导入器：磁盘 → DB（幂等 upsert / replace）
# ───────────────────────────────────────────────────────────────────


def import_reports_from_disk(force: bool = False) -> dict:
    """导入复盘报告到 daily_reports。

    2026-09-07 移除 TOS：云权威库已迁移 Supabase，报告以本地 reports/ 为准
    （mtime 守卫，幂等 upsert）。
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

    # ── 本地扫描（mtime 守卫）──
    if not REPORTS_DIR.exists():
        return {"imported": 0, "error": "reports 目录不存在"}

    def _scan_file(f: Path, report_date: str, fallback_type: str = "") -> None:
        """单文件：mtime 未变则跳过；变化/新增则导入并记录。

        2026-10 回退（用户反馈 HTML 报告难看，恢复 markdown 渲染）：
        早盘/复盘报告**优先入库 .md**（Dashboard 展示 markdown 版）；.html 仅在无 .md
        兄弟文件时作为兜底入库（兼容历史仅 HTML 的日子）。
        """
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
        # Markdown 优先：早盘/复盘报告若 .md 兄弟文件存在，.html 版本不入库（仅记 mtime）
        if (
            report_type in _HTML_REPORT_TYPES
            and f.suffix.lower() == ".html"
            and f.with_suffix(".md").exists()
        ):
            changed[rel] = mtime
            return
        if report_date and report_type:
            db.report_upsert(
                report_date,
                report_type,
                f.read_text(encoding="utf-8"),
                source_file=str(f),
            )
            imported += 1
        changed[rel] = mtime

    for sub in sorted(REPORTS_DIR.iterdir()):
        if not sub.is_dir():
            continue
        if sub.name == "weekly":
            for f in sorted(sub.glob("*.md")) + sorted(sub.glob("*.html")):
                _scan_file(f, _weekly_date(f.name) or "", fallback_type="周报")
            continue
        if not sub.name.isdigit() or len(sub.name) != 8:
            continue
        for f in sorted(sub.glob("*.md")) + sorted(sub.glob("*.html")):
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
    for known in (
        "进化周报",  # P2 自进化周报（必须放"周报"前，避免被前缀吞）
        "复盘报告",
        "早盘报告",
        "早盘机会",
        "每日信号",
        "周报",
        "周度组合回顾",
    ):
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
