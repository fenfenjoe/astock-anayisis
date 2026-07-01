import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import pytest


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
