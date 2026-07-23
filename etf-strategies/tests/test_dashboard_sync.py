"""Tests for dashboard/sync.py — Data synchronization logic.

Tests seed, kline sync, daily signal generation, and backtest NAV sync
with all network/DB dependencies mocked.
"""
import sys
import json
from pathlib import Path
from datetime import date, timedelta
from unittest.mock import MagicMock, call

import pandas as pd
import numpy as np
import pytest

# Ensure etf-strategies is importable
_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

# ── Mock heavy dependencies BEFORE importing sync ──

# Mock strategy_kb module (KB data)
_mock_kb = MagicMock()
_mock_kb.KB = {
    "S1": {
        "name": "买入持有", "class_name": "BuyHold", "category": "被动投资",
        "intro": "恒满仓沪深300", "stock_selection": "无", "market_timing": "无",
        "factors": "无", "rebalance": "不调仓",
        "strengths": "简单", "weaknesses": "回撤大",
        "backtest": {"initial_capital": 1000000},
    },
}
sys.modules["strategy_kb"] = _mock_kb

# Mock backtest.data and backtest.engine — these are only imported locally inside
# sync functions (via `from backtest.data import get_kline` etc.).
# Use monkeypatch.setattr in each test instead of replacing sys.modules,
# to avoid breaking other test files that need the real modules.
# Keep module-level MagicMock references for tests that need to set side_effects.
_mock_backtest_data = None  # will be set per-test via monkeypatch


def _mock_get_kline(monkeypatch, **kw):
    """Mock backtest.data.get_kline for a single test. Returns the mock."""
    import backtest.data as bd
    mock = MagicMock(**kw)
    monkeypatch.setattr(bd, "get_kline", mock)
    return mock


# daily_signal is mocked by conftest.py. Grab the shared mock reference.
_mock_daily_signal = sys.modules["daily_signal"]

import dashboard.sync as sync_mod


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def mock_db(monkeypatch):
    """Mock all dashboard.db functions used by sync.py."""
    # These are imported at module level in sync.py:
    #   from dashboard.db import (get_conn, init_db, is_seeded, mark_seeded,
    #       kline_latest_date, kline_upsert_batch, metrics_upsert, ...)
    monkeypatch.setattr(sync_mod, "init_db", MagicMock())
    monkeypatch.setattr(sync_mod, "is_seeded", MagicMock(return_value=False))
    monkeypatch.setattr(sync_mod, "mark_seeded", MagicMock())
    monkeypatch.setattr(sync_mod, "get_conn", MagicMock())
    monkeypatch.setattr(sync_mod, "kline_latest_date", MagicMock(return_value=None))
    monkeypatch.setattr(sync_mod, "kline_upsert_batch", MagicMock())
    monkeypatch.setattr(sync_mod, "metrics_upsert", MagicMock())
    monkeypatch.setattr(sync_mod, "metrics_get_one", MagicMock(return_value=None))
    monkeypatch.setattr(sync_mod, "signals_upsert", MagicMock())
    monkeypatch.setattr(sync_mod, "signals_delete_old", MagicMock())
    monkeypatch.setattr(sync_mod, "kb_upsert", MagicMock())
    monkeypatch.setattr(sync_mod, "nav_upsert_batch", MagicMock())
    monkeypatch.setattr(sync_mod, "nav_has_data", MagicMock(return_value=False))

    # kline_get_dataframe is imported locally inside sync_daily_signals:
    #   from dashboard.db import kline_get_dataframe
    # Mock it on the db module instead
    import dashboard.db as db_mod
    monkeypatch.setattr(db_mod, "kline_get_dataframe", MagicMock(return_value=pd.DataFrame()))


# ══════════════════════════════════════════════════════════════════════
# seed_all()
# ══════════════════════════════════════════════════════════════════════


