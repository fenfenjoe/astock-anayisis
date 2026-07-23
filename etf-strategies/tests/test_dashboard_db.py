"""Tests for dashboard/db.py — SQLite CRUD operations.

Uses in-memory SQLite databases via monkeypatching to avoid touching
the production cache.db file.
"""
import sys
import sqlite3
import json
from pathlib import Path
from datetime import date, timedelta
from contextlib import contextmanager

import pytest

# Ensure dashboard is importable
_PARENT = Path(__file__).resolve().parent.parent
if str(_PARENT) not in sys.path:
    sys.path.insert(0, str(_PARENT))

import dashboard.db as db_mod


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def use_memory_db(monkeypatch):
    """Redirect all DB operations to an in-memory SQLite database."""
    mem_conn = sqlite3.connect(":memory:")
    mem_conn.row_factory = sqlite3.Row
    mem_conn.execute("PRAGMA journal_mode=WAL")
    mem_conn.execute("PRAGMA foreign_keys=ON")

    @contextmanager
    def _get_conn():
        try:
            yield mem_conn
            mem_conn.commit()
        except Exception:
            mem_conn.rollback()
            raise

    monkeypatch.setattr(db_mod, "get_conn", _get_conn)
    monkeypatch.setattr(db_mod, "DB_PATH", Path(":memory:"))
    yield mem_conn
    mem_conn.close()


@pytest.fixture
def seeded_db(use_memory_db):
    """Initialize schema and mark as seeded."""
    db_mod.init_db()
    db_mod.mark_seeded()
    return use_memory_db


# ══════════════════════════════════════════════════════════════════════
# Schema & Initialization
# ══════════════════════════════════════════════════════════════════════


class TestInitDb:
    def test_init_creates_all_tables(self, use_memory_db):
        db_mod.init_db()
        conn = use_memory_db
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        names = {r["name"] for r in tables}
        expected = {"kline_daily", "strategy_metrics", "daily_signals",
                    "strategy_kb", "backtest_nav", "metadata"}
        assert expected.issubset(names)

    def test_init_is_idempotent(self, use_memory_db):
        db_mod.init_db()
        db_mod.init_db()  # Should not raise
        db_mod.init_db()  # Third time's the charm

    def test_init_creates_indexes(self, use_memory_db):
        db_mod.init_db()
        conn = use_memory_db
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
        ).fetchall()
        names = {r["name"] for r in indexes}
        expected = {"idx_kline_code", "idx_kline_date",
                    "idx_signal_sid", "idx_nav_name"}
        assert expected.issubset(names)


class TestIsSeeded:
    def test_not_seeded_initially(self, use_memory_db):
        db_mod.init_db()
        assert db_mod.is_seeded() is False

    def test_seeded_after_mark(self, use_memory_db):
        db_mod.init_db()
        db_mod.mark_seeded()
        assert db_mod.is_seeded() is True

    def test_mark_seeded_idempotent(self, use_memory_db):
        db_mod.init_db()
        db_mod.mark_seeded()
        db_mod.mark_seeded()
        assert db_mod.is_seeded() is True

    def test_seeded_value_not_one_returns_false(self, use_memory_db):
        """If seeded key exists but value is not '1', treat as not seeded."""
        db_mod.init_db()
        with db_mod.get_conn() as conn:
            conn.execute("INSERT INTO metadata(key, value) VALUES('seeded', '0')")
        assert db_mod.is_seeded() is False


# ══════════════════════════════════════════════════════════════════════
# K-line CRUD
# ══════════════════════════════════════════════════════════════════════


