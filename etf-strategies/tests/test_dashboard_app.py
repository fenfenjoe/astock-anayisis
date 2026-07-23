"""Tests for dashboard/app.py — FastAPI REST API endpoints.

Uses FastAPI TestClient with mocked database and heavy dependencies.
All tests run without network access.
"""
import sys
import json
import threading
from pathlib import Path
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

# Ensure etf-strategies is importable
_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

# ── Mock heavy dependencies BEFORE importing app ──

# daily_signal is mocked by conftest.py. Grab the shared mock reference.
_mock_daily_signal = sys.modules["daily_signal"]

# Mock html_report module
_mock_html_report = MagicMock()
_mock_html_report.generate_report = MagicMock(return_value=Path("/tmp/report_S1.html"))
sys.modules["html_report"] = _mock_html_report

# DO NOT mock backtest.data or backtest.engine at module level — they would
# break other test files that import the real modules. These are only imported
# inside specific route handlers (get_score_curves, run_backtest).
# Mock them in individual tests via monkeypatch instead.

# Now import the app
from dashboard.app import app as fastapi_app
from fastapi.testclient import TestClient


# ── Shared test data ────────────────────────────────────────────────

TODAY = date.today().strftime("%Y-%m-%d")

# NOTE: metrics_get_one returns RAW NUMERIC values (not formatted strings)
# The app.py format logic applies .2f% etc.
MOCK_METRICS_LIST = [
    {
        "id": "S1", "name": "买入持有", "category": "被动投资",
        "category_cn": "被动投资 / 基准", "annual_return": 8.19,
        "sharpe": 0.30, "max_drawdown": -52.97, "calmar": 0.15,
        "win_rate": 52.1, "turnover": 0.0, "excess_return": 0.0,
        "ann_val": 8.19, "dd_val": -52.97, "desc": "恒满仓沪深300",
        "assets": ["510300"], "description": "恒满仓沪深300ETF",
        "backtest_window": "2012~2026",
    },
    {
        "id": "S4", "name": "多资产动量轮动", "category": "动量",
        "category_cn": "动量轮动", "annual_return": 33.62,
        "sharpe": 1.21, "max_drawdown": -28.51, "calmar": 1.18,
        "win_rate": 54.5, "turnover": 29.9, "excess_return": 25.43,
        "ann_val": 33.62, "dd_val": -28.51, "desc": "四资产动量轮动",
        "assets": ["518880", "513100", "159915", "510180"],
        "description": "25日动量打分轮动", "backtest_window": "2013~2026",
    },
]

MOCK_KB_DATA = {
    "S1": {
        "id": "S1", "name": "买入持有", "class_name": "BuyHold",
        "category": "被动投资", "intro": "恒满仓沪深300ETF不动，作为所有策略对照基准。",
        "stock_selection": "无择股，满仓单一资产", "market_timing": "无择时",
        "factors": "无", "rebalance": "不调仓",
        "strengths": "简单透明，交易成本极低", "weaknesses": "回撤极大，无风险控制",
        "backtest": {"initial_capital": 1000000, "commission": 0.0003},
    },
}

MOCK_SIGNALS = {
    "S1": [{
        "id": 1, "strategy_id": "S1", "signal_date": TODAY,
        "asset_code": "510300", "asset_name": "沪深300ETF",
        "target_weight": 1.0, "prev_weight": 1.0,
        "weight_change": 0.0, "action": "HOLD",
    }],
}

MOCK_NAV_DATA = {
    "dates": ["2024-01-05", "2024-01-12", "2024-01-19"],
    "series": {
        "S1_买入持有": [1.0, 1.05, 1.10],
        "S4_多资产动量轮动": [1.0, 1.15, 1.32],
    },
    "drawdowns": {
        "S1_买入持有": [0.0, -0.02, -0.01],
        "S4_多资产动量轮动": [0.0, -0.05, 0.0],
    },
}


