import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from unittest.mock import MagicMock
import pandas as pd
import pytest


# ── Shared mock: daily_signal ─────────────────────────────────────────
# Both test_dashboard_app.py and test_dashboard_sync.py need daily_signal
# mocked. Using a single module-level mock managed here avoids them fighting
# over sys.modules["daily_signal"].
_REAL_DAILY_SIGNAL = sys.modules.get("daily_signal")
# Only create the mock if the real module hasn't been imported yet, OR if
# another test file has already replaced it with its own mock. We use a
# consistent mock object that both test files share.
if "daily_signal" not in sys.modules or isinstance(sys.modules["daily_signal"], MagicMock):
    _shared_ds_mock = MagicMock()
    _shared_ds_mock.STRAT_MAP = {}
    _shared_ds_mock.get_etf_name = MagicMock(return_value="TestETF")
    sys.modules["daily_signal"] = _shared_ds_mock
else:
    # Real module is loaded — don't replace it; individual tests should
    # use monkeypatch.setattr to mock specific attributes.
    _shared_ds_mock = None


@pytest.fixture(autouse=True)
def _reset_daily_signal_mock():
    """Reset the shared daily_signal mock before each test."""
    if _shared_ds_mock is not None:
        _shared_ds_mock.STRAT_MAP = {}
        _shared_ds_mock.get_etf_name = MagicMock(return_value="TestETF")
    yield
    if _shared_ds_mock is not None:
        _shared_ds_mock.STRAT_MAP = {}


@pytest.fixture
def synth_prices():
    """合成价格：510300 每日涨1%，511260 每日涨0.1%，共10个交易日。"""
    dates = pd.date_range("2024-01-01", periods=10, freq="B")
    return pd.DataFrame({
        "510300": [100 * (1.01 ** i) for i in range(10)],
        "511260": [100 * (1.001 ** i) for i in range(10)],
    }, index=dates)


@pytest.fixture
def flat_prices():
    """平价序列（无收益）：便于测再平衡算术。"""
    dates = pd.date_range("2024-01-01", periods=10, freq="B")
    return pd.DataFrame({
        "510300": [100.0] * 10,
        "511260": [100.0] * 10,
    }, index=dates)
