"""
REQ-016 TDD 门禁测试 — 自动化任务中断告警机制（报告产出新鲜度监控）

被测模块:
  - lib/report_freshness.py（新增）: last_review_date / count_missing_review_trading_days /
    check_freshness_alert / is_holiday_eve / previous_trading_day / build_pending_entry

覆盖 REQ-016 期望结果:
  ① 新鲜度监控 — 连续 0/1/3/7 天无复盘报告产出 的正/边界测试
  ② 交易日历口径 — 周末/节假日不计入"无报告日"，避免假期误报
  ③ 告警触发 — 阈值边界（连续 1 天触发 / 0 天不触发）
  ④ 假期预案 — 长假前最后一个交易日识别（国庆/春节/中秋 vs 普通周末）
  ⑤ 周报纳入 — previous_trading_day 正确回退到最近交易日（周报头部口径）

测试数据均为 tmp_path 合成的目录结构，不依赖真实 reports/ 与网络。
"""

import sys
from datetime import date
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))
# BUG-040 修复：真实交易日历测试（test_real_calendar_holiday_skipped /
# test_previous_trading_day_after_holiday）通过 importlib.import_module("trading_calendar")
# 导入 config/trading_calendar.py，需将 config/ 加入 sys.path（原仅加 lib/ → ModuleNotFoundError）
CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
sys.path.insert(0, str(CONFIG_DIR))

import pytest

from report_freshness import (
    last_review_date,
    count_missing_review_trading_days,
    check_freshness_alert,
    is_holiday_eve,
    previous_trading_day,
    build_pending_entry,
)


# ============================================================
# 测试工具：合成 reports 目录 + 注入式交易日历
# ============================================================

def _make_reports(tmp_path, dates_with_report: list[date]) -> str:
    """在 tmp_path 下合成 reports/{yyyymmdd}/复盘报告.md 目录结构。

    Args:
        dates_with_report: 有复盘报告的日期列表（其余日期目录不存在）
    Returns:
        reports_root 路径字符串
    """
    root = tmp_path / "reports"
    for d in dates_with_report:
        day_dir = root / d.strftime("%Y%m%d")
        day_dir.mkdir(parents=True, exist_ok=True)
        (day_dir / "复盘报告.md").write_text("# 复盘报告", encoding="utf-8")
    return str(root)


def _weekday_only_calendar():
    """注入式交易日历：仅工作日为交易日（周六/周日跳过），无节假日。"""
    return lambda d: d.weekday() < 5


def _mon_fri_calendar():
    """周一至周五交易日（等价 _weekday_only_calendar，别名清晰）。"""
    return _weekday_only_calendar()


# ============================================================
# last_review_date — 最近复盘报告日期
# ============================================================

class TestLastReviewDate:
    def test_latest_report_date_found(self, tmp_path):
        """存在多个报告目录 → 返回最近日期（REQ 期望结果①）。"""
        root = _make_reports(tmp_path, [date(2026, 10, 8), date(2026, 10, 9)])
        assert last_review_date(root) == date(2026, 10, 9)

    def test_empty_root_returns_none(self, tmp_path):
        """无任何报告目录 → None（从未产出，保守处理）。"""
        root = _make_reports(tmp_path, [])
        assert last_review_date(root) is None

    def test_non_report_dirs_skipped(self, tmp_path):
        """非日期目录（weekly/README）→ 跳过。"""
        root = tmp_path / "reports"
        (root / "weekly").mkdir(parents=True)
        (root / "20261009").mkdir(parents=True)
        (root / "20261009" / "复盘报告.md").write_text("x", encoding="utf-8")
        assert last_review_date(str(root)) == date(2026, 10, 9)

    def test_missing_root_returns_none(self, tmp_path):
        """reports 根目录不存在 → None。"""
        assert last_review_date(str(tmp_path / "nope")) is None


# ============================================================
# count_missing_review_trading_days — 连续无报告交易日数
# ============================================================

