"""
信号收益追踪核心逻辑 — REQ-001

从 auto_evening_review.md §7.6 的嵌入式 Python 提取。
纯计算函数，不读写磁盘，不调用外部 API。

依赖: trading_calendar.py (next_trading_day, is_trading_day)

新增（2026-08-07 修复 BUG-XXX: signal_tracking.json 从未被写入）：
  - parse_signal_markdown()   — 解析每日信号.md，提取已触发/已执行的信号记录
  - merge_new_signals()       — 将解析出的新信号并入追踪库（去重）
  - settle_due_signals()      — 目标价结算：T+3 窗口内 hit/stopped/miss（v2.0 改）

新增（REQ-006，2026-09-09）：
  - is_simulated()            — 判定"未执行模拟样本"（显式 simulated 字段优先，否则按 status_history 推断）
  - settle_due_signals()      — 结算时标注 simulated（未执行信号按假设结算，P&L 归模拟口径）
  - update_aggregation()      — total_pnl_amount 仅含已执行；simulated_pnl_amount 单列未执行模拟 P&L
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
# 已执行/未执行模拟样本判定（REQ-006）
# ============================================================

def is_simulated(sig: dict) -> bool:
    """判断信号是否为"未执行模拟样本"（REQ-006）。

    未执行信号（status=triggered 且从无 executed/partial_executed 记录）按假设结算，
    其 P&L 是信号质量评估（方向/目标达成率）而非账户损益，不计入账户级统计。

    判定规则：
    1. 显式 `simulated` 字段优先（True/False）
    2. 无该字段 → 按 status_history 推断：含 executed/partial_executed → 已执行(False)
    3. status 字段兜底：status ∈ {executed, partial_executed} → 已执行(False)
    4. 其余情况（含旧记录无历史）→ 视为未执行模拟(True，保守推断)
    """
    if 'simulated' in sig:
        return bool(sig.get('simulated'))
    if sig.get('status') in ('executed', 'partial_executed'):
        return False
    history = sig.get('status_history') or []
    return not any(h.get('status') in ('executed', 'partial_executed') for h in history)


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
    # REQ-006: total_pnl_amount 仅含已执行样本；simulated_pnl_amount 单独列示未执行模拟 P&L（假设口径）
    total_executed_pnl = agg['by_urgency']['high']['total_pnl'] + agg['by_urgency']['low']['total_pnl']
    total_simulated_pnl = agg['by_urgency']['high']['simulated_pnl'] + agg['by_urgency']['low']['simulated_pnl']
    tracking['aggregates'] = {
        'total_signals_tracked': agg['by_urgency']['high']['count'] + agg['by_urgency']['low']['count'],
        'total_resolved': agg['by_urgency']['high']['settled'] + agg['by_urgency']['low']['settled'],
        'total_open': len(signals) - (agg['by_urgency']['high']['settled'] + agg['by_urgency']['low']['settled']),
        'total_pnl_amount': round(total_executed_pnl, 2),
        'simulated_pnl_amount': round(total_simulated_pnl, 2),
        'total_avoided_loss': round(sum(s.get('avoided_loss', 0.0) for s in signals), 2),
        'win_count': agg['by_urgency']['high']['win_count'] + agg['by_urgency']['low']['win_count'],
        'lose_count': 0,  # 下面按已执行样本重算
        'by_urgency': {
            k: {
                'count': v['count'], 'resolved': v['settled'],
                'total_pnl': round(v['total_pnl'], 2),
                'simulated_pnl': round(v['simulated_pnl'], 2),
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
                'simulated_pnl': round(v['simulated_pnl'], 2),
            }
            for k, v in agg['by_priority'].items()
        },
    }
    # win_rate / lose_count 仅基于已执行样本（REQ-006）
    win_count = tracking['aggregates']['win_count']
    executed_settled = sum(1 for s in signals
                           if s.get('status') == 'settled' and not is_simulated(s))
    lose_count = executed_settled - win_count
    tracking['aggregates']['lose_count'] = lose_count
    tracking['aggregates']['win_rate'] = (
        round((win_count / executed_settled * 100), 1)
        if executed_settled else None
    )
    return tracking


def _empty_agg() -> dict:
    """聚合桶初始结构。total_pnl 仅含已执行样本；simulated_pnl 单独列示（REQ-006）。"""
    return {'count': 0, 'settled': 0, 'total_pnl': 0.0, 'simulated_pnl': 0.0, 'win_count': 0}


def _update_bucket(agg_dict: dict, key: str, signal: dict) -> None:
    if key not in agg_dict:
        agg_dict[key] = _empty_agg()
    bucket = agg_dict[key]
    bucket['count'] += 1
    if signal.get('status') == 'settled':
        bucket['settled'] += 1
        pnl = signal.get('pnl', 0.0)
        # REQ-006: 未执行模拟样本的 P&L 单列（假设口径），不入账户级
        if is_simulated(signal):
            bucket['simulated_pnl'] += pnl
        else:
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

# ── 枚举约束（CHAT.md 任务4 · 与 docs/signal-enums.md / signal_tracking_cloud.py 一致）──
# 复用既有 VALID_TRADE_TYPE / VALID_URGENCY / VALID_PRIORITY（L248-250），新增其余枚举
# 注意：追踪库/云库 status 用英文内部值（markdown 显示层的中文状态由 _TRACKABLE_STATUSES 映射）
# 2026-09 v3.0：新增 expired（已过期）——盘中"触发后回落离开交易价"或"75%窗口过期"写入云库
ENUM_STATUS = {'open', 'triggered', 'executed', 'partial_executed', 'settled', 'expired'}
ENUM_DIRECTION = {'buy', 'sell'}
ENUM_SOURCE = {'morning_analysis', 'intraday_check', 'evening_review'}
ENUM_OUTCOME = {'hit', 'stopped', 'miss'}

_ENUM_FIELDS = {
    'trade_type': VALID_TRADE_TYPE,
    'direction': ENUM_DIRECTION,
    'priority': VALID_PRIORITY,
    'urgency': VALID_URGENCY,
    'source': ENUM_SOURCE,
    'outcome': ENUM_OUTCOME,
    'status': ENUM_STATUS,
}


def assert_valid_signal_record(rec: dict) -> dict:
    """校验单条信号记录的枚举字段；非法值抛 ValueError。返回原 dict。

    只校验存在且有值的受约束字段；数值字段做类型规整。供 merge_new_signals 及
    signal_tracking_cloud.to_row 双端调用（生成/入库两侧同口径）。
    注意：这是"抛异常"版；原 validate_signal_record（L253，返回错误列表）保留不动。
    """
    for field, allowed in _ENUM_FIELDS.items():
        val = rec.get(field)
        if val is None:
            continue
        v = str(val).strip()
        if v not in allowed:
            raise ValueError(
                f"信号字段 {field} 值 {v!r} 不在合法枚举 {sorted(allowed)} 内 "
                f"(signal_id={rec.get('signal_id')})"
            )
        rec[field] = v
    for field in ('target_price', 'stop_price', 'entry_price', 'trigger_price',
                  'expected_trigger_rate', 'target_pct', 'stop_pct', 'trade_price'):
        val = rec.get(field)
        if val is not None and not isinstance(val, (int, float)):
            try:
                rec[field] = float(val)
            except (TypeError, ValueError):
                raise ValueError(
                    f"信号字段 {field} 应为数值，实际 {val!r} (signal_id={rec.get('signal_id')})"
                )
    return rec


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


def _parse_pct_or_price(cell: str) -> tuple:
    """解析单个价位单元格：'+3%' → (pct=3.0, price=None)；'1.75' → (pct=None, price=1.75)。
    空/— → (None, None)。"""
    cell = (cell or '').strip()
    if not cell or cell == '—':
        return None, None
    m = re.match(r'([+-]?\d+(?:\.\d+)?)\s*%', cell)
    if m:
        return float(m.group(1)), None
    m = re.match(r'([+-]?\d+(?:\.\d+)?)', cell)
    if m:
        return None, float(m.group(1))
    return None, None


def _parse_price_cols(g, header: list[str]) -> dict:
    """解析价格列：v3.0 三列（交易价/目标价/止损价）优先，v2.0 目标/止损 列兜底。

    返回 {trade_price, target_price, target_pct, stop_price, stop_pct}。
    g(idx) 取单元格文本（row → cell）；header 为表头列名列表。
    - 交易价：'1.70' → trade_price=1.70；'—' → None
    - 目标价/止损价：显式价或百分比（'+3%'/'1.75'）
    """
    result = {'trade_price': None, 'target_price': None, 'target_pct': None,
              'stop_price': None, 'stop_pct': None}
    c_trade = _col(header, '交易价')
    if c_trade >= 0:
        trade = g(c_trade)
        if trade and trade != '—':
            _pct, price = _parse_pct_or_price(trade)
            result['trade_price'] = price if price is not None else None
        c_tgt = _col(header, '目标价')
        c_stop = _col(header, '止损价')
        if c_tgt >= 0:
            pct, price = _parse_pct_or_price(g(c_tgt))
            result['target_pct'] = pct
            result['target_price'] = price
        if c_stop >= 0:
            pct, price = _parse_pct_or_price(g(c_stop))
            result['stop_pct'] = pct
            result['stop_price'] = price
        return result
    # v2.0 兜底：目标/止损 合并列
    c_tgt_stop = _col(header, '目标/止损')
    if c_tgt_stop >= 0:
        result.update(_parse_target_stop(g(c_tgt_stop)))
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

        ts = _parse_price_cols(g, header)
        records.append({
            'signal_id': signal_id,
            'ticker': ticker,
            'name': target.split('(')[0] if '(' in target else target,
            'trade_type': _map_trade_type(op_type, direction),
            'direction': 'sell' if '卖' in direction else 'buy',
            'priority': priority or 'P2',
            'urgency': urgency_val,
            'expected_trigger_rate': _parse_expected_rate(g(c_exp_rate)),
            'trade_price': ts['trade_price'],
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

    # 触发价/入场价回填（2026-09-14 任务4 调整）：
    #   盘中验证记录 已不再生成（CHAT.md），但为兼容过渡期/历史 markdown，
    #   若段落仍在则提取作为触发价（写入 trigger_price；entry_price 作为入场价代理）。
    # 过滤规则（任务4 调整）：只要求 份额>0（可交易的信号）即入库；
    #   不再强制 entry_price——买入价由复盘 7.6.1b（录入交易）回填，触发价由盘中写云库，
    #   二者都缺时信号保持无价记录（settle 侧对无 entry_price 信号跳过结算）。
    verify_prices = _extract_trigger_prices(md_text)
    for rec in records:
        if rec['signal_id'] in verify_prices:
            # trigger_price：直接写（盘中触发价）；entry_price：仅当尚未回填时用触发价作代理
            rec['trigger_price'] = verify_prices[rec['signal_id']]
            if rec.get('entry_price') is None:
                rec['entry_price'] = verify_prices[rec['signal_id']]
    records = [r for r in records if r.get('shares', 0) > 0]
    return records


def parse_signal_rows_all(md_text: str, today: str = '') -> list[dict]:
    """解析每日信号.md 信号总表的【全部行】（含 未触发/已触发/已执行/已过期），用于云库入库。

    与 parse_signal_markdown 的差异：
    - parse_signal_markdown 只追踪 已触发/已执行/部分执行（结算收益用）；
    - 本函数把整表按行转成云库 JSON 记录（status 用英文内部值：未触发→open、已过期→expired），
      供 auto_morning_analysis 生成每日信号.md 后立刻云库入库、auto_intraday_check 状态变更后同步云库，
      使 Dashboard「每日信号」页早盘即可见（2026-09-15 BUG-FIX：早盘只写 md
      不写云库 → daily-signals 查云库为空）。
    today: 'YYYY-MM-DD'，缺省用 date.today()。
    """
    if not today:
        today = date.today().isoformat()
    _STATUS_CN2EN = {
        '待执行': 'open',        # 旧词元兼容
        '未触发': 'open',        # v3.0 初始状态
        '已触发': 'triggered',
        '已执行': 'executed',
        '部分执行': 'partial_executed',
        '已过期': 'expired',     # v3.0 盘中回落/窗口过期
    }
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
    c_cond = _col(header, '触发条件')
    c_window = _col(header, '有效时段')

    records = []
    for row in rows:
        def g(idx):
            return row[idx] if 0 <= idx < len(row) else ''

        signal_id = g(c_id)
        if not signal_id.startswith('SIG-'):
            continue
        status_cn = g(c_status).strip()
        status = _STATUS_CN2EN.get(status_cn)
        if status is None:
            continue  # 已取消/已废弃等：不入库
        ticker = _extract_ticker(g(c_target))
        if not ticker:
            continue
        target = g(c_target)
        ts = _parse_price_cols(g, header)
        records.append({
            'signal_id': signal_id,
            'ticker': ticker,
            'name': target.split('(')[0] if '(' in target else target,
            'trade_type': _map_trade_type(g(c_op), g(c_dir)),
            'direction': 'sell' if '卖' in g(c_dir) else 'buy',
            'priority': g(c_prio) or 'P2',
            'urgency': _URGENCY_MAP.get(g(c_urg), 'low'),
            'expected_trigger_rate': _parse_expected_rate(g(c_exp_rate)),
            'trade_price': ts['trade_price'],
            'target_pct': ts['target_pct'],
            'stop_pct': ts['stop_pct'],
            'target_price': ts['target_price'],
            'stop_price': ts['stop_price'],
            'expected_return_date': g(c_exp) if g(c_exp) and g(c_exp) != '—' else '',
            'trigger_date': today,
            'status': status,
            'source': 'morning_analysis',
            'trigger_condition': g(c_cond) if g(c_cond) else None,
            'valid_window': g(c_window) if g(c_window) else None,
            'position': g(c_qty) if g(c_qty) else None,
        })
    return records


def parse_trigger_records_from_md(md_text: str, today: str = '') -> list[dict]:
    """解析每日信号.md `## 信号触发记录` 节 → cloud_upsert_trigger_records 可用的记录列表。

    2026-09-24 新增：早盘生成信号时预填每条信号的**第一条生成记录**（触发条件摘要=生成原因、
    状态=已生成），盘中触发时追加"已触发"记录——本函数把该节整表解析为云表记录
    （signal_trigger_records），供 auto_morning_analysis 第五步半与盘中检查 §5.2 落库。

    返回记录键（与 signal_tracking_cloud.to_trigger_row 对齐）：
      signal_id / trigger_date / trigger_time / priority / ticker / name /
      action_type / condition（触发条件摘要=生成原因或触发摘要）/ status / suggest / result
    标的列 '名称(代码)' → name + ticker 拆分；无 signal_id 的行（占位/空行）跳过。
    today: 'YYYY-MM-DD'，缺省用 date.today()。
    """
    if not today:
        today = date.today().isoformat()
    header, rows = _parse_table_rows(md_text, '## 信号触发记录')
    c_time = _col(header, '触发时间', '时间')
    c_id = _col(header, '信号ID')
    c_prio = _col(header, '优先级')
    c_target = _col(header, '标的')
    c_op = _col(header, '操作类型')
    c_cond = _col(header, '触发条件摘要', '触发条件')
    c_status = _col(header, '当前状态', '状态')
    c_suggest = _col(header, '建议操作')
    c_result = _col(header, '用户操作')

    records = []
    for row in rows:
        def g(idx):
            return row[idx] if 0 <= idx < len(row) else ''

        signal_id = g(c_id).strip()
        if not signal_id.startswith('SIG-'):
            continue
        target = g(c_target)
        ticker = _extract_ticker(target)
        rec = {
            'signal_id': signal_id,
            'trigger_date': today,
            'trigger_time': g(c_time).strip() or None,
            'priority': g(c_prio).strip() or 'P2',
            'ticker': ticker or '',
            'name': target.split('(')[0].strip() if '(' in target else target.strip(),
            'action_type': g(c_op).strip(),
            'condition': g(c_cond).strip(),
            'status': g(c_status).strip(),
            'suggest': g(c_suggest).strip(),
            'result': g(c_result).strip() or None,
        }
        records.append(rec)
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
    """将新信号并入追踪库（按 signal_id 去重）。返回更新后的 dict（不写磁盘）。

    并入前逐条做枚举校验（assert_valid_signal_record），非法记录抛 ValueError——
    生成侧严格遵守枚举是任务4 的硬性要求，宁可中断也不入库脏数据。
    """
    existing_ids = {s.get('signal_id') for s in tracking.get('signals', [])}
    added = 0
    for rec in new_records:
        assert_valid_signal_record(rec)
        if rec['signal_id'] in existing_ids:
            continue
        tracking.setdefault('signals', []).append(rec)
        existing_ids.add(rec['signal_id'])
        added += 1
    tracking['_updated'] = date.today().isoformat()
    return tracking


def _resolve_target_price(sig: dict) -> tuple:
    """计算信号目标价/止损价：显式价格优先，否则用百分比×基准价。

    2026-09-14 任务4：入场价可能由录入交易/触发价回填；entry_price 缺时回退 trigger_price。
    2026-09 v3.0：再回退 trade_price（交易价）——盘中/结算时入场价尚未回填时，
    百分比目标/止损按信号生成时的计划交易价换算。
    """
    entry = sig.get('entry_price') or sig.get('trigger_price') or sig.get('trade_price') or 0.0
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
        entry = sig.get('entry_price') or sig.get('trigger_price') or 0.0
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

        # REQ-006: 结算前判定是否"未执行模拟样本"（status 尚未改为 settled 时推断）
        simulated = is_simulated(sig)
        sig['simulated'] = simulated
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
            'note': f'T+3目标价结算: {outcome} @{settle_price}'
                    + ('（模拟，未执行）' if simulated else ''),
        })

    return tracking
