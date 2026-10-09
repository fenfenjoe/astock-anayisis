"""
REQ-013 TDD 门禁测试 — 复盘类任务跨实例互斥运行锁 + staging/归档写入前原子性校验

被测模块:
  - lib/run_lock.py（新增）: acquire_lock / release_lock / read_lock / is_stale / check_modified
  - lib/staging_verify.py（扩展）: check_archive_source_date

覆盖 REQ-013 期望结果:
  ① 跨实例互斥锁 — acquire_lock 首次成功/二次被拒/stale 自动接管/takeover 强制接管
  ② 手动触发优先级可配置 — acquire_lock(takeover=True)
  ③ 归档幂等保护 — check_archive_source_date 目标日期==今日 允许 / ==次日 拒绝
  ④ 写入前置校验 — check_modified 检测 mtime 变化（.conflict 副本触发条件）
  ⑤ 可观测 — 锁文件含 instance_id/acquired_at/pid；read_lock 可读取
  ⑥ 测试 — 全部函数正向 + 边界覆盖

测试覆盖要求（REQ-013 测试交付物）:
  - 锁获取/释放/stale 判定覆盖：首次获取成功、二次获取被拒、超时后可获取、释放后可获取、损坏锁文件容错
  - staging 归档校验覆盖：目标日期==今日（允许归档）、目标日期==次日（拒绝并降级）、文件缺失
"""

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

import pytest

from run_lock import (
    acquire_lock,
    release_lock,
    read_lock,
    is_stale,
    check_modified,
    LOCK_FILE_SUFFIX,
)
from staging_verify import check_archive_source_date


# ============================================================
# fixtures — 临时锁目录（每次测试独立，不污染 config/）
# ============================================================

@pytest.fixture
def lock_dir(tmp_path):
    """临时锁目录（模拟 config/run_locks/）。"""
    d = tmp_path / "run_locks"
    d.mkdir()
    return str(d)


def _lock_path(lock_dir, task):
    return str(Path(lock_dir) / f"{task}{LOCK_FILE_SUFFIX}")


def _write_lock(lock_dir, task, **overrides):
    """直接写入一个锁文件（构造 stale / 损坏等场景）。"""
    lock = {
        'task': task,
        'instance_id': 'inst-test',
        'pid': 12345,
        'acquired_at': datetime.now().isoformat(),
        'hostname': 'test-host',
    }
    lock.update(overrides)
    Path(_lock_path(lock_dir, task)).write_text(
        json.dumps(lock, ensure_ascii=False), encoding='utf-8')
    return lock


# ============================================================
# acquire_lock — 跨实例互斥锁获取
# ============================================================