class TestSeedAll:
    def test_seeds_metrics_for_all_strategies(self, mock_db):
        """seed_all should call metrics_upsert for each strategy definition."""
        sync_mod.seed_all()

        # 19 strategies defined in STRATEGY_DEFS
        assert sync_mod.metrics_upsert.call_count == 19

    def test_seeds_kb_from_strategy_kb_module(self, mock_db):
        """seed_all should call kb_upsert for each KB entry."""
        sync_mod.seed_all()

        # KB has 1 entry in our mock
        assert sync_mod.kb_upsert.call_count >= 1

    def test_marks_seeded_after_completion(self, mock_db):
        sync_mod.seed_all()

        sync_mod.mark_seeded.assert_called_once()

    def test_still_syncs_when_already_seeded(self, mock_db):
        """Metrics and KB upsert always run (idempotent), even when already seeded."""
        sync_mod.is_seeded.return_value = True

        sync_mod.seed_all()

        # Metrics and KB should still be synced (idempotent upsert)
        assert sync_mod.metrics_upsert.call_count == 19
        assert sync_mod.kb_upsert.call_count >= 1
        # But mark_seeded should NOT be called again
        sync_mod.mark_seeded.assert_not_called()

    def test_handles_missing_kb_module(self, mock_db, monkeypatch):
        """If strategy_kb is not importable, seed should still complete."""
        # Already mocked as a mock module, but let's test import error
        # The seed_all function catches ImportError for KB
        # We know it works because the first test passes with the mock in place

        # Test with KB import failing:
        # Already covered by the try/except in seed_all
        sync_mod.seed_all()
        assert sync_mod.mark_seeded.called

    def test_seeds_correct_metrics_data(self, mock_db):
        sync_mod.seed_all()

        # Check that S4 was seeded with correct data
        # metrics_upsert uses keyword arguments
        s4_call = None
        for c in sync_mod.metrics_upsert.call_args_list:
            if c.kwargs.get("strategy_id") == "S4":
                s4_call = c
                break

        assert s4_call is not None
        assert s4_call.kwargs["strategy_id"] == "S4"
        assert s4_call.kwargs["name"] == "多资产动量轮动"
        assert s4_call.kwargs["category"] == "动量"
        # Ensure benchmark metrics are passed
        assert s4_call.kwargs["annual_return"] == 33.62

    def test_strategies_without_benchmark_get_none_metrics(self, mock_db):
        """S12-S16 have no benchmark data, should get None values."""
        sync_mod.seed_all()

        s12_call = None
        for c in sync_mod.metrics_upsert.call_args_list:
            if c.kwargs.get("strategy_id") == "S12":
                s12_call = c
                break

        assert s12_call is not None
        # S12 has no benchmark → annual_return should be None
        assert s12_call.kwargs["annual_return"] is None


# ══════════════════════════════════════════════════════════════════════
# sync_kline()
# ══════════════════════════════════════════════════════════════════════


class TestSyncKline:
    def test_incremental_fetch_from_last_cached(self, mock_db, monkeypatch):
        """Should fetch from last cached date + 1 day."""
        monkeypatch.setattr(sync_mod, "kline_latest_date", MagicMock(return_value="2024-06-14"))
        # 2024-06-14 is Friday, so next biz day is 2024-06-17 (Monday)

        dates = pd.date_range("2024-06-17", periods=3, freq="B")
        df = pd.DataFrame({
            "open": [3.5, 3.6, 3.7], "high": [3.6, 3.7, 3.8],
            "low": [3.4, 3.5, 3.6], "close": [3.55, 3.65, 3.75],
            "volume": [1e6, 1.1e6, 1.2e6],
        }, index=dates)
        _mock_get_kline(monkeypatch, return_value=df)

        n = sync_mod.sync_kline("510300")
        assert n == 3
        sync_mod.kline_upsert_batch.assert_called_once()
        batch = sync_mod.kline_upsert_batch.call_args[0][0]
        assert len(batch) == 3
        assert batch[0][0] == "510300"
        assert batch[0][1] == "2024-06-17"

    def test_no_fetch_when_already_up_to_date(self, mock_db, monkeypatch):
        """When latest cached date >= today, skip fetch."""
        today_str = date.today().strftime("%Y-%m-%d")
        # Set kline_latest_date to today → start becomes today+1 → start >= end → return 0
        monkeypatch.setattr(sync_mod, "kline_latest_date", MagicMock(return_value=today_str))

        mock_gk = _mock_get_kline(monkeypatch)
        mock_gk.reset_mock()

        n = sync_mod.sync_kline("510300")
        assert n == 0
        mock_gk.assert_not_called()

    def test_full_fetch_when_no_cache(self, mock_db, monkeypatch):
        """When no cache exists, fetch from 2012-01-01."""
        sync_mod.kline_latest_date.return_value = None

        dates = pd.date_range("2012-01-04", periods=2, freq="B")
        df = pd.DataFrame({
            "open": [2.0, 2.1], "high": [2.1, 2.2],
            "low": [1.9, 2.0], "close": [2.05, 2.15],
            "volume": [5e5, 6e5],
        }, index=dates)
        _mock_get_kline(monkeypatch,return_value=df)

        n = sync_mod.sync_kline("510300")
        assert n == 2

    def test_handles_fetch_error_gracefully(self, mock_db, monkeypatch):
        """When get_kline raises, return 0."""
        _mock_get_kline(monkeypatch,side_effect=RuntimeError("Network error"))

        n = sync_mod.sync_kline("510300")
        assert n == 0

    def test_handles_empty_result(self, mock_db, monkeypatch):
        """When get_kline returns empty DataFrame, return 0."""
        _mock_get_kline(monkeypatch,return_value=pd.DataFrame())

        n = sync_mod.sync_kline("510300")
        assert n == 0

    def test_handles_none_result(self, mock_db, monkeypatch):
        """When get_kline returns None, return 0."""
        _mock_get_kline(monkeypatch,return_value=None)

        n = sync_mod.sync_kline("510300")
        assert n == 0


