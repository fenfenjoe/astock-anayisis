"""
report_freshness.py — 报告产出新鲜度监控（REQ-016）

自动化任务中断告警机制：检测"连续 N 个交易日无复盘报告产出"（决策盲区），
在自动化静默失败时主动告警，避免长盲区（2026-09-24~09-30 连续 7 交易日盲区教训）。

设计原则：
- 纯计算 + 目录扫描，不调用外部 API，不修改任何生产数据文件（写入由 prompt 层负责）。
- 交易日历注入式：is_trading_day / next_trading_day 作为参数传入（默认从
  config.trading_calendar 导入），保持纯函数可测性。
- 非交易日（周末/节假日）不计入"无报告日"，避免假期误报（REQ 约束①）。

函数一览：
  last_review_date(reports_root) -> date | None
      最近有 复盘报告.md 的 reports/{yyyyMMdd}/ 目录日期。

  count_missing_review_trading_days(reports_root, end_date, is_trading_day=None) -> int
      从 end_date 往回（含 end_date），连续多少个交易日无复盘报告；
      跳过非交易日；遇到有报告的交易日停止。

  check_freshness_alert(reports_root, end_date, is_trading_day=None, threshold=1) -> dict
      {alert, streak, last_review_date, detail} — streak >= threshold → alert=true。

  is_holiday_eve(today, next_trading_day, threshold_days=4) -> bool
      判断 today 是否为长假前最后一个交易日（下一个交易日间隔 >= threshold_days 天；
      普通周末 3 天不触发，3 天小长假+周末 4 天触发）。

  previous_trading_day(today, is_trading_day=None) -> date | None
      today 之前最近的交易日（不含 today）。

  build_pending_entry(streak, last_review_date, today, seq) -> str
      生成 PENDING_CONFIRMATION.md「待确认」表的一行（供 prompt 写入）。
"""

from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional, Union

# 默认交易日历（可注入覆盖）
try:
    from config.trading_calendar import is_trading_day as _default_is_trading_day
except ImportError:  # pragma: no cover — 仅当 config 不可用时兜底（工作日近似）
    def _default_is_trading_day(d: date) -> bool:  # type: ignore[misc]
        return d.weekday() < 5


TradingDayFn = Callable[[date], bool]


# ============================================================
# 最近复盘报告日期
# ============================================================

def last_review_date(reports_root: Union[str, Path]) -> Optional[date]:
    """定位最近一次含 复盘报告.md 的 reports/{yyyyMMdd}/ 目录日期。

    Args:
        reports_root: reports/ 目录路径

    Returns:
        最近复盘日期；无则 None
    """
    root = Path(reports_root)
    if not root.is_dir():
        return None
    latest: Optional[date] = None
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            d = date(int(child.name[:4]), int(child.name[4:6]), int(child.name[6:8]))
        except (ValueError, IndexError):
            continue  # 跳过 weekly 等非日期目录
        if (child / "复盘报告.md").is_file():
            if latest is None or d > latest:
                latest = d
    return latest


# ============================================================
# 连续无报告交易日数（核心新鲜度函数）
# ============================================================

def _report_exists(reports_root: Path, d: date) -> bool:
    """指定日期是否有 复盘报告.md。"""
    return (reports_root / d.strftime("%Y%m%d") / "复盘报告.md").is_file()


def count_missing_review_trading_days(
    reports_root: Union[str, Path],
    end_date: date,
    is_trading_day: Optional[TradingDayFn] = None,
) -> int:
    """统计截至 end_date（含）连续多少个交易日无复盘报告产出。

    Args:
        reports_root: reports/ 目录路径
        end_date: 检查截止日（含当天）；调用方应传"已完成的交易日"
            （早盘/收盘前置检查传 previous_trading_day(today)，
            逻辑巡检 17:07 传 today 检查当日复盘是否产出）
        is_trading_day: 交易日判定函数，默认 config.trading_calendar.is_trading_day

    Returns:
        连续无报告交易日数：0 表示 end_date（或其最近交易日）有报告；
        非交易日不计入；遇到有报告的交易日停止向前。
    """
    if is_trading_day is None:
        is_trading_day = _default_is_trading_day
    root = Path(reports_root)
    streak = 0
    cursor = end_date
    # 保护：最多回退 400 天，避免异常输入死循环
    for _ in range(400):
        if not is_trading_day(cursor):
            cursor -= timedelta(days=1)
            continue
        if _report_exists(root, cursor):
            break
        streak += 1
        cursor -= timedelta(days=1)
    return streak


