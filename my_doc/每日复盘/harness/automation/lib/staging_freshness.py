"""
Staging 新鲜度检测 — 早盘分析前判断 staging 是否过期

纯计算 + 目录扫描，不调用外部 API，不读写生产数据文件。
判断依据：staging 头部的"执行日期"，兼容新旧两种格式：
  旧格式: `> 本文件由 ... 执行日期：**YYYY-MM-DD（周X）早盘前/收盘后**`
  新格式: `# 今日早盘分析 — YYYY-MM-DD（周X）` + `<!-- ... 供 YYYY-MM-DD 早盘分析使用 -->`
"""

import re
from datetime import date
from typing import Optional


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
            return date.fromisoformat(m.group(1))
    return None
