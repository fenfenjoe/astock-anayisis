"""
信号收益追踪核心逻辑 — REQ-001

从 auto_evening_review.md §7.6 的嵌入式 Python 提取。
纯计算函数，不读写磁盘，不调用外部 API。

依赖: trading_calendar.py (next_trading_day, is_trading_day)

新增（2026-08-07 修复 BUG-XXX: signal_tracking.json 从未被写入）：
  - parse_signal_markdown()   — 解析每日信号.md，提取已触发/已执行的信号记录
  - merge_new_signals()       — 将解析出的新信号并入追踪库（去重）
  - settle_due_signals()      — 目标价结算：T+3 窗口内 hit/stopped/miss（v2.0 改）
"""

import re
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
    m = re.search(r'(\d{6})', 标的)
    return m.group(1) if m else ''


def _parse_quantity(仓位: str) -> int:
    """从 '-1,100份（约-25%）' 提取份额绝对值。"""
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


def _parse_expected_rate(raw: str):
    """解析 '40' / '40%' → 40.0；'—'/空 → None"""
    if not raw or raw == '—':
        return None
    m = re.search(r'(\d+(?:\.\d+)?)', raw)
    return float(m.group(1)) if m else None


def _parse_target_stop(raw: str) -> dict:
    """解析目标/止损列：'目标+3%/止损-2%'（百分比）或 '目标1.75/止损1.66'（显式价）。
    返回 {target_pct, stop_pct, target_price, stop_price}，无值均为 None。"""
    result = {'target_pct': None, 'stop_pct': None, 'target_price': None, 'stop_price': None}
    if not raw or raw == '—':
        return result
    for part in raw.replace('，', '/').split('/'):
        part = part.strip()
        m = re.match(r'目标\s*([+-]?\d+(?:\.\d+)?)\s*%', part)
        if m:
            result['target_pct'] = float(m.group(1)); continue
        m = re.match(r'止损\s*([+-]?\d+(?:\.\d+)?)\s*%', part)
        if m:
            result['stop_pct'] = float(m.group(1)); continue
        m = re.match(r'目标\s*(\d+(?:\.\d+)?)', part)
        if m:
            result['target_price'] = float(m.group(1)); continue
        m = re.match(r'止损\s*(\d+(?:\.\d+)?)', part)
        if m:
            result['stop_price'] = float(m.group(1)); continue
    return result


def _strip_md(cell: str) -> str:
    """剥离单元格中的 markdown 加粗标记（**已触发** → 已触发）。"""
    return cell.replace('**', '').strip()