class TestKlineCrud:
    def test_upsert_and_get(self, use_memory_db):
        db_mod.init_db()
        db_mod.kline_upsert("510300", "2024-01-15", 3.50, 3.60, 3.45, 3.55, 1000000)

        rows = db_mod.kline_get("510300")
        assert len(rows) == 1
        assert rows[0]["code"] == "510300"
        assert rows[0]["close"] == 3.55
        assert rows[0]["date"] == "2024-01-15"

    def test_upsert_is_repeatable(self, use_memory_db):
        """Re-upserting the same primary key should replace, not duplicate."""
        db_mod.init_db()
        db_mod.kline_upsert("510300", "2024-06-01", 1.0, 2.0, 0.5, 1.5, 500)
        db_mod.kline_upsert("510300", "2024-06-01", 1.1, 2.1, 0.6, 1.6, 600)

        rows = db_mod.kline_get("510300")
        assert len(rows) == 1
        assert rows[0]["close"] == 1.6

    def test_upsert_batch(self, use_memory_db):
        db_mod.init_db()
        batch = [
            ("510300", "2024-01-02", 3.50, 3.60, 3.45, 3.55, 1e6),
            ("510300", "2024-01-03", 3.56, 3.62, 3.50, 3.60, 1.1e6),
            ("511260", "2024-01-02", 100.1, 100.2, 100.0, 100.15, 5e5),
        ]
        db_mod.kline_upsert_batch(batch)

        assert len(db_mod.kline_get("510300")) == 2
        assert len(db_mod.kline_get("511260")) == 1

    def test_get_with_date_range(self, use_memory_db):
        db_mod.init_db()
        for day in range(1, 10):
            db_mod.kline_upsert("510300", f"2024-01-{day:02d}",
                                3.5, 3.6, 3.4, 3.5 + day * 0.01, 1e6)

        rows_all = db_mod.kline_get("510300")
        assert len(rows_all) == 9

        rows_range = db_mod.kline_get("510300", start="2024-01-03", end="2024-01-05")
        assert len(rows_range) == 3

    def test_get_unknown_code_returns_empty(self, use_memory_db):
        db_mod.init_db()
        assert db_mod.kline_get("999999") == []

    def test_get_dataframe(self, use_memory_db):
        db_mod.init_db()
        db_mod.kline_upsert("510300", "2024-01-15", 3.50, 3.60, 3.45, 3.55, 1e6)
        db_mod.kline_upsert("510300", "2024-01-16", 3.56, 3.62, 3.50, 3.60, 1.1e6)

        df = db_mod.kline_get_dataframe("510300")
        assert len(df) == 2
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert df.index.name == "date"

    def test_get_dataframe_empty_returns_empty_df(self, use_memory_db):
        db_mod.init_db()
        df = db_mod.kline_get_dataframe("nonexistent")
        assert len(df) == 0

    def test_latest_date(self, use_memory_db):
        db_mod.init_db()
        assert db_mod.kline_latest_date("510300") is None

        db_mod.kline_upsert("510300", "2024-03-01", 3.5, 3.6, 3.4, 3.55, 1e6)
        db_mod.kline_upsert("510300", "2024-03-05", 3.6, 3.7, 3.5, 3.65, 1.1e6)
        assert db_mod.kline_latest_date("510300") == "2024-03-05"

    def test_all_codes(self, use_memory_db):
        db_mod.init_db()
        codes = ["510300", "511260", "159915"]
        for code in codes:
            db_mod.kline_upsert(code, "2024-01-15", 3.5, 3.6, 3.4, 3.55, 1e6)

        result = db_mod.kline_all_codes()
        assert sorted(result) == sorted(codes)

    def test_upsert_default_volume_zero(self, use_memory_db):
        db_mod.init_db()
        db_mod.kline_upsert("510300", "2024-06-01", 1.0, 2.0, 0.5, 1.5)
        rows = db_mod.kline_get("510300")
        assert rows[0]["volume"] == 0.0


# ══════════════════════════════════════════════════════════════════════
# Strategy Metrics CRUD
# ══════════════════════════════════════════════════════════════════════


