"""
Harness 测试共享 fixtures

提供信号样本、追踪数据库、REQ索引等测试数据。
所有数据均为合成数据，不依赖真实行情。
"""

import pytest
from datetime import date, datetime
from pathlib import Path


@pytest.fixture
def sample_buy_signal() -> dict:
    """标准买入信号样本"""
    return {
        'signal_id': 'SIG-001',
        'ticker': '510300',
        'ticker_name': '沪深300ETF',
        'trade_type': 'buy',
        'urgency': 'high',
        'priority': 'P1',
        'entry_price': 4.50,
        'shares': 10000,
        'trigger_date': '2026-07-27',
        'window_start': '2026-07-27T09:30:00',
        'window_end': '2026-07-27T11:30:00',
        'status': 'triggered',
    }


@pytest.fixture
def sample_sell_signal() -> dict:
    """标准卖出信号样本"""
    return {
        'signal_id': 'SIG-002',
        'ticker': '159915',
        'ticker_name': '创业板ETF',
        'trade_type': 'sell',
        'urgency': 'low',
        'priority': 'P2',
        'entry_price': 2.80,
        'sell_price': 2.80,
        'cost_basis': 2.60,
        'shares': 5000,
        'trigger_date': '2026-07-25',
        'window_start': '2026-07-25T13:00:00',
        'window_end': '2026-07-25T15:00:00',
        'status': 'triggered',
    }


@pytest.fixture
def sample_signals_list(sample_buy_signal, sample_sell_signal) -> list[dict]:
    """包含多条信号的列表"""
    return [sample_buy_signal, sample_sell_signal]


@pytest.fixture
def sample_tracking_db(sample_buy_signal, sample_sell_signal) -> dict:
    """完整的 signal_tracking.json 结构样本（含空聚合）"""
    return {
        '_schema': '1.0',
        'signals': [sample_buy_signal, sample_sell_signal],
        'aggregation': {
            'by_urgency': {
                'high': {'count': 1, 'settled': 0, 'total_pnl': 0.0, 'win_count': 0},
                'low': {'count': 1, 'settled': 0, 'total_pnl': 0.0, 'win_count': 0},
            },
            'by_priority': {
                'P0': {'count': 0, 'settled': 0, 'total_pnl': 0.0, 'win_count': 0},
                'P1': {'count': 1, 'settled': 0, 'total_pnl': 0.0, 'win_count': 0},
                'P2': {'count': 1, 'settled': 0, 'total_pnl': 0.0, 'win_count': 0},
            },
            'by_trade_type': {},
            'by_ticker': {},
        },
    }


@pytest.fixture
def sample_req_index() -> list[dict]:
    """REQ 索引样本（模拟 REQ_INDEX.md 的解析结果）"""
    return [
        {'id': 'REQ-001', 'status': 'IMPLEMENTED', 'priority': 'P1', 'created_date': '2026-07-24'},
        {'id': 'REQ-002', 'status': 'IMPLEMENTED', 'priority': 'P1', 'created_date': '2026-07-24'},
        {'id': 'REQ-003', 'status': 'OPEN', 'priority': 'P2', 'created_date': '2026-07-26'},
    ]


@pytest.fixture
def tests_dir() -> str:
    """返回 tests/ 目录的绝对路径"""
    return str(Path(__file__).resolve().parent)
