"""
REQ-010 TDD 门禁测试 — P0 触发后条件反转的"显式放弃"确认交互

被测模块: lib/p0_tracking.py（REQ-010 扩展，REQ-007 补充而非推翻）
覆盖:
  - finalize_p0_result:  识别"显式放弃"合法终态（用户操作=放弃/显式放弃，或响应状态含"放弃"）
                          非法路径: 放弃后仍执行 → transition_warning 标记 + 按已执行处理
  - calc_p0_execution_rate: 新口径 triggered=executed+waived+missed;
                          rate=executed/(executed+missed)（显式放弃不计入缺失/分母）;
                          显式放弃单独披露（waived / waived_ids）; unexecuted_ids 仅含错过
  - parse_p0_signals:    识别"显式放弃"状态（最终结果=显式放弃/未执行（放弃）兼容旧值）
  - check_p0_abandon_alert: 连续 ≥threshold 日显式放弃 → 告警审视信号设计（防滥用）

测试覆盖要求（REQ-010 测试交付物）:
  - calc_p0_execution_rate：显式放弃不计入执行缺失；放弃+执行混合场景；连续放弃阈值
  - parse_p0_signals：识别"显式放弃（合法终态）"状态
  - 状态转换：触发→放弃/执行/错过 三条合法路径 + 非法路径（放弃后仍执行）
"""

import sys
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from p0_tracking import (
    parse_p0_signals,
    finalize_p0_result,
    calc_p0_execution_rate,
    merge_p0_daily,
    check_p0_abandon_alert,
)


# ============================================================
# 样本构造
# ============================================================

_P0_HEADER = (
    "| 信号ID | 标的 | 操作类型 | 触发时间 | 检查点 | 响应状态 | 用户操作 | 最终结果 |\n"
    "|--------|------|:------:|:---:|:---:|:---:|:---:|:---:|\n"
)


def _mk_p0_section(rows: list[str]) -> str:
    """用标准 8 列格式组装 `## P0 执行追踪` 节 markdown。"""
    return (
        "## P0 执行追踪\n\n"
        "> P0 信号触发后立即在此登记。盘中检查每检查点追加一行；收盘复盘更新最终结果。\n\n"
        + _P0_HEADER
        + "\n".join(rows)
        + "\n"
    )


def _mk_rec(signal_id: str, actions: list[str], statuses: list[str] | None = None,
            existing_final: str = '') -> dict:
    """构造一条 P0 记录：actions = 各检查点用户操作；statuses = 各检查点响应状态（可选）；
    existing_final = 已有最终结果。"""
    if statuses is None:
        statuses = ['🚨已触发未执行'] * len(actions)
    return {
        'signal_id': signal_id,
        'name': '工商银行(601398)',
        'op_type': '减仓（1/3锁利）',
        'trigger_time': '11:05',
        'checkpoints': [
            {'checkpoint': f'c{i}', 'status': s, 'user_action': a, 'final_result': ''}
            for i, (a, s) in enumerate(zip(actions, statuses))
        ],
        'final_result': existing_final or '',
    }


# ============================================================
# parse_p0_signals — 识别"显式放弃"状态
# ============================================================

class TestParseP0SignalsWaived:
    def test_final_result_explicit_waive(self):
        """最终结果列 = 显式放弃 → 记录识别为显式放弃（合法终态）。"""
        md = _mk_p0_section([
            "| SIG-20260915-02 | 工商银行(601398) | 减仓（1/3锁利） | 10:37 | 触发时点 | 🚨已触发 | 显式放弃 | 显式放弃 |",
        ])
        records = parse_p0_signals(md, '2026-09-15')
        assert len(records) == 1
        rec = records[0]
        assert rec['checkpoints'][0]['user_action'] == '显式放弃'
        assert rec['final_result'] == '显式放弃'

    def test_final_result_legacy_waive(self):
        """最终结果列 = 未执行（放弃）（REQ-007 旧措辞）→ 兼容识别。"""
        md = _mk_p0_section([
            "| SIG-20260915-02 | 工商银行(601398) | 减仓（1/3锁利） | 10:37 | 触发时点 | 🚨已触发 | 放弃 | 未执行（放弃） |",
        ])
        records = parse_p0_signals(md, '2026-09-15')
        assert records[0]['final_result'] == '未执行（放弃）'

    def test_status_cancelled_waive(self):
        """响应状态 = 已取消（显式放弃）→ 用户操作待填时仍识别为放弃路径。"""
        md = _mk_p0_section([
            "| SIG-20260915-02 | 工商银行(601398) | 减仓（1/3锁利） | 10:37 | 触发时点 | 已取消（显式放弃） | 待填 | — |",
        ])
        records = parse_p0_signals(md, '2026-09-15')
        rec = records[0]
        finalized = finalize_p0_result([rec])
        assert finalized[0]['final_result'] == '显式放弃'