class TestAcquireLock:
    def test_first_acquire_succeeds(self, lock_dir):
        """首次获取 → acquired=true，锁文件已写入（REQ 期望结果①）。"""
        result = acquire_lock('evening_review', lock_dir, instance_id='inst-A')
        assert result['acquired'] is True
        lock = read_lock('evening_review', lock_dir)
        assert lock is not None
        assert lock['task'] == 'evening_review'
        assert lock['instance_id'] == 'inst-A'
        assert 'acquired_at' in lock
        assert 'pid' in lock

    def test_second_acquire_rejected(self, lock_dir):
        """已持锁（未 stale）→ 二次获取被拒（REQ 期望结果① 第二实例显式退出）。"""
        acquire_lock('morning_analysis', lock_dir, instance_id='inst-A')
        result = acquire_lock('morning_analysis', lock_dir, instance_id='inst-B')
        assert result['acquired'] is False
        assert result['reason'] == 'held'
        assert 'inst-A' in result['lock']['instance_id']

    def test_stale_auto_takeover(self, lock_dir):
        """stale 超时后（45 分钟）→ 自动接管（REQ 期望结果① stale 超时）。"""
        stale_time = (datetime.now() - timedelta(minutes=60)).isoformat()
        _write_lock(lock_dir, 'evening_review', instance_id='inst-dead',
                    acquired_at=stale_time)
        result = acquire_lock('evening_review', lock_dir, instance_id='inst-new')
        assert result['acquired'] is True
        assert result['reason'] == 'stale_taken'
        lock = read_lock('evening_review', lock_dir)
        assert lock['instance_id'] == 'inst-new'

    def test_takeover_force(self, lock_dir):
        """takeover=True → 即使未 stale 也强制接管（REQ 期望结果② 手动优先级）。"""
        _write_lock(lock_dir, 'intraday_0940', instance_id='inst-running')
        result = acquire_lock('intraday_0940', lock_dir, instance_id='inst-manual',
                              takeover=True)
        assert result['acquired'] is True
        assert result['reason'] == 'takeover'
        lock = read_lock('intraday_0940', lock_dir)
        assert lock['instance_id'] == 'inst-manual'

    def test_acquire_after_release(self, lock_dir):
        """释放后可再次获取（锁不永久阻塞，REQ 约束③）。"""
        acquire_lock('evening_review', lock_dir, instance_id='inst-A')
        release_lock('evening_review', lock_dir, instance_id='inst-A')
        result = acquire_lock('evening_review', lock_dir, instance_id='inst-B')
        assert result['acquired'] is True

    def test_corrupt_lock_file_tolerated(self, lock_dir):
        """损坏锁文件（非 JSON）→ 视为未持有，可获取（容错）。"""
        Path(_lock_path(lock_dir, 'evening_review')).write_text(
            'not a json {{{', encoding='utf-8')
        result = acquire_lock('evening_review', lock_dir, instance_id='inst-A')
        assert result['acquired'] is True

    def test_custom_timeout(self, lock_dir):
        """自定义 stale 超时（如 10 分钟）→ 15 分钟前的锁判定为 stale。"""
        stale_time = (datetime.now() - timedelta(minutes=15)).isoformat()
        _write_lock(lock_dir, 'evening_review', instance_id='inst-dead',
                    acquired_at=stale_time)
        # 默认 45 分钟 → 未 stale
        assert acquire_lock('evening_review', lock_dir, instance_id='inst-A')['acquired'] is False
        # 自定义 10 分钟 → stale，可获取
        result = acquire_lock('evening_review', lock_dir, instance_id='inst-B',
                              timeout_minutes=10)
        assert result['acquired'] is True


# ============================================================
# is_stale — stale 判定（纯函数）
# ============================================================

class TestIsStale:
    def test_fresh_not_stale(self):
        """刚获取的锁 → 未 stale。"""
        lock = {'acquired_at': datetime.now().isoformat()}
        assert is_stale(lock, timeout_minutes=45) is False

    def test_old_is_stale(self):
        """60 分钟前的锁 → stale。"""
        old = (datetime.now() - timedelta(minutes=60)).isoformat()
        assert is_stale({'acquired_at': old}, timeout_minutes=45) is True

    def test_boundary_exactly_timeout(self):
        """恰好 45 分钟 → 视为 stale（>= 边界）。"""
        exact = (datetime.now() - timedelta(minutes=45)).isoformat()
        assert is_stale({'acquired_at': exact}, timeout_minutes=45) is True

    def test_missing_acquired_at_is_stale(self):
        """缺 acquired_at（异常锁）→ 视为 stale（不永久阻塞）。"""
        assert is_stale({}, timeout_minutes=45) is True

    def test_invalid_acquired_at_is_stale(self):
        """acquired_at 无法解析 → 视为 stale。"""
        assert is_stale({'acquired_at': 'not-a-date'}, timeout_minutes=45) is True


# ============================================================
# read_lock / release_lock — 读取与释放
# ============================================================

class TestReadLock:
    def test_read_existing(self, lock_dir):
        _write_lock(lock_dir, 'evening_review', instance_id='inst-A')
        lock = read_lock('evening_review', lock_dir)
        assert lock['instance_id'] == 'inst-A'
        assert lock['task'] == 'evening_review'

    def test_read_missing_returns_none(self, lock_dir):
        assert read_lock('evening_review', lock_dir) is None

    def test_read_corrupt_returns_none(self, lock_dir):
        """损坏锁文件 → read_lock 返回 None（容错，不抛异常）。"""
        Path(_lock_path(lock_dir, 'evening_review')).write_text('{{{', encoding='utf-8')
        assert read_lock('evening_review', lock_dir) is None