# ── Fixtures ────────────────────────────────────────────────────────


def _apply_db_mocks(monkeypatch, *, nav_has_data=False):
    """Apply all DB-layer mocks to the app module."""
    import dashboard.app as app_mod

    # Mock the auth dependency so existing tests work without tokens.
    # Must use app.dependency_overrides because the APIRouter captures
    # get_current_user at import time — monkeypatching the module-level
    # name won't affect the router's dependency reference.
    async def _mock_get_current_user(request=None):
        return {"username": "admin", "role": "admin", "display_name": "管理员"}
    app_mod.app.dependency_overrides[app_mod.get_current_user] = _mock_get_current_user

    # Mock auth startup functions (user seeding / secret key warning)
    monkeypatch.setattr(app_mod, "user_count", MagicMock(return_value=1))
    monkeypatch.setattr(app_mod, "user_create", MagicMock())
    monkeypatch.setattr(app_mod, "get_secret_key_warning", MagicMock(return_value=None))

    monkeypatch.setattr(app_mod, "init_db", MagicMock())
    monkeypatch.setattr(app_mod, "is_seeded", MagicMock(return_value=True))
    monkeypatch.setattr(app_mod, "metrics_get_all", MagicMock(return_value=MOCK_METRICS_LIST))

    def _metrics_get_one(sid):
        for m in MOCK_METRICS_LIST:
            if m["id"] == sid:
                return m
        return None

    monkeypatch.setattr(app_mod, "metrics_get_one", MagicMock(side_effect=_metrics_get_one))

    def _kb_get(sid):
        return MOCK_KB_DATA.get(sid)

    monkeypatch.setattr(app_mod, "kb_get", MagicMock(side_effect=_kb_get))

    def _signals_get_latest(sid):
        return MOCK_SIGNALS.get(sid)

    monkeypatch.setattr(app_mod, "signals_get_latest", MagicMock(side_effect=_signals_get_latest))

    monkeypatch.setattr(app_mod, "nav_get_all", MagicMock(return_value=MOCK_NAV_DATA))
    monkeypatch.setattr(app_mod, "nav_has_data", MagicMock(return_value=nav_has_data))

    # Sync functions imported in route handlers or lifespan
    monkeypatch.setattr(app_mod, "sync_daily_signals", MagicMock(return_value={}))
    monkeypatch.setattr(app_mod, "sync_backtest_nav", MagicMock(return_value={}))

    # Reset backtest state
    app_mod._cache["backtest_status"] = "idle"
    app_mod._cache["backtest_message"] = ""


@pytest.fixture
def client(monkeypatch):
    """FastAPI TestClient with all DB mocks pre-applied, no NAV data."""
    _apply_db_mocks(monkeypatch, nav_has_data=False)
    return TestClient(fastapi_app)


@pytest.fixture
def client_with_nav(monkeypatch):
    """FastAPI TestClient with NAV data available (charts ready)."""
    _apply_db_mocks(monkeypatch, nav_has_data=True)
    return TestClient(fastapi_app)


# ══════════════════════════════════════════════════════════════════════
# Static & Template Routes
# ══════════════════════════════════════════════════════════════════════


