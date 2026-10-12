"""signal_tracking_cloud 单测 — 云库读写层（Phase 3 信号云库化）

覆盖：JSON→云表行映射（固定列集合）、云表行→JSON 反向、本地 JSON 兜底读取、
云库不可达时的降级路径。云库真实读写为可选（REAL_CLOUD=1 时执行，默认跳过，
避免单测依赖网络）。
"""
import json
import os
import sys
from pathlib import Path

import pytest

_AUTOMATION = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_AUTOMATION))

from lib import signal_tracking_cloud as stc  # noqa: E402

REAL_CLOUD = os.environ.get("REAL_CLOUD") == "1"


def _sample_sig():
    return {
        "signal_id": "SIG-20260908-TEST",
        "ticker": "512480",
        "name": "半导体ETF",
        "trade_type": "buy",
        "direction": "buy",
        "priority": "P1",
        "urgency": "high",
        "expected_trigger_rate": 40.0,
        "target_pct": 3.0,
        "stop_pct": -2.0,
        "target_price": None,
        "stop_price": None,
        "expected_return_date": "",
        "trigger_date": "2026-09-08",
        "entry_price": 1.234,
        "shares": 1000,
        "status": "triggered",
        "status_history": [{"date": "2026-09-08", "status": "triggered", "note": "test"}],
        "avoided_loss": None,
        "settle_date": None,
        "exit_date": None,
        "settle_price": None,
        "pnl": None,
        "holding_days": None,
        "outcome": None,
    }


class TestToRow:
    def test_non_none_columns(self):
        """to_row 只含非 None 列（任务4：跳过 None 列，upsert 不覆盖盘中/复盘已写字段）。"""
        row = stc.to_row(_sample_sig())
        # 关键映射
        assert row["signal_id"] == "SIG-20260908-TEST"
        assert row["signal_date"] == "2026-09-08"  # trigger_date → signal_date
        assert "target_price" not in row  # None 值列不出现
        assert row["created_at"]  # 自动填充
        assert row["updated_at"]

    def test_sell_columns_absent_when_none(self):
        """卖出信号列（cost_basis/sell_price）为 None 时不出现（任务4 跳过 None 列）。"""
        row = stc.to_row(_sample_sig())
        assert "cost_basis" not in row
        assert "sell_price" not in row


class TestFromRow:
    def test_roundtrip(self):
        """to_row → from_row 保留核心字段，signal_date 还原为 trigger_date。"""
        sig = _sample_sig()
        row = stc.to_row(sig)
        back = stc.from_row(row)
        assert back["signal_id"] == sig["signal_id"]
        assert back["trigger_date"] == "2026-09-08"
        assert back["ticker"] == "512480"
        assert back["status"] == "triggered"
        assert back["expected_trigger_rate"] == 40.0

    def test_none_filtered(self):
        """from_row 过滤掉 None 列（与 JSON 结构一致）。"""
        row = stc.to_row(_sample_sig())
        back = stc.from_row(row)
        assert "cost_basis" not in back
        assert "pnl" not in back


