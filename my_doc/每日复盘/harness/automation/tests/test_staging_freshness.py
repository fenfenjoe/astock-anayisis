"""
Staging 执行日期解析 测试套件

被测源码:
  - lib/staging_freshness.py — parse_staging_execution_date
"""

import pytest
from datetime import date
from lib.staging_freshness import parse_staging_execution_date, is_staging_stale, find_latest_review_report


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


# ============================================================
# is_staging_stale
# ============================================================

class TestIsStagingStale:
    def test_stale_when_exec_before_today(self):
        """执行日 < 今天 → 过期"""
        stale, diag = is_staging_stale(date(2026, 8, 7), date(2026, 8, 10))
        assert stale is True
        assert diag['days_old'] == 3

    def test_fresh_when_exec_today(self):
        """执行日 == 今天 → 新鲜"""
        stale, diag = is_staging_stale(date(2026, 8, 10), date(2026, 8, 10))
        assert stale is False
        assert diag['days_old'] == 0

    def test_fresh_when_exec_future(self):
        """执行日 > 今天（提前生成）→ 新鲜"""
        stale, diag = is_staging_stale(date(2026, 8, 11), date(2026, 8, 10))
        assert stale is False

    def test_stale_when_none(self):
        """执行日 None → 保守判过期"""
        stale, diag = is_staging_stale(None, date(2026, 8, 10))
        assert stale is True
        assert diag['reason'] is not None


# ============================================================
# find_latest_review_report
# ============================================================

class TestFindLatestReviewReport:
    def test_finds_latest(self, tmp_path):
        """多个日期目录，取含复盘报告的最大日期"""
        (tmp_path / '20260805').mkdir()
        (tmp_path / '20260805' / '复盘报告.md').write_text('x', encoding='utf-8')
        (tmp_path / '20260807').mkdir()
        (tmp_path / '20260807' / '复盘报告.md').write_text('x', encoding='utf-8')
        (tmp_path / '20260810').mkdir()  # 无复盘报告
        assert find_latest_review_report(tmp_path) == date(2026, 8, 7)

    def test_skips_non_date_dirs(self, tmp_path):
        """跳过 weekly 等非日期目录"""
        (tmp_path / 'weekly').mkdir()
        (tmp_path / '20260805').mkdir()
        (tmp_path / '20260805' / '复盘报告.md').write_text('x', encoding='utf-8')
        assert find_latest_review_report(tmp_path) == date(2026, 8, 5)

    def test_none_when_empty(self, tmp_path):
        """空目录 → None"""
        assert find_latest_review_report(tmp_path) is None

    def test_none_when_no_review(self, tmp_path):
        """有日期目录但无复盘报告 → None"""
        (tmp_path / '20260810').mkdir()
        assert find_latest_review_report(tmp_path) is None

    def test_none_when_root_missing(self, tmp_path):
        """目录不存在 → None"""
        assert find_latest_review_report(tmp_path / 'nope') is None