def _parse_table_rows(md_text: str, section: str) -> tuple[list[str], list[list[str]]]:
    """从 markdown 中解析某节标题下的表格。
    返回 (header, rows)：header 为表头列名列表，rows 为数据行（已去分隔线）。
    单元格自动剥离 markdown 加粗标记（BUG-012）。"""
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
            raw_rows.append([_strip_md(c) for c in line.strip().strip('|').split('|')])

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
    只返回可追踪收益的信号：必须同时具备 入场价（来自盘中验证记录）+ 份额，
    否则无法结算 P&L，不追踪收益（2026-08-26 优化）。
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
    c_exp_rate = _col(header, '预期触发率')
    c_tgt_stop = _col(header, '目标/止损')

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

        ts = _parse_target_stop(g(c_tgt_stop))
        records.append({
            'signal_id': signal_id,
            'ticker': ticker,
            'name': target.split('(')[0] if '(' in target else target,
            'trade_type': _map_trade_type(op_type, direction),
            'direction': 'sell' if '卖' in direction else 'buy',
            'priority': priority or 'P2',
            'urgency': urgency_val,
            'expected_trigger_rate': _parse_expected_rate(g(c_exp_rate)),
            'target_pct': ts['target_pct'],
            'stop_pct': ts['stop_pct'],
            'target_price': ts['target_price'],
            'stop_price': ts['stop_price'],
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
    # 无入场价或无份额的信号无法结算 P&L → 不追踪收益（与 settle_due_signals 的
    # "无入场价或份额无法结算" 口径一致，避免追踪库积累永不结算的僵尸信号）
    records = [r for r in records if r.get('entry_price') and r.get('shares', 0) > 0]
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
        # 优先级: "当前X.XXX" → "现价X.XXX"(真实记录格式) → "开盘X.XXX" → 数据列开头的裸数字(如 "0.808, -0.37%")
        price = None
        m = re.search(r'(?:当前|现价|开盘)([\d.]+)', key_data)
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


def _resolve_target_price(sig: dict) -> tuple:
    """计算信号目标价/止损价：显式价格优先，否则用百分比×触发价。"""
    entry = sig.get('entry_price') or 0.0
    target = sig.get('target_price')
    if target is None and sig.get('target_pct') is not None and entry:
        target = round(entry * (1 + sig['target_pct'] / 100.0), 4)
    stop = sig.get('stop_price')
    if stop is None and sig.get('stop_pct') is not None and entry:
        stop = round(entry * (1 + sig['stop_pct'] / 100.0), 4)
    return target, stop


def settle_due_signals(tracking: dict, price_history: dict, today: str = '') -> dict:
    """目标价结算：触发后 T+3 交易日内，收盘达到目标价→达标(hit)；触发止损→stopped；
    否则按 T+3 收盘价结算(miss)。返回更新后的 dict（不写磁盘）。

    price_history: {ticker: {date_iso: close_float}} — 触发日至 T+3 的每日收盘价，
    由调用方（复盘 prompt 脚本）用腾讯财经日K填充。
    仅结算 status ∈ {open, triggered, executed, partial_executed} 且已到期的信号。

    T+3 窗口：含触发日共 3 个交易日（触发日、T+1、T+2），到期日 = 触发日后推 2 个交易日。
    """
    if not today:
        today = date.today().isoformat()

    for sig in tracking.get('signals', []):
        if sig.get('status') not in ('open', 'triggered', 'executed', 'partial_executed'):
            continue
        if sig.get('priority') == 'P0':
            continue  # P0 风控信号不结算（纪律无 P&L，spec §6.1）
        try:
            trigger_date = date.fromisoformat(sig['trigger_date'])
            today_date = date.fromisoformat(today)
        except Exception:
            continue

        # T+3 结算日（含触发日共 3 个交易日 → 后推 2 个交易日）
        settle_date = trigger_date
        for _ in range(2):
            settle_date = next_trading_day(settle_date)
        if today_date < settle_date:
            continue  # 未到期

        ticker = sig.get('ticker', '')
        hist = price_history.get(ticker, {})
        if not hist:
            continue  # 无价格数据，等待下次

        window_dates = sorted(d for d in hist
                              if trigger_date.isoformat() <= d <= settle_date.isoformat())
        closes = [hist[d] for d in window_dates]
        if not closes:
            continue

        target_price, stop_price = _resolve_target_price(sig)
        is_buy = sig.get('trade_type') == 'buy'
        entry = sig.get('entry_price') or 0.0
        shares = sig.get('shares', 0)
        if not entry or not shares:
            continue  # 无入场价或份额无法结算，等待补充

        # 达标/止损判定（按日期顺序，取最先发生的）
        outcome = 'miss'
        settle_price = closes[-1]  # 默认 T+3 收盘
        hit_idx = len(window_dates) - 1
        for i, (d, close) in enumerate(zip(window_dates, closes)):
            if target_price is not None:
                if (is_buy and close >= target_price) or (not is_buy and close <= target_price):
                    outcome = 'hit'; settle_price = target_price; hit_idx = i
                    break
            if stop_price is not None:
                if (is_buy and close <= stop_price) or (not is_buy and close >= stop_price):
                    outcome = 'stopped'; settle_price = stop_price; hit_idx = i
                    break

        if is_buy:
            pnl = calc_buy_pnl(entry, settle_price, shares)
            avoided_loss = 0.0
        else:
            sell_price = entry
            cost = sig.get('cost_basis', sell_price) or sell_price
            pnl = calc_sell_pnl(sell_price, cost, shares)
            avoided_loss = calc_avoided_loss(sell_price, settle_price, shares)

        sig['pnl'] = round(pnl, 2)
        sig['avoided_loss'] = round(avoided_loss, 2)
        sig['outcome'] = outcome
        sig['settle_price'] = settle_price
        sig['settle_date'] = today
        sig['exit_date'] = today
        sig['holding_days'] = hit_idx + 1
        sig['status'] = 'settled'
        sig.setdefault('status_history', []).append({
            'date': today, 'status': 'settled',
            'note': f'T+3目标价结算: {outcome} @{settle_price}',
        })

    return tracking