class TestLocalFallback:
    def test_local_load_missing_file(self, tmp_path, monkeypatch):
        """本地 JSON 不存在 → 返回 []（不抛错）。"""
        monkeypatch.setattr(stc, "LOCAL_TRACKING", tmp_path / "nope.json")
        assert stc.local_load_signals() == []

    def test_local_load_valid(self, tmp_path, monkeypatch):
        """本地 JSON 有效 → 返回 signals。"""
        f = tmp_path / "signal_tracking.json"
        f.write_text(json.dumps({"signals": [_sample_sig()]}, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(stc, "LOCAL_TRACKING", f)
        sigs = stc.local_load_signals()
        assert len(sigs) == 1
        assert sigs[0]["signal_id"] == "SIG-20260908-TEST"

    def test_load_signals_cloud_disabled(self, monkeypatch):
        """云库不可用 → load_signals 走本地兜底。"""
        monkeypatch.setattr(stc, "cloud_enabled", lambda: False)
        # 用临时本地文件
        import tempfile
        tmp = Path(tempfile.mkdtemp()) / "signal_tracking.json"
        tmp.write_text(json.dumps({"signals": [_sample_sig()]}, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(stc, "LOCAL_TRACKING", tmp)
        sigs = stc.load_signals()
        assert len(sigs) == 1

    def test_upsert_signals_cloud_disabled_mirror(self, tmp_path, monkeypatch):
        """云库不可用 → upsert_signals 仍镜像本地（不抛错）。"""
        f = tmp_path / "signal_tracking.json"
        f.write_text(json.dumps({"signals": []}, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(stc, "LOCAL_TRACKING", f)
        monkeypatch.setattr(stc, "cloud_enabled", lambda: False)
        ok = stc.upsert_signals([_sample_sig()], mirror_local=True)
        assert ok == 0  # 云库写失败
        # 本地镜像仍写入
        data = json.loads(f.read_text(encoding="utf-8"))
        assert len(data["signals"]) == 1


# ═══════════════════════════════════════════════════════════════
# 终态状态保护（2026-09-21 BUG-FIX）：盘中检查不得回退 已执行/已结算 信号
# ═══════════════════════════════════════════════════════════════

class TestProtectTerminalStatus:
    """protect_terminal_status 纯函数：已执行/部分执行/已结算 状态不可被回退。

    事故背景（2026-09-21）：用户已在 Dashboard 一键执行 通信ETF/创新药ETF
    （云库 status=executed），盘中检查重新解析 markdown 后整体 upsert，
    把 executed 覆盖成 expired/triggered。本保护按"终态等级"拦截降级。
    """

    def _rec(self, sid, status):
        return {"signal_id": sid, "status": status}

    def test_executed_not_downgraded_to_expired(self):
        """已执行 → 已过期 被拦截（保留 executed）— 今日事故主场景。"""
        existing = {"SIG-01": "executed"}
        out = stc.protect_terminal_status([self._rec("SIG-01", "expired")], existing)
        assert out[0]["status"] == "executed"

    def test_executed_not_downgraded_to_triggered(self):
        """已执行 → 已触发 被拦截 — 今日事故另一场景。"""
        existing = {"SIG-02": "executed"}
        out = stc.protect_terminal_status([self._rec("SIG-02", "triggered")], existing)
        assert out[0]["status"] == "executed"

    def test_executed_not_downgraded_to_open(self):
        existing = {"SIG-01": "executed"}
        out = stc.protect_terminal_status([self._rec("SIG-01", "open")], existing)
        assert out[0]["status"] == "executed"

    def test_settled_not_downgraded_to_executed(self):
        """已结算是最高终态，不可被降回已执行。"""
        existing = {"SIG-03": "settled"}
        out = stc.protect_terminal_status([self._rec("SIG-03", "executed")], existing)
        assert out[0]["status"] == "settled"

    def test_partial_executed_not_downgraded(self):
        existing = {"SIG-04": "partial_executed"}
        out = stc.protect_terminal_status([self._rec("SIG-04", "expired")], existing)
        assert out[0]["status"] == "partial_executed"

    def test_open_to_triggered_allowed(self):
        """未触发 → 已触发 是升级，放行。"""
        existing = {"SIG-05": "open"}
        out = stc.protect_terminal_status([self._rec("SIG-05", "triggered")], existing)
        assert out[0]["status"] == "triggered"

    def test_triggered_to_expired_allowed(self):
        """已触发 → 已过期（窗口过期/回落）是盘中正常流转，放行。"""
        existing = {"SIG-06": "triggered"}
        out = stc.protect_terminal_status([self._rec("SIG-06", "expired")], existing)
        assert out[0]["status"] == "expired"

    def test_triggered_to_executed_allowed(self):
        """已触发 → 已执行（确认执行）是升级，放行。"""
        existing = {"SIG-07": "triggered"}
        out = stc.protect_terminal_status([self._rec("SIG-07", "executed")], existing)
        assert out[0]["status"] == "executed"

    def test_expired_not_revived_to_triggered(self):
        """已过期不可被复活回已触发。"""
        existing = {"SIG-08": "expired"}
        out = stc.protect_terminal_status([self._rec("SIG-08", "triggered")], existing)
        assert out[0]["status"] == "expired"

    def test_no_existing_status_unchanged(self):
        """云库无该信号（新增）→ 原样保留。"""
        out = stc.protect_terminal_status([self._rec("SIG-NEW", "triggered")], {})
        assert out[0]["status"] == "triggered"

    def test_does_not_mutate_input(self):
        """不改入参记录（返回新列表）。"""
        rec = self._rec("SIG-01", "expired")
        stc.protect_terminal_status([rec], {"SIG-01": "executed"})
        assert rec["status"] == "expired"


class TestCloudUpsertProtectsExecuted:
    """cloud_upsert_signals 集成保护：upsert 前查既有状态并应用终态保护。"""

    def test_upsert_keeps_executed_status(self, monkeypatch):
        """云库既有 executed，传入 expired → upsert 的行 status 仍为 executed。"""
        captured = {}

        class FakeCloud:
            @staticmethod
            def enabled():
                return True

            @staticmethod
            def select(table, columns="*", filters=None, order=None, limit=None, offset=None):
                assert table == "signal_tracking"
                return [{"signal_id": "SIG-20260921-04", "status": "executed"}]

            @staticmethod
            def upsert_many(table, rows, on_conflict=None):
                captured["rows"] = rows
                return len(rows)

        monkeypatch.setattr(stc, "cloud_db", FakeCloud)
        rec = {
            "signal_id": "SIG-20260921-04", "trigger_date": "2026-09-21",
            "status": "expired", "source": "intraday_check",
        }
        ok = stc.cloud_upsert_signals([rec])
        assert ok == 1
        assert captured["rows"][0]["status"] == "executed"

    def test_upsert_allows_triggered(self, monkeypatch):
        """既有 triggered，传入 triggered → 保持 triggered（同等级放行）。"""
        captured = {}

        class FakeCloud:
            @staticmethod
            def enabled():
                return True

            @staticmethod
            def select(table, columns="*", filters=None, order=None, limit=None, offset=None):
                return [{"signal_id": "SIG-1", "status": "triggered"}]

            @staticmethod
            def upsert_many(table, rows, on_conflict=None):
                captured["rows"] = rows
                return len(rows)

        monkeypatch.setattr(stc, "cloud_db", FakeCloud)
        rec = {"signal_id": "SIG-1", "trigger_date": "2026-09-21", "status": "triggered"}
        stc.cloud_upsert_signals([rec])
        assert captured["rows"][0]["status"] == "triggered"

    def test_upsert_select_failure_falls_back(self, monkeypatch):
        """既有状态查询失败 → 不阻塞，按原记录 upsert（降级保持旧行为）。"""
        captured = {}

        class FakeCloud:
            @staticmethod
            def enabled():
                return True

            @staticmethod
            def select(table, columns="*", filters=None, order=None, limit=None, offset=None):
                raise RuntimeError("select 挂了")

            @staticmethod
            def upsert_many(table, rows, on_conflict=None):
                captured["rows"] = rows
                return len(rows)

        monkeypatch.setattr(stc, "cloud_db", FakeCloud)
        rec = {"signal_id": "SIG-1", "trigger_date": "2026-09-21", "status": "expired"}
        stc.cloud_upsert_signals([rec])
        assert captured["rows"][0]["status"] == "expired"


# ═══════════════════════════════════════════════════════════════
# 信号触发记录落库（2026-09-21 新增：signal_trigger_records 表）
# ═══════════════════════════════════════════════════════════════

class TestTriggerRecordRow:
    """to_trigger_row：触发记录 dict → 云表行映射。"""

    def _sample(self):
        return {
            "signal_id": "SIG-20260921-04",
            "trigger_date": "2026-09-21",
            "trigger_time": "10:32",
            "priority": "P1",
            "ticker": "515880",
            "name": "通信ETF",
            "action_type": "建仓",
            "condition": "现价 0.714 > 0.71 交易价",
            "status": "已触发",
            "suggest": "按 7,500 份建仓",
            "result": "待用户填写",
        }

    def test_full_mapping(self):
        row = stc.to_trigger_row(self._sample())
        assert row["signal_id"] == "SIG-20260921-04"
        assert row["trigger_date"] == "2026-09-21"
        assert row["trigger_time"] == "10:32"
        assert row["action_type"] == "建仓"
        assert row["condition"].startswith("现价")
        assert row["status"] == "已触发"
        assert row["result"] == "待用户填写"
        assert row["created_at"]
        assert row["updated_at"]

    def test_skips_none_columns(self):
        rec = self._sample()
        rec["result"] = None
        rec["suggest"] = None
        row = stc.to_trigger_row(rec)
        assert "result" not in row
        assert "suggest" not in row

    def test_missing_signal_id_returns_empty(self):
        rec = self._sample()
        rec["signal_id"] = None
        assert stc.to_trigger_row(rec) == {}

    def test_missing_trigger_time_returns_empty(self):
        rec = self._sample()
        rec["trigger_time"] = ""
        assert stc.to_trigger_row(rec) == {}


class TestCloudUpsertTriggerRecords:
    """cloud_upsert_trigger_records：写云库 + 幂等键 + 降级。"""

    def _sample(self):
        return {
            "signal_id": "SIG-20260921-06-盘中",
            "trigger_date": "2026-09-21",
            "trigger_time": "10:32",
            "priority": "P1",
            "ticker": "159992",
            "name": "创新药ETF",
            "action_type": "建仓",
            "condition": "医药工业十五五规划 + 涨停潮",
            "status": "已触发",
            "suggest": "按 9,400 份建仓",
            "result": "待用户填写",
        }

    def test_upsert_many_called_with_on_conflict(self, monkeypatch):
        captured = {}

        class FakeCloud:
            @staticmethod
            def enabled():
                return True

            @staticmethod
            def upsert_many(table, rows, on_conflict=None):
                captured["table"] = table
                captured["rows"] = rows
                captured["on_conflict"] = on_conflict
                return len(rows)

        monkeypatch.setattr(stc, "cloud_db", FakeCloud)
        ok = stc.cloud_upsert_trigger_records([self._sample()])
        assert ok == 1
        assert captured["table"] == "signal_trigger_records"
        assert captured["on_conflict"] == "signal_id,trigger_time"
        assert captured["rows"][0]["signal_id"] == "SIG-20260921-06-盘中"

    def test_cloud_disabled_returns_zero(self, monkeypatch):
        monkeypatch.setattr(stc, "cloud_enabled", lambda: False)
        assert stc.cloud_upsert_trigger_records([self._sample()]) == 0

    def test_upsert_exception_returns_zero(self, monkeypatch):
        class FakeCloud:
            @staticmethod
            def enabled():
                return True

            @staticmethod
            def upsert_many(table, rows, on_conflict=None):
                raise RuntimeError("upsert 挂了")

        monkeypatch.setattr(stc, "cloud_db", FakeCloud)
        assert stc.cloud_upsert_trigger_records([self._sample()]) == 0

    def test_invalid_rows_filtered(self, monkeypatch):
        captured = {}

        class FakeCloud:
            @staticmethod
            def enabled():
                return True

            @staticmethod
            def upsert_many(table, rows, on_conflict=None):
                captured["rows"] = rows
                return len(rows)

        monkeypatch.setattr(stc, "cloud_db", FakeCloud)
        ok = stc.cloud_upsert_trigger_records([
            self._sample(),
            {"signal_id": None, "trigger_time": "10:00"},   # 缺 signal_id → 丢弃
            {"signal_id": "SIG-X", "trigger_time": ""},     # 缺 trigger_time → 丢弃
        ])
        assert ok == 1
        assert len(captured["rows"]) == 1


class TestCloudLoadTriggerRecords:
    """cloud_load_trigger_records：按 signal_id/日期过滤读取。"""

    def test_filter_by_signal_id(self, monkeypatch):
        captured = {}

        class FakeCloud:
            @staticmethod
            def enabled():
                return True

            @staticmethod
            def select(table, columns="*", filters=None, order=None, limit=None, offset=None):
                captured["table"] = table
                captured["filters"] = filters
                return [{"signal_id": "SIG-20260921-04", "trigger_time": "10:32"}]

        monkeypatch.setattr(stc, "cloud_db", FakeCloud)
        rows = stc.cloud_load_trigger_records(signal_id="SIG-20260921-04")
        assert len(rows) == 1
        assert captured["table"] == "signal_trigger_records"
        assert ("signal_id", "eq", "SIG-20260921-04") in captured["filters"]

    def test_cloud_disabled_returns_empty(self, monkeypatch):
        monkeypatch.setattr(stc, "cloud_enabled", lambda: False)
        assert stc.cloud_load_trigger_records(signal_id="SIG-1") == []

    def test_select_exception_returns_empty(self, monkeypatch):
        class FakeCloud:
            @staticmethod
            def enabled():
                return True

            @staticmethod
            def select(table, columns="*", filters=None, order=None, limit=None, offset=None):
                raise RuntimeError("select 挂了")

        monkeypatch.setattr(stc, "cloud_db", FakeCloud)
        assert stc.cloud_load_trigger_records(signal_id="SIG-1") == []


# ═══════════════════════════════════════════════════════════════
# 盘中检查记录落库（2026-09-24 新增：signal_check_records 表）
# 每次盘中检查对每条信号的检查结果落库，一行 = 信号 × 检查点
# ═══════════════════════════════════════════════════════════════

class TestCheckRecordRow:
    """to_check_row：检查记录 dict → 云表行映射。"""

    def _sample(self):
        return {
            "signal_id": "SIG-20260924-01",
            "check_date": "2026-09-24",
            "check_time": "10:32",
            "check_point": "10:30",
            "ticker": "515880",
            "name": "通信ETF",
            "price": 0.714,
            "trade_price": 0.71,
            "condition_met": "触发",
            "status_before": "未触发",
            "status_after": "已触发",
            "note": "现价 0.714 ≥ 交易价 0.71 → 触发",
        }

    def test_full_mapping(self):
        row = stc.to_check_row(self._sample())
        assert row["signal_id"] == "SIG-20260924-01"
        assert row["check_date"] == "2026-09-24"
        assert row["check_time"] == "10:32"
        assert row["check_point"] == "10:30"
        assert row["price"] == 0.714
        assert row["trade_price"] == 0.71
        assert row["condition_met"] == "触发"
        assert row["status_before"] == "未触发"
        assert row["status_after"] == "已触发"
        assert row["note"].startswith("现价")
        assert row["created_at"]
        assert row["updated_at"]

    def test_skips_none_columns(self):
        rec = self._sample()
        rec["note"] = None
        rec["trade_price"] = None
        row = stc.to_check_row(rec)
        assert "note" not in row
        assert "trade_price" not in row
        assert row["price"] == 0.714

    def test_missing_signal_id_returns_empty(self):
        rec = self._sample()
        rec["signal_id"] = None
        assert stc.to_check_row(rec) == {}

    def test_missing_check_time_returns_empty(self):
        rec = self._sample()
        rec["check_time"] = ""
        assert stc.to_check_row(rec) == {}


class TestCloudUpsertCheckRecords:
    """cloud_upsert_check_records：写云库 + 幂等键 + 降级。"""

    def _sample(self):
        return {
            "signal_id": "SIG-20260924-01",
            "check_date": "2026-09-24",
            "check_time": "10:32",
            "check_point": "10:30",
            "ticker": "515880",
            "name": "通信ETF",
            "price": 0.714,
            "trade_price": 0.71,
            "condition_met": "触发",
            "status_before": "未触发",
            "status_after": "已触发",
            "note": "现价 0.714 ≥ 交易价 0.71 → 触发",
        }

    def test_upsert_many_called_with_on_conflict(self, monkeypatch):
        captured = {}

        class FakeCloud:
            @staticmethod
            def enabled():
                return True

            @staticmethod
            def upsert_many(table, rows, on_conflict=None):
                captured["table"] = table
                captured["rows"] = rows
                captured["on_conflict"] = on_conflict
                return len(rows)

        monkeypatch.setattr(stc, "cloud_db", FakeCloud)
        ok = stc.cloud_upsert_check_records([self._sample()])
        assert ok == 1
        assert captured["table"] == "signal_check_records"
        assert captured["on_conflict"] == "signal_id,check_date,check_time"
        assert captured["rows"][0]["signal_id"] == "SIG-20260924-01"
        assert captured["rows"][0]["condition_met"] == "触发"

    def test_cloud_disabled_returns_zero(self, monkeypatch):
        monkeypatch.setattr(stc, "cloud_enabled", lambda: False)
        assert stc.cloud_upsert_check_records([self._sample()]) == 0

    def test_upsert_exception_returns_zero(self, monkeypatch):
        class FakeCloud:
            @staticmethod
            def enabled():
                return True

            @staticmethod
            def upsert_many(table, rows, on_conflict=None):
                raise RuntimeError("upsert 挂了")

        monkeypatch.setattr(stc, "cloud_db", FakeCloud)
        assert stc.cloud_upsert_check_records([self._sample()]) == 0

    def test_invalid_rows_filtered(self, monkeypatch):
        captured = {}

        class FakeCloud:
            @staticmethod
            def enabled():
                return True

            @staticmethod
            def upsert_many(table, rows, on_conflict=None):
                captured["rows"] = rows
                return len(rows)

        monkeypatch.setattr(stc, "cloud_db", FakeCloud)
        ok = stc.cloud_upsert_check_records([
            self._sample(),
            {"signal_id": None, "check_time": "10:00"},  # 缺 signal_id → 丢弃
            {"signal_id": "SIG-X", "check_time": ""},    # 缺 check_time → 丢弃
        ])
        assert ok == 1
        assert len(captured["rows"]) == 1


class TestCloudLoadCheckRecords:
    """cloud_load_check_records：按 signal_id/日期过滤读取。"""

    def test_filter_by_signal_id(self, monkeypatch):
        captured = {}

        class FakeCloud:
            @staticmethod
            def enabled():
                return True

            @staticmethod
            def select(table, columns="*", filters=None, order=None, limit=None, offset=None):
                captured["table"] = table
                captured["filters"] = filters
                return [{"signal_id": "SIG-20260924-01", "check_time": "10:32"}]

        monkeypatch.setattr(stc, "cloud_db", FakeCloud)
        rows = stc.cloud_load_check_records(signal_id="SIG-20260924-01")
        assert len(rows) == 1
        assert captured["table"] == "signal_check_records"
        assert ("signal_id", "eq", "SIG-20260924-01") in captured["filters"]

    def test_filter_by_date(self, monkeypatch):
        captured = {}

        class FakeCloud:
            @staticmethod
            def enabled():
                return True

            @staticmethod
            def select(table, columns="*", filters=None, order=None, limit=None, offset=None):
                captured["filters"] = filters
                return []

        monkeypatch.setattr(stc, "cloud_db", FakeCloud)
        stc.cloud_load_check_records(check_date="2026-09-24")
        assert ("check_date", "eq", "2026-09-24") in captured["filters"]

    def test_cloud_disabled_returns_empty(self, monkeypatch):
        monkeypatch.setattr(stc, "cloud_enabled", lambda: False)
        assert stc.cloud_load_check_records(signal_id="SIG-1") == []

    def test_select_exception_returns_empty(self, monkeypatch):
        class FakeCloud:
            @staticmethod
            def enabled():
                return True

            @staticmethod
            def select(table, columns="*", filters=None, order=None, limit=None, offset=None):
                raise RuntimeError("select 挂了")

        monkeypatch.setattr(stc, "cloud_db", FakeCloud)
        assert stc.cloud_load_check_records(signal_id="SIG-1") == []


@pytest.mark.skipif(not REAL_CLOUD, reason="REAL_CLOUD=1 时才对真实云库读写")
class TestRealCloud:
    def test_cloud_roundtrip(self):
        """真实云库：读 9 条 + 幂等重写。"""
        sigs = stc.cloud_load_signals()
        assert len(sigs) >= 1
        ok = stc.cloud_upsert_signals(sigs)
        assert ok == len(sigs)
        assert len(stc.cloud_load_signals()) == len(sigs)
