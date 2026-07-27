"""
信号收益追踪核心逻辑 — REQ-001

从 auto_evening_review.md §7.6 的嵌入式 Python 提取。
纯计算函数，不读写磁盘，不调用外部 API。

依赖: trading_calendar.py (next_trading_day, is_trading_day)
"""

import sys
from datetime import date, timedelta
from pathlib import Path

# 确保可导入同目录的 trading_calendar
_HERE = Path(__file__).resolve().parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from config.trading_calendar import next_trading_day, is_trading_day


# ============================================================
# P&L 计算
# ============================================================

def calc_buy_pnl(entry_price: float, exit_price: float, shares: int) -> float:
    """买入信号 P&L = (出场价 - 入场价) * 份额"""
    return (exit_price - entry_price) * shares


def calc_sell_pnl(sell_price: float, cost_basis: float, shares: int) -> float:
    """卖出信号 P&L = (卖出价 - 成本基准) * 份额"""
    return (sell_price - cost_basis) * shares


def calc_avoided_loss(sell_price: float, price_after_n_days: float, shares: int) -> float:
    """避免的损失 = (卖出价 - N日后价格) * 份额
    正值 = 卖出后价格下跌，成功避免了损失
    负值 = 卖出后价格上涨，卖早了
    """
    return (sell_price - price_after_n_days) * shares


# ============================================================
# 结算与归档判定
# ============================================================

def calc_settlement_date(trigger_date: date, urgency: str) -> date:
    """计算信号结算日期。
    urgency='high' => trigger_date + 2个交易日
    urgency='low'  => trigger_date + 5个交易日
    """
    if urgency == 'high':
        days_forward = 2
    elif urgency == 'low':
        days_forward = 5
    else:
        raise ValueError(f"Invalid urgency: {urgency!r}, expected 'high' or 'low'")

    result = trigger_date
    for _ in range(days_forward):
        result = next_trading_day(result)
    return result


def is_archived(signal_date: date, current_date: date, archive_days: int = 90) -> bool:
    """信号是否已超过归档期限（默认90天）"""
    return (current_date - signal_date).days >= archive_days


# ============================================================
# 聚合统计
# ============================================================

def update_aggregation(tracking: dict) -> dict:
    """重算 signal_tracking.json 的聚合统计。
    输入 tracking dict 的完整内容，返回更新后的 dict（不写磁盘）。

    聚合维度: by_urgency, by_priority, by_trade_type, by_ticker
    """
    signals = tracking.get('signals', [])

    agg = {
        'by_urgency': {'high': _empty_agg(), 'low': _empty_agg()},
        'by_priority': {'P0': _empty_agg(), 'P1': _empty_agg(), 'P2': _empty_agg()},
        'by_trade_type': {},
        'by_ticker': {},
    }

    for sig in signals:
        urgency = sig.get('urgency', 'low')
        priority = sig.get('priority', 'P2')
        trade_type = sig.get('trade_type', 'unknown')
        ticker = sig.get('ticker', 'unknown')

        _update_bucket(agg['by_urgency'], urgency, sig)
        _update_bucket(agg['by_priority'], priority, sig)

        if trade_type not in agg['by_trade_type']:
            agg['by_trade_type'][trade_type] = _empty_agg()
        _update_bucket(agg['by_trade_type'], trade_type, sig)

        if ticker not in agg['by_ticker']:
            agg['by_ticker'][ticker] = _empty_agg()
        _update_bucket(agg['by_ticker'], ticker, sig)

    tracking['aggregation'] = agg
    return tracking


def _empty_agg() -> dict:
    return {'count': 0, 'settled': 0, 'total_pnl': 0.0, 'win_count': 0}


def _update_bucket(agg_dict: dict, key: str, signal: dict) -> None:
    if key not in agg_dict:
        agg_dict[key] = _empty_agg()
    bucket = agg_dict[key]
    bucket['count'] += 1
    if signal.get('status') == 'settled':
        bucket['settled'] += 1
        pnl = signal.get('pnl', 0.0)
        bucket['total_pnl'] += pnl
        if pnl > 0:
            bucket['win_count'] += 1


# ============================================================
# 信号结算
# ============================================================

def settle_signal(signal: dict, current_price: float) -> dict:
    """结算单条信号，填充 pnl / avoided_loss / settled_date / status。
    返回更新后的 signal dict（不修改原对象）。
    """
    import copy
    result = copy.deepcopy(signal)

    trade_type = signal.get('trade_type', 'buy')
    shares = signal.get('shares', 0)

    if trade_type == 'buy':
        entry_price = signal.get('entry_price', 0.0)
        result['pnl'] = calc_buy_pnl(entry_price, current_price, shares)
        result['avoided_loss'] = 0.0
    elif trade_type == 'sell':
        sell_price = signal.get('sell_price', signal.get('entry_price', 0.0))
        cost_basis = signal.get('cost_basis', 0.0)
        result['pnl'] = calc_sell_pnl(sell_price, cost_basis, shares)
        result['avoided_loss'] = calc_avoided_loss(sell_price, current_price, shares)
    else:
        result['pnl'] = 0.0
        result['avoided_loss'] = 0.0

    result['settled_date'] = date.today().isoformat()
    result['status'] = 'settled'
    return result


# ============================================================
# Schema 校验
# ============================================================

REQUIRED_FIELDS = ['signal_id', 'ticker', 'trade_type', 'urgency', 'priority', 'entry_price', 'shares']
VALID_URGENCY = {'high', 'low'}
VALID_PRIORITY = {'P0', 'P1', 'P2'}
VALID_TRADE_TYPE = {'buy', 'sell'}


def validate_signal_record(signal: dict) -> list[str]:
    """校验信号记录的完整性和合法性。返回错误列表，空列表表示合法。"""
    errors = []

    for field in REQUIRED_FIELDS:
        if field not in signal or signal[field] is None:
            errors.append(f"missing required field: {field}")

    if signal.get('urgency') not in VALID_URGENCY:
        errors.append(f"invalid urgency: {signal.get('urgency')!r}, expected high/low")

    if signal.get('priority') not in VALID_PRIORITY:
        errors.append(f"invalid priority: {signal.get('priority')!r}, expected P0/P1/P2")

    if signal.get('trade_type') not in VALID_TRADE_TYPE:
        errors.append(f"invalid trade_type: {signal.get('trade_type')!r}, expected buy/sell")

    return errors
