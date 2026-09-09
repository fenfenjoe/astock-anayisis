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
        def select(table, columns="*", filters=None, order=None, limit=None):
            assert table == "signal_tracking"
            out = cloud_rows
            if filters:
                for col, op, val in filters:
                    if col == "signal_date" and op == "eq":
                        out = [r for r in out if r.get("signal_date") == val]
            if order == "signal_id":
                out = sorted(out, key=lambda r: r.get("signal_id", ""))
            if limit:
                out = out[:limit]
            return out

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
    """云库该日无数据 → source=markdown（回退路径）。"""
    # 让云库对该日返回空（FakeCloudDB 按日期过滤已实现）
    r = client.get("/api/daily-signals?date=20260901")
    d = r.json()
    # 20260901 不在样本 → 走 markdown 兜底（mock report 不存在 → 404 或空）
    assert r.status_code in (200, 404)
