"""Tests: 持仓/资产页「交易录入」— portfolio.py 账本逻辑 + /api/portfolio/trades 端点。

- Unit 层：用 tmp 目录模拟 每日调仓.md/持仓.md（monkeypatch portfolio 路径），
  覆盖解析/序列化/校验（含 T+1）/追加/撤销。
- API 层：沿用 test_dashboard_app.py 的 DB mock 模式（get_current_user 用
  dependency_overrides），append/undo 走真实文件流（tmp 路径），不触网。
"""
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

from fastapi.testclient import TestClient
from dashboard.app import app as fastapi_app
from dashboard import portfolio
from dashboard import db as db_mod

DAILY_TMPL = """# 仓位

## 0. 可用金额

16131

## 1. 当前持仓


持仓：

| 股票名称 | 代码 | 持仓量（份） | 成本价（元） | 
| -------- | ------ | ------------ | ------------ | 
| 航空航天ETF | 159227 | 1,400 | 2.731 | 
| 半导体ETF | 512480 | 6,100 | 1.044 | 

## 2. 调仓记录


| 日期 | 股票名称 | 股票代码 | 交易数量 | 交易价格 | 买入/卖出 | 备注 |
|---|---|---|---|---|---|---|
| 2026-08-27 | 半导体ETF | 512480 | 6,100 | 1.044 | 买入 | 买入信号  |
| 2026-08-27 | 电网设备ETF | 159326 | 1,900 | 1.695 | 卖出 | 正T卖出  |
"""

POS_TMPL = """# 当前持仓

> 本文件由每日复盘自动同步自 每日调仓.md，反映最新持仓状态。
> 最后更新: 自动同步
可用金额: 16131 元

| 股票名称 | 代码 | 持仓数量（份） | 成本价（元） |
| -------- | ------ | -------------- | ------------ |
| 航空航天ETF | 159227 | 1,400 | 2.731 |
| 半导体ETF | 512480 | 6,100 | 1.044 |
"""


@pytest.fixture
def ledger_paths(tmp_path, monkeypatch):
    """把 portfolio 的两个账本文件路径指向 tmp 目录，并写入初始状态。

    2026-09-07 已移除 TOS：portfolio 本地文件读写即为唯一路径，无需禁用云端。
    """
    daily = tmp_path / "my_doc" / "每日复盘" / "每日调仓.md"
    holdings = tmp_path / "my_doc" / "每日复盘" / "harness" / "config" / "持仓.md"
    daily.parent.mkdir(parents=True)
    holdings.parent.mkdir(parents=True)
    daily.write_text(DAILY_TMPL, encoding="utf-8")
    holdings.write_text(POS_TMPL, encoding="utf-8")
    monkeypatch.setattr(portfolio, "TRADES_MD", daily)
    monkeypatch.setattr(portfolio, "HOLDINGS_MD", holdings)
    monkeypatch.setattr(portfolio, "SNAPSHOT_DIR", tmp_path / ".dsh" / "trade-entry" / "undo")
    return {"daily": daily, "holdings": holdings}


def _trade(**kw):
    base = {"trade_date": "2026-08-28", "name": "半导体ETF", "code": "512480",
            "quantity": 1000, "price": 1.10, "side": "买入", "remark": ""}
    base.update(kw)
    return base


# ═══════════════════════════════════════════════════════════════
# Unit: 账本
# ═══════════════════════════════════════════════════════════════

def test_parse_and_roundtrip(ledger_paths):
    st = portfolio.read_daily_ledger()
    assert st["cash"] == 16131
    assert len(st["positions"]) == 2
    assert len(st["trades"]) == 2
    assert st["trades"][0]["side"] == "买入"

    out = portfolio.serialize_daily_ledger_md(st)
    st2 = portfolio.parse_daily_ledger_md(out)
    assert st2["cash"] == st["cash"]
    assert len(st2["positions"]) == len(st["positions"])
    assert len(st2["trades"]) == len(st["trades"])
    assert st2["trades"][0] == st["trades"][0]


