# -*- coding: utf-8 -*-
"""测试：测试环境隔离防护 — 确保 pytest 运行时不会污染真实 DB / 云端数据。

背景（2026-08-31 事故）：test_dashboard_auth.py 用 `with TestClient(app)` 触发
lifespan，lifespan 执行真实启动副作用（CLOUD_RESTORE 云下载覆盖本地 +
import_holdings/trades 写真实 DB + upload_reports 上传云），且测试进程读了
.env 的 DB_MODE=memory / CLOUD_RESTORE_ON_START=1 → 测试数据污染真实 DB 并
经 memory 快照回传扩散到 TOS。

本测试验证三层防护：
1. conftest 在测试进程设置 DB_MODE=file + CLOUD_RESTORE_ON_START=0（环境变量优先，
   load_env_file 不覆盖已存在键）
2. app.lifespan 在测试环境跳过启动副作用
3. 测试期间对真实 DB 写操作有拦截
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))


# ═══════════════════════════════════════════════════════════════
# 防护1: conftest 环境隔离
# ═══════════════════════════════════════════════════════════════

def test_conftest_sets_safe_env():
    """测试进程必须运行在安全环境：DB 文件模式 + 禁用启动云恢复 + 禁用云权威库。"""
    assert os.environ.get("DB_MODE", "").lower() != "memory", \
        "测试进程 DB_MODE 必须不是 memory（防止 memory 快照回传污染 TOS）"
    assert os.environ.get("CLOUD_RESTORE_ON_START", "").lower() in ("", "0", "false"), \
        "测试进程必须禁用 CLOUD_RESTORE_ON_START（防止启动时云下载覆盖本地）"
    assert os.environ.get("DASHBOARD_DB_BACKEND", "file").lower() != "cloud", \
        "测试进程必须禁用 DASHBOARD_DB_BACKEND=cloud（防止测试数据写入真实云库）"
    assert os.environ.get("AGENT_DB_BACKEND", "file").lower() != "cloud", \
        "测试进程必须禁用 AGENT_DB_BACKEND=cloud（防止测试数据写入真实云库）"


def test_load_env_does_not_override_existing():
    """load_env_file 不覆盖已存在的环境变量（隔离防护的前提）。"""
    from load_env import load_env_file
    os.environ["DB_MODE"] = "file"
    os.environ["CLOUD_RESTORE_ON_START"] = "0"
    os.environ["DASHBOARD_DB_BACKEND"] = "file"
    os.environ["AGENT_DB_BACKEND"] = "file"
    # 模拟 load_env_file 读 .env（含 DB_MODE=memory / 云后端开关）
    load_env_file()
    assert os.environ["DB_MODE"] == "file"  # 未被 .env 覆盖
    assert os.environ["CLOUD_RESTORE_ON_START"] == "0"
    assert os.environ["DASHBOARD_DB_BACKEND"] == "file"
    assert os.environ["AGENT_DB_BACKEND"] == "file"


def test_db_not_in_memory_mode_under_pytest():
    """pytest 进程里 dashboard.db 必须 USE_MEMORY=False（写本地文件而非云端快照）。"""
    import dashboard.db as db_mod
    assert db_mod.USE_MEMORY is False, \
        "测试进程 USE_MEMORY 必须为 False，否则 memory 回传会污染 TOS"
    assert db_mod.USE_CLOUD is False, \
        "测试进程 USE_CLOUD 必须为 False，否则测试数据写入真实云库"


# ═══════════════════════════════════════════════════════════════
# 防护2: app.lifespan 测试免疫
# ═══════════════════════════════════════════════════════════════

def test_lifespan_skips_side_effects_in_test_env(monkeypatch):
    """lifespan 在测试环境下必须跳过启动副作用（不调用真实导入/上传/云恢复）。"""
    import dashboard.app as app_mod
    from dashboard import scheduler as sched_mod

    calls = {"import_holdings": 0, "import_trades": 0,
             "import_reports": 0, "upload_reports": 0}

    def _spy_holdings():
        calls["import_holdings"] += 1
        return False

    def _spy_trades():
        calls["import_trades"] += 1
        return False

    def _spy_import_reports():
        calls["import_reports"] += 1
        return {"imported": 0}

    def _spy_upload_reports():
        calls["upload_reports"] += 1
        return {"uploaded": 0}

    monkeypatch.setattr(sched_mod, "import_holdings_from_md", _spy_holdings)
    monkeypatch.setattr(sched_mod, "import_trades_from_md", _spy_trades)
    monkeypatch.setattr(sched_mod, "import_reports_from_disk", _spy_import_reports)
    monkeypatch.setattr(sched_mod, "upload_reports_to_cloud", _spy_upload_reports)

    # 模拟测试环境：即使 lifespan 被触发，副作用函数也不应被调用
    from fastapi.testclient import TestClient
    with TestClient(app_mod.app) as tc:
        assert tc.get("/").status_code in (200, 307)  # 页面可达

    # lifespan 完成后检查：真实副作用函数不应被调用
    # （依赖 app.py lifespan 的测试免疫：PYTEST 环境检测）
    assert calls["import_holdings"] == 0, "测试中 lifespan 不应调用 import_holdings_from_md"
    assert calls["import_trades"] == 0, "测试中 lifespan 不应调用 import_trades_from_md"
    assert calls["import_reports"] == 0, "测试中 lifespan 不应调用 import_reports_from_disk"
    assert calls["upload_reports"] == 0, "测试中 lifespan 不应调用 upload_reports_to_cloud"


# ═══════════════════════════════════════════════════════════════
# 防护3: 真实 DB 写拦截
# ═══════════════════════════════════════════════════════════════

def test_real_db_untouched_by_api_trade_test(monkeypatch, tmp_path):
    """API 交易录入测试（_apply_api_mocks 模式）绝不能写真实 cache.db。

    复刻 test_portfolio_trades.py 的 _apply_api_mocks 隔离方式，
    验证其 DB mock 完整拦截 _sync_ledger_to_db 的真实写路径。
    """
    from dashboard import db as db_mod
    from dashboard import portfolio

    # 用 MagicMock 替换真实 DB 写函数（同 _apply_api_mocks），并打点
    calls = {"replace": 0, "trades": 0}
    mock_replace = MagicMock(side_effect=lambda rows: calls.__setitem__("replace", calls["replace"] + 1))
    mock_trades = MagicMock(side_effect=lambda rows: calls.__setitem__("trades", calls["trades"] + 1))
    monkeypatch.setattr(db_mod, "portfolio_holdings_replace", mock_replace)
    monkeypatch.setattr(db_mod, "portfolio_trades_replace_all", mock_trades)

    # 隔离文件路径（同 ledger_paths fixture）
    daily = tmp_path / "每日调仓.md"
    daily.write_text("# 仓位\n\n## 0. 可用金额\n\n16131\n\n## 1. 当前持仓\n\n持仓：\n\n"
                     "| 股票名称 | 代码 | 持仓量（份） | 成本价（元） | \n"
                     "| -------- | ------ | ------------ | ------------ | \n"
                     "| 半导体ETF | 512480 | 6,100 | 1.044 | \n\n"
                     "## 2. 调仓记录\n\n"
                     "| 日期 | 股票名称 | 股票代码 | 交易数量 | 交易价格 | 买入/卖出 | 备注 |\n"
                     "|---|---|---|---|---|---|---|\n"
                     "| 2026-08-27 | 半导体ETF | 512480 | 6,100 | 1.044 | 买入 | 买入信号  |\n",
                     encoding="utf-8")
    holdings_f = tmp_path / "持仓.md"
    holdings_f.write_text("可用金额: 16131 元\n", encoding="utf-8")
    monkeypatch.setattr(portfolio, "TRADES_MD", daily)
    monkeypatch.setattr(portfolio, "HOLDINGS_MD", holdings_f)
    monkeypatch.setattr(portfolio, "SNAPSHOT_DIR", tmp_path / "undo")
    monkeypatch.setattr(portfolio, "_cs_get", None)
    monkeypatch.setattr(portfolio, "_cs_put", None)
    monkeypatch.setattr(portfolio, "_cs_del", None)
    monkeypatch.setattr(portfolio, "_cs_list", None)

    # mock api_daily 依赖（同 _apply_api_mocks 其余部分）
    monkeypatch.setattr(db_mod, "portfolio_holdings_get_all",
                        lambda: portfolio.read_daily_ledger()["positions"])
    monkeypatch.setattr(db_mod, "portfolio_trades_get_all",
                        lambda: list(reversed(portfolio.read_daily_ledger()["trades"])))
    _meta = {"available_cash": "16131", "total_assets": "0", "account_source": "manual"}
    monkeypatch.setattr(db_mod, "meta_get", lambda k, d=None: _meta.get(k, d))
    monkeypatch.setattr(db_mod, "meta_set", lambda k, v: _meta.update({k: str(v)}))

    def _fake_valuation(holdings, available_cash=0.0, refresh_prices=False):
        return {"totals": {"total_assets": 0, "available_cash": available_cash}, "rows": []}
    monkeypatch.setattr(portfolio, "compute_valuation", _fake_valuation)

    async def _mock_user(request=None):
        return {"username": "admin", "role": "admin", "display_name": "管理员"}
    from dashboard import app as app_mod
    app_mod.app.dependency_overrides[app_mod.get_current_user] = _mock_user

    from fastapi.testclient import TestClient
    tc = TestClient(app_mod.app)
    r = tc.post("/api/portfolio/trades", json={
        "trade_date": "2026-08-28", "name": "半导体ETF", "code": "512480",
        "quantity": 1000, "price": 1.10, "side": "买入", "remark": "测试录入",
    })
    assert r.status_code == 200, r.text
    # 关键断言：写操作必须被 mock 拦截（走 MagicMock，而非真实 DB 函数）
    assert calls["replace"] == 1, "portfolio_holdings_replace 应被 mock 拦截恰好 1 次"
    assert calls["trades"] == 1, "portfolio_trades_replace_all 应被 mock 拦截恰好 1 次"
    app_mod.app.dependency_overrides.clear()
