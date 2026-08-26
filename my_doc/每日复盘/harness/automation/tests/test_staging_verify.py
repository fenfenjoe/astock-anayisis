"""
staging_verify.py 测试 — staging 生成验证
覆盖: 大小/目标日期/今日标记/mtime 新鲜度
"""

import sys
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from staging_verify import verify_staging_content, verify_staging_file, check_review_staging


def _mk_content(tomorrow='2026-08-27', today='2026-08-26', size=600):
    """构造足够大的合法 staging 内容"""
    return f"# 今日早盘分析 — {tomorrow}\n\n> 本文件由 {today} 收盘复盘自动生成\n\n" + ("内容占位" * (size // 4))


class TestVerifyStagingContent:
    def test_valid(self):
        assert verify_staging_content(_mk_content(), '2026-08-27', '2026-08-26') == []

    def test_too_small(self):
        errors = verify_staging_content('短内容', '2026-08-27', '2026-08-26', 'f1')
        assert any('TOO SMALL' in e for e in errors)

    def test_wrong_date(self):
        content = _mk_content(tomorrow='2026-08-28')  # 不含目标日 27
        errors = verify_staging_content(content, '2026-08-27', '2026-08-26', 'f1')
        assert any('WRONG DATE' in e for e in errors)
        assert '2026-08-28' in [e for e in errors if 'WRONG DATE' in e][0]

    def test_stale_no_today_marker(self):
        content = _mk_content(today='2026-08-25')  # 缺今日 26
        errors = verify_staging_content(content, '2026-08-27', '2026-08-26', 'f1')
        assert any('STALE' in e for e in errors)

    def test_today_marker_mmdd_form(self):
        """今日标记也接受 MM-DD 形式（如 08/26）"""
        content = _mk_content().replace('2026-08-26', '08/26')
        assert verify_staging_content(content, '2026-08-27', '2026-08-26') == []

    def test_multiple_errors(self):
        content = '太短且日期也不对'
        errors = verify_staging_content(content, '2026-08-27', '2026-08-26', 'f1')
        assert len(errors) == 1  # TOO SMALL 短路返回


class TestVerifyStagingFile:
    def test_missing_file(self, tmp_path):
        errors, meta = verify_staging_file(str(tmp_path / 'nope.md'), '2026-08-27', '2026-08-26')
        assert any('MISSING' in e for e in errors)

    def test_valid_file(self, tmp_path):
        p = tmp_path / 'staging.md'
        p.write_text(_mk_content(), encoding='utf-8')
        errors, meta = verify_staging_file(str(p), '2026-08-27', '2026-08-26')
        assert errors == []
        assert meta['size_kb'] > 0


class TestCheckReviewStaging:
    def _result(self, path='s1.md', content='', mtime=None, size=600, missing=False):
        from datetime import datetime
        if mtime is None:
            mtime = datetime(2026, 8, 26, 16, 0)
        return {'path': path, 'content': content, 'mtime': mtime, 'size': size, 'missing': missing}

    def _state(self, status='completed', completed_at='2026-08-26T15:52:00'):
        return {'tasks': {'evening_review': {'status': status, 'completed_at': completed_at}}}

    def test_not_completed_exempt(self):
        assert check_review_staging(self._state(status='running'), [], '2026-08-27') == []

    def test_valid(self):
        content = '# 今日早盘分析 — 2026-08-27\n' + 'x' * 600
        r = self._result(content=content, size=620)
        assert check_review_staging(self._state(), [r], '2026-08-27') == []

    def test_missing_file(self):
        r = self._result(missing=True)
        failures = check_review_staging(self._state(), [r], '2026-08-27')
        assert any('MISSING' in f for f in failures)

    def test_stale_mtime_before_review(self):
        from datetime import datetime
        r = self._result(mtime=datetime(2026, 8, 26, 14, 0))  # 早于复盘完成 15:52
        failures = check_review_staging(self._state(), [r], '2026-08-27')
        assert any('STALE' in f for f in failures)

    def test_outdated_no_tomorrow(self):
        r = self._result(content='# 今日早盘分析 — 2026-08-26\n' + 'x' * 600)  # 旧日期
        failures = check_review_staging(self._state(), [r], '2026-08-27')
        assert any('OUTDATED' in f for f in failures)

    def test_too_small(self):
        r = self._result(content='短', size=100)
        failures = check_review_staging(self._state(), [r], '2026-08-27')
        assert any('TOO_SMALL' in f for f in failures)

    def test_mixed_multiple(self):
        from datetime import datetime
        r1 = self._result(path='a.md', content='# 今日早盘分析 — 2026-08-27\n' + 'x' * 600, size=620)
        r2 = self._result(path='b.md', content='旧内容', size=50, mtime=datetime(2026, 8, 25, 9, 0))
        failures = check_review_staging(self._state(), [r1, r2], '2026-08-27')
        # r1 通过；r2 的 STALE（mtime 早于复盘完成）短路（continue），仅报 STALE
        assert len(failures) == 1
        assert any('STALE' in f and 'b.md' in f for f in failures)