# ============================================================
# 告警判定（阈值边界）
# ============================================================

def check_freshness_alert(
    reports_root: Union[str, Path],
    end_date: date,
    is_trading_day: Optional[TradingDayFn] = None,
    threshold: int = 1,
) -> dict:
    """新鲜度告警判定。

    Args:
        reports_root: reports/ 目录路径
        end_date: 检查截止日（语义同 count_missing_review_trading_days）
        is_trading_day: 交易日判定函数
        threshold: 告警阈值（连续无报告交易日数），REQ 默认 1

    Returns:
        {
            'alert': bool,
            'streak': int,
            'last_review_date': date | None,
            'detail': str,
        }
    """
    if is_trading_day is None:
        is_trading_day = _default_is_trading_day
    streak = count_missing_review_trading_days(
        reports_root, end_date, is_trading_day)
    latest = last_review_date(reports_root)
    alert = streak >= threshold
    if latest is None:
        detail = f"连续 {streak} 个交易日无复盘报告产出（从未检测到复盘报告）"
    else:
        detail = (
            f"连续 {streak} 个交易日无复盘报告产出"
            f"（最近报告 {latest.isoformat()}）"
        )
    return {
        "alert": alert,
        "streak": streak,
        "last_review_date": latest,
        "detail": detail,
    }


# ============================================================
# 长假前最后交易日识别（假期预案）
# ============================================================

def is_holiday_eve(
    today: date,
    next_trading_day: date,
    threshold_days: int = 4,
) -> bool:
    """判断 today 是否为长假前最后一个交易日。

    下一个交易日与 today 的间隔 >= threshold_days 天 → 视为长假前夜。
    - 普通周末：周五 → 下周一，间隔 3 天 → 不触发（默认阈值 4）
    - 3 天小长假（中秋/端午）：周四 → 下周一，间隔 4 天 → 触发
    - 国庆/春节长假期：间隔 >= 8 天 → 触发

    Args:
        today: 当前交易日
        next_trading_day: 下一个交易日（调用方从 config.trading_calendar.next_trading_day 获取）
        threshold_days: 间隔阈值（天），默认 4

    Returns:
        True 若下一个交易日间隔 >= threshold_days（长假前最后交易日）
    """
    gap = (next_trading_day - today).days
    return gap >= threshold_days


# ============================================================
# 上一交易日（周报/早盘 end_date 口径）
# ============================================================

def previous_trading_day(
    today: date,
    is_trading_day: Optional[TradingDayFn] = None,
) -> Optional[date]:
    """返回 today 之前最近的交易日（不含 today）。

    Args:
        today: 当前日期
        is_trading_day: 交易日判定函数

    Returns:
        上一交易日；若无更早交易日则 None
    """
    if is_trading_day is None:
        is_trading_day = _default_is_trading_day
    cursor = today - timedelta(days=1)
    for _ in range(400):
        if cursor.year < 1970:
            return None
        if is_trading_day(cursor):
            return cursor
        cursor -= timedelta(days=1)
    return None


# ============================================================
# PENDING_CONFIRMATION 表格行
# ============================================================

def build_pending_entry(
    streak: int,
    last_review_date: Optional[date],
    today: date,
    seq: int,
) -> str:
    """生成 PENDING_CONFIRMATION.md「待确认」表的一行。

    格式对齐 auto_logic_inspect 的写入口径：
    `| {序号} | {MM-DD} | REQ-016 | {事项} | P1 | +1天 |`

    Args:
        streak: 连续无报告交易日数
        last_review_date: 最近复盘报告日期（None → 从未产出）
        today: 告警日期
        seq: PENDING 序号（prompt 层从文件读取最大序号 +1）

    Returns:
        markdown 表格行
    """
    last = last_review_date.isoformat() if last_review_date else "无记录（从未产出）"
    return (
        f"| {seq} | {today.strftime('%m-%d')} | REQ-016 | "
        f"🚨 **报告新鲜度告警：连续 {streak} 个交易日无复盘报告产出**"
        f"（最近报告 {last}）→ 存在决策盲区，请排查自动化中断原因"
        f"（对照 BUG-019）并确认是否补跑复盘 | P1 | +1天 |"
    )
