"""
Staging 执行日期解析 测试套件

被测源码:
  - lib/staging_freshness.py — parse_staging_execution_date
"""

import pytest
from datetime import date
from lib.staging_freshness import parse_staging_execution_date


# ============================================================
# parse_staging_execution_date
# ============================================================

class TestParseStagingExecutionDate:
    def test_old_format_morning(self):
        """旧格式：执行日期：**YYYY-MM-DD（周X）早盘前**"""
        text = (
            '# 每日复盘上下文\n\n'
            '> 本文件由 2026-08-07 收盘复盘（补跑，2026-08-10 早盘前生成）自动生成。'
            '执行日期：**2026-08-10（周一）早盘前**\n'
        )
        assert parse_staging_execution_date(text) == date(2026, 8, 10)

    def test_old_format_review(self):
        """旧格式：执行日期：**YYYY-MM-DD（周X）收盘后**"""
        text = (
            '# 每日复盘上下文\n\n'
            '> 本文件由 2026-08-10 收盘复盘自动生成。'
            '执行日期：**2026-08-11（周二）收盘后**\n'
        )
        assert parse_staging_execution_date(text) == date(2026, 8, 11)

    def test_new_format_morning_title(self):
        """新格式：标题 # 今日早盘分析 — YYYY-MM-DD（周X）"""
        text = (
            '# 今日早盘分析 — 2026-08-11（周二）\n\n'
            '<!-- 本文件由 2026-08-10 收盘复盘自动生成，供 2026-08-11 早盘分析使用 -->\n'
        )
        assert parse_staging_execution_date(text) == date(2026, 8, 11)

    def test_new_format_comment(self):
        """新格式：仅注释 供 YYYY-MM-DD 早盘分析使用（不被生成日干扰）"""
        text = (
            '# 其他标题\n\n'
            '<!-- 本文件由 2026-08-10 收盘复盘自动生成，供 2026-08-11 早盘分析使用 -->\n'
        )
        assert parse_staging_execution_date(text) == date(2026, 8, 11)

    def test_no_date(self):
        """无日期 → None"""
        assert parse_staging_execution_date('# 无日期文件\n正文') is None

    def test_empty_text(self):
        """空文本 → None"""
        assert parse_staging_execution_date('') is None
        assert parse_staging_execution_date(None) is None