class TestReleaseLock:
    def test_release_own_lock(self, lock_dir):
        acquire_lock('evening_review', lock_dir, instance_id='inst-A')
        result = release_lock('evening_review', lock_dir, instance_id='inst-A')
        assert result['released'] is True
        assert read_lock('evening_review', lock_dir) is None

    def test_release_others_lock_rejected(self, lock_dir):
        """释放他人持有的锁 → 拒绝（防误释放）。"""
        acquire_lock('evening_review', lock_dir, instance_id='inst-A')
        result = release_lock('evening_review', lock_dir, instance_id='inst-B')
        assert result['released'] is False
        # 锁仍在
        assert read_lock('evening_review', lock_dir)['instance_id'] == 'inst-A'

    def test_release_missing_lock(self, lock_dir):
        """无锁可释放 → released=false（幂等，不报错）。"""
        result = release_lock('evening_review', lock_dir, instance_id='inst-A')
        assert result['released'] is False

    def test_release_force_flag(self, lock_dir):
        """force=True → 释放任意实例持有的锁（stale 兜底清理通道）。"""
        _write_lock(lock_dir, 'evening_review', instance_id='inst-dead')
        result = release_lock('evening_review', lock_dir, instance_id='inst-other', force=True)
        assert result['released'] is True


# ============================================================
# check_modified — 写入前置校验（读-改-写 + mtime 校验）
# ============================================================

class TestCheckModified:
    def test_unchanged_not_modified(self, tmp_path):
        """mtime 未变 → 未被修改（可安全写入）。"""
        p = tmp_path / "task_state.json"
        p.write_text('{"a": 1}', encoding='utf-8')
        snapshot = p.stat().st_mtime_ns
        assert check_modified(str(p), snapshot) is False

    def test_changed_is_modified(self, tmp_path):
        """文件在读取后被修改（mtime 变化）→ 检测到冲突。"""
        p = tmp_path / "task_state.json"
        p.write_text('{"a": 1}', encoding='utf-8')
        snapshot = p.stat().st_mtime_ns
        time.sleep(0.02)  # 确保 mtime 变化
        p.write_text('{"a": 2}', encoding='utf-8')
        assert check_modified(str(p), snapshot) is True

    def test_missing_file_is_modified(self, tmp_path):
        """文件被删除 → 视为修改（冲突）。"""
        p = tmp_path / "task_state.json"
        p.write_text('{"a": 1}', encoding='utf-8')
        snapshot = p.stat().st_mtime_ns
        p.unlink()
        assert check_modified(str(p), snapshot) is True

    def test_none_snapshot_returns_false(self, tmp_path):
        """快照为 None（首次写入前）→ 不判冲突。"""
        p = tmp_path / "task_state.json"
        p.write_text('{"a": 1}', encoding='utf-8')
        assert check_modified(str(p), None) is False


# ============================================================
# check_archive_source_date — 归档幂等保护（staging 目标日期校验）
# ============================================================

class TestCheckArchiveSourceDate:
    TODAY = '2026-10-09'
    TOMORROW = '2026-10-10'

    def _staging_content(self, exec_date: str) -> str:
        """构造标准 staging 内容（模板第 3 行格式）。"""
        return (
            "# 每日早盘上下文（10/09 周五）\n\n"
            f"> 本文件由 2026-10-08 收盘复盘自动生成。执行日期：**{exec_date}（周五）早盘**\n\n"
            "## 一、我的持仓\n\n| 股票名称 | 代码 | 持仓数量（份） |\n"
        )

    def test_today_allowed(self):
        """目标日期 == 今日 → 允许归档（errors 空）。"""
        errors = check_archive_source_date(self._staging_content(self.TODAY), self.TODAY)
        assert errors == []

    def test_tomorrow_rejected(self):
        """目标日期 == 次日（已被并发覆盖）→ 拒绝归档（REQ 期望结果③）。"""
        errors = check_archive_source_date(
            self._staging_content(self.TOMORROW), self.TODAY)
        assert len(errors) >= 1
        assert '次日' in errors[0] or '非今日' in errors[0] or '2026-10-10' in errors[0]

    def test_missing_exec_date_rejected(self):
        """内容无执行日期 → 拒绝归档（无法确认是当日原件）。"""
        content = "# 每日早盘上下文\n\n## 一、我的持仓\n\n"
        errors = check_archive_source_date(content, self.TODAY)
        assert len(errors) >= 1

    def test_empty_content_rejected(self):
        """内容为空 → 拒绝归档（文件缺失/未生成）。"""
        errors = check_archive_source_date('', self.TODAY)
        assert len(errors) >= 1

    def test_other_date_rejected(self):
        """执行日期为更早的日期（过期文件）→ 拒绝归档。"""
        errors = check_archive_source_date(
            self._staging_content('2026-10-08'), self.TODAY)
        assert len(errors) >= 1