def test_append_buy_updates_cost_cash_and_files(ledger_paths):
    st = portfolio.append_trade(_trade())
    assert st["cash"] == 15031
    p = next(x for x in st["positions"] if x["code"] == "512480")
    assert p["shares"] == 7100
    assert abs(p["cost_price"] - 1.0519) < 1e-6
    assert len(st["trades"]) == 3

    daily_text = ledger_paths["daily"].read_text(encoding="utf-8")
    assert "| 2026-08-28 | 半导体ETF | 512480 | 1,000 | 1.1 | 买入 |  |" in daily_text
    # 成本移动平均 1.0519（4 位小数）
    assert "| 半导体ETF | 512480 | 7,100 | 1.0519 |" in daily_text
    pos_text = ledger_paths["holdings"].read_text(encoding="utf-8")
    assert "可用金额: 15031 元" in pos_text
    assert "| 半导体ETF | 512480 | 7,100 | 1.0519 |" in pos_text


def test_trade_fee_buy_deducts_cash_and_notes(ledger_paths):
    """买入手续费：现金多扣，备注自动带「手续费X元」。"""
    st = portfolio.append_trade(_trade(fee=5.0))
    assert st["cash"] == 16131 - 1100 - 5.0
    assert st["trades"][-1]["remark"] == "手续费5.00元"
    daily_text = ledger_paths["daily"].read_text(encoding="utf-8")
    assert "| 1.1 | 买入 | 手续费5.00元 |" in daily_text


def test_trade_fee_sell_reduces_proceeds(ledger_paths):
    """卖出手续费：现金少收（成交额-手续费）。"""
    st = portfolio.append_trade(_trade(side="卖出", quantity=1000, price=1.10, fee=6.0))
    assert st["cash"] == 16131 + 1100 - 6.0
    assert st["trades"][-1]["remark"] == "手续费6.00元"


def test_trade_fee_validation(ledger_paths):
    st = portfolio.read_daily_ledger()
    ok, err = portfolio.validate_trade(st, _trade(fee=-1))
    assert not ok and "手续费" in err
    ok, err = portfolio.validate_trade(st, _trade(quantity=100, price=1.0, fee=500))
    assert not ok and "手续费" in err
    # 买入净支出 = 金额+手续费 > 现金 → 拦截（15000×1.1+5 = 16505 > 16131）
    ok, err = portfolio.validate_trade(st, _trade(quantity=15000, price=1.1, fee=5))
    assert not ok and "可用金额" in err


def test_is_stock_and_t0(ledger_paths):
    assert portfolio.is_stock("601398") and portfolio.is_stock("002142") and portfolio.is_stock("688001")
    assert not portfolio.is_stock("512480") and not portfolio.is_stock("159227")
    assert portfolio.is_t0("513100") and not portfolio.is_t0("512480")


def test_sell_clears_position_and_refunds_cash(ledger_paths):
    st = portfolio.append_trade(_trade(side="卖出", quantity=6100, price=1.07))
    assert st["cash"] == 16131 + 6100 * 1.07
    assert all(p["code"] != "512480" for p in st["positions"])
    assert len(st["positions"]) == 1


def test_validate_rejections(ledger_paths):
    st = portfolio.read_daily_ledger()
    ok, err = portfolio.validate_trade(st, _trade(quantity=99999, side="卖出"))
    assert not ok and "仅持有" in err
    ok, err = portfolio.validate_trade(st, _trade(code="12345"))
    assert not ok and "6 位" in err
    ok, err = portfolio.validate_trade(st, _trade(name="恒生科技ETF", side="卖出", quantity=100))
    assert not ok and "名称" in err
    ok, err = portfolio.validate_trade(st, _trade(quantity=100000, price=10, side="买入"))
    assert not ok and "可用金额" in err
    ok, err = portfolio.validate_trade(st, _trade(quantity=100.5))
    assert not ok