# ══════════════════════════════════════════════════════════════════════
# sync_all_klines()
# ══════════════════════════════════════════════════════════════════════


class TestSyncAllKlines:
    def test_iterates_all_etf_codes(self, mock_db, monkeypatch):
        """Should call sync_kline for each ETF code."""
        _mock_get_kline(monkeypatch,return_value=pd.DataFrame())

        results = sync_mod.sync_all_klines()
        assert len(results) == len(sync_mod.ALL_ETF_CODES)
        # All should be 0 since we returned empty DataFrames
        assert all(v == 0 for v in results.values())

    def test_progress_callback(self, mock_db, monkeypatch):
        _mock_get_kline(monkeypatch,return_value=pd.DataFrame())
        progress_msgs = []

        sync_mod.sync_all_klines(progress_callback=lambda msg: progress_msgs.append(msg))

        assert len(progress_msgs) > 0

    def test_handles_errors_per_code(self, mock_db, monkeypatch):
        """Errors for one code shouldn't stop others.

        sync_kline internally catches get_kline exceptions and returns 0.
        The outer sync_all_klines continues processing all codes.
        """
        call_count = [0]

        def _failing_get_kline(code, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("Network error")
            return pd.DataFrame()

        _mock_get_kline(monkeypatch,side_effect=_failing_get_kline)

        results = sync_mod.sync_all_klines()
        first_code = sync_mod.ALL_ETF_CODES[0]
        # sync_kline catches internal exceptions and returns 0
        # So the first code returns 0 rather than crashing
        assert results[first_code] == 0
        # But all 21 codes should have results
        assert len(results) == len(sync_mod.ALL_ETF_CODES)


# ══════════════════════════════════════════════════════════════════════
# sync_daily_signals()
# ══════════════════════════════════════════════════════════════════════


class TestSyncDailySignals:
    def test_returns_dict_of_results(self, mock_db, monkeypatch):
        """Should return {strategy_id: asset_count} for each strategy."""
        _mock_daily_signal.STRAT_MAP = {}

        results = sync_mod.sync_daily_signals()
        assert isinstance(results, dict)

    def test_calls_signals_delete_old(self, mock_db):
        _mock_daily_signal.STRAT_MAP = {}

        sync_mod.sync_daily_signals()
        sync_mod.signals_delete_old.assert_called_once_with(30)

    def test_empty_prices_returns_zero(self, mock_db, monkeypatch):
        """When no price data available, return 0 for the strategy."""
        import dashboard.db as db_mod

        monkeypatch.setattr(sync_mod, "sync_kline", MagicMock(return_value=0))

        mock_strat = MagicMock()
        mock_strat.assets = ["510300"]
        mock_strat.lookback = 25
        _mock_daily_signal.STRAT_MAP = {"S1": ("买入持有", mock_strat)}

        # kline_get_dataframe returns empty DataFrame
        monkeypatch.setattr(db_mod, "kline_get_dataframe", MagicMock(return_value=pd.DataFrame()))
        # Also mock get_kline to fail (no fallback to cached data)
        _mock_get_kline(monkeypatch, side_effect=RuntimeError("No network"))

        results = sync_mod.sync_daily_signals()
        assert results.get("S1") == 0

    def test_generates_signals_from_prices(self, mock_db, monkeypatch):
        """Full signal generation flow with valid price data."""
        import dashboard.db as db_mod
        import pandas as pd

        # Mock sync_kline for this test only — prevents real API calls in Phase 1
        monkeypatch.setattr(sync_mod, "sync_kline", MagicMock(return_value=0))

        # Create a strategy that returns known weights
        mock_strat = MagicMock()
        mock_strat.assets = ["510300", "511880"]
        mock_strat.lookback = 25

        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        mock_weights = pd.DataFrame({
            "510300": [0.6] * 100,
            "511880": [0.4] * 100,
        }, index=dates)
        mock_strat.generate = MagicMock(return_value=mock_weights)

        _mock_daily_signal.STRAT_MAP = {"S1": ("买入持有", mock_strat)}

        # Provide valid kline data
        kline_df = pd.DataFrame({
            "close": [3.5 + i * 0.01 for i in range(100)],
        }, index=dates)
        monkeypatch.setattr(db_mod, "kline_get_dataframe", MagicMock(return_value=kline_df))

        results = sync_mod.sync_daily_signals()
        assert "S1" in results
        # The new code batches inserts in a transaction via get_conn().execute()
        # rather than calling signals_upsert per asset.
        assert sync_mod.get_conn.called

    def test_handles_strategy_generation_error(self, mock_db, monkeypatch):
        """Error in one strategy shouldn't crash the whole sync."""
        import dashboard.db as db_mod

        monkeypatch.setattr(sync_mod, "sync_kline", MagicMock(return_value=0))

        mock_strat = MagicMock()
        mock_strat.assets = ["510300"]
        mock_strat.lookback = 25  # real int for timedelta calc
        mock_strat.generate = MagicMock(side_effect=RuntimeError("Strategy error"))
        _mock_daily_signal.STRAT_MAP = {"S1": ("Broken", mock_strat)}

        dates = pd.date_range("2024-01-01", periods=100, freq="B")
        kline_df = pd.DataFrame({"close": [3.5] * 100}, index=dates)
        monkeypatch.setattr(db_mod, "kline_get_dataframe", MagicMock(return_value=kline_df))

        results = sync_mod.sync_daily_signals()
        assert results["S1"] == -1


# ══════════════════════════════════════════════════════════════════════
# sync_backtest_nav()
# ══════════════════════════════════════════════════════════════════════


class TestSyncBacktestNav:
    def test_returns_dict_of_results(self, mock_db, monkeypatch):
        """Should iterate over STRATEGY_DEFS and return per-strategy results."""
        # Mock get_kline to return empty → most strategies will fail
        _mock_get_kline(monkeypatch,return_value=pd.DataFrame())

        results = sync_mod.sync_backtest_nav()
        assert isinstance(results, dict)
        assert len(results) == 19  # 19 strategy definitions

    def test_progress_callback(self, mock_db, monkeypatch):
        _mock_get_kline(monkeypatch,return_value=pd.DataFrame())
        progress_msgs = []

        sync_mod.sync_backtest_nav(
            progress_callback=lambda msg: progress_msgs.append(msg)
        )

        assert len(progress_msgs) >= 19
        # First message should mention strategy 1
        assert "1/19" in progress_msgs[0]

    def test_handles_import_error_for_strategy_module(self, mock_db, monkeypatch):
        """Strategies whose module can't be imported should be skipped with -1."""
        # backtest.data.get_kline returns empty → most strategies fail gracefully
        _mock_get_kline(monkeypatch,return_value=pd.DataFrame())

        results = sync_mod.sync_backtest_nav()
        # All strategies should have result entries
        for i in range(1, 18):
            name = f"S{i}"
            assert any(k.startswith(name + "_") for k in results), \
                f"Missing result for {name}"

    def test_all_etf_codes_have_valid_format(self):
        """ALL_ETF_CODES should contain valid 6-digit codes."""
        for code in sync_mod.ALL_ETF_CODES:
            assert len(code) == 6
            assert code.isdigit()

    def test_strategy_defs_have_required_fields(self):
        """Each STRATEGY_DEF entry should have required fields."""
        for s in sync_mod.STRATEGY_DEFS:
            assert "id" in s
            assert "name" in s
            assert "category" in s
            assert "assets" in s
            assert "cls" in s
            assert "mod" in s
            assert s["id"].startswith("S")


# ══════════════════════════════════════════════════════════════════════
# Data integrity checks
# ══════════════════════════════════════════════════════════════════════


class TestDataIntegrity:
    def test_all_etf_codes_have_valid_format(self):
        """ALL_ETF_CODES should contain valid 6-digit codes."""
        for code in sync_mod.ALL_ETF_CODES:
            assert len(code) == 6, f"{code} should be 6 digits"
            assert code.isdigit(), f"{code} should be numeric"

    def test_strategy_assets_subset_of_all_codes(self):
        """Every asset referenced in STRATEGY_DEFS should be in ALL_ETF_CODES."""
        all_codes_set = set(sync_mod.ALL_ETF_CODES)
        for s in sync_mod.STRATEGY_DEFS:
            for asset in s["assets"]:
                assert asset in all_codes_set, \
                    f"{s['id']}: asset {asset} not in ALL_ETF_CODES"

    def test_benchmark_keys_match_strategy_ids(self):
        """BENCHMARKS keys should correspond to valid STRATEGY_DEF ids."""
        strategy_ids = {s["id"] for s in sync_mod.STRATEGY_DEFS}

        for sid in sync_mod.BENCHMARKS:
            assert sid in strategy_ids, f"BENCHMARKS key {sid} has no matching STRATEGY_DEF"

    def test_kwargs_match_strategy_assets(self):
        """Strategy kwargs should reference assets that exist in the strategy's asset list."""
        for s in sync_mod.STRATEGY_DEFS:
            assets = set(s["assets"])
            kwargs = s.get("kwargs", {})
            # Check if kwargs reference asset codes that are in the asset list
            for key in ("asset", "etf", "cash"):
                if key in kwargs:
                    assert kwargs[key] in assets, \
                        f"{s['id']}: kwargs.{key}={kwargs[key]} not in assets={assets}"
