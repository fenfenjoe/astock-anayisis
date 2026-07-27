"""
REQ-002: 信号设计质量提升 测试套件

被测源码:
  - lib/signal_design.py      — 窗口计算 / 紧急度排序 / 过期判定 / 规则检查

覆盖要点:
  - 时间窗口里程碑计算 (50%/75%)
  - 价格可达性判定 (基于波动率)
  - 75%强制过期 (P0豁免)
  - 紧急度排序优先级
  - 主备路径检查
  - 分级阈值生成
"""

import pytest
from datetime import datetime, timedelta
from lib.signal_design import (
    calc_window_milestones,
    is_price_reachable,
    should_expire,
    sort_by_urgency,
    check_main_backup_paths,
    generate_graded_thresholds,
)


# ============================================================
# calc_window_milestones
# ============================================================

class TestCalcWindowMilestones:
    def test_4h_window(self):
        """4小时窗口: 50%=2h, 75%=3h"""
        start = datetime(2026, 7, 27, 9, 30)
        end = datetime(2026, 7, 27, 13, 30)
        result = calc_window_milestones(start, end)
        assert result['total_minutes'] == 240
        assert result['pct50'] == datetime(2026, 7, 27, 11, 30)
        assert result['pct75'] == datetime(2026, 7, 27, 12, 30)

    def test_1h_window(self):
        """1小时窗口: 50%=30min, 75%=45min"""
        start = datetime(2026, 7, 27, 10, 0)
        end = datetime(2026, 7, 27, 11, 0)
        result = calc_window_milestones(start, end)
        assert result['total_minutes'] == 60
        assert result['pct50'] == datetime(2026, 7, 27, 10, 30)
        assert result['pct75'] == datetime(2026, 7, 27, 10, 45)

    def test_cross_lunch_break(self):
        """跨午休窗口: 上午到下午"""
        start = datetime(2026, 7, 27, 11, 0)
        end = datetime(2026, 7, 27, 14, 0)
        result = calc_window_milestones(start, end)
        assert result['total_minutes'] == 180


# ============================================================
# is_price_reachable
# ============================================================

class TestIsPriceReachable:
    def test_close_price_reachable(self):
        """距离1%剩30分钟 => 可达"""
        # 30min/240min = 0.125, sqrt(0.125)=0.354
        # max_move = 3% * 0.354 = 1.06% > 1% => True
        assert is_price_reachable(100.0, 101.0, 30) is True

    def test_far_price_not_reachable(self):
        """距离5%剩5分钟 => 不可达"""
        # 5min/240min = 0.021, sqrt(0.021)=0.144
        # max_move = 3% * 0.144 = 0.43% < 5% => False
        assert is_price_reachable(100.0, 105.0, 5) is False

    def test_already_at_target(self):
        """已在目标价 => 可达"""
        assert is_price_reachable(100.0, 100.0, 10) is True


# ============================================================
# should_expire
# ============================================================

class TestShouldExpire:
    @pytest.fixture
    def base_signal(self):
        return {
            'signal_id': 'SIG-001',
            'priority': 'P1',
            'urgency': 'high',
            'window_start': '2026-07-27T09:30:00',
            'window_end': '2026-07-27T11:30:00',
        }

    def test_p0_exempt(self, base_signal):
        """P0信号在75%后也不应过期"""
        sig = dict(base_signal)
        sig['priority'] = 'P0'
        # 75% = 11:00, 当前 11:10 => 已过75%
        current = datetime(2026, 7, 27, 11, 10)
        assert should_expire(sig, current) is False

    def test_non_p0_before_75pct(self, base_signal):
        """非P0在75%前 => 不应过期"""
        # 75% = 11:00, 当前 10:30 => 未到75%
        current = datetime(2026, 7, 27, 10, 30)
        assert should_expire(base_signal, current) is False

    def test_non_p0_after_75pct(self, base_signal):
        """非P0在75%后 => 应过期"""
        # 75% = 11:00, 当前 11:10 => 已过75%
        current = datetime(2026, 7, 27, 11, 10)
        assert should_expire(base_signal, current) is True

    def test_non_p0_exactly_at_75pct(self, base_signal):
        """非P0恰好在75%时刻 => 应过期 (>= 判定)"""
        # 75% = 11:00, 当前恰好在 11:00
        current = datetime(2026, 7, 27, 11, 0)
        assert should_expire(base_signal, current) is True

    def test_missing_window_returns_false(self, base_signal):
        """缺少窗口信息 => 保守不触发"""
        sig = dict(base_signal)
        del sig['window_start']
        current = datetime(2026, 7, 27, 12, 0)
        assert should_expire(sig, current) is False