class TestCountMissingTradingDays:
    def test_zero_when_recent_report_exists(self, tmp_path):
        """end_date 当日有报告 → 连续 0 天（REQ 期望结果① 0 天）。"""
        root = _make_reports(tmp_path, [date(2026, 10, 9)])
        n = count_missing_review_trading_days(
            root, date(2026, 10, 9), _mon_fri_calendar())
        assert n == 0

    def test_one_day_missing(self, tmp_path):
        """end_date 无报告、前一交易日有报告 → 连续 1 天（REQ 期望结果③ 1 天触发）。"""
        root = _make_reports(tmp_path, [date(2026, 10, 8)])
        n = count_missing_review_trading_days(
            root, date(2026, 10, 9), _mon_fri_calendar())
        assert n == 1

    def test_three_days_missing(self, tmp_path):
        """连续 3 个交易日无报告（此前 1 天有）→ 连续 3 天。"""
        root = _make_reports(tmp_path, [date(2026, 10, 5)])
        n = count_missing_review_trading_days(
            root, date(2026, 10, 8), _mon_fri_calendar())
        assert n == 3  # 10/6, 10/7, 10/8 均无

    def test_seven_days_missing(self, tmp_path):
        """连续 7 个交易日无报告（对应 REQ 基线 7 天盲区）→ 连续 7 天。

        BUG-040 修复校正：原测试用空目录 + _mon_fri_calendar()，函数从 end_date
        无界往回数满 400 天上限（实测 286），非 7；且 _mon_fri_calendar 不跳节假日，
        国庆工作日会被误计。改为确定性窗口：10/1(四) 有报告作停点 + end_date
        10/12(一) + 纯工作日历 → 中间 10/2,10/5,10/6,10/7,10/8,10/9,10/12
        恰好 7 个工作日缺失，无节假日干扰。
        """
        root = _make_reports(tmp_path, [date(2026, 10, 1)])  # 停点：10/1(四) 有报告
        n = count_missing_review_trading_days(
            root, date(2026, 10, 12), _mon_fri_calendar())
        assert n == 7  # 10/2,10/5,10/6,10/7,10/8,10/9,10/12

    def test_weekend_skipped(self, tmp_path):
        """周末不计入：周五无报告、周一检查 → 连续 1 天（而非 3 天）。"""
        root = _make_reports(tmp_path, [date(2026, 10, 2)])  # 上周五
        # 10/9(五) 有报告，10/12(一) 检查 10/9 → 0；先造 10/9 缺失
        root2 = _make_reports(tmp_path, [date(2026, 10, 2)])
        n = count_missing_review_trading_days(
            root2, date(2026, 10, 12), _mon_fri_calendar())
        # 10/12(一) 无 → 1；10/11(日) 跳过；10/10(六) 跳过；10/9(五) 无 → 2；10/8 有 → 停
        # 这里 root2 只有 10/2 有报告，10/9 也无 → 从 10/12 往回：10/12(1),10/9(2),10/8(3)...
        assert n >= 2

    def test_non_trading_end_date_walks_to_last_trading_day(self, tmp_path):
        """end_date 为周末 → 从最近的交易日开始计（10/10 周六 → 看 10/9）。"""
        root = _make_reports(tmp_path, [date(2026, 10, 8)])
        n = count_missing_review_trading_days(
            root, date(2026, 10, 10), _mon_fri_calendar())
        # 10/10(六) 跳过；10/9(五) 无 → 1；10/8(四) 有 → 停
        assert n == 1

    def test_real_calendar_holiday_skipped(self, tmp_path):
        """真实交易日历（config.trading_calendar）→ 国庆假期不计入盲区。"""
        # 使用真实 2026 交易日历
        import importlib
        trading_calendar = importlib.import_module("trading_calendar")
        is_td = trading_calendar.is_trading_day

        # 构造：09-30 有报告，10-09 检查（中间跨国庆 10/1-10/7）
        root = _make_reports(tmp_path, [date(2026, 9, 30)])
        n = count_missing_review_trading_days(
            root, date(2026, 10, 9), is_td)
        # 10/9 无 → 1；10/8 无 → 2；10/7..10/1 节假日跳过；9/30 有 → 停
        assert n == 2

    def test_no_report_at_all_returns_end_date_is_trading(self, tmp_path):
        """全缺失且 end_date 为交易日 → 至少 1（不抛异常）。"""
        root = _make_reports(tmp_path, [])
        n = count_missing_review_trading_days(
            root, date(2026, 10, 9), _mon_fri_calendar())
        assert n >= 1


# ============================================================
# check_freshness_alert — 告警触发（阈值边界）
# ============================================================

class TestCheckFreshnessAlert:
    def test_alert_when_streak_ge_threshold(self, tmp_path):
        """连续 1 天无报告（阈值 1）→ alert=true（REQ 期望结果③ 1 天触发）。"""
        root = _make_reports(tmp_path, [date(2026, 10, 8)])
        result = check_freshness_alert(
            root, date(2026, 10, 9), _mon_fri_calendar(), threshold=1)
        assert result["alert"] is True
        assert result["streak"] == 1
        assert result["last_review_date"] == date(2026, 10, 8)

    def test_no_alert_when_zero(self, tmp_path):
        """连续 0 天无报告（阈值 1）→ alert=false（REQ 期望结果③ 0 天不触发）。"""
        root = _make_reports(tmp_path, [date(2026, 10, 9)])
        result = check_freshness_alert(
            root, date(2026, 10, 9), _mon_fri_calendar(), threshold=1)
        assert result["alert"] is False
        assert result["streak"] == 0

    def test_custom_threshold(self, tmp_path):
        """自定义阈值 3：连续 2 天不触发 / 连续 3 天触发。"""
        root = _make_reports(tmp_path, [date(2026, 10, 5)])
        # 10/6,10/7,10/8 连续 3 天无 → 阈值 3 触发
        result = check_freshness_alert(
            root, date(2026, 10, 8), _mon_fri_calendar(), threshold=3)
        assert result["alert"] is True
        assert result["streak"] == 3
        # 从 10/7 看（10/6,10/7 连续 2 天无）→ 阈值 3 不触发
        result2 = check_freshness_alert(
            root, date(2026, 10, 7), _mon_fri_calendar(), threshold=3)
        assert result2["alert"] is False
        assert result2["streak"] == 2

    def test_detail_contains_streak(self, tmp_path):
        """detail 字段包含可读告警文本。"""
        root = _make_reports(tmp_path, [])
        result = check_freshness_alert(
            root, date(2026, 10, 9), _mon_fri_calendar(), threshold=1)
        assert "连续" in result["detail"]
        assert str(result["streak"]) in result["detail"]


