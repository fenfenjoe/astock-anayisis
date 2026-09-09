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
    def test_fixed_column_set(self):
        """to_row 输出固定列集合（PostgREST 批量 upsert 各行键一致）。"""
        row = stc.to_row(_sample_sig())
        assert set(row.keys()) == set(stc._ALL_COLUMNS)
        # 关键映射
        assert row["signal_id"] == "SIG-20260908-TEST"
        assert row["signal_date"] == "2026-09-08"  # trigger_date → signal_date
        assert row["target_price"] is None
        assert row["created_at"]  # 自动填充
        assert row["updated_at"]

    def test_sell_columns_present(self):
        """卖出信号列（cost_basis/sell_price）在固定集合内（缺失为 None）。"""
        row = stc.to_row(_sample_sig())
        assert "cost_basis" in row and row["cost_basis"] is None
        assert "sell_price" in row and row["sell_price"] is None


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


@pytest.mark.skipif(not REAL_CLOUD, reason="REAL_CLOUD=1 时才对真实云库读写")
class TestRealCloud:
    def test_cloud_roundtrip(self):
        """真实云库：读 9 条 + 幂等重写。"""
        sigs = stc.cloud_load_signals()
        assert len(sigs) >= 1
        ok = stc.cloud_upsert_signals(sigs)
        assert ok == len(sigs)
        assert len(stc.cloud_load_signals()) == len(sigs)