# ============================================================
# sort_by_urgency
# ============================================================

class TestSortByUrgency:
    def test_mixed_sort(self):
        """混合排序: 高P0 > 高P1 > 低P1 > 高P2 > 低P2"""
        signals = [
            {'id': 'a', 'urgency': 'low',  'priority': 'P2'},
            {'id': 'b', 'urgency': 'high', 'priority': 'P0'},
            {'id': 'c', 'urgency': 'low',  'priority': 'P1'},
            {'id': 'd', 'urgency': 'high', 'priority': 'P1'},
            {'id': 'e', 'urgency': 'high', 'priority': 'P2'},
        ]
        result = sort_by_urgency(signals)
        ids = [s['id'] for s in result]
        assert ids == ['b', 'd', 'c', 'e', 'a']

    def test_same_urgency_different_priority(self):
        """同紧不同优: 高P0 > 高P1 > 高P2"""
        signals = [
            {'id': 'a', 'urgency': 'high', 'priority': 'P2'},
            {'id': 'b', 'urgency': 'high', 'priority': 'P0'},
        ]
        result = sort_by_urgency(signals)
        assert result[0]['id'] == 'b'

    def test_same_priority_different_urgency(self):
        """同优不同紧: 高P1 > 低P1"""
        signals = [
            {'id': 'a', 'urgency': 'low',  'priority': 'P1'},
            {'id': 'b', 'urgency': 'high', 'priority': 'P1'},
        ]
        result = sort_by_urgency(signals)
        assert result[0]['id'] == 'b'

    def test_stable_sort(self):
        """排序稳定性: 同权重保持原顺序"""
        signals = [
            {'id': 'first',  'urgency': 'high', 'priority': 'P1'},
            {'id': 'second', 'urgency': 'high', 'priority': 'P1'},
        ]
        result = sort_by_urgency(signals)
        assert result[0]['id'] == 'first'
        assert result[1]['id'] == 'second'


# ============================================================
# check_main_backup_paths
# ============================================================

class TestCheckMainBackupPaths:
    def test_has_backup(self):
        """同时有主路径和备选路径"""
        sig = {'main_condition': 'price < 5.0', 'backup_condition': 'volume > 1e6'}
        ok, reason = check_main_backup_paths(sig)
        assert ok is True
        assert reason == ''

    def test_no_backup(self):
        """缺少备选路径"""
        sig = {'main_condition': 'price < 5.0', 'backup_condition': ''}
        ok, reason = check_main_backup_paths(sig)
        assert ok is False
        assert '备选路径' in reason

    def test_empty_main_condition(self):
        """主触发条件为空"""
        sig = {'main_condition': '', 'backup_condition': 'volume > 1e6'}
        ok, reason = check_main_backup_paths(sig)
        assert ok is False
        assert '主触发条件' in reason


# ============================================================
# generate_graded_thresholds
# ============================================================

class TestGenerateGradedThresholds:
    def test_price_volume_thresholds(self):
        """价格97% + 量70%"""
        strict = {'price': 5.0, 'volume': 1000000}
        result = generate_graded_thresholds(strict)
        assert result['strict'] == strict
        assert result['loose']['price'] == 4.85  # 5.0 * 0.97
        assert result['loose']['volume'] == 700000  # 1e6 * 0.7

    def test_price_only(self):
        """仅有价格字段"""
        strict = {'price': 10.0}
        result = generate_graded_thresholds(strict)
        assert result['loose']['price'] == 9.7
        assert 'volume' not in result['loose']
