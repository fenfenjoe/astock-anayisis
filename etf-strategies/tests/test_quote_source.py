"""行情多源容错测试（backtest/quote_source.py）。

验证：健康探测（连续失败降级/恢复回切）+ 多源切换编排（主→备→兜底）。
全部 mock，不依赖真实网络。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pytest


# ═══════════════════════════════════════════════════════════════
# SourceHealth：单源健康状态机
# ═══════════════════════════════════════════════════════════════

def test_health_initial_up():
    from backtest.quote_source import SourceHealth
    h = SourceHealth(name="tencent", max_fail=3, recovery_probes=2)
    assert h.is_up() is True
    assert h.consecutive_failures == 0


def test_health_down_after_max_failures():
    from backtest.quote_source import SourceHealth
    h = SourceHealth(name="eastmoney", max_fail=3, recovery_probes=2)
    for _ in range(3):
        h.record_failure()
    assert h.is_down() is True
    assert h.consecutive_failures == 3


def test_health_resets_on_success():
    from backtest.quote_source import SourceHealth
    h = SourceHealth(name="eastmoney", max_fail=3, recovery_probes=2)
    h.record_failure()
    h.record_failure()
    h.record_success()  # 成功重置
    assert h.consecutive_failures == 0
    assert h.is_up() is True


def test_health_recovery_probe():
    """down 后需要连续 recovery_probes 次成功才回 up"""
    from backtest.quote_source import SourceHealth
    h = SourceHealth(name="eastmoney", max_fail=2, recovery_probes=2)
    h.record_failure()
    h.record_failure()
    assert h.is_down() is True
    # 第一次成功：进入探测期，仍未 up
    h.record_success()
    assert h.is_down() is True
    # 第二次成功：恢复 up
    h.record_success()
    assert h.is_up() is True


# ═══════════════════════════════════════════════════════════════
# MultiSourceQuote：多源切换编排
# ═══════════════════════════════════════════════════════════════

def _ok_source(name, value):
    """构造一个总是成功返回 value 的源"""
    class S:
        def __init__(self):
            self.calls = []
        def fetch(self):
            self.calls.append(name)
            return value
        def __repr__(self):
            return name
    return S()


def _fail_source(name, exc=ConnectionError("down")):
    """构造一个总是失败的源"""
    class S:
        def __init__(self):
            self.calls = []
        def fetch(self):
            self.calls.append(name)
            raise exc
        def __repr__(self):
            return name
    return S()


def test_multisource_uses_primary_when_healthy():
    from backtest.quote_source import MultiSourceQuote
    primary = _ok_source("tencent", {"close": 4.385})
    backup = _ok_source("eastmoney", {"close": 4.386})
    ms = MultiSourceQuote(sources=[primary, backup], max_fail=2, recovery_probes=2)
    result = ms.fetch()
    assert result == {"close": 4.385}
    assert primary.calls == ["tencent"]  # 只用了主源
    assert backup.calls == []


def test_multisource_falls_back_to_backup():
    from backtest.quote_source import MultiSourceQuote
    primary = _fail_source("tencent")
    backup = _ok_source("eastmoney", {"close": 4.386})
    ms = MultiSourceQuote(sources=[primary, backup], max_fail=2, recovery_probes=2)
    result = ms.fetch()
    assert result == {"close": 4.386}
    assert backup.calls == ["eastmoney"]


def test_multisource_all_fail_raises():
    from backtest.quote_source import MultiSourceQuote
    primary = _fail_source("tencent")
    backup = _fail_source("eastmoney", exc=RuntimeError("no data"))
    ms = MultiSourceQuote(sources=[primary, backup], max_fail=1, recovery_probes=2)
    with pytest.raises(RuntimeError, match="所有行情源均不可用"):
        ms.fetch()


def test_multisource_marks_primary_down_then_recovers():
    """主源连续失败后标记 down，恢复后自动回切（down 源照常尝试探测）"""
    from backtest.quote_source import MultiSourceQuote

    class FlakySource:
        """主源：前2次失败，之后成功"""
        def __init__(self):
            self.calls = 0
        def fetch(self):
            self.calls += 1
            if self.calls <= 2:
                raise ConnectionError("flaky")
            return {"close": 4.385}
        def __repr__(self):
            return "flaky"

    primary = FlakySource()
    backup = _ok_source("eastmoney", {"close": 4.386})
    ms = MultiSourceQuote(sources=[primary, backup], max_fail=2, recovery_probes=1)

    # 前2次：主源失败 → 用备源；主源连续2次失败 → down
    r1 = ms.fetch()
    assert r1 == {"close": 4.386}
    r2 = ms.fetch()
    assert r2 == {"close": 4.386}
    # 主源 down，但第3次仍尝试探测 → 已恢复 → 回切主源
    r3 = ms.fetch()
    assert r3["close"] == 4.385  # 主源恢复后优先主源
    health = ms.sources[0][1]
    assert health.consecutive_failures == 0


def test_multisource_down_source_probed_not_blocking():
    """down 源仍被探测（照常尝试），失败不阻塞返回备源结果"""
    from backtest.quote_source import MultiSourceQuote

    class DownPrimary:
        def __init__(self):
            self.calls = 0
        def fetch(self):
            self.calls += 1
            raise ConnectionError("down")
        def __repr__(self):
            return "downprimary"

    primary = DownPrimary()
    backup = _ok_source("eastmoney", {"close": 4.386})
    ms = MultiSourceQuote(sources=[primary, backup], max_fail=1, recovery_probes=2)

    ms.fetch()  # 第1次：primary 失败 → down（max_fail=1），用 backup
    assert primary.calls == 1
    # 第2次：primary 已 down，但照常尝试探测（失败），结果仍用 backup
    r2 = ms.fetch()
    assert r2 == {"close": 4.386}
    assert primary.calls == 2  # down 源仍被探测
    assert backup.calls == ["eastmoney", "eastmoney"]


# ═══════════════════════════════════════════════════════════════
# 交叉校验：双源价差一致性
# ═══════════════════════════════════════════════════════════════

def test_cross_validate_match():
    """双源一致 → match=True，无告警"""
    from backtest.quote_source import cross_validate_series
    p = {"2026-10-08": 4.389, "2026-10-09": 4.385}
    b = {"2026-10-08": 4.390, "2026-10-09": 4.384}
    r = cross_validate_series(p, b, "510300")
    assert r["match"] is True
    assert r["dates"] == 2


def test_cross_validate_mismatch_warns():
    """双源价差超 0.5% → match=False（打 WARN，不抛异常）"""
    from backtest.quote_source import cross_validate_series
    p = {"2026-10-08": 4.389, "2026-10-09": 4.385}
    b = {"2026-10-08": 4.100, "2026-10-09": 4.384}  # 10-08 价差 ~6.6%
    r = cross_validate_series(p, b, "510300")
    assert r["match"] is False
    assert r["max_diff_pct"] > 0.5


def test_cross_validate_no_common_dates_skips():
    """无公共日期 → 跳过校验，不误报 mismatch"""
    from backtest.quote_source import cross_validate_series
    p = {"2026-10-08": 4.389}
    b = {"2026-10-09": 4.385}
    r = cross_validate_series(p, b, "510300")
    assert r["match"] is True
    assert r["reason"] == "无公共日期，跳过校验"


def test_cross_validate_df_alignment():
    """DataFrame 版：按 close 列对齐比较"""
    import pandas as pd
    from backtest.quote_source import cross_validate_df
    idx = pd.to_datetime(["2026-10-08", "2026-10-09"])
    p = pd.DataFrame({"close": [4.389, 4.385]}, index=idx)
    b = pd.DataFrame({"close": [4.390, 4.384]}, index=idx)
    r = cross_validate_df(p, b, "510300")
    assert r["match"] is True
    assert r["dates"] == 2