# ============================================================
# finalize_p0_result — 三条合法路径 + 非法路径
# ============================================================

class TestFinalizeP0ResultWaived:
    def test_waive_explicit(self):
        """用户操作=显式放弃 → 最终结果 显式放弃（合法终态，不问责）。"""
        recs = finalize_p0_result([_mk_rec('SIG-W1', ['显式放弃'])])
        assert recs[0]['final_result'] == '显式放弃'
        assert 'transition_warning' not in recs[0]

    def test_waive_legacy_word(self):
        """用户操作=放弃（REQ-007 旧写法）→ 同样判定为 显式放弃。"""
        recs = finalize_p0_result([_mk_rec('SIG-W2', ['放弃'])])
        assert recs[0]['final_result'] == '显式放弃'

    def test_execute_path(self):
        """合法路径①：触发→执行 → 已执行。"""
        recs = finalize_p0_result([_mk_rec('SIG-E1', ['已执行'])])
        assert recs[0]['final_result'] == '已执行'

    def test_missed_path(self):
        """合法路径③：触发→错过（全程待填/错过）→ 未执行（错过）。"""
        recs = finalize_p0_result([_mk_rec('SIG-M1', ['待填', '错过'])])
        assert recs[0]['final_result'] == '未执行（错过）'

    def test_illegal_waive_then_execute(self):
        """非法路径：放弃后仍执行 → transition_warning 标记，最终结果按已执行（执行优先）。"""
        recs = finalize_p0_result([_mk_rec('SIG-X1', ['放弃', '已执行'])])
        assert recs[0]['final_result'] == '已执行'
        assert 'transition_warning' in recs[0]
        assert '非法' in recs[0]['transition_warning']

    def test_execute_then_waive_is_illegal_too(self):
        """非法路径：执行后再声明放弃 → 同样标记（矛盾状态），最终按已执行。"""
        recs = finalize_p0_result([_mk_rec('SIG-X2', ['已执行', '显式放弃'])])
        assert recs[0]['final_result'] == '已执行'
        assert 'transition_warning' in recs[0]

    def test_status_waive_with_pending_action(self):
        """响应状态=已取消（显式放弃）+ 用户操作=待填 → 显式放弃（状态列证据兜底）。"""
        recs = finalize_p0_result([_mk_rec('SIG-W3', ['待填'], statuses=['已取消（显式放弃）'])])
        assert recs[0]['final_result'] == '显式放弃'

    def test_preserves_existing_final_result(self):
        """已存在最终结果（如盘中已标 已过期）→ 保留，不覆盖。"""
        recs = finalize_p0_result(
            [_mk_rec('SIG-F1', ['错过'], existing_final='已过期（14:45截止未执行）')]
        )
        assert recs[0]['final_result'] == '已过期（14:45截止未执行）'


# ============================================================
# calc_p0_execution_rate — 显式放弃不计入缺失/分母
# ============================================================