def test_t1_same_day_buy_not_sellable(ledger_paths):
    st = portfolio.read_daily_ledger()
    st = portfolio.apply_trade(st, _trade())  # 当日买入 1000
    # 卖 6200 > 原持仓 6100：多出的 1000 是当日买入 → T+1 拦截
    ok, err = portfolio.validate_trade(st, _trade(quantity=6200, price=1.11, side="卖出"))
    assert not ok and "T+1" in err
    # 卖 2000 ≤ 6100：合法（卖的是昨日持仓）
    ok, _ = portfolio.validate_trade(st, _trade(quantity=2000, price=1.11, side="卖出"))
    assert ok


def test_t0_same_day_buy_sellable(ledger_paths):
    st = portfolio.read_daily_ledger()
    assert portfolio.is_t0("513100") and not portfolio.is_t0("512480")
    st = portfolio.apply_trade(st, _trade(code="513100", name="纳指ETF", quantity=1000, price=2.3))
    ok, err = portfolio.validate_trade(st, _trade(code="513100", name="纳指ETF",
                                                  quantity=1000, price=2.31, side="卖出"))
    assert ok, err


def test_undo_restores_previous_state(ledger_paths):
    portfolio.append_trade(_trade())
    st = portfolio.undo_last_trade()
    assert st["cash"] == 16131
    assert len(st["trades"]) == 2
    p = next(x for x in st["positions"] if x["code"] == "512480")
    assert p["shares"] == 6100 and p["cost_price"] == 1.044
    # 无快照时撤销 → ValueError
    with pytest.raises(ValueError):
        portfolio.undo_last_trade()


# ═══════════════════════════════════════════════════════════════
# API: /api/portfolio/trades
# ═══════════════════════════════════════════════════════════════

def _apply_api_mocks(monkeypatch, ledger_paths):
    """mock 认证 + DB 层 + 估值计算；账本文件走 tmp 真实文件。"""
    import dashboard.app as app_mod

    async def _mock_user(request=None):
        return {"username": "admin", "role": "admin", "display_name": "管理员"}
    app_mod.app.dependency_overrides[app_mod.get_current_user] = _mock_user

    monkeypatch.setattr(app_mod, "init_db", MagicMock())
    monkeypatch.setattr(app_mod, "user_count", MagicMock(return_value=1))
    monkeypatch.setattr(app_mod, "user_create", MagicMock())
    monkeypatch.setattr(app_mod, "get_secret_key_warning", MagicMock(return_value=None))

    # DB 镜像：以文件为准（模拟 scheduler 的 file → DB 同步语义）
    monkeypatch.setattr(db_mod, "portfolio_holdings_replace", MagicMock())
    monkeypatch.setattr(db_mod, "portfolio_trades_replace_all", MagicMock())
    monkeypatch.setattr(db_mod, "portfolio_holdings_get_all",
                        MagicMock(side_effect=lambda: portfolio.read_daily_ledger()["positions"]))
    monkeypatch.setattr(db_mod, "portfolio_trades_get_all",
                        MagicMock(side_effect=lambda: list(reversed(portfolio.read_daily_ledger()["trades"]))))
    _meta = {"available_cash": "16131", "total_assets": "0", "account_source": "manual"}
    monkeypatch.setattr(db_mod, "meta_get",
                        MagicMock(side_effect=lambda k, d=None: _meta.get(k, d)))
    # 2026-09-08：_build_portfolio_response 改用 meta_get_all 批量读，测试需同步 mock
    monkeypatch.setattr(db_mod, "meta_get_all",
                        MagicMock(side_effect=lambda: dict(_meta)))
    monkeypatch.setattr(db_mod, "meta_set",
                        MagicMock(side_effect=lambda k, v: _meta.update({k: str(v)})))

    # 估值计算：不触网
    def _fake_valuation(holdings, available_cash=0.0, refresh_prices=False):
        mv = sum(float(h.get("shares") or 0) * 1.0 for h in holdings)
        return {
            "rows": [{"code": h["code"], "name": h["name"], "shares": h["shares"],
                      "cost_price": h.get("cost_price"), "close": 1.0,
                      "mkt_value": float(h.get("shares") or 0), "cost_value": 0.0,
                      "pnl": None, "pnl_pct": None} for h in holdings],
            "totals": {"mkt_value": mv, "cost_value": 0.0, "pnl": None, "pnl_pct": None,
                       "total_assets": mv + (available_cash or 0), "available_cash": available_cash},
            "computed_at": "2026-08-28",
        }
    monkeypatch.setattr(portfolio, "compute_valuation", MagicMock(side_effect=_fake_valuation))
    return _meta