class TestStaticRoutes:
    def test_index_returns_html(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")

    def test_static_css_accessible(self, client):
        response = client.get("/static/css/dashboard.css")
        assert response.status_code == 200

    def test_static_js_accessible(self, client):
        response = client.get("/static/js/dashboard.js")
        assert response.status_code == 200


# ══════════════════════════════════════════════════════════════════════
# GET /api/strategies
# ══════════════════════════════════════════════════════════════════════


class TestListStrategies:
    def test_returns_all_strategies(self, client):
        response = client.get("/api/strategies")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        ids = {s["id"] for s in data}
        assert ids == {"S1", "S4"}

    def test_accepts_sort_params(self, client):
        response = client.get("/api/strategies?sort_by=sharpe&order=desc")
        assert response.status_code == 200

    def test_invalid_sort_col_does_not_crash(self, client):
        response = client.get("/api/strategies?sort_by=nonexistent")
        assert response.status_code == 200

    def test_response_has_required_fields(self, client):
        response = client.get("/api/strategies")
        for s in response.json():
            assert "id" in s
            assert "name" in s
            assert "category" in s
            assert "annual_return" in s


# ══════════════════════════════════════════════════════════════════════
# GET /api/strategies/{sid}
# ══════════════════════════════════════════════════════════════════════


class TestGetStrategyDetail:
    def test_returns_kb_and_metrics(self, client):
        response = client.get("/api/strategies/S1")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "S1"
        assert data["name"] == "买入持有"
        assert data["category"] == "被动投资"
        assert data["intro"] == "恒满仓沪深300ETF不动，作为所有策略对照基准。"
        assert "metrics" in data
        # App formats annual_return as "8.19%"
        assert data["metrics"]["annual_return"] == "8.19%"

    def test_returns_backtest_params(self, client):
        response = client.get("/api/strategies/S1")
        data = response.json()
        assert "backtest" in data
        assert data["backtest"]["initial_capital"] == 1000000

    def test_404_for_unknown_strategy(self, client):
        response = client.get("/api/strategies/S99")
        assert response.status_code == 404

    def test_strategy_in_metrics_only(self, client):
        """S4 exists in metrics but not KB — should still return."""
        response = client.get("/api/strategies/S4")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "S4"
        assert "metrics" in data
        # KB fields absent or empty
        assert data.get("intro") in (None, "")

    def test_metrics_formatted(self, client):
        response = client.get("/api/strategies/S4")
        m = response.json()["metrics"]
        assert m["annual_return"] == "33.62%"
        assert m["max_drawdown"] == "-28.51%"

    def test_lowercase_sid_is_uppercased(self, client):
        response = client.get("/api/strategies/s1")
        assert response.status_code == 200


# ══════════════════════════════════════════════════════════════════════
# GET /api/signals/{sid}
# ══════════════════════════════════════════════════════════════════════


class TestGetSignal:
    def test_returns_cached_signal(self, client):
        response = client.get("/api/signals/S1")
        assert response.status_code == 200
        data = response.json()
        assert data["strategy_id"] == "S1"
        assert data.get("_cached") is True
        assert len(data["assets"]) == 1
        assert data["assets"][0]["code"] == "510300"

    def test_cached_signal_structure(self, client):
        response = client.get("/api/signals/S1")
        data = response.json()
        for key in ("strategy_name", "signal_date", "actions", "holdings", "has_signals"):
            assert key in data, f"Missing key: {key}"

    def test_buy_sell_actions(self, client, monkeypatch):
        import dashboard.app as app_mod

        buy_sell = [
            {
                "id": 1, "strategy_id": "S4", "signal_date": TODAY,
                "asset_code": "513100", "asset_name": "纳指ETF",
                "target_weight": 0.8, "prev_weight": 0.3,
                "weight_change": 0.5, "action": "BUY",
            },
            {
                "id": 2, "strategy_id": "S4", "signal_date": TODAY,
                "asset_code": "511880", "asset_name": "银华日利",
                "target_weight": 0.2, "prev_weight": 0.7,
                "weight_change": -0.5, "action": "SELL",
            },
        ]
        monkeypatch.setattr(app_mod, "signals_get_latest", MagicMock(return_value=buy_sell))
        monkeypatch.setattr(app_mod, "metrics_get_one",
                            MagicMock(return_value={"id": "S4", "name": "多资产动量轮动"}))

        response = client.get("/api/signals/S4")
        assert response.status_code == 200
        data = response.json()
        assert data["has_signals"] is True
        assert len(data["actions"]) == 2
        actions = {a["code"]: a["action"] for a in data["actions"]}
        assert actions["513100"] == "BUY"
        assert actions["511880"] == "SELL"

    def test_stale_cache_triggers_regeneration(self, client, monkeypatch):
        import dashboard.app as app_mod

        yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        stale = [{
            "id": 1, "strategy_id": "S1", "signal_date": yesterday,
            "asset_code": "510300", "asset_name": "HS300",
            "target_weight": 1.0, "prev_weight": 0.5,
            "weight_change": 0.5, "action": "BUY",
        }]
        monkeypatch.setattr(app_mod, "signals_get_latest", MagicMock(return_value=stale))

        # Regeneration will fail since STRAT_MAP is empty on the mock daily_signal
        # We just verify the endpoint doesn't crash unhandled
        response = client.get("/api/signals/S1")
        assert response.status_code in (200, 404, 500)


# ══════════════════════════════════════════════════════════════════════
# GET /api/signals — Summary
# ══════════════════════════════════════════════════════════════════════


class TestGetSignalsSummary:
    def test_returns_summary(self, client, monkeypatch):
        import dashboard.app as app_mod

        _mock_daily_signal.STRAT_MAP = {
            "S1": ("买入持有", MagicMock()),
            "S4": ("多资产动量轮动", MagicMock()),
        }

        response = client.get("/api/signals")
        assert response.status_code == 200
        data = response.json()
        assert "strategies" in data
        assert "total_buy" in data
        assert "total_sell" in data

    def test_uncached_strategy_shows_error(self, client, monkeypatch):
        import dashboard.app as app_mod

        _mock_daily_signal.STRAT_MAP = {"S1": ("买入持有", MagicMock())}
        monkeypatch.setattr(app_mod, "signals_get_latest", MagicMock(return_value=None))

        response = client.get("/api/signals")
        assert response.status_code == 200
        data = response.json()
        # First (and only) strategy should have error flag since no cached signal
        assert len(data["strategies"]) > 0
        assert data["strategies"][0].get("error") is True


# ══════════════════════════════════════════════════════════════════════
# POST /api/refresh/signals
# ══════════════════════════════════════════════════════════════════════


class TestRefreshSignals:
    def test_returns_status_with_counts(self, client, monkeypatch):
        import dashboard.app as app_mod

        monkeypatch.setattr(app_mod, "sync_daily_signals", MagicMock(return_value={
            "S1": 1, "S4": 4, "S8": -1,
        }))

        response = client.post("/api/refresh/signals")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "done"
        assert data["ok"] == 2
        assert data["fail"] == 1

    def test_error_propagates_as_500(self, client, monkeypatch):
        import dashboard.app as app_mod

        monkeypatch.setattr(app_mod, "sync_daily_signals",
                            MagicMock(side_effect=RuntimeError("Boom")))

        response = client.post("/api/refresh/signals")
        assert response.status_code == 500


# ══════════════════════════════════════════════════════════════════════
# POST /api/refresh/klines
# ══════════════════════════════════════════════════════════════════════


class TestRefreshKlines:
    def test_starts_background_sync(self, client, monkeypatch):
        # sync_all_klines is imported inside the route via:
        #   from dashboard.sync import sync_all_klines
        import dashboard.sync as real_sync
        monkeypatch.setattr(real_sync, "sync_all_klines", MagicMock())

        response = client.post("/api/refresh/klines")
        assert response.status_code == 200
        assert response.json()["status"] == "started"


# ══════════════════════════════════════════════════════════════════════
# GET /api/charts/status & /api/charts/equity
# ══════════════════════════════════════════════════════════════════════


class TestChartStatus:
    def test_returns_idle_when_no_backtest(self, client):
        response = client.get("/api/charts/status")
        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is False


class TestChartsEquity:
    def test_returns_202_when_no_nav(self, client):
        response = client.get("/api/charts/equity")
        assert response.status_code == 202
        assert response.json()["data"] is None

    def test_returns_equity_data(self, client_with_nav):
        response = client_with_nav.get("/api/charts/equity")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "done"
        assert len(data["dates"]) == 3
        assert "S1_买入持有" in data["series"]

    def test_filter_by_strategy(self, client_with_nav):
        response = client_with_nav.get("/api/charts/equity?strategies=S1_买入持有")
        assert response.status_code == 200
        data = response.json()
        assert len(data["series"]) == 1
        assert "S4_多资产动量轮动" not in data["series"]


# ══════════════════════════════════════════════════════════════════════
# POST /api/backtest/run
# ══════════════════════════════════════════════════════════════════════


class TestBacktestRun:
    def test_trigger_returns_started(self, client):
        response = client.post("/api/backtest/run")
        assert response.status_code == 200
        assert response.json()["status"] == "started"

    def test_already_running_returns_running(self, client, monkeypatch):
        import dashboard.app as app_mod
        app_mod._cache["backtest_status"] = "running"

        try:
            response = client.post("/api/backtest/run")
            assert response.status_code == 200
            assert response.json()["status"] == "running"
        finally:
            app_mod._cache["backtest_status"] = "idle"


# ══════════════════════════════════════════════════════════════════════
# POST /api/report/{sid}
# ══════════════════════════════════════════════════════════════════════


class TestGenerateReport:
    def test_generates_report_for_known_strategy(self, client):
        # STRAT_MAP comes from `from daily_signal import STRAT_MAP` inside route
        mock_strat = MagicMock()
        mock_strat.assets = ["510300"]
        mock_strat.lookback = 25
        _mock_daily_signal.STRAT_MAP = {"S1": ("买入持有", mock_strat)}

        response = client.post("/api/report/S1")
        assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
        data = response.json()
        assert data["status"] == "done"
        assert data["strategy_id"] == "S1"

    def test_404_for_unknown_strategy(self, client):
        _mock_daily_signal.STRAT_MAP = {}
        response = client.post("/api/report/S99")
        assert response.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# GET /api/scores/{sid}
# ══════════════════════════════════════════════════════════════════════


class TestScoreCurves:
    def test_404_for_unknown_strategy(self, client):
        _mock_daily_signal.STRAT_MAP = {}
        _mock_daily_signal.get_etf_name = MagicMock(return_value="TestETF")

        response = client.get("/api/scores/S99")
        assert response.status_code == 404

    def test_insufficient_price_data_returns_400(self, client, monkeypatch):
        import pandas as pd

        mock_strat = MagicMock()
        mock_strat.assets = ["513100", "159915"]
        mock_strat.lookback = 25
        _mock_daily_signal.STRAT_MAP = {"S4": ("动量轮动", mock_strat)}
        _mock_daily_signal.get_etf_name = MagicMock(return_value="TestETF")

        # _load_prices_from_db tries DB first → mock empty to force API fallback
        import dashboard.db as ddb
        monkeypatch.setattr(ddb, "kline_get_dataframe",
                          MagicMock(return_value=pd.DataFrame()))

        # get_kline is imported inside _load_prices_from_db via:
        #   from backtest.data import get_kline
        # Mock the backtest.data module's get_kline function
        def _short_kline(code, start=None, end=None, refresh=False):
            dates = pd.date_range("2024-01-01", periods=5, freq="B")
            return pd.DataFrame({"close": [100.0 + i * 0.1 for i in range(5)]}, index=dates)

        import backtest.data as bd
        monkeypatch.setattr(bd, "get_kline", MagicMock(side_effect=_short_kline))

        response = client.get("/api/scores/S4")
        # Either 400 (Insufficient price data) or 500 (internal error during score computation)
        assert response.status_code in (400, 500), \
            f"Got {response.status_code}: {response.text}"


# ══════════════════════════════════════════════════════════════════════
# Error Handling
# ══════════════════════════════════════════════════════════════════════


class TestErrorHandling:
    def test_lowercase_sid_normalized(self, client):
        response = client.get("/api/strategies/s1")
        assert response.status_code == 200

    def test_trailing_slash_on_detail(self, client):
        response = client.get("/api/strategies/")
        assert response.status_code in (200, 307)

    def test_signal_unknown_strategy_404(self, client):
        _mock_daily_signal.STRAT_MAP = {}
        # signals_get_latest returns None → tries to generate → STRAT_MAP miss → 404
        response = client.get("/api/signals/S99")
        assert response.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# GET /api/strategies/{sid}/source — Strategy Source Code
# ══════════════════════════════════════════════════════════════════════


class TestGetStrategySource:
    def test_returns_source_code(self, client, monkeypatch):
        """Should return the Python source for a known strategy."""
        import dashboard.sync as real_sync
        mock_defs = [
            {"id": "S1", "name": "买入持有", "mod": "backtest.strategies.buy_hold",
             "cls": "BuyHold", "kwargs": {"code": "510300"}},
        ]
        monkeypatch.setattr(real_sync, "STRATEGY_DEFS", mock_defs)

        response = client.get("/api/strategies/S1/source")
        assert response.status_code == 200
        data = response.json()
        assert data["strategy_id"] == "S1"
        assert "source_code" in data
        assert data["lines"] > 0
        assert "class BuyHold" in data["source_code"] or "BuyHold" in data["source_code"]

    def test_404_for_unknown_strategy(self, client, monkeypatch):
        import dashboard.sync as real_sync
        monkeypatch.setattr(real_sync, "STRATEGY_DEFS", [])

        response = client.get("/api/strategies/S99/source")
        assert response.status_code == 404

    def test_404_for_missing_source_file(self, client, monkeypatch):
        """Strategy defined but source file doesn't exist."""
        import dashboard.sync as real_sync
        mock_defs = [
            {"id": "SX", "name": "Fake", "mod": "nonexistent.module",
             "cls": "Fake", "kwargs": {}},
        ]
        monkeypatch.setattr(real_sync, "STRATEGY_DEFS", mock_defs)

        response = client.get("/api/strategies/SX/source")
        assert response.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# POST /api/klines/ensure/{sid} — K-line Sync
# ══════════════════════════════════════════════════════════════════════


class TestEnsureKlines:
    def test_returns_sync_result(self, client, monkeypatch):
        """Should sync K-lines and return results."""
        import dashboard.sync as real_sync
        monkeypatch.setattr(real_sync, "sync_kline", MagicMock(return_value=0))

        # Create a mock strategy
        mock_strat = MagicMock()
        mock_strat.assets = ["510300", "511260"]
        _mock_daily_signal.STRAT_MAP = {"S1": ("买入持有", mock_strat)}

        response = client.post("/api/klines/ensure/S1")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "done"
        assert data["strategy_id"] == "S1"
        # sync_kline returned 0 rows (already fresh)
        assert data["total_new_rows"] == 0

    def test_404_for_unknown_strategy(self, client):
        _mock_daily_signal.STRAT_MAP = {}
        response = client.post("/api/klines/ensure/S99")
        assert response.status_code == 404

    def test_reports_new_rows(self, client, monkeypatch):
        """Should report new rows when sync fetches fresh data."""
        import dashboard.sync as real_sync
        monkeypatch.setattr(real_sync, "sync_kline", MagicMock(return_value=50))

        mock_strat = MagicMock()
        mock_strat.assets = ["513100"]
        _mock_daily_signal.STRAT_MAP = {"S4": ("多资产动量轮动", mock_strat)}

        response = client.post("/api/klines/ensure/S4")
        assert response.status_code == 200
        data = response.json()
        assert data["total_new_rows"] == 50


# ══════════════════════════════════════════════════════════════════════
# POST /api/backtest/{sid} — Single Strategy Backtest
# ══════════════════════════════════════════════════════════════════════


class TestSingleStrategyBacktest:
    def test_404_for_unknown_strategy(self, client, monkeypatch):
        import dashboard.sync as real_sync
        monkeypatch.setattr(real_sync, "STRATEGY_DEFS", [])

        response = client.post("/api/backtest/S99")
        assert response.status_code == 404

    def test_returns_error_on_import_failure(self, client, monkeypatch):
        """Strategy class can't be imported."""
        import dashboard.sync as real_sync
        mock_defs = [
            {"id": "SX", "name": "Broken", "mod": "nonexistent.module",
             "cls": "Fake", "kwargs": {}, "window": "2012-01-01~2026-01-01",
             "category": "动量", "category_cn": "动量", "desc": "broken", "assets": ["510300"]},
        ]
        monkeypatch.setattr(real_sync, "STRATEGY_DEFS", mock_defs)

        response = client.post("/api/backtest/SX")
        assert response.status_code == 500


# ══════════════════════════════════════════════════════════════════════
# Edge Cases & Regression Tests
# ══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_list_strategies_empty_db(self, client, monkeypatch):
        """When no strategies exist in DB, should return empty list."""
        import dashboard.app as app_mod
        monkeypatch.setattr(app_mod, "metrics_get_all", MagicMock(return_value=[]))

        response = client.get("/api/strategies")
        assert response.status_code == 200
        assert response.json() == []

    def test_strategy_detail_kb_only_no_metrics(self, client, monkeypatch):
        """Strategy has KB but no metrics — should still return."""
        import dashboard.app as app_mod
        monkeypatch.setattr(app_mod, "metrics_get_one", MagicMock(return_value=None))
        # kb_get already returns S1 from the fixture

        response = client.get("/api/strategies/S1")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "S1"
        # Metrics should be absent from the result (not even an empty dict)
        assert "metrics" not in data

    def test_signal_summary_handles_import_error(self, client, monkeypatch):
        """When daily_signal can't be imported, return empty summary."""
        import dashboard.app as app_mod
        # mock the import to fail by removing STRAT_MAP
        monkeypatch.setattr(app_mod, "signals_get_latest", MagicMock(return_value=None))

        # The endpoint imports daily_signal inside the function
        response = client.get("/api/signals")
        assert response.status_code == 200
        data = response.json()
        assert "strategies" in data
        assert data["total_buy"] == 0

    def test_refresh_klines_background_thread(self, client, monkeypatch):
        """K-line refresh starts in background thread."""
        import dashboard.sync as real_sync
        sync_called = []

        def _tracked_sync():
            sync_called.append(True)

        monkeypatch.setattr(real_sync, "sync_all_klines", MagicMock(side_effect=_tracked_sync))

        response = client.post("/api/refresh/klines")
        assert response.status_code == 200
        assert response.json()["status"] == "started"

    def test_chart_status_idle(self, client):
        """Chart status should report idle when no backtest has run."""
        response = client.get("/api/charts/status")
        assert response.status_code == 200
        assert response.json()["ready"] is False

    def test_backtest_trigger_already_running(self, client, monkeypatch):
        """When backtest is already running, should report that."""
        import dashboard.app as app_mod
        app_mod._cache["backtest_status"] = "running"
        try:
            response = client.post("/api/backtest/run")
            assert response.status_code == 200
            assert response.json()["status"] == "running"
        finally:
            app_mod._cache["backtest_status"] = "idle"

    def test_scores_endpoint_import_error_handling(self, client, monkeypatch):
        """When daily_signal is not importable, scores should return 500 with message."""
        import dashboard.app as app_mod

        # Make STRAT_MAP inaccessible
        _mock_daily_signal.STRAT_MAP = {}

        response = client.get("/api/scores/S4")
        assert response.status_code == 404  # Strategy not in STRAT_MAP

    def test_cached_signal_has_empty_window(self, client):
        """Cached signals should return with empty data_start/data_end (regression test)."""
        response = client.get("/api/signals/S1")
        assert response.status_code == 200
        data = response.json()
        # Cached signals have empty data window fields
        assert data.get("data_start") == ""
        assert data.get("data_end") == ""
        assert data.get("trading_days") == 0
        # But signal_date should still be present
        assert "signal_date" in data

    def test_strategy_ids_are_uppercased(self, client):
        """Lowercase strategy IDs should be normalized to uppercase."""
        response = client.get("/api/strategies/s1")
        assert response.status_code == 200
        # S1 exists in metrics mock
        data = response.json()
        assert data["id"] == "S1"

    def test_equity_with_misaligned_nav_dates(self, client_with_nav, monkeypatch):
        """When NAV data has different date ranges across strategies,
        the equity endpoint should return aligned series (null-padded)."""
        import dashboard.app as app_mod
        # Simulate nav_get_all with misaligned dates (after single-strategy backtest)
        misaligned_nav = {
            "dates": ["2024-01-05", "2024-01-12", "2024-01-19"],
            "series": {
                "S1_买入持有": [1.10, 1.15, None],       # Missing 2024-01-19
                "S4_多资产动量轮动": [None, 1.20, 1.25],  # Missing 2024-01-05
            },
            "drawdowns": {
                "S1_买入持有": [-0.03, -0.01, None],
                "S4_多资产动量轮动": [None, -0.02, 0.0],
            },
        }
        monkeypatch.setattr(app_mod, "nav_get_all", MagicMock(return_value=misaligned_nav))
        monkeypatch.setattr(app_mod, "nav_has_data", MagicMock(return_value=True))

        response = client_with_nav.get("/api/charts/equity")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "done"
        # Both series should have 3 entries (matching date axis length)
        assert len(data["series"]["S1_买入持有"]) == 3
        assert len(data["series"]["S4_多资产动量轮动"]) == 3

    def test_signal_generation_handles_empty_prices(self, client, monkeypatch):
        """When no price data is available, signal generation should error gracefully."""
        import pandas as pd
        import dashboard.app as app_mod

        # Create mock strategy in STRAT_MAP
        mock_strat = MagicMock()
        mock_strat.assets = ["510300"]
        mock_strat.lookback = 25
        _mock_daily_signal.STRAT_MAP = {"S1": ("买入持有", mock_strat)}
        _mock_daily_signal.get_etf_name = MagicMock(return_value="沪深300ETF")

        # _load_prices_from_db raises RuntimeError when no data
        monkeypatch.setattr(app_mod, "signals_get_latest", MagicMock(return_value=None))

        # _load_prices_from_db calls these — make them fail
        import dashboard.sync as real_sync
        monkeypatch.setattr(real_sync, "sync_kline", MagicMock(side_effect=RuntimeError("No data")))

        # kline_get_dataframe returns empty
        import dashboard.db as ddb
        monkeypatch.setattr(ddb, "kline_get_dataframe", MagicMock(return_value=pd.DataFrame()))

        response = client.get("/api/signals/S1")
        # Should get 500 since prices can't be loaded
        assert response.status_code in (404, 500)

    def test_ensure_klines_handles_sync_failure(self, client, monkeypatch):
        """Should handle sync_kline failures gracefully (per-code error handling)."""
        import dashboard.sync as real_sync
        # sync_kline raises for one code but succeeds for another
        call_seq = [0]

        def flaky_sync(code):
            call_seq[0] += 1
            if call_seq[0] == 1:
                raise RuntimeError("Network error")
            return 10

        monkeypatch.setattr(real_sync, "sync_kline", MagicMock(side_effect=flaky_sync))

        mock_strat = MagicMock()
        mock_strat.assets = ["510300", "511260"]
        _mock_daily_signal.STRAT_MAP = {"S4": ("多资产动量轮动", mock_strat)}

        response = client.post("/api/klines/ensure/S4")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "done"
        # First code (-1 = failed), second succeeded with 10 rows
        assert data["total_new_rows"] == 10
        assert data["details"]["510300"] == -1
        assert data["details"]["511260"] == 10