class TestCalcP0ExecutionRateWaived:
    def test_waived_not_counted_as_missing(self):
        """1 执行 + 1 显式放弃 + 0 错过 → 执行率 100.0%（放弃不拖累），waived=1。"""
        recs = [
            _mk_rec('SIG-A', ['已执行']),
            _mk_rec('SIG-B', ['显式放弃']),
        ]
        summary = calc_p0_execution_rate(recs)
        assert summary['triggered'] == 2      # 触发=执行+放弃+错过
        assert summary['executed'] == 1
        assert summary['waived'] == 1
        assert summary['missed'] == 0
        assert summary['rate'] == 100.0       # 1/(1+0)
        assert summary['unexecuted_ids'] == []
        assert 'SIG-B' in summary['waived_ids']

    def test_mixed_execute_waive_miss(self):
        """混合场景：1 执行 + 1 显式放弃 + 1 错过 → rate=50.0，unexecuted 仅含错过。"""
        recs = [
            _mk_rec('SIG-A', ['已执行']),
            _mk_rec('SIG-B', ['显式放弃']),
            _mk_rec('SIG-C', ['错过']),
        ]
        summary = calc_p0_execution_rate(recs)
        assert summary['triggered'] == 3
        assert summary['executed'] == 1
        assert summary['waived'] == 1
        assert summary['missed'] == 1
        assert summary['rate'] == 50.0
        assert summary['unexecuted_ids'] == ['SIG-C']
        assert summary['waived_ids'] == ['SIG-B']

    def test_all_waived_rate_none(self):
        """全部显式放弃 → 无应执行项，rate=None（无问责点），waived 单独披露。"""
        recs = [
            _mk_rec('SIG-A', ['显式放弃']),
            _mk_rec('SIG-B', ['放弃']),
        ]
        summary = calc_p0_execution_rate(recs)
        assert summary['triggered'] == 2
        assert summary['waived'] == 2
        assert summary['missed'] == 0
        assert summary['rate'] is None
        assert summary['unexecuted_ids'] == []

    def test_zero_triggered(self):
        """无 P0 → 全零，rate=None。"""
        summary = calc_p0_execution_rate([])
        assert summary['triggered'] == 0
        assert summary['executed'] == 0
        assert summary['waived'] == 0
        assert summary['missed'] == 0
        assert summary['rate'] is None

    def test_legacy_waive_final_classified_waived(self):
        """既有最终结果=未执行（放弃）（旧数据）→ calc 按显式放弃披露，不计入缺失。"""
        recs = [_mk_rec('SIG-L1', ['放弃'], existing_final='未执行（放弃）')]
        summary = calc_p0_execution_rate(recs)
        assert summary['waived'] == 1
        assert summary['missed'] == 0
        assert summary['unexecuted_ids'] == []

    def test_status_waive_counts_waived(self):
        """响应状态=已取消（显式放弃）+ 用户待填 → 计为显式放弃（REQ-010 状态列证据）。"""
        recs = [_mk_rec('SIG-S1', ['待填'], statuses=['已取消（显式放弃）'])]
        summary = calc_p0_execution_rate(recs)
        assert summary['waived'] == 1
        assert summary['missed'] == 0


# ============================================================
# check_p0_abandon_alert — 连续放弃阈值（防滥用）
# ============================================================

def _mk_store() -> dict:
    return {'_schema': '1.0', '_updated': '', 'daily': {}}