@pytest.fixture
def api_client(monkeypatch, ledger_paths):
    _apply_api_mocks(monkeypatch, ledger_paths)
    return TestClient(fastapi_app)


def test_api_append_trade_ok(api_client, ledger_paths):
    r = api_client.post("/api/portfolio/trades", json={
        "trade_date": "2026-08-28", "name": "半导体ETF", "code": "512480",
        "quantity": 1000, "price": 1.10, "side": "买入", "remark": "测试录入",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert "已录入" in body["message"]
    # 持仓表已自动调整
    assert body["holdings"]
    semi = next(h for h in body["holdings"] if h["code"] == "512480")
    assert semi["shares"] == 7100
    # 调仓记录已追加（接口返回最近 30 条）
    assert body["trades"][0]["remark"] == "测试录入"
    assert body["trades"][0]["side"] == "买入"
    # 文件已同步
    assert "测试录入" in ledger_paths["daily"].read_text(encoding="utf-8")


def test_api_append_trade_with_fee(api_client):
    """带手续费的买入：现金净扣（金额+手续费），消息含手续费提示。"""
    r = api_client.post("/api/portfolio/trades", json={
        "trade_date": "2026-08-28", "name": "半导体ETF", "code": "512480",
        "quantity": 1000, "price": 1.10, "side": "买入", "remark": "", "fee": 5.0,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert "手续费 5.00 元" in body["message"]
    assert "15,026" in body["message"]  # 16131 - 1100 - 5
    assert float(body["meta"]["available_cash"]) == 15026.0


def test_api_append_trade_rejects_t1(api_client):
    # 先当日买入 1000
    api_client.post("/api/portfolio/trades", json={
        "trade_date": "2026-08-28", "name": "半导体ETF", "code": "512480",
        "quantity": 1000, "price": 1.10, "side": "买入", "remark": ""})
    # 再当日卖出 6200（> 原持仓 6100）→ T+1 拦截
    r = api_client.post("/api/portfolio/trades", json={
        "trade_date": "2026-08-28", "name": "半导体ETF", "code": "512480",
        "quantity": 6200, "price": 1.11, "side": "卖出", "remark": ""})
    assert r.status_code == 400
    assert "T+1" in r.json()["detail"]


def test_api_append_trade_invalid(api_client):
    r = api_client.post("/api/portfolio/trades", json={
        "trade_date": "2026-08-28", "name": "", "code": "512480",
        "quantity": 100, "price": 1.0, "side": "买入", "remark": ""})
    assert r.status_code == 400
    assert "名称" in r.json()["detail"]


def test_api_undo_trade(api_client, ledger_paths):
    r1 = api_client.post("/api/portfolio/trades", json={
        "trade_date": "2026-08-28", "name": "半导体ETF", "code": "512480",
        "quantity": 1000, "price": 1.10, "side": "买入", "remark": "待撤销"})
    assert r1.status_code == 200
    r2 = api_client.post("/api/portfolio/trades/undo")
    assert r2.status_code == 200, r2.text
    body = r2.json()
    semi = next(h for h in body["holdings"] if h["code"] == "512480")
    assert semi["shares"] == 6100
    assert all(t["remark"] != "待撤销" for t in body["trades"])
    # 无快照可撤销
    r3 = api_client.post("/api/portfolio/trades/undo")
    assert r3.status_code == 400


def test_api_toggle_scheduler_auto(api_client):
    """可视化 auto 开关端点：开启/关闭自动调度。"""
    r = api_client.post("/api/scheduler/auto", json={"enabled": True})
    assert r.status_code == 200, r.text
    assert r.json()["auto_enabled"] is True
    r2 = api_client.post("/api/scheduler/auto", json={"enabled": False})
    assert r2.status_code == 200, r2.text
    assert r2.json()["auto_enabled"] is False