class TestMetricsCrud:
    def test_upsert_and_get_one(self, use_memory_db):
        db_mod.init_db()
        db_mod.metrics_upsert(
            "S1", "买入持有", "被动投资", "被动投资 / 基准",
            8.19, 0.30, -52.97, 0.15, 52.1, 0.0, 0.0,
            ["510300(沪深300ETF)"], "恒满仓沪深300", "2012~2026",
        )
        m = db_mod.metrics_get_one("S1")
        assert m is not None
        assert m["name"] == "买入持有"
        assert m["annual_return"] == 8.19
        assert m["sharpe"] == 0.30
        assert m["max_drawdown"] == -52.97
        assert isinstance(m["assets"], list)
        assert "510300(沪深300ETF)" in m["assets"][0]

    def test_get_one_nonexistent(self, use_memory_db):
        db_mod.init_db()
        assert db_mod.metrics_get_one("S99") is None

    def test_get_all_default_sort(self, use_memory_db):
        db_mod.init_db()
        db_mod.metrics_upsert(
            "S2", "策略二", "动量", "动量", 10.0, 1.0, -20.0, 0.5, 55.0, 5.0, 0.0,
            ["510300"], "desc", "window")
        db_mod.metrics_upsert(
            "S1", "策略一", "被动投资", "被动投资", 8.0, 0.5, -30.0, 0.3, 52.0, 1.0, 0.0,
            ["510300"], "desc", "window")
        db_mod.metrics_upsert(
            "S10", "策略十", "动量", "动量", 12.0, 1.2, -15.0, 0.8, 56.0, 3.0, 0.0,
            ["510300"], "desc", "window")

        all_m = db_mod.metrics_get_all()
        # Default sort by strategy_id natural: S1, S2, S10
        assert [m["id"] for m in all_m] == ["S1", "S2", "S10"]

    def test_get_all_sort_by_sharpe_desc(self, use_memory_db):
        db_mod.init_db()
        db_mod.metrics_upsert(
            "S1", "A", "被动投资", "被动投资", 8.0, 0.5, -30.0, 0.3, 52.0, 1.0, 0.0,
            ["510300"], "desc", "window")
        db_mod.metrics_upsert(
            "S2", "B", "动量", "动量", 10.0, 1.0, -20.0, 0.5, 55.0, 5.0, 0.0,
            ["510300"], "desc", "window")
        db_mod.metrics_upsert(
            "S3", "C", "趋势", "趋势", 5.0, 0.3, -40.0, 0.1, 50.0, 2.0, 0.0,
            ["510300"], "desc", "window")

        all_m = db_mod.metrics_get_all(sort_by="sharpe", order="desc")
        assert all_m[0]["sharpe"] == 1.0  # S2
        assert all_m[1]["sharpe"] == 0.5  # S1
        assert all_m[2]["sharpe"] == 0.3  # S3

    def test_get_all_sort_by_annual_return_asc(self, use_memory_db):
        db_mod.init_db()
        db_mod.metrics_upsert(
            "S1", "A", "", "", 30.0, None, None, None, None, None, None,
            [], "", "")
        db_mod.metrics_upsert(
            "S2", "B", "", "", 10.0, None, None, None, None, None, None,
            [], "", "")

        all_m = db_mod.metrics_get_all(sort_by="annual_return", order="asc")
        assert all_m[0]["ann_val"] == 10.0
        assert all_m[1]["ann_val"] == 30.0

    def test_get_all_invalid_sort_col_falls_back_to_id(self, use_memory_db):
        db_mod.init_db()
        db_mod.metrics_upsert(
            "S1", "A", "", "", 8.0, None, None, None, None, None, None,
            [], "", "")
        # Invalid sort column should default to strategy_id without error
        result = db_mod.metrics_get_all(sort_by="nonexistent_col", order="desc")
        assert len(result) == 1

    def test_format_strings_for_frontend(self, use_memory_db):
        db_mod.init_db()
        db_mod.metrics_upsert(
            "S1", "Test", "动量", "动量 / 轮动",
            15.55, 1.234, -25.67, 0.606, 54.32, 12.34, -3.21,
            ["510300"], "A test strategy", "2018~2025",
        )
        m = db_mod.metrics_get_all()[0]
        # Formatted values
        assert m["annual_return"] == "15.55%"
        assert m["max_drawdown"] == "-25.67%"
        assert m["sharpe"] == 1.23
        assert m["calmar"] == 0.61
        assert m["win_rate"] == "54.3%"
        assert m["turnover"] == 12.3
        assert m["excess_return"] == "-3.21%"
        # Raw values preserved
        assert m["ann_val"] == 15.55
        assert m["dd_val"] == -25.67

    def test_null_metrics_display_as_dash(self, use_memory_db):
        db_mod.init_db()
        db_mod.metrics_upsert(
            "S12", "待回测策略", "多因子", "多因子",
            None, None, None, None, None, None, None,
            ["513100"], "待回测", "待回测",
        )
        m = db_mod.metrics_get_all()[0]
        assert m["annual_return"] == "—"
        assert m["max_drawdown"] == "—"
        assert m["sharpe"] is None
        assert m["calmar"] is None
        assert m["win_rate"] == "—"
        assert m["backtest_window"] == "待回测"

    def test_upsert_overwrites_existing(self, use_memory_db):
        db_mod.init_db()
        db_mod.metrics_upsert(
            "S1", "Old", "", "", 5.0, 0.2, -10.0, 0.5, 50.0, 1.0, 0.0,
            [], "", "")
        db_mod.metrics_upsert(
            "S1", "New", "", "", 20.0, 1.5, -5.0, 4.0, 60.0, 2.0, 0.0,
            [], "", "")

        m = db_mod.metrics_get_one("S1")
        assert m["name"] == "New"
        assert m["annual_return"] == 20.0

    def test_assets_json_handles_invalid(self, use_memory_db):
        """Should not crash on malformed JSON in assets_json."""
        db_mod.init_db()
        with db_mod.get_conn() as conn:
            conn.execute("""
                INSERT INTO strategy_metrics
                (strategy_id, name, assets_json)
                VALUES ('S99', 'Bad', '{invalid json')
            """)
        result = db_mod.metrics_get_all()
        # Should not raise — just return empty list for assets
        assert any(r["id"] == "S99" for r in result)
        s99 = next(r for r in result if r["id"] == "S99")
        assert s99["assets"] == []