class TestCheckP0AbandonAlert:
    def test_two_consecutive_days_alerts(self):
        """连续 2 日有显式放弃 → 告警（默认阈值=2）。"""
        store = _mk_store()
        merge_p0_daily(store, '2026-09-08', {'triggered': 1, 'executed': 1, 'waived': 1, 'missed': 0, 'rate': 100.0})
        merge_p0_daily(store, '2026-09-09', {'triggered': 1, 'executed': 0, 'waived': 1, 'missed': 0, 'rate': None})
        result = check_p0_abandon_alert(store)
        assert result['alert'] is True
        assert result['streak'] == 2

    def test_single_day_no_alert(self):
        """仅 1 日显式放弃 → 不告警（连续 2 日才告警）。"""
        store = _mk_store()
        merge_p0_daily(store, '2026-09-08', {'triggered': 1, 'executed': 1, 'waived': 1, 'missed': 0, 'rate': 100.0})
        result = check_p0_abandon_alert(store)
        assert result['alert'] is False
        assert result['streak'] == 1

    def test_interrupted_streak_no_alert(self):
        """放弃日被无放弃日中断 → trailing streak 归零，不告警。"""
        store = _mk_store()
        merge_p0_daily(store, '2026-09-08', {'triggered': 1, 'executed': 1, 'waived': 1, 'missed': 0, 'rate': 100.0})
        merge_p0_daily(store, '2026-09-09', {'triggered': 1, 'executed': 0, 'waived': 0, 'missed': 1, 'rate': 0.0})
        merge_p0_daily(store, '2026-09-10', {'triggered': 1, 'executed': 1, 'waived': 1, 'missed': 0, 'rate': 100.0})
        result = check_p0_abandon_alert(store)
        assert result['alert'] is False
        assert result['streak'] == 1  # 最近一段连续放弃仅 1 日（09-10）

    def test_custom_threshold(self):
        """自定义阈值=3：连续 2 日不告警，连续 3 日告警。"""
        store = _mk_store()
        merge_p0_daily(store, '2026-09-08', {'triggered': 1, 'executed': 1, 'waived': 1, 'missed': 0, 'rate': 100.0})
        merge_p0_daily(store, '2026-09-09', {'triggered': 1, 'executed': 1, 'waived': 1, 'missed': 0, 'rate': 100.0})
        r2 = check_p0_abandon_alert(store, threshold=3)
        assert r2['alert'] is False
        merge_p0_daily(store, '2026-09-10', {'triggered': 1, 'executed': 1, 'waived': 1, 'missed': 0, 'rate': 100.0})
        r3 = check_p0_abandon_alert(store, threshold=3)
        assert r3['alert'] is True
        assert r3['streak'] == 3

    def test_no_waive_days(self):
        """无任何显式放弃日 → 不告警，streak=0。"""
        store = _mk_store()
        merge_p0_daily(store, '2026-09-08', {'triggered': 1, 'executed': 1, 'waived': 0, 'missed': 0, 'rate': 100.0})
        result = check_p0_abandon_alert(store)
        assert result['alert'] is False
        assert result['streak'] == 0


# ============================================================
# 端到端：REQ-010 期望结果场景还原
# ============================================================

class TestReq010Scenario:
    def test_condition_reversal_waive_scenario(self):
        """还原 9/15 工行场景：触发 → 条件反转 → 用户显式放弃 → 不问责、执行率不受损。"""
        md = _mk_p0_section([
            "| SIG-20260915-02 | 工商银行(601398) | 减仓（1/3锁利） | 10:37 | 触发时点 | 🚨已触发 | 待填 | — |",
            "| SIG-20260915-02 | 工商银行(601398) | 减仓（1/3锁利） | 10:37 | 10:30检查 | 🟡条件反转 | 待填 | — |",
            "| SIG-20260915-02 | 工商银行(601398) | 减仓（1/3锁利） | 10:37 | 11:00检查 | 已取消（显式放弃） | 显式放弃 | — |",
        ])
        records = parse_p0_signals(md, '2026-09-15')
        assert len(records) == 1
        summary = calc_p0_execution_rate(records)
        assert summary['waived'] == 1
        assert summary['missed'] == 0
        assert summary['rate'] is None  # 无应执行项 → 不构成执行缺失
        assert summary['unexecuted_ids'] == []

    def test_no_reply_is_missed(self):
        """条件反转后用户截止前未回复 → 未执行（错过），计入执行缺失。"""
        md = _mk_p0_section([
            "| SIG-20260909-01 | 黄金ETF(518880) | 减仓评估 | 09:30 | 触发时点 | 🚨已触发 | 待填 | — |",
            "| SIG-20260909-01 | 黄金ETF(518880) | 减仓评估 | 09:30 | 13:30检查 | 🟡条件反转 | 待填 | — |",
            "| SIG-20260909-01 | 黄金ETF(518880) | 减仓评估 | 09:30 | 14:45截止 | 已过期（14:45截止未响应） | 错过 | 未执行（错过） |",
        ])
        records = parse_p0_signals(md, '2026-09-09')
        summary = calc_p0_execution_rate(records)
        assert summary['missed'] == 1
        assert summary['waived'] == 0
        assert summary['rate'] == 0.0
        assert 'SIG-20260909-01' in summary['unexecuted_ids']
