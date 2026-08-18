"""Tests for dashboard/notify.py — 企业微信信号触发通知（纯函数部分）.

测试解析 每日信号.md 的 `## 信号触发记录` 表、消息组装与去重逻辑。
不触碰真实 cache.db / 网络。
"""
import sys
from pathlib import Path

_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from dashboard.notify import (  # noqa: E402
    ACTIONABLE,
    parse_trigger_records,
    build_message,
    diff_new_triggers,
    _key_of,
)

# 真实格式样例（取自 reports/20260814/每日信号.md 的触发记录表）
SAMPLE = """## 信号触发记录

> 盘中分析执行时，若信号总表中"待执行"信号的触发条件满足，则在此追加触发记录。

| 触发时间 | 信号ID | 优先级 | 标的 | 操作类型 | 触发条件摘要 | 当前状态 | 建议操作 | 用户操作 |
|----------|--------|:---:|------|:------:|-------------|:------:|----------|:------:|
| 10:00 | SIG-20260814-04 | P1 | 电网ETF(159326) | 正T | 主路径：开盘1.692=昨收+量比1.15>0.7 | 已触发 | 正T买入半仓 | 待用户填写 |
| 10:00 | SIG-20260814-05 | P2 | 航空航天ETF(159227) | 观察 | 量比1.82>1.2+价格1.031站上1.02 | 已触发 | 观察确认 | 待用户填写 |
| 10:00 | SIG-20260814-06 | P2 | 半导体ETF(512480) | 观察 | 高开+1.31%>1% | 已废弃 | 观察确认 | 待用户填写 |
"""


def test_parse_trigger_records_basic():
    records = parse_trigger_records(SAMPLE)
    assert len(records) == 3
    r0 = records[0]
    assert r0["signal_id"] == "SIG-20260814-04"
    assert r0["priority"] == "P1"
    assert r0["ticker"] == "电网ETF(159326)"
    assert r0["action_type"] == "正T"
    assert r0["status"] == "已触发"
    assert "开盘1.692" in r0["condition"]
    assert "正T买入半仓" in r0["suggest"]


def test_parse_respects_section_and_status():
    records = parse_trigger_records(SAMPLE)
    statuses = {r["signal_id"]: r["status"] for r in records}
    assert statuses["SIG-20260814-06"] == "已废弃"


def test_parse_empty_or_missing_section():
    assert parse_trigger_records("") == []
    assert parse_trigger_records("## 信号总表\n\n| a | b |\n|---|---|\n| 1 | 2 |") == []
    assert parse_trigger_records(
        "## 信号触发记录\n\n> 暂无触发记录\n\n（暂无）") == []


def test_build_message_contains_key_fields():
    records = parse_trigger_records(SAMPLE)
    msg = build_message(records[0])
    assert "SIG-20260814-04" in msg
    assert "电网ETF(159326)" in msg
    assert "正T买入半仓" in msg
    assert "信号触发" in msg


def test_diff_new_triggers_filters_sent_and_non_actionable():
    records = parse_trigger_records(SAMPLE)
    sent = {_key_of(records[0])}  # SIG-04 已推送过
    new = diff_new_triggers(records, sent)
    ids = [r["signal_id"] for r in new]
    # SIG-04 已被 sent 过滤；SIG-06 已废弃不可操作
    assert ids == ["SIG-20260814-05"]


def test_diff_upgrade_status_is_actionable():
    rec = {"signal_id": "SIG-1", "trigger_time": "10:00", "status": "已升级"}
    assert "已升级" in ACTIONABLE
    assert diff_new_triggers([rec], set()) == [rec]
    rec["status"] = "已过期"
    assert diff_new_triggers([rec], set()) == []


def test_key_of_signal_plus_time():
    r = {"signal_id": "SIG-20260814-01", "trigger_time": "10:00"}
    assert _key_of(r) == "SIG-20260814-01|10:00"
