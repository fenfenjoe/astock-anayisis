#!/usr/bin/env python3
"""
A股交易日历判断工具。

用于自动化流水线在定时触发时判断今天是否为交易日，
非交易日自动跳过所有分析任务。

数据来源优先级：
1. 已知节假日/调休列表（硬编码，需每年更新）
2. 周末自动排除
3. 日内时间判断（是否在交易时段内）

使用方法：
    python trading_calendar.py                    # 输出今天是否为交易日
    python trading_calendar.py 2026-07-21         # 输出指定日期是否为交易日
    python trading_calendar.py --market-open      # 输出当前是否在交易时段内
"""

import json
import sys
from datetime import datetime, date, time
from pathlib import Path


# =============================================================================
# A股节假日列表（每年更新）
# 格式: "YYYY-MM-DD" = 全天休市
# =============================================================================
# 2026年中国A股节假日（含调休工作日）：
# 元旦: 1月1日
# 春节: 2月16日-2月20日 (农历正月初一为2月17日)
# 清明节: 4月4日-4月5日
# 劳动节: 5月1日-5月3日
# 端午节: 6月18日-6月20日
# 中秋节: 9月25日-9月26日
# 国庆节: 10月1日-10月7日
# 注: 2026年调休工作日已包含在内（不在此列表中的调休日可交易）

HOLIDAYS_2026 = {
    # 元旦
    "2026-01-01",
    # 春节（除夕2/16→初五2/20，2/21-2/22周末自然休息）
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",
    # 清明节
    "2026-04-04", "2026-04-05",
    # 劳动节
    "2026-05-01", "2026-05-02", "2026-05-03",
    # 端午节
    "2026-06-18", "2026-06-19", "2026-06-20",
    # 中秋节
    "2026-09-25", "2026-09-26",
    # 国庆节
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
    "2026-10-05", "2026-10-06", "2026-10-07",
}

# 调休工作日（周末但交易所开市）
TRADING_WEEKENDS_2026 = {
    # 2026年调休工作日（需根据国务院通知逐年更新）
    # 春节前补班: 2月14日(周六)
    "2026-02-14",
    # 劳动节前补班: 4月26日(周日)
    "2026-04-26",
    # 国庆节前补班: 9月27日(周日)
    "2026-09-27",
    # 国庆节后补班: 10月10日(周六)
    "2026-10-10",
}

# 所有节假日（按年份索引）
HOLIDAYS_BY_YEAR = {
    2026: HOLIDAYS_2026,
}

TRADING_WEEKENDS_BY_YEAR = {
    2026: TRADING_WEEKENDS_2026,
}

# =============================================================================
# 交易时间定义 (CST = UTC+8)
# =============================================================================
MORNING_SESSION_START = time(9, 30)
MORNING_SESSION_END = time(11, 30)
AFTERNOON_SESSION_START = time(13, 0)
AFTERNOON_SESSION_END = time(15, 0)

# 集合竞价时间
CALL_AUCTION_START = time(9, 15)
CALL_AUCTION_END = time(9, 25)

# 盘前/盘后关键时间窗口
PRE_MARKET_ANALYSIS_START = time(7, 30)   # 早盘分析最早开始时间
PRE_MARKET_ANALYSIS_END = time(9, 10)      # 早盘分析最晚完成时间
POST_MARKET_REVIEW_START = time(15, 0)     # 复盘最早开始时间


def is_trading_day(check_date: date | None = None) -> bool:
    """判断指定日期是否为A股交易日。

    Args:
        check_date: 要检查的日期，默认为今天

    Returns:
        True 如果该日期是交易日
    """
    if check_date is None:
        check_date = date.today()

    date_str = check_date.isoformat()

    # 1. 周末 → 非交易日（除非是调休工作日）
    if check_date.weekday() >= 5:  # Saturday=5, Sunday=6
        year_trading_weekends = TRADING_WEEKENDS_BY_YEAR.get(check_date.year, set())
        return date_str in year_trading_weekends

    # 2. 工作日 → 检查是否节假日
    year_holidays = HOLIDAYS_BY_YEAR.get(check_date.year, set())
    return date_str not in year_holidays


