"""
信号收益追踪核心逻辑 — REQ-001

从 auto_evening_review.md §7.6 的嵌入式 Python 提取。
纯计算函数，不读写磁盘，不调用外部 API。

依赖: trading_calendar.py (next_trading_day, is_trading_day)

新增（2026-08-07 修复 BUG-XXX: signal_tracking.json 从未被写入）：
  - parse_signal_markdown()   — 解析每日信号.md，提取已触发/已执行的信号记录
  - merge_new_signals()       — 将解析出的新信号并入追踪库（去重）
  - settle_due_signals()      — 结算到期信号（高紧急度2日 / 低紧急度到预期收益日）
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
    # 兼容 signal_tracking.json 的 'aggregates' 字段（v1.0 schema）
    tracking['aggregates'] = {
        'total_signals_tracked': agg['by_urgency']['high']['count'] + agg['by_urgency']['low']['count'],
        'total_resolved': agg['by_urgency']['high']['settled'] + agg['by_urgency']['low']['settled'],
        'total_open': len(signals) - (agg['by_urgency']['high']['settled'] + agg['by_urgency']['low']['settled']),
        'total_pnl_amount': round(agg['by_urgency']['high']['total_pnl'] + agg['by_urgency']['low']['total_pnl'], 2),
        'total_avoided_loss': round(sum(s.get('avoided_loss', 0.0) for s in signals), 2),
        'win_count': agg['by_urgency']['high']['win_count'] + agg['by_urgency']['low']['win_count'],
        'lose_count': agg['by_urgency']['high']['settled'] + agg['by_urgency']['low']['settled']
                      - (agg['by_urgency']['high']['win_count'] + agg['by_urgency']['low']['win_count']),
        'by_urgency': {
            k: {
                'count': v['count'], 'resolved': v['settled'],
                'total_pnl': round(v['total_pnl'], 2),
                'total_avoided_loss': round(sum(
                    s.get('avoided_loss', 0.0) for s in signals if s.get('urgency') == k
                ), 2),
            }
            for k, v in agg['by_urgency'].items()
        },
        'by_priority': {
            k: {
                'count': v['count'], 'resolved': v['settled'],
                'total_pnl': round(v['total_pnl'], 2),
            }
            for k, v in agg['by_priority'].items()
        },
    }
    # win_rate
    total_settled = agg['by_urgency']['high']['settled'] + agg['by_urgency']['low']['settled']
    tracking['aggregates']['win_rate'] = (
        round((tracking['aggregates']['win_count'] / total_settled * 100), 1)
        if total_settled else None
    )
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


# ============================================================
# 信号文件解析 → 追踪库写入（2026-08-07 新增）
# ============================================================
# BUG-XXX 根因：auto_evening_review.md §7.6.1/7.6.2 的嵌入式脚本是骨架，
# 解析逻辑全是注释，导致 signal_tracking.json 的 signals 从未被写入。
# 修复：把解析/去重/结算逻辑下沉到 lib，prompt 只负责调用 + 写盘。

# 信号总表中会被录入追踪库的状态（只追踪已触发的信号）
_TRACKABLE_STATUSES = {'已触发', '已执行', '部分执行'}

# 操作类型 → trade_type 映射（buy=买入类 / sell=卖出类）
_TRADE_TYPE_KEYWORDS = {
    'buy': ('正T', '加仓', '买入', '建仓', '低吸'),
    'sell': ('反T', '减仓', '锁利', '卖出', '止损', '清仓', '高抛'),
}
_URGENCY_MAP = {'高': 'high', '低': 'low'}


def _extract_ticker(标的: str) -> str:
    """从 '银行ETF(512800)' 提取 6 位代码；提取失败返回空串。"""
    import re
    m = re.search(r'(\d{6})', 标的)
    return m.group(1) if m else ''


def _parse_quantity(仓位: str) -> int:
    """从 '-1,100份（约-25%）' 提取份额绝对值。"""
    import re
    m = re.search(r'([\d,]+)\s*份', 仓位)
    return int(m.group(1).replace(',', '')) if m else 0


def _map_trade_type(操作类型: str, 方向: str) -> str:
    """操作类型 → buy/sell。无法判定时用方向兜底。"""
    for trade_type, keywords in _TRADE_TYPE_KEYWORDS.items():
        if any(k in 操作类型 for k in keywords):
            return trade_type
    if '买' in 方向:
        return 'buy'
    if '卖' in 方向:
        return 'sell'
    return 'buy'


def _parse_table_rows(md_text: str, section: str) -> tuple[list[str], list[list[str]]]:
    """从 markdown 中解析某节标题下的表格。
    返回 (header, rows)：header 为表头列名列表，rows 为数据行（已去分隔线）。"""
    lines = md_text.splitlines()
    collecting = False
    raw_rows = []
    for line in lines:
        if line.startswith('##') and line.strip() != section:
            if collecting:
                break
        if line.strip() == section:
            collecting = True
            continue
        if collecting and line.strip().startswith('|'):
            raw_rows.append([c.strip() for c in line.strip().strip('|').split('|')])

    header = []
    rows = []
    for row in raw_rows:
        # 分隔线 |:---:| → 跳过
        if row and all(c.replace(':', '').replace('-', '').strip() == '' for c in row):
            continue
        # 首行含表头关键字 → 记为 header
        if not header and row and any(k in c for c in row for k in ('优先级', '信号ID', '标的')):
            header = row
            continue
        if row and any(c for c in row):
            rows.append(row)
    return header, rows


def _col(header: list[str], *names: str) -> int:
    """在表头中定位列索引；找不到返回 -1。"""
    for i, h in enumerate(header):
        if any(name in h for name in names):
            return i
    return -1


def parse_signal_markdown(md_text: str, today: str = '') -> list[dict]:
    """解析每日信号.md，提取已触发/已执行的信号记录。

    只录入状态 ∈ {已触发, 已执行, 部分执行} 的信号（未触发的已过期/已废弃不追踪）。
    返回记录列表（entry_price 由调用方补充，见 merge 前的校验）。
    today: 'YYYY-MM-DD'，缺省用 date.today()。
    """
    if not today:
        today = date.today().isoformat()

    header, rows = _parse_table_rows(md_text, '## 信号总表')
    c_prio = _col(header, '优先级')
    c_target = _col(header, '标的')
    c_op = _col(header, '操作类型')
    c_status = _col(header, '状态')
    c_dir = _col(header, '方向')
    c_urg = _col(header, '紧急度')
    c_exp = _col(header, '预期收益日')
    c_qty = _col(header, '仓位')
    c_id = _col(header, '信号ID')

    records = []
    for row in rows:
        def g(idx):
            return row[idx] if 0 <= idx < len(row) else ''

        priority = g(c_prio)
        target = g(c_target)
        op_type = g(c_op)
        status = g(c_status)
        direction = g(c_dir)
        urgency = g(c_urg)
        expected_date = g(c_exp)
        quantity_raw = g(c_qty)
        signal_id = g(c_id)

        if status not in _TRACKABLE_STATUSES:
            continue
        if not signal_id.startswith('SIG-'):
            continue

        ticker = _extract_ticker(target)
        if not ticker:
            continue

        urgency_val = _URGENCY_MAP.get(urgency, 'low')

        records.append({
            'signal_id': signal_id,
            'ticker': ticker,
            'name': target.split('(')[0] if '(' in target else target,
            'trade_type': _map_trade_type(op_type, direction),
            'direction': 'sell' if '卖' in direction else 'buy',
            'priority': priority or 'P2',
            'urgency': urgency_val,
            'expected_return_date': expected_date if expected_date and expected_date != '—' else '',
            'trigger_date': today,
            'entry_price': None,   # 需调用方从盘中数据补充
            'shares': _parse_quantity(quantity_raw),
            'status': 'triggered',
            'status_history': [{'date': today, 'status': 'triggered', 'note': '从每日信号.md解析录入'}],
        })

    # 从盘中验证记录提取触发价 → 补充 entry_price
    verify_prices = _extract_trigger_prices(md_text)
    for rec in records:
        if rec['entry_price'] is None and rec['signal_id'] in verify_prices:
            rec['entry_price'] = verify_prices[rec['signal_id']]
    return records


def _extract_trigger_prices(md_text: str) -> dict:
    """从 '## 盘中验证记录' 中提取每条信号首次出现时的当前价。
    返回 {signal_id: price}。匹配 '当前X.XXX' 或 '开盘X.XXX'。"""
    import re
    header, rows = _parse_table_rows(md_text, '## 盘中验证记录')
    c_id = _col(header, '信号ID')
    c_data = _col(header, '关键数据')
    prices = {}
    for row in rows:
        def g(idx):
            return row[idx] if 0 <= idx < len(row) else ''
        signal_id = g(c_id)
        key_data = g(c_data)
        if not signal_id.startswith('SIG-') or not key_data:
            continue
        # 优先级: "当前X.XXX" → "开盘X.XXX" → 数据列开头的裸数字(如 "0.808, -0.37%")
        price = None
        m = re.search(r'当前([\d.]+)', key_data)
        if not m:
            m = re.search(r'开盘([\d.]+)', key_data)
        if m:
            price = m.group(1)
        else:
            m = re.match(r'^\s*([\d.]+)', key_data)
            if m:
                price = m.group(1)
        if price and price.count('.') <= 1:
            # 首次出现才记录（触发价 = 信号首现时价格）
            prices.setdefault(signal_id, float(price))
    return prices


def merge_new_signals(tracking: dict, new_records: list[dict]) -> dict:
    """将新信号并入追踪库（按 signal_id 去重）。返回更新后的 dict（不写磁盘）。"""
    existing_ids = {s.get('signal_id') for s in tracking.get('signals', [])}
    added = 0
    for rec in new_records:
        if rec['signal_id'] in existing_ids:
            continue
        tracking.setdefault('signals', []).append(rec)
        existing_ids.add(rec['signal_id'])
        added += 1
    tracking['_updated'] = date.today().isoformat()
    return tracking


def settle_due_signals(tracking: dict, price_lookup: dict, today: str = '') -> dict:
    """结算到期信号。返回更新后的 dict（不写磁盘）。

    price_lookup: {ticker: current_price} — 今日收盘价表。
    规则：
      - status in {open, triggered, executed, partial_executed} 才结算
      - 高紧急度: trigger_date + 2个交易日（用 days_since>=2 近似）
      - 低紧急度: expected_return_date <= today
    买入: P&L=(现价-入场价)*份额；卖出: P&L=(入场价-成本)*份额, 避免损失=(入场价-现价)*份额
    """
    if not today:
        today = date.today().isoformat()

    for sig in tracking.get('signals', []):
        if sig.get('status') not in ('open', 'triggered', 'executed', 'partial_executed'):
            continue

        # 判定是否到期
        due = False
        reason = ''
        try:
            trigger_date = date.fromisoformat(sig['trigger_date'])
            today_date = date.fromisoformat(today)
        except Exception:
            continue

        if sig.get('urgency') == 'high':
            # 触发日 + 2 自然日视为到期（交易日近似，够用）
            if (today_date - trigger_date).days >= 2:
                due = True
                reason = '高紧急度2日自动结算'
        elif sig.get('urgency') == 'low':
            if sig.get('expected_return_date'):
                try:
                    if today_date >= date.fromisoformat(sig['expected_return_date']):
                        due = True
                        reason = f'低紧急度预期收益日{sig["expected_return_date"]}到期'
                except Exception:
                    pass

        if not due:
            continue

        # 结算
        ticker = sig.get('ticker', '')
        current_price = price_lookup.get(ticker, 0.0)
        if current_price <= 0:
            continue  # 无现价无法结算，等待下次

        shares = sig.get('shares', 0)
        if sig.get('trade_type') == 'buy':
            entry = sig.get('entry_price') or 0.0
            sig['pnl'] = round((current_price - entry) * shares, 2)
            sig['avoided_loss'] = 0.0
        else:  # sell
            sell_price = sig.get('entry_price') or 0.0
            cost = sig.get('cost_basis', sell_price) or sell_price
            sig['pnl'] = round((sell_price - cost) * shares, 2)
            sig['avoided_loss'] = round((sell_price - current_price) * shares, 2)

        sig['status'] = 'settled'
        sig['exit_date'] = today
        sig.setdefault('status_history', []).append({
            'date': today, 'status': 'settled', 'note': reason,
        })

    return tracking