# ══════════════════════════════════════════════════════════════════════
# Daily Signals CRUD
# ══════════════════════════════════════════════════════════════════════


class TestSignalsCrud:
    def test_upsert_and_get_latest(self, use_memory_db):
        db_mod.init_db()
        db_mod.signals_upsert("S1", "2024-06-15", "510300", "沪深300ETF",
                              0.6, 0.4, "BUY")
        db_mod.signals_upsert("S1", "2024-06-15", "511880", "银华日利",
                              0.4, 0.6, "SELL")

        rows = db_mod.signals_get_latest("S1")
        assert rows is not None
        assert len(rows) == 2
        codes = {r["asset_code"] for r in rows}
        assert codes == {"510300", "511880"}

    def test_get_latest_returns_most_recent_date(self, use_memory_db):
        db_mod.init_db()
        db_mod.signals_upsert("S1", "2024-06-10", "510300", "HS300",
                              0.5, 0.5, "HOLD")
        db_mod.signals_upsert("S1", "2024-06-15", "510300", "HS300",
                              0.7, 0.5, "BUY")

        rows = db_mod.signals_get_latest("S1")
        assert rows[0]["signal_date"] == "2024-06-15"
        assert rows[0]["target_weight"] == 0.7

    def test_get_latest_nonexistent_strategy(self, use_memory_db):
        db_mod.init_db()
        assert db_mod.signals_get_latest("S99") is None

    def test_weight_change_is_computed(self, use_memory_db):
        db_mod.init_db()
        db_mod.signals_upsert("S1", "2024-06-15", "510300", "HS300",
                              0.75, 0.25, "BUY")
        rows = db_mod.signals_get_latest("S1")
        assert abs(rows[0]["weight_change"] - 0.5) < 1e-9

    def test_delete_old(self, use_memory_db):
        db_mod.init_db()
        old_date = (date.today() - timedelta(days=60)).strftime("%Y-%m-%d")
        recent_date = (date.today() - timedelta(days=5)).strftime("%Y-%m-%d")

        db_mod.signals_upsert("S1", old_date, "510300", "HS300", 0.5, 0.5, "HOLD")
        db_mod.signals_upsert("S1", recent_date, "510300", "HS300", 0.7, 0.5, "BUY")

        db_mod.signals_delete_old(days=30)

        # Old signal should be deleted
        rows_old = db_mod.signals_get_latest("S1")
        assert rows_old is not None
        # After delete, the latest should be the recent one
        assert rows_old[0]["signal_date"] == recent_date

    def test_upsert_is_repeatable(self, use_memory_db):
        """UNIQUE constraint means re-upsert replaces, not duplicates."""
        db_mod.init_db()
        db_mod.signals_upsert("S1", "2024-06-15", "510300", "HS300",
                              0.5, 0.3, "BUY")
        db_mod.signals_upsert("S1", "2024-06-15", "510300", "HS300",
                              0.9, 0.5, "SELL")

        rows = db_mod.signals_get_latest("S1")
        # Should still be unique entries
        assert len(rows) >= 1
        s = [r for r in rows if r["asset_code"] == "510300"]
        assert len(s) == 1
        assert s[0]["target_weight"] == 0.9
        assert s[0]["action"] == "SELL"


# ══════════════════════════════════════════════════════════════════════
# Strategy KB CRUD
# ══════════════════════════════════════════════════════════════════════


