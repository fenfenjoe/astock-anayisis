"""dashboard/api_daily.py — 盘中检查记录 API 测试（2026-09-24 新增）

覆盖：
- GET /api/signal-check-records?signal_id=... 按信号ID过滤
- GET /api/signal-check-records?date=... 按日期过滤
- 云库不可用时返回空列表（不 500）

无网络：cloud_db 用 monkeypatch mock。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from dashboard import app as app_mod
from fastapi.testclient import TestClient


def _sample_records():
    """单信号多检查点样本（含触发/未触发/已过期三种判定）。"""
    return [
        {
            "signal_id": "SIG-20260924-01",
            "check_date": "2026-09-24",
            "check_time": "09:40",
            "check_point": "09:40",
            "ticker": "515880",
            "name": "通信ETF",
            "price": 0.705,
            "trade_price": 0.71,
            "condition_met": "未触发",
            "status_before": "未触发",
            "status_after": "未触发",
            "note": "现价 0.705 < 交易价 0.71，量比 0.8 未达标",
        },
        {
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
        },
        {
            "signal_id": "SIG-20260924-02",
            "check_date": "2026-09-24",
            "check_time": "14:30",
            "check_point": "14:30",
            "ticker": "159992",
            "name": "创新药ETF",
            "price": 0.82,
            "trade_price": 0.85,
            "condition_met": "已过期",
            "status_before": "未触发",
            "status_after": "已过期",
            "note": "75%窗口过期",
        },
    ]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    async def _fake_user(request=None):
        return {"username": "tester", "role": "admin"}

    app_mod.app.dependency_overrides[app_mod.get_current_user] = _fake_user

    records = _sample_records()

    class FakeCloudDB:
        @staticmethod
        def enabled():
            return True

        @staticmethod
        def select(table, columns="*", filters=None, order=None, limit=None,
                   offset=None):
            assert table == "signal_check_records"
            out = records
            if filters:
                for col, op, val in filters:
                    if col == "signal_id" and op == "eq":
                        out = [r for r in out if r.get("signal_id") == val]
                    elif col == "check_date" and op == "eq":
                        out = [r for r in out if r.get("check_date") == val]
            if order == "check_date.desc,check_time.desc":
                out = sorted(
                    out,
                    key=lambda r: (r.get("check_date", ""), r.get("check_time", "")),
                    reverse=True,
                )
            if limit:
                out = out[:limit]
            return out

    import sys as _sys
    monkeypatch.setitem(_sys.modules, "cloud_db", FakeCloudDB)

    yield TestClient(app_mod.app)
    app_mod.app.dependency_overrides.clear()


def test_filter_by_signal_id(client):
    """按 signal_id 过滤 → 只返回该信号的检查记录（多检查点）。"""
    r = client.get("/api/signal-check-records?signal_id=SIG-20260924-01")
    assert r.status_code == 200
    d = r.json()
    assert len(d["items"]) == 2
    item = d["items"][0]
    assert item["signal_id"] == "SIG-20260924-01"
    assert item["check_time"] == "10:32"
    assert item["condition_met"] == "触发"
    assert item["status_before"] == "未触发"
    assert item["status_after"] == "已触发"
    assert item["note"]
    assert item["price"] == 0.714


def test_filter_by_date(client):
    """按日期过滤 → 只返回该日的检查记录。"""
    r = client.get("/api/signal-check-records?date=20260924")
    assert r.status_code == 200
    d = r.json()
    assert len(d["items"]) == 3
    assert {i["signal_id"] for i in d["items"]} == {"SIG-20260924-01", "SIG-20260924-02"}


def test_no_filter_returns_all_sorted(client):
    """无过滤 → 全部记录，按日期+时间倒序。"""
    r = client.get("/api/signal-check-records")
    assert r.status_code == 200
    d = r.json()
    assert len(d["items"]) == 3
    # 倒序：14:30 在前，10:32 次之，09:40 在后
    assert d["items"][0]["check_time"] == "14:30"
    assert d["items"][2]["check_time"] == "09:40"


def test_no_match_returns_empty(client):
    """无匹配 → 空列表。"""
    r = client.get("/api/signal-check-records?signal_id=SIG-NOPE")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_cloud_disabled_returns_empty(client, monkeypatch):
    """云库不可用 → 空列表（不 500）。"""
    import sys as _sys

    class DisabledCloud:
        @staticmethod
        def enabled():
            return False

    monkeypatch.setitem(_sys.modules, "cloud_db", DisabledCloud)
    r = client.get("/api/signal-check-records?signal_id=SIG-1")
    assert r.status_code == 200
    assert r.json()["items"] == []
