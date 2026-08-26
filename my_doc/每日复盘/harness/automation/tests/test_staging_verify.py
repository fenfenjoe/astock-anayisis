"""
staging_verify.py 测试 — staging 生成验证
覆盖: 大小/目标日期/今日标记/mtime 新鲜度
"""

import sys
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from staging_verify import verify_staging_content, verify_staging_file


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
