"""
position_sync.py 测试 — 可用金额解析/交叉验证/建仓份额计算
"""

import sys
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from position_sync import (
    parse_available_cash,
    verify_cash_change,
    calc_position_shares,
    POSITION_RATIOS,
)


# ============================================================
# parse_available_cash
# ============================================================

class TestParseAvailableCash:
    def test_plain_number(self):
        md = "## 0. 可用金额\n\n25701\n"
        assert parse_available_cash(md) == 25701

    def test_thousand_separator(self):
        md = "## 0. 可用金额\n\n25,701\n"
        assert parse_available_cash(md) == 25701

    def test_trailing_text(self):
        md = "## 0. 可用金额\n\n25701 元\n"
        assert parse_available_cash(md) == 25701

    def test_missing_section(self):
        md = "## 1. 当前持仓\n\n| 股票名称 | 代码 |\n"
        assert parse_available_cash(md) is None

    def test_non_numeric(self):
        md = "## 0. 可用金额\n\n未知\n"
        assert parse_available_cash(md) is None

    def test_real_file_shape(self):
        md = (
            "# 仓位\n\n"
            "## 0. 可用金额\n\n25701\n\n"
            "## 1. 当前持仓\n\n| 股票名称 | 代码 |\n"
        )
        assert parse_available_cash(md) == 25701


# ============================================================
# verify_cash_change
# ============================================================

class TestVerifyCashChange:
    def test_no_trades_no_change(self):
        assert verify_cash_change(10000, 10000, []) == []

    def test_buy_decreases_cash(self):
        trades = [{'direction': '买入', 'qty': 1000, 'price': 2.0}]
        assert verify_cash_change(10000, 8000, trades) == []

    def test_sell_increases_cash(self):
        trades = [{'direction': '卖出', 'qty': 500, 'price': 3.0}]
        assert verify_cash_change(10000, 11500, trades) == []

    def test_mixed_trades(self):
        trades = [
            {'direction': '买入', 'qty': 1000, 'price': 2.0},  # -2000
            {'direction': '卖出', 'qty': 500, 'price': 3.0},   # +1500
        ]
        assert verify_cash_change(10000, 9500, trades) == []

    def test_deviation_warns(self):
        trades = [{'direction': '买入', 'qty': 1000, 'price': 2.0}]
        warnings = verify_cash_change(10000, 7000, trades)  # 期望8000
        assert len(warnings) == 1
        assert '1000' in warnings[0]

    def test_tolerance_parameter(self):
        trades = [{'direction': '买入', 'qty': 1000, 'price': 2.0}]
        assert verify_cash_change(10000, 7999.5, trades, tolerance=1.0) == []
        assert len(verify_cash_change(10000, 7998.5, trades, tolerance=1.0)) == 1


# ============================================================
# calc_position_shares
# ============================================================

class TestCalcPositionShares:
    def test_normal_calc(self):
        # 25701 × 1/3 / 1.70 = 5039.4 → 5000
        assert calc_position_shares(25701, 1.70, 1 / 3) == 5000

    def test_round_to_lot(self):
        # 10000 × 1/3 / 2.0 = 1666.6 → 1600
        assert calc_position_shares(10000, 2.0, 1 / 3) == 1600

    def test_less_than_one_lot(self):
        # 500 × 1/3 / 2.0 = 83.3 → 不足100份 → 0
        assert calc_position_shares(500, 2.0, 1 / 3) == 0

    def test_zero_price(self):
        assert calc_position_shares(10000, 0, 1 / 3) == 0

    def test_zero_cash(self):
        assert calc_position_shares(0, 2.0, 1 / 3) == 0

    def test_ratios_defined(self):
        assert POSITION_RATIOS == {'open_high': 1 / 3, 'upgrade': 1 / 4, 'probe': 1 / 5}
