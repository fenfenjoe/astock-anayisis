"""
信号-成交对账 — P0 修复：信号执行统计来源改造

背景：用户在"持仓/资产"界面"录入交易"记录真实执行，但信号系统（signal_tracking）
只统计 signal.status=executed，两套数据未打通 → 执行率恒为 0。
方案（用户确认）：盘中/复盘时对账——发现与信号匹配的成交 → 更新信号状态为 executed。

本模块为**纯函数**：只做匹配/状态回填/摘要，不读写磁盘、不调云库；
数据源（signals/trades）与写回（cloud_update_fields）由调用方 prompt 提供。

匹配键（严格，宁缺勿滥）：
  - signal.signal_date == trade.trade_date（同日）
  - signal.ticker == trade.code（6 位代码）
  - signal.trade_type ↔ trade.side（buy↔买入 / sell↔卖出）
匹配范围：signal.status ∈ {open, triggered}（终态保护——executed/settled 不动）。
"""

from datetime import datetime
import re

_ACTIVE_STATUSES = ('open', 'triggered')
_SIDE_MAP = {'buy': '买入', 'sell': '卖出'}
_REMARK_SIG_ID = re.compile(r'执行信号\s*(SIG-[\w\-]+)', re.IGNORECASE)


def _side_matches(trade_type: str, side: str) -> bool:
    """信号 trade_type 与成交 side 是否同向。"""
    return _SIDE_MAP.get(trade_type, '') == (side or '').strip()


def _remark_signal_id(trade: dict) -> str | None:
    """从成交 remark 提取关联的信号 ID（如 '执行信号 SIG-20260921-04'）。"""
    remark = str(trade.get('remark') or '')
    m = _REMARK_SIG_ID.search(remark)
    return m.group(1) if m else None


def match_trades(signals: list, trades: list) -> list:
    """匹配信号与成交，返回 [{signal, trade, matched_at, match_by}]。

    匹配优先级：
      1. remark_signal_id：成交 remark 显式关联的信号 ID（最精确，用户录入时自动带）
      2. strict：同日 + 同码 + 同向（兜底）
    一信号多成交取第一笔；终态信号不参与。
    """
    matches = []
    active = [s for s in signals if (s.get('status') or '').strip().lower() in _ACTIVE_STATUSES]
    by_id = {s.get('signal_id'): s for s in active if s.get('signal_id')}

    # 第一轮：remark 信号 ID 精确匹配（每个信号只取第一笔）
    used_trades = set()
    for t in trades:
        sid = _remark_signal_id(t)
        if sid and sid in by_id:
            sig = by_id[sid]
            # 终态保护（防御：active 已过滤，但再确认一次）
            matches.append({
                'signal': sig,
                'trade': t,
                'matched_at': datetime.now().isoformat(timespec='seconds'),
                'match_by': 'remark_signal_id',
            })
            used_trades.add(id(t))

    # 第二轮：剩余未匹配信号走严格键（同日+同码+同向）
    matched_sids = {m['signal'].get('signal_id') for m in matches}
    for sig in active:
        if sig.get('signal_id') in matched_sids:
            continue
        sig_date = str(sig.get('signal_date') or sig.get('trigger_date') or '').strip()
        ticker = str(sig.get('ticker') or sig.get('code') or '').strip()
        trade_type = (sig.get('trade_type') or '').strip().lower()
        hit = None
        for t in trades:
            if id(t) in used_trades:
                continue  # 已被 remark 匹配占用的成交不再用于严格匹配
            if str(t.get('trade_date', '')).strip() != sig_date:
                continue
            if str(t.get('code', '')).strip() != ticker:
                continue
            if not _side_matches(trade_type, t.get('side', '')):
                continue
            hit = t
            break
        if hit is not None:
            matches.append({
                'signal': sig,
                'trade': hit,
                'matched_at': datetime.now().isoformat(timespec='seconds'),
                'match_by': 'strict',
            })
            used_trades.add(id(hit))
    return matches


def apply_matches(signals: list, matches: list) -> list:
    """按匹配结果生成更新后的信号列表（副本）。

    命中 → status=executed + entry_price=成交价 + entry_time=成交时间。
    未命中信号原样返回（引用，但本函数不改入参）。
    """
    by_id = {}
    for m in matches:
        sid = m['signal'].get('signal_id')
        if sid:
            by_id[sid] = m['trade']
    updated = []
    for s in signals:
        rec = dict(s)  # 副本，不改入参
        trade = by_id.get(rec.get('signal_id'))
        if trade is not None:
            rec['status'] = 'executed'
            rec['entry_price'] = trade.get('price')
            rec['entry_time'] = str(trade.get('trade_date', '')) + ' ' + _entry_time_of(trade)
        updated.append(rec)
    return updated


def _entry_time_of(trade: dict) -> str:
    """从成交记录取时间（created_at 或 trade_date 兜底）。"""
    raw = str(trade.get('created_at') or '').strip()
    if len(raw) >= 5:
        return raw[-5:]  # HH:MM（ISO 时间尾）
    return '00:00'


def summarize_reconcile(signals_before: list, signals_after: list, matches: list) -> dict:
    """对账摘要：matched / updated / unmatched（当日 open 但无成交）。

    注意：unmatched 基于 signals_before 中当日 active 但未被匹配的信号。
    """
    matched_ids = {m['signal'].get('signal_id') for m in matches}
    active_ids_before = {
        s.get('signal_id') for s in signals_before
        if (s.get('status') or '').strip().lower() in _ACTIVE_STATUSES
    }
    unmatched = [
        {'signal_id': sid} for sid in active_ids_before if sid not in matched_ids
    ]
    # updated = 匹配后状态变成 executed 的信号
    updated_ids = {
        s.get('signal_id') for s in signals_after
        if (s.get('status') or '').strip().lower() == 'executed'
        and s.get('signal_id') in matched_ids
    }
    return {
        'matched_count': len(matches),
        'updated_count': len(updated_ids),
        'matched': [{'signal_id': m['signal'].get('signal_id'),
                     'code': m['trade'].get('code'),
                     'price': m['trade'].get('price'),
                     'time': m['trade'].get('created_at')} for m in matches],
        'unmatched': unmatched,
    }