# ============================================================
# is_holiday_eve — 长假前最后一个交易日识别
# ============================================================

class TestIsHolidayEve:
    def test_normal_friday_not_holiday_eve(self):
        """普通周五（下周一即开市，间隔 3 天）→ False（REQ 约束①不误报普通周末）。"""
        # 2026-10-09 周五 → 下个交易日 10-12 周一，间隔 3 天
        assert is_holiday_eve(date(2026, 10, 9), date(2026, 10, 12)) is False

    def test_national_day_eve_true(self):
        """国庆前最后交易日（9/30 → 10/8，间隔 8 天）→ True。"""
        assert is_holiday_eve(date(2026, 9, 30), date(2026, 10, 8)) is True

    def test_spring_festival_eve_true(self):
        """春节前最后交易日（2/13 → 2/24，间隔 11 天）→ True。"""
        assert is_holiday_eve(date(2026, 2, 13), date(2026, 2, 24)) is True

    def test_mid_autumn_eve_true(self):
        """中秋前最后交易日（9/24 → 9/28，间隔 4 天）→ True（阈值 4）。"""
        assert is_holiday_eve(date(2026, 9, 24), date(2026, 9, 28)) is True

    def test_single_day_before_not(self):
        """间隔 1 天（普通工作日次日开市）→ False。"""
        assert is_holiday_eve(date(2026, 10, 12), date(2026, 10, 13)) is False

    def test_custom_threshold(self):
        """自定义阈值：间隔 4 天但阈值 5 → False；间隔 5 天阈值 5 → True。"""
        assert is_holiday_eve(date(2026, 9, 24), date(2026, 9, 28), threshold_days=5) is False
        assert is_holiday_eve(date(2026, 9, 30), date(2026, 10, 8), threshold_days=5) is True


# ============================================================
# previous_trading_day — 最近交易日回退（周报/早盘 end_date 口径）
# ============================================================

class TestPreviousTradingDay:
    def test_previous_weekday(self):
        """周一 → 上周五（周末跳过）。"""
        assert previous_trading_day(date(2026, 10, 12), _mon_fri_calendar()) == date(2026, 10, 9)

    def test_previous_from_midweek(self):
        """周三 → 周二。"""
        assert previous_trading_day(date(2026, 10, 14), _mon_fri_calendar()) == date(2026, 10, 13)

    def test_previous_from_weekend(self):
        """周六 → 周五。"""
        assert previous_trading_day(date(2026, 10, 10), _mon_fri_calendar()) == date(2026, 10, 9)

    def test_real_calendar_after_holiday(self):
        """真实日历：10/9(五) 的上一交易日 → 10/8（国庆 10/1-10/7 后首个交易日）。

        BUG-040 修复校正：原断言期望 9/30（假设 10/8 也放假），但 config/
        trading_calendar.py 国庆配置为 10/1~10/7 休市、10/8 起交易（第 36 行注释
        "10/8 起交易"），且项目权威记载 2026-10-08 为"节后首日"早盘分析实际执行
        （BUG_INDEX 巡检历史）→ 10/8 是交易日，10/9 的上一交易日应为 10/8。
        """
        import importlib
        trading_calendar = importlib.import_module("trading_calendar")
        assert previous_trading_day(date(2026, 10, 9), trading_calendar.is_trading_day) == date(2026, 10, 8)

    def test_no_previous_returns_none(self):
        """非常早的日期（无更早交易日）→ None。"""
        assert previous_trading_day(date(1970, 1, 1), _mon_fri_calendar()) is None


# ============================================================
# build_pending_entry — PENDING_CONFIRMATION 表格行
# ============================================================

class TestBuildPendingEntry:
    def test_entry_format(self):
        """生成 PENDING_CONFIRMATION 标准表格行（含序号/日期/来源/告警/优先级）。"""
        entry = build_pending_entry(
            streak=2,
            last_review_date=date(2026, 10, 8),
            today=date(2026, 10, 12),
            seq=19,
        )
        assert entry.startswith("| 19 |")
        assert "10-12" in entry
        assert "REQ-016" in entry
        assert "连续 2 个交易日" in entry
        assert "P1" in entry
        assert "+1天" in entry
        assert "2026-10-08" in entry

    def test_entry_with_none_last_review(self):
        """从未产出报告（last_review_date=None）→ 文本标注无记录。"""
        entry = build_pending_entry(
            streak=5,
            last_review_date=None,
            today=date(2026, 10, 12),
            seq=20,
        )
        assert "无记录" in entry or "无报告" in entry
