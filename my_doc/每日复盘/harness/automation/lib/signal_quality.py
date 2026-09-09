"""
信号质量统计核心逻辑 — 每日信号模块优化（spec: docs/superpowers/specs/2026-08-26-signal-quality-design.md）

从 signal_tracking.json 的 signals 计算 A 层 8 项质量指标。
纯计算函数，不读写磁盘，不调用外部 API。

指标（A 层全自动）:
  触发率 / 目标达成率 / 平均达标天数 / 平均盈亏比 / 方向准确率 /
  预期vs实际触发率偏差 / 信号期望价值 / 单笔最大亏损

REQ-006（2026-09-09）:
  账户级指标（期望价值/盈亏比/最大亏损/方向准确率/目标达成率/平均达标天数）
  仅基于"已执行样本"；"未执行模拟样本"单独披露（simulated_* 字段，假设口径）。
"""

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from signal_tracking import is_simulated

_TRIGGERED_STATUSES = ('triggered', 'executed', 'partial_executed', 'settled')


def split_executed_simulated(settled: list) -> tuple:
    """将已结算信号分为 (已执行样本, 未执行模拟样本) 两组（REQ-006）。

    账户级指标只应基于已执行样本；未执行模拟样本的 P&L 是假设口径，
    仅用于方向/目标达成率评估。
    """
    executed = [s for s in settled if not is_simulated(s)]
    simulated = [s for s in settled if is_simulated(s)]
    return executed, simulated


def _is_triggered(sig: dict) -> bool:
    return sig.get('status') in _TRIGGERED_STATUSES


def calc_trigger_rate(signals: list, priority: str = None) -> float:
    """触发率 = 已触发 / 总数。priority 为 None 时统计全部（百分比）。"""
    pool = [s for s in signals if priority is None or s.get('priority') == priority]
    if not pool:
        return 0.0
    hit = sum(1 for s in pool if _is_triggered(s))
    return round(hit / len(pool) * 100, 1)


def calc_target_hit_rate(settled: list) -> float:
    """目标达成率 = outcome=='hit' / 已结算数（百分比）。"""
    if not settled:
        return 0.0
    hits = sum(1 for s in settled if s.get('outcome') == 'hit')
    return round(hits / len(settled) * 100, 1)


def calc_avg_hit_days(settled: list) -> float:
    """平均达标天数 = 达标信号 holding_days 平均（快进快出验证，目标 1-2 天）。"""
    hits = [s.get('holding_days') for s in settled
            if s.get('outcome') == 'hit' and s.get('holding_days') is not None]
    if not hits:
        return 0.0
    return round(sum(hits) / len(hits), 1)


def calc_avg_profit_loss_ratio(settled: list) -> float:
    """平均盈亏比 = 平均盈利单金额 / 平均亏损单金额（按 pnl 绝对值）。"""
    wins = [s.get('pnl', 0.0) for s in settled if (s.get('pnl') or 0) > 0]
    losses = [s.get('pnl', 0.0) for s in settled if (s.get('pnl') or 0) < 0]
    if not wins or not losses:
        return 0.0
    avg_win = sum(wins) / len(wins)
    avg_loss = abs(sum(losses) / len(losses))
    return round(avg_win / avg_loss, 2)


def calc_direction_accuracy(settled: list) -> float:
    """方向准确率 = 信号方向与结算方向一致比例（百分比）。
    buy: settle_price >= entry_price → 正确；sell: settle_price <= entry_price → 正确。"""
    correct = 0
    total = 0
    for s in settled:
        trade_type = s.get('trade_type')
        if trade_type not in ('buy', 'sell'):
            continue
        is_buy = trade_type == 'buy'
        entry = s.get('entry_price') or 0.0
        settle_p = s.get('settle_price') or 0.0
        if (is_buy and settle_p >= entry) or (not is_buy and settle_p <= entry):
            correct += 1
        total += 1
    if not total:
        return 0.0
    return round(correct / total * 100, 1)


def calc_expected_vs_actual(signals: list) -> dict:
    """预期触发率 vs 实际触发率（生成者校准）。
    返回 {rows: [{signal_id, expected, triggered}], avg_gap: float|None}
    avg_gap = 实际触发率 − 预期均值（百分点），正值=生成者偏保守，负值=偏乐观。"""
    rows = []
    for s in signals:
        exp = s.get('expected_trigger_rate')
        if exp is None:
            continue
        rows.append({
            'signal_id': s.get('signal_id', ''),
            'expected': exp,
            'triggered': _is_triggered(s),
        })
    if not rows:
        return {'rows': [], 'avg_gap': None}
    actual_rate = sum(1 for r in rows if r['triggered']) / len(rows) * 100
    avg_exp = sum(r['expected'] for r in rows) / len(rows)
    return {'rows': rows, 'avg_gap': round(actual_rate - avg_exp, 1)}


def calc_signal_expected_value(settled: list) -> float:
    """信号期望价值 = 平均单次 P&L（已结算信号）。"""
    if not settled:
        return 0.0
    return round(sum(s.get('pnl', 0.0) for s in settled) / len(settled), 2)


def calc_max_loss(settled: list) -> float:
    """单笔最大亏损 = min(pnl)（短线风控）。无亏损（全为盈利）返回 0.0。"""
    pnls = [s.get('pnl', 0.0) for s in settled]
    if not pnls or min(pnls) >= 0:
        return 0.0
    return round(min(pnls), 2)


def generate_quality_dashboard(signals: list, settled: list, today: str = '') -> dict:
    """汇总 A 层 8 项指标为仪表盘数据 dict（复盘 prompt 渲染为表格）。

    REQ-006: 账户级指标（期望价值/盈亏比/最大亏损/方向准确率/目标达成率/平均达标天数）
    仅基于已执行样本；未执行模拟样本单独披露（simulated_* 字段，标注假设口径）。
    """
    executed, simulated = split_executed_simulated(settled)
    dashboard = {
        'date': today,
        'trigger_rate_p1': calc_trigger_rate(signals, 'P1'),
        'trigger_rate_all': calc_trigger_rate(signals),
        'target_hit_rate': calc_target_hit_rate(executed),
        'avg_hit_days': calc_avg_hit_days(executed),
        'avg_profit_loss_ratio': calc_avg_profit_loss_ratio(executed),
        'direction_accuracy': calc_direction_accuracy(executed),
        'expected_vs_actual': calc_expected_vs_actual(signals),
        'signal_expected_value': calc_signal_expected_value(executed),
        'max_loss': calc_max_loss(executed),
        # 未执行模拟样本单独披露（假设口径，不入账户级）
        'simulated_count': len(simulated),
        'simulated_pnl_amount': round(sum(s.get('pnl', 0.0) for s in simulated), 2),
        'simulated_expected_value': calc_signal_expected_value(simulated),
        'simulated_target_hit_rate': calc_target_hit_rate(simulated),
    }
    return dashboard