class TestKbCrud:
    def test_upsert_and_get(self, use_memory_db):
        db_mod.init_db()
        db_mod.kb_upsert(
            "S1", "买入持有", "BuyHold", "被动投资",
            "恒满仓沪深300", "无择股", "无择时",
            "无", "不调仓", "简单透明", "回撤大",
            {"initial_capital": 1000000, "commission": 0.0003},
        )
        kb = db_mod.kb_get("S1")
        assert kb is not None
        assert kb["name"] == "买入持有"
        assert kb["class_name"] == "BuyHold"
        assert kb["intro"] == "恒满仓沪深300"
        assert isinstance(kb["backtest"], dict)
        assert kb["backtest"]["initial_capital"] == 1000000

    def test_get_nonexistent(self, use_memory_db):
        db_mod.init_db()
        assert db_mod.kb_get("S99") is None

    def test_upsert_overwrites(self, use_memory_db):
        db_mod.init_db()
        db_mod.kb_upsert("S1", "Old", "", "", "", "", "", "", "", "", "", {})
        db_mod.kb_upsert("S1", "New", "", "", "", "", "", "", "", "", "", {})
        kb = db_mod.kb_get("S1")
        assert kb["name"] == "New"

    def test_backtest_json_handles_invalid(self, use_memory_db):
        db_mod.init_db()
        with db_mod.get_conn() as conn:
            conn.execute("""
                INSERT INTO strategy_kb (strategy_id, name, backtest_params)
                VALUES ('S99', 'Bad', '{broken')
            """)
        kb = db_mod.kb_get("S99")
        assert kb is not None
        assert kb["backtest"] == {}


# ══════════════════════════════════════════════════════════════════════
# Backtest NAV CRUD
# ══════════════════════════════════════════════════════════════════════


class TestNavCrud:
    def test_has_data_empty_initially(self, use_memory_db):
        db_mod.init_db()
        assert db_mod.nav_has_data() is False

    def test_upsert_batch_and_has_data(self, use_memory_db):
        db_mod.init_db()
        rows = [
            ("S1_买入持有", "2024-01-05", 1.05, -0.02),
            ("S1_买入持有", "2024-01-12", 1.08, -0.01),
            ("S4_多资产动量轮动", "2024-01-05", 1.15, -0.05),
        ]
        db_mod.nav_upsert_batch(rows)
        assert db_mod.nav_has_data() is True

    def test_get_all_returns_correct_structure(self, use_memory_db):
        db_mod.init_db()
        rows = [
            ("S1_买入持有", "2024-01-05", 1.10, -0.03),
            ("S1_买入持有", "2024-01-12", 1.15, -0.01),
            ("S4_动量轮动", "2024-01-05", 1.20, -0.02),
        ]
        db_mod.nav_upsert_batch(rows)

        data = db_mod.nav_get_all()
        assert "dates" in data
        assert "series" in data
        assert "drawdowns" in data
        assert len(data["dates"]) == 2  # 2024-01-05, 2024-01-12
        assert "S1_买入持有" in data["series"]
        assert len(data["series"]["S1_买入持有"]) == 2
        assert data["series"]["S1_买入持有"] == [1.10, 1.15]
        assert data["drawdowns"]["S1_买入持有"] == [-0.03, -0.01]

    def test_get_all_with_strategy_filter(self, use_memory_db):
        db_mod.init_db()
        rows = [
            ("S1_买入持有", "2024-01-05", 1.10, -0.03),
            ("S4_动量轮动", "2024-01-05", 1.20, -0.02),
        ]
        db_mod.nav_upsert_batch(rows)

        data = db_mod.nav_get_all(strategy_names=["S1_买入持有"])
        assert len(data["series"]) == 1
        assert "S1_买入持有" in data["series"]
        assert "S4_动量轮动" not in data["series"]

    def test_get_all_empty_returns_placeholder(self, use_memory_db):
        db_mod.init_db()
        data = db_mod.nav_get_all()
        assert data == {"dates": [], "series": {}, "drawdowns": {}}

    def test_nav_null_drawdown_becomes_zero(self, use_memory_db):
        db_mod.init_db()
        db_mod.nav_upsert_batch([("S1_买入持有", "2024-01-05", 1.0, None)])
        data = db_mod.nav_get_all()
        assert data["drawdowns"]["S1_买入持有"] == [0.0]

    def test_upsert_batch_is_repeatable(self, use_memory_db):
        """INSERT OR REPLACE means re-upserting same PK should not duplicate."""
        db_mod.init_db()
        db_mod.nav_upsert_batch([("S1_买入持有", "2024-01-05", 1.05, -0.02)])
        db_mod.nav_upsert_batch([("S1_买入持有", "2024-01-05", 1.10, -0.01)])

        data = db_mod.nav_get_all()
        assert len(data["dates"]) == 1
        assert data["series"]["S1_买入持有"] == [1.10]

    def test_get_all_aligns_mismatched_date_ranges(self, use_memory_db):
        """When strategies have NAV data for different date ranges,
        series should be aligned to the full date axis with null padding."""
        db_mod.init_db()
        # S1 has data for dates A, B
        db_mod.nav_upsert_batch([
            ("S1_买入持有", "2024-01-05", 1.10, -0.03),
            ("S1_买入持有", "2024-01-12", 1.15, -0.01),
        ])
        # S4 has data for dates B, C (only shares 2024-01-12 with S1)
        db_mod.nav_upsert_batch([
            ("S4_动量轮动", "2024-01-12", 1.20, -0.02),
            ("S4_动量轮动", "2024-01-19", 1.25, 0.0),
        ])

        data = db_mod.nav_get_all()
        # Full date axis should be A, B, C
        assert data["dates"] == ["2024-01-05", "2024-01-12", "2024-01-19"]

        # S1 should have [1.10, 1.15, None] — null for missing 2024-01-19
        assert data["series"]["S1_买入持有"] == [1.10, 1.15, None]
        # S4 should have [None, 1.20, 1.25] — null for missing 2024-01-05
        assert data["series"]["S4_动量轮动"] == [None, 1.20, 1.25]
        # Drawdowns should be similarly aligned
        assert data["drawdowns"]["S1_买入持有"] == [-0.03, -0.01, None]
        assert data["drawdowns"]["S4_动量轮动"] == [None, -0.02, 0.0]

    def test_get_all_single_strategy_all_dates_present(self, use_memory_db):
        """When only one strategy exists, all dates should align without nulls."""
        db_mod.init_db()
        db_mod.nav_upsert_batch([
            ("S1_买入持有", "2024-01-05", 1.10, -0.03),
            ("S1_买入持有", "2024-01-12", 1.15, -0.01),
        ])

        data = db_mod.nav_get_all()
        assert data["dates"] == ["2024-01-05", "2024-01-12"]
        assert data["series"]["S1_买入持有"] == [1.10, 1.15]
        # No nulls since all dates are present for this strategy


