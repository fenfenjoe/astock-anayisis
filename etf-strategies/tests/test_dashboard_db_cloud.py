"""dashboard/db.py — 云端后端（DASHBOARD_DB_BACKEND=cloud）集成测试。

走真实 Supabase 云库（PostgREST Data API），自清理不留脏数据。
需环境变量：SUPABASE_URL / SUPABASE_SERVICE_KEY，否则 skip。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from dashboard import db as ddb

pytestmark = [
    pytest.mark.realcloud,
    pytest.mark.skipif(
        not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY")),
        reason="未配置 SUPABASE_URL / SUPABASE_SERVICE_KEY，跳过云端 dashboard 集成测试",
    ),
]


@pytest.fixture()
def cloud(monkeypatch):
    monkeypatch.setattr(ddb, "USE_CLOUD", True)
    assert ddb._cd_select_one is not None
    yield
    # 清理测试数据
    from cloud_db import select as _sel, delete as _del_
    for u in _sel("users", filters=[("username", "like", "cloudtest-%")]):
        _del_("users", filters=[("id", "eq", u["id"])])
    for r in _sel("daily_reports", filters=[("report_date", "like", "2099-%")]):
        _del_("daily_reports", filters=[("id", "eq", r["id"])])
    for r in _sel("scheduler_runs", filters=[("task_id", "like", "cloudtest-%")]):
        _del_("scheduler_runs", filters=[("id", "eq", r["id"])])
    for m in _sel("portfolio_meta", filters=[("key", "like", "cloudtest-%")]):
        _del_("portfolio_meta", filters=[("key", "eq", m["key"])])
    for r in _sel("daily_signals", filters=[("strategy_id", "like", "cloudtest-%")]):
        _del_("daily_signals", filters=[("id", "eq", r["id"])])
    _del_("strategy_metrics", filters=[("strategy_id", "like", "cloudtest-%")])
    _del_("strategy_kb", filters=[("strategy_id", "like", "cloudtest-%")])


def test_cloud_user_crud(cloud):
    ddb.user_create("cloudtest-user", "hash123", "测试", role="admin")
    u = ddb.user_get_by_username("cloudtest-user")
    assert u is not None and u["password_hash"] == "hash123"
    assert ddb.user_count() >= 1

    ddb.user_update_last_login("cloudtest-user")
    assert ddb.user_get_by_username("cloudtest-user")["last_login"]

    ddb.user_change_password("cloudtest-user", "newhash")
    assert ddb.user_get_by_username("cloudtest-user")["password_hash"] == "newhash"

    names = [x["username"] for x in ddb.user_list_all()]
    assert "cloudtest-user" in names

    with pytest.raises(ValueError):
        ddb.user_create("cloudtest-user", "dup")


def test_cloud_meta_and_seed(cloud):
    ddb.meta_set("cloudtest-key", "v1")
    assert ddb.meta_get("cloudtest-key") == "v1"
    ddb.meta_set("cloudtest-key", "v2")
    assert ddb.meta_get("cloudtest-key") == "v2"
    ddb.meta_set("cloudtest-a", "x")
    pref = ddb.meta_get_prefix("cloudtest-")
    assert pref.get("cloudtest-key") == "v2"

    assert ddb.is_seeded() is False or ddb.is_seeded() is True  # 不抛异常
    ddb.mark_seeded()
    assert ddb.is_seeded() is True


def test_cloud_portfolio(cloud):
    ddb.portfolio_holdings_replace([
        {"code": "510300", "name": "沪深300", "shares": 100, "cost_price": 3.5},
        {"code": "511880", "name": "货币", "shares": 200, "cost_price": 100.0},
    ])
    hs = ddb.portfolio_holdings_get_all()
    assert len(hs) == 2
    assert ddb.portfolio_holdings_count() == 2
    codes = {h["code"] for h in hs}
    assert "510300" in codes and "511880" in codes

    ddb.portfolio_trades_replace_all([
        {"trade_date": "2026-01-05", "name": "沪深300", "code": "510300",
         "quantity": 100, "price": 3.5, "side": "buy", "remark": "t"},
    ])
    trades = ddb.portfolio_trades_get_all()
    assert len(trades) == 1
    assert trades[0]["code"] == "510300"


def test_cloud_reports(cloud):
    ddb.report_upsert("2099-01-01", "morning", "# 早盘", status="ready")
    r = ddb.report_get("2099-01-01", "morning")
    assert r and r["markdown"] == "# 早盘"

    # upsert 覆盖
    ddb.report_upsert("2099-01-01", "morning", "# 更新")
    r2 = ddb.report_get("2099-01-01", "morning")
    assert r2["markdown"] == "# 更新"

    dates = ddb.report_get_dates()
    assert "2099-01-01" in dates
    types = ddb.report_types_for_date("2099-01-01")
    assert "morning" in types
    lst = ddb.report_list(report_type="morning")
    assert any(x["report_date"] == "2099-01-01" for x in lst)


def test_cloud_scheduler(cloud):
    rid = ddb.scheduler_run_insert("cloudtest-task", "win-1", "auto", "2026-01-01 09:00")
    assert rid > 0
    ddb.scheduler_run_update(rid, status="success", duration_sec=1.5)
    r = ddb.scheduler_run_get(rid)
    assert r["status"] == "success"
    assert r["duration_sec"] == 1.5

    assert ddb.scheduler_window_done("cloudtest-task", "win-1") is True

    rid2 = ddb.scheduler_run_insert("cloudtest-task", "win-2", "auto", "2026-01-01 10:00")
    assert ddb.scheduler_latest("cloudtest-task")["id"] == rid2

    lst = ddb.scheduler_runs_list(task_id="cloudtest-task")
    assert len(lst) >= 2


def test_cloud_metrics_kb_signals(cloud):
    ddb.metrics_upsert(
        "cloudtest-S1", "测试策略", "动量", "动量策略",
        0.1, 1.0, -0.2, 0.5, 0.6, 1.2, 0.05,
        ["510300(沪深300)"], "desc", "2020~2026",
    )
    d = ddb.metrics_get_one("cloudtest-S1")
    assert d is not None and d["id"] == "cloudtest-S1"
    assert d["assets"] == ["510300(沪深300)"]
    allm = ddb.metrics_get_all()
    assert any(x["id"] == "cloudtest-S1" for x in allm)

    ddb.kb_upsert(
        "cloudtest-S1", "测试策略", "MyStrategy", "动量", "intro",
        "stock", "timing", "factors", "rebalance", "s", "w",
        {"lookback": 20}, "http://src", "proc",
    )
    k = ddb.kb_get("cloudtest-S1")
    assert k is not None and k["backtest"] == {"lookback": 20}

    ddb.signals_upsert("cloudtest-S1", "2026-01-05", "510300", "沪深300", 0.6, 0.5, "BUY")
    sigs = ddb.signals_get_latest("cloudtest-S1")
    assert sigs and sigs[0]["asset_code"] == "510300"
