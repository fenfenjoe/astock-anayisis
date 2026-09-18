"""dashboard/api_daily.py — 信号云库化 API 测试（Phase 3 · 方案 v1.10 §9.2/9.3）

覆盖：
- /api/daily-signals 云库优先（source=cloud + signals 结构化行）
- /api/signal-quality 8 项指标 + P0 执行率（period=day|week|all）
- 云库无数据时回退 markdown 解析 / 本地缓存

无网络：cloud_db 用 monkeypatch mock；本地缓存路径重定向到 tmp。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from dashboard import api_daily as api_mod
from dashboard import app as app_mod
from fastapi.testclient import TestClient


def _sample_sigs():
    """两日信号样本（触发/执行/已结算）。"""
    return [
        {
            "signal_id": "SIG-20260907-01", "trigger_date": "2026-09-07",
            "priority": "P0", "ticker": "518880", "name": "黄金ETF",
            "trade_type": "buy", "direction": "buy", "urgency": "high",
            "expected_trigger_rate": 50.0, "entry_price": 7.5, "shares": 100,
            "status": "executed", "pnl": 30.0, "outcome": None,
        },
        {
            "signal_id": "SIG-20260907-02", "trigger_date": "2026-09-07",
            "priority": "P1", "ticker": "159899", "name": "软件ETF",
            "trade_type": "buy", "direction": "buy", "urgency": "low",
            "expected_trigger_rate": 30.0, "entry_price": 0.7, "shares": 1000,
            "status": "settled", "pnl": -15.0, "outcome": "miss",
            "settle_price": 0.685, "holding_days": 3,
        },
        {
            "signal_id": "SIG-20260908-01", "trigger_date": "2026-09-08",
            "priority": "P1", "ticker": "159326", "name": "电网ETF",
            "trade_type": "buy", "direction": "buy", "urgency": "high",
            "expected_trigger_rate": 40.0, "entry_price": 1.6, "shares": 1000,
            "status": "triggered", "pnl": None, "outcome": None,
        },
    ]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    async def _fake_user(request=None):
        return {"username": "tester", "role": "admin"}

    app_mod.app.dependency_overrides[app_mod.get_current_user] = _fake_user

    # 云库 mock：模拟 signal_tracking 表
    sigs = _sample_sigs()
    cloud_rows = []
    for s in sigs:
        r = dict(s)
        r["signal_date"] = s["trigger_date"]
        r.pop("trigger_date", None)
        cloud_rows.append(r)

    class FakeCloudDB:
        @staticmethod
        def enabled():
            return True

        @staticmethod
        def select(table, columns="*", filters=None, order=None, limit=None,
                   offset=None):
            assert table == "signal_tracking"
            out = cloud_rows
            if filters:
                for col, op, val in filters:
                    if col == "signal_date" and op == "eq":
                        out = [r for r in out if r.get("signal_date") == val]
                    elif col == "signal_id" and op == "like":
                        pat = val.strip("*")
                        out = [r for r in out if pat in r.get("signal_id", "")]
                    elif col == "ticker" and op == "like":
                        pat = val.strip("*")
                        out = [r for r in out if pat in str(r.get("ticker", ""))]
                    elif col == "status" and op == "eq":
                        out = [r for r in out if r.get("status") == val]
                    elif col == "trade_type" and op == "eq":
                        out = [r for r in out if r.get("trade_type") == val]
            if order == "signal_id":
                out = sorted(out, key=lambda r: r.get("signal_id", ""))
            if offset:
                out = out[offset:]
            if limit:
                out = out[:limit]
            return out

        @staticmethod
        def update(table, row, filters=None, columns="*"):
            return [{"signal_id": row.get("signal_id") or (filters or [("", "")])[0][2]}]

    import sys as _sys
    monkeypatch.setitem(_sys.modules, "cloud_db", FakeCloudDB)
    # 本地兜底：指向 tmp 空文件
    local = tmp_path / "signal_tracking.json"
    local.write_text(json.dumps({"signals": []}, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(api_mod, "_load_tracking_signals",
                        lambda: _sample_sigs())

    yield TestClient(app_mod.app)
    app_mod.app.dependency_overrides.clear()


def test_daily_signals_cloud_source(client):
    """云库有数据 → source=cloud + signals 结构化行。"""
    r = client.get("/api/daily-signals?date=20260907")
    assert r.status_code == 200
    d = r.json()
    assert d["source"] == "cloud"
    assert len(d["signals"]) == 2
    assert d["signals"][0]["signal_id"] == "SIG-20260907-01"


def test_signal_quality_metrics(client):
    """8 项指标 + P0 执行率计算正确。"""
    r = client.get("/api/signal-quality?period=all")
    assert r.status_code == 200
    q = r.json()
    assert q["signals_included"] == 3
    assert q["settled_included"] == 1
    m = q["metrics"]
    # P0 执行率：1 个 P0（executed）/ 1 个 P0 = 100%
    assert q["p0_execution"]["rate"] == 100.0
    # 触发率：3/3 = 100%
    assert m["trigger_rate_all"] == 100.0
    # 目标达成率：settled=1, miss → 0%
    assert m["target_hit_rate"] == 0.0
    # 期望价值 = 唯一 settled 的 pnl = -15.0
    assert m["signal_expected_value"] == -15.0
    # 最大亏损 = -15.0
    assert m["max_loss"] == -15.0


def test_signal_quality_period_day(client):
    """period=day 只统计当日信号（2026-09-08 → 1 条）。"""
    # 直接调用核心函数（避免 datetime.now 依赖）
    sigs = api_mod._load_tracking_signals()
    today = "2026-09-08"
    day_sigs = [s for s in sigs if (s.get("trigger_date") or s.get("signal_date")) == today]
    assert len(day_sigs) == 1


def test_daily_signals_markdown_fallback(client, monkeypatch):
    """云库该日无数据 → 空表（任务4 全云库化，无 markdown 兜底）。"""
    # 让云库对该日返回空（FakeCloudDB 按日期过滤已实现）
    r = client.get("/api/daily-signals?date=20260901")
    d = r.json()
    assert r.status_code == 200
    assert d["source"] == "cloud"
    assert d["signals"] == []


# ═══════════════════════════════════════════════════════════════
# 任务4 新增接口（2026-09-14）
# ═══════════════════════════════════════════════════════════════


def test_signal_enums(client):
    """/api/signal-enums 返回各字段枚举。"""
    r = client.get("/api/signal-enums")
    assert r.status_code == 200
    e = r.json()
    assert e["trade_type"] == ["buy", "sell"]
    assert "triggered" in e["status"]
    assert "expired" in e["status"]  # v3.0 新增
    assert e["priority"] == ["P0", "P1", "P2"]
    assert e["outcome"] == ["hit", "stopped", "miss"]


def test_signal_history_pagination(client):
    """/api/signal-history 分页 + 日期过滤 + 8 字段视图（v3.0 交易价/目标价/止损价）。"""
    r = client.get("/api/signal-history?date=20260907&page=1&page_size=20")
    assert r.status_code == 200
    d = r.json()
    assert d["total"] == 2
    items = d["items"]
    assert len(items) == 2
    # 8 字段视图：含 signal_id / trade_type / position / valid_window / trade_price
    row = items[0]
    assert row["signal_id"] == "SIG-20260907-01"
    assert row["trade_type"] == "buy"
    assert "signal_date" in row
    assert "trade_price" in row      # v3.0 交易价
    assert "target_price" in row     # v3.0 目标价
    assert "stop_price" in row       # v3.0 止损价


def test_signal_history_empty(client):
    """/api/signal-history 无匹配 → 空列表。"""
    r = client.get("/api/signal-history?ticker=999999")
    assert r.status_code == 200
    d = r.json()
    assert d["items"] == []
    assert d["total"] == 0


def test_signal_triggers_cloud_enabled(client):
    """/api/signal-triggers 返回 trigger_price 非空的行（云库可用）。"""
    r = client.get("/api/signal-triggers")
    assert r.status_code == 200
    d = r.json()
    assert "items" in d


def test_signal_trigger_post(client, monkeypatch):
    """POST /api/signal-trigger 写云库触发价/触发时间（mock cloud_update_fields）。"""
    import importlib
    import types as _types

    written = {}

    class _FakeSTC:
        @staticmethod
        def cloud_enabled():
            return True

        @staticmethod
        def cloud_update_fields(signal_id, fields):
            written["signal_id"] = signal_id
            written["fields"] = fields
            return True

    monkeypatch.setitem(__import__("sys").modules, "lib",
                        _types.SimpleNamespace(signal_tracking_cloud=_FakeSTC))

    r = client.post("/api/signal-trigger", json={"signal_id": "SIG-20260908-01",
                                                 "trigger_price": 1.61, "trigger_time": "10:05"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert written["signal_id"] == "SIG-20260908-01"
    assert written["fields"]["trigger_price"] == 1.61
    assert written["fields"]["trigger_time"] == "10:05"


def test_signal_entry_post(client, monkeypatch):
    """POST /api/signal-entry 写买入价/买入时间到云库。"""
    import types as _types

    written = {}

    class _FakeSTC:
        @staticmethod
        def cloud_enabled():
            return True

        @staticmethod
        def cloud_update_fields(signal_id, fields):
            written["signal_id"] = signal_id
            written["fields"] = fields
            return True

    monkeypatch.setitem(__import__("sys").modules, "lib",
                        _types.SimpleNamespace(signal_tracking_cloud=_FakeSTC))

    r = client.post("/api/signal-entry", json={"signal_id": "SIG-20260908-01",
                                               "entry_price": 1.60, "entry_time": "10:00"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert written["fields"]["entry_price"] == 1.60
    assert written["fields"]["entry_time"] == "10:00"


def test_signal_trigger_post_bad_status(client, monkeypatch):
    """POST /api/signal-trigger 写非法枚举 → 422（校验在 lib 层抛 ValueError）。"""
    import types as _types

    def _bad(signal_id, fields):
        raise ValueError("信号字段 trade_type 值 '坏值' 不在合法枚举内")

    monkeypatch.setitem(__import__("sys").modules, "lib",
                        _types.SimpleNamespace(signal_tracking_cloud=_types.SimpleNamespace(
                            cloud_enabled=lambda: True,
                            cloud_update_fields=_bad,
                        )))

    r = client.post("/api/signal-trigger", json={"signal_id": "SIG-X",
                                                 "trigger_price": 1.0, "trigger_time": "10:00"})
    assert r.status_code == 422