# ══════════════════════════════════════════════════════════════════════
# Users CRUD
# ══════════════════════════════════════════════════════════════════════


class TestUsersCrud:
    def test_user_create_and_get(self, use_memory_db):
        db_mod.init_db()
        db_mod.user_create("admin", "$2b$12$fakehash", "管理员", "admin")
        user = db_mod.user_get_by_username("admin")
        assert user is not None
        assert user["username"] == "admin"
        assert user["display_name"] == "管理员"
        assert user["role"] == "admin"
        assert user["is_active"] == 1

    def test_get_nonexistent_user(self, use_memory_db):
        db_mod.init_db()
        assert db_mod.user_get_by_username("nobody") is None

    def test_user_count(self, use_memory_db):
        db_mod.init_db()
        assert db_mod.user_count() == 0
        db_mod.user_create("admin", "$2b$12$hash", "管理员", "admin")
        assert db_mod.user_count() == 1
        db_mod.user_create("user2", "$2b$12$hash", "用户2", "viewer")
        assert db_mod.user_count() == 2

    def test_update_last_login(self, use_memory_db):
        db_mod.init_db()
        db_mod.user_create("admin", "$2b$12$hash", "管理员", "admin")
        # Should not raise
        db_mod.user_update_last_login("admin")
        user = db_mod.user_get_by_username("admin")
        assert user["last_login"] is not None

    def test_change_password(self, use_memory_db):
        db_mod.init_db()
        db_mod.user_create("admin", "$2b$12$oldhash", "管理员", "admin")
        db_mod.user_change_password("admin", "$2b$12$newhash")
        user = db_mod.user_get_by_username("admin")
        assert user["password_hash"] == "$2b$12$newhash"

    def test_list_all_users(self, use_memory_db):
        db_mod.init_db()
        db_mod.user_create("admin", "$2b$12$hash1", "管理员", "admin")
        db_mod.user_create("viewer1", "$2b$12$hash2", "访客", "viewer")
        users = db_mod.user_list_all()
        assert len(users) == 2
        assert users[0]["username"] == "admin"
        # Password hash should NOT be in the output
        assert "password_hash" not in users[0]
