"""dashboard/api_daily.py — 信号触发记录 API 测试（2026-09-21 新增）

覆盖：
- GET /api/signal-trigger-records?signal_id=... 按信号ID过滤
- GET /api/signal-trigger-records?date=... 按日期过滤
- 云库不可用时返回空列表（不 500）

无网络：cloud_db 用 monkeypatch mock。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from dashboard import api_daily as api_mod
from dashboard import app as app_mod
from fastapi.testclient import TestClient


def _sample_records():
    """两日触发记录样本（含盘中追加信号）。"""
    return [
        {
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
        },
        {
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
        },
        {
            "signal_id": "SIG-20260916-04",
            "trigger_date": "2026-09-16",
            "trigger_time": "10:31",
            "priority": "P1",
            "ticker": "159326",
            "name": "电网设备ETF",
            "action_type": "正T",
            "condition": "午后路径三条件齐备",
            "status": "已触发",
            "suggest": "正T 1,975份",
            "result": "待用户填写",
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
            assert table == "signal_trigger_records"
            out = records
            if filters:
                for col, op, val in filters:
                    if col == "signal_id" and op == "eq":
                        out = [r for r in out if r.get("signal_id") == val]
                    elif col == "trigger_date" and op == "eq":
                        out = [r for r in out if r.get("trigger_date") == val]
            if order == "trigger_date.desc,trigger_time.desc":
                out = sorted(
                    out,
                    key=lambda r: (r.get("trigger_date", ""), r.get("trigger_time", "")),
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
    """按 signal_id 过滤 → 只返回该信号的触发记录。"""
    r = client.get("/api/signal-trigger-records?signal_id=SIG-20260921-04")
    assert r.status_code == 200
    d = r.json()
    assert len(d["items"]) == 1
    item = d["items"][0]
    assert item["signal_id"] == "SIG-20260921-04"
    assert item["name"] == "通信ETF"
    assert item["trigger_time"] == "10:32"
    assert item["action_type"] == "建仓"
    assert item["condition"]
    assert item["status"] == "已触发"
    assert item["result"] == "待用户填写"


def test_filter_by_date(client):
    """按日期过滤 → 只返回该日的触发记录。"""
    r = client.get("/api/signal-trigger-records?date=20260921")
    assert r.status_code == 200
    d = r.json()
    assert len(d["items"]) == 2
    assert {i["signal_id"] for i in d["items"]} == {"SIG-20260921-04", "SIG-20260921-06-盘中"}


def test_no_filter_returns_all_sorted(client):
    """无过滤 → 全部记录，按日期+时间倒序。"""
    r = client.get("/api/signal-trigger-records")
    assert r.status_code == 200
    d = r.json()
    assert len(d["items"]) == 3
    # 倒序：09-21 的两条在前，09-16 的在后
    assert d["items"][0]["trigger_date"] == "2026-09-21"
    assert d["items"][2]["trigger_date"] == "2026-09-16"


def test_no_match_returns_empty(client):
    """无匹配 → 空列表。"""
    r = client.get("/api/signal-trigger-records?signal_id=SIG-NOPE")
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
    r = client.get("/api/signal-trigger-records?signal_id=SIG-1")
    assert r.status_code == 200
    assert r.json()["items"] == []
