"""
REQ-003: 早盘板块扫描池增加"业绩驱动"类别 + 涨停潮建仓联防 + 证伪阈值距离 测试套件

被测源码:
  - lib/signal_design.py  — 新增 REQ-003 校验函数

覆盖要点:
  - is_earnings_window        — 财报披露窗口判断 (8/31中报 / 4/30年报 / 10/31三季报)
  - check_mainline_guard      — 涨停潮建仓"主线不弱化"联防 (回落>1% 降级观察)
  - check_falsify_distance    — 证伪阈值与触发价 ≥0.5% 距离校验
"""

import pytest
from datetime import date
from lib.signal_design import (
    is_earnings_window,
    check_mainline_guard,
    check_falsify_distance,
)


# ============================================================
# is_earnings_window
# ============================================================

class TestIsEarningsWindow:
    def test_mid_report_window(self):
        """中报窗口内 (8/20) => True"""
        assert is_earnings_window(date(2026, 8, 20)) is True

    def test_deadline_830(self):
        """中报截止日 8/31 => True"""
        assert is_earnings_window(date(2026, 8, 31)) is True

    def test_annual_report_window(self):
        """年报窗口内 (4/20) => True"""
        assert is_earnings_window(date(2026, 4, 20)) is True

    def test_q3_window(self):
        """三季报窗口内 (10/20) => True"""
        assert is_earnings_window(date(2026, 10, 20)) is True

    def test_outside_window(self):
        """非财报窗口 (1/15) => False"""
        assert is_earnings_window(date(2026, 1, 15)) is False

    def test_after_deadline(self):
        """截止日之后 (9/15) => False"""
        assert is_earnings_window(date(2026, 9, 15)) is False

    def test_str_input(self):
        """支持 ISO 字符串输入"""
        assert is_earnings_window("2026-08-20") is True


# ============================================================
# check_mainline_guard
# ============================================================

class TestCheckMainlineGuard:
    def test_mainline_weakens(self):
        """主线回落 >1% => 降级观察 (不通过)"""
        ok, reason = check_mainline_guard(-1.5)
        assert ok is False
        assert '降级' in reason

    def test_mainline_flat(self):
        """主线平盘 => 通过"""
        ok, reason = check_mainline_guard(0.0)
        assert ok is True
        assert reason == ''

    def test_mainline_rises(self):
        """主线上涨 => 通过"""
        ok, reason = check_mainline_guard(0.8)
        assert ok is True
        assert reason == ''

    def test_slight_weakness_below_threshold(self):
        """回落 -0.8% (未达 1%) => 通过"""
        ok, reason = check_mainline_guard(-0.8)
        assert ok is True
        assert reason == ''

    def test_exactly_at_threshold(self):
        """恰好回落 1.0% => 按边界处理为不通过 (回落>=1% 即降级)"""
        ok, reason = check_mainline_guard(-1.0)
        assert ok is False
        assert '降级' in reason

    def test_custom_threshold(self):
        """自定义阈值 2% => 回落 1.5% 通过, 回落 2.5% 不通过"""
        ok1, _ = check_mainline_guard(-1.5, threshold=2.0)
        ok2, _ = check_mainline_guard(-2.5, threshold=2.0)
        assert ok1 is True
        assert ok2 is False


# ============================================================
# check_falsify_distance
# ============================================================

class TestCheckFalsifyDistance:
    def test_sufficient_distance(self):
        """距离 >=0.5% => 通过 (1.95 触发 / 1.94 证伪: 0.51%)"""
        ok, pct = check_falsify_distance(1.95, 1.94)
        assert ok is True
        assert pct >= 0.5

    def test_insufficient_distance(self):
        """距离 <0.5% => 不通过 (1.95 / 1.949: 0.05%)"""
        ok, pct = check_falsify_distance(1.95, 1.949)
        assert ok is False
        assert pct < 0.5

    def test_zero_distance(self):
        """证伪价 == 触发价 => 不通过 (0%)"""
        ok, pct = check_falsify_distance(1.95, 1.95)
        assert ok is False
        assert pct == 0.0

    def test_reversed_direction(self):
        """触发价低于证伪价 (对称距离) => 同样校验绝对值"""
        ok, pct = check_falsify_distance(1.94, 1.95)
        assert ok is True
        assert pct >= 0.5

    def test_exactly_at_minimum(self):
        """恰好 0.5% => 边界通过 (>= 判定)"""
        # 0.5% of 2.0 = 0.01
        ok, pct = check_falsify_distance(2.0, 1.99)
        assert ok is True
        assert abs(pct - 0.5) < 1e-9

    def test_invalid_zero_trigger(self):
        """触发价为 0 => 非法输入, 返回不通过"""
        ok, pct = check_falsify_distance(0.0, 0.1)
        assert ok is False
        assert pct is None
