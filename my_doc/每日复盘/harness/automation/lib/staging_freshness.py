"""
Staging 新鲜度检测 — 早盘分析前判断 staging 是否过期

纯计算 + 目录扫描，不调用外部 API，不读写生产数据文件。
判断依据：staging 头部的"执行日期"，兼容新旧两种格式：
  旧格式: `> 本文件由 ... 执行日期：**YYYY-MM-DD（周X）早盘前/收盘后**`
  新格式: `# 今日早盘分析 — YYYY-MM-DD（周X）` + `<!-- ... 供 YYYY-MM-DD 早盘分析使用 -->`
"""

import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional, Tuple, Union


# 三种格式的匹配模式，按优先级排列（执行日期字段 > 供X使用注释 > 标题）
_DATE_PATTERNS = [
    # 旧格式：执行日期：**YYYY-MM-DD（周X）早盘前/收盘后**
    re.compile(r'执行日期[:：]\s*\*{0,2}(\d{4}-\d{2}-\d{2})'),
    # 新格式注释：供 YYYY-MM-DD 早盘分析使用
    re.compile(r'供\s*(\d{4}-\d{2}-\d{2})\s*早盘分析使用'),
    # 新格式标题：# 今日早盘分析 — YYYY-MM-DD（周X）
    re.compile(r'^#\s*今日早盘分析\s*[—\-–]\s*(\d{4}-\d{2}-\d{2})', re.MULTILINE),
]


def parse_staging_execution_date(text: Optional[str]) -> Optional[date]:
    """解析 staging 中的执行日期。

    Args:
        text: staging 文件全文；None/空串返回 None

    Returns:
        执行日期；解析失败返回 None
    """
    if not text:
        return None
    for pat in _DATE_PATTERNS:
        m = pat.search(text)
        if m:
            try:
                return date.fromisoformat(m.group(1))
            except ValueError:
                return None
    return None


def is_staging_stale(exec_date: Optional[date], today: date) -> Tuple[bool, dict]:
    """判定 staging 是否过期。

    Args:
        exec_date: staging 执行日期；None 表示无法解析
        today: 今天日期

    Returns:
        (is_stale, diag) 其中 diag = {exec_date, days_old, reason}
    """
    if exec_date is None:
        return (True, {
            'exec_date': None,
            'days_old': None,
            'reason': '无法解析执行日期，保守判为过期',
        })
    days_old = (today - exec_date).days
    if exec_date < today:
        return (True, {
            'exec_date': exec_date.isoformat(),
            'days_old': days_old,
            'reason': f'执行日 {exec_date} 早于今日 {today}',
        })
    return (False, {
        'exec_date': exec_date.isoformat(),
        'days_old': days_old,
        'reason': f'执行日 {exec_date} 为今日或未来',
    })


def find_latest_review_report(reports_root: Union[str, Path]) -> Optional[date]:
    """定位最近一次含 复盘报告.md 的 reports/{yyyyMMdd}/ 目录日期。

    Args:
        reports_root: reports/ 目录路径

    Returns:
        最近复盘日期；无则 None
    """
    root = Path(reports_root)
    if not root.is_dir():
        return None
    latest = None
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            d = datetime.strptime(child.name, '%Y%m%d').date()
        except ValueError:
            continue  # 跳过 weekly 等非日期目录
        if (child / '复盘报告.md').is_file():
            if latest is None or d > latest:
                latest = d
    return latest


def staging_health_check(
    staging_text: Optional[str],
    today: date,
    reports_root: Union[str, Path],
) -> dict:
    """早盘前的 staging 综合健康检查。

    Args:
        staging_text: staging 文件全文；None 表示文件缺失
        today: 今天日期
        reports_root: reports/ 目录路径（用于定位最近复盘）

    Returns:
        {
            'exists': bool,
            'exec_date': date | None,
            'stale': bool,
            'latest_review_date': date | None,
            'action': 'use' | 'rebuild' | 'missing',
        }
    """
    if not staging_text:
        return {
            'exists': False,
            'exec_date': None,
            'stale': True,
            'latest_review_date': find_latest_review_report(reports_root),
            'action': 'missing',
        }
    exec_date = parse_staging_execution_date(staging_text)
    stale, _diag = is_staging_stale(exec_date, today)
    if exec_date is None or stale:
        action = 'rebuild'
    else:
        action = 'use'
    return {
        'exists': True,
        'exec_date': exec_date,
        'stale': stale,
        'latest_review_date': find_latest_review_report(reports_root),
        'action': action,
    }