def is_market_open(now: datetime | None = None) -> bool:
    """判断当前时间是否在A股连续竞价交易时段内。

    Args:
        now: 要检查的时间，默认为当前时间

    Returns:
        True 如果当前在 9:30-11:30 或 13:00-15:00 范围内
    """
    if now is None:
        now = datetime.now()

    current_time = now.time()

    # 早盘时段
    if MORNING_SESSION_START <= current_time <= MORNING_SESSION_END:
        return True

    # 午盘时段
    if AFTERNOON_SESSION_START <= current_time <= AFTERNOON_SESSION_END:
        return True

    return False


def is_pre_market_window(now: datetime | None = None) -> bool:
    """判断当前是否在早盘分析时间窗口内（7:30-9:10 CST）。"""
    if now is None:
        now = datetime.now()
    current_time = now.time()
    return PRE_MARKET_ANALYSIS_START <= current_time <= PRE_MARKET_ANALYSIS_END


def is_post_market_window(now: datetime | None = None) -> bool:
    """判断当前是否在收盘后（15:00 CST 之后）。"""
    if now is None:
        now = datetime.now()
    return now.time() >= POST_MARKET_REVIEW_START


def is_intraday_window(now: datetime | None = None) -> bool:
    """判断当前是否在盘中交易时段内（含午休）。"""
    if now is None:
        now = datetime.now()
    current_time = now.time()
    return MORNING_SESSION_START <= current_time <= AFTERNOON_SESSION_END


def next_trading_day(from_date: date | None = None) -> date:
    """返回下一个交易日（不含今天）。"""
    if from_date is None:
        from_date = date.today()

    next_day = from_date
    while True:
        next_day = date(next_day.year, next_day.month, next_day.day)
        next_day = date.fromordinal(next_day.toordinal() + 1)
        if is_trading_day(next_day):
            return next_day


def trading_day_status(check_date: date | None = None) -> dict:
    """返回指定日期的完整交易状态信息（供 prompt 使用）。

    Returns:
        dict 包含 is_trading_day, is_weekend, is_holiday, next_trading_day 等
    """
    if check_date is None:
        check_date = date.today()

    is_td = is_trading_day(check_date)
    is_weekend = check_date.weekday() >= 5
    date_str = check_date.isoformat()

    # 判断是否节假日（工作日但非交易日=节假日）
    year_holidays = HOLIDAYS_BY_YEAR.get(check_date.year, set())
    is_holiday = (not is_weekend) and date_str in year_holidays

    # 判断是否调休工作日（周末但交易）
    year_trading_weekends = TRADING_WEEKENDS_BY_YEAR.get(check_date.year, set())
    is_trading_weekend = is_weekend and date_str in year_trading_weekends

    status = {
        "date": date_str,
        "weekday": check_date.strftime("%A"),
        "is_trading_day": is_td,
        "is_weekend": is_weekend,
        "is_holiday": is_holiday,
        "is_trading_weekend": is_trading_weekend,
        "next_trading_day": None,
        "market_open_now": is_market_open(),
        "pre_market_window_now": is_pre_market_window(),
        "post_market_window_now": is_post_market_window(),
    }

    if not is_td:
        status["next_trading_day"] = next_trading_day(check_date).isoformat()

    return status


# =============================================================================
# CLI 入口
# =============================================================================
if __name__ == "__main__":
    if "--market-open" in sys.argv:
        print(json.dumps({"market_open": is_market_open()}))
    elif "--status" in sys.argv:
        if len(sys.argv) > 2:
            check_date = date.fromisoformat(sys.argv[2])
        else:
            check_date = date.today()
        print(json.dumps(trading_day_status(check_date), indent=2, ensure_ascii=False))
    elif len(sys.argv) > 1:
        check_date = date.fromisoformat(sys.argv[1])
        print(json.dumps(trading_day_status(check_date), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(trading_day_status(), indent=2, ensure_ascii=False))
