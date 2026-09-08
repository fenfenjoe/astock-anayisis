"""
REQ-007 TDD 门禁测试 — P0 信号执行追踪机制

被测模块: lib/p0_tracking.py（REQ-007 新增）
覆盖:
  - parse_p0_signals:      解析 每日信号.md 的 `## P0 执行追踪` 节 → 按 signal_id 分组记录
  - finalize_p0_result:    确定每条 P0 的最终结果（零容忍，不做结果论豁免）
  - calc_p0_execution_rate:P0 执行率 = 已执行 P0 / 已触发 P0
  - merge_p0_daily:        当日摘要并入跨日 store（幂等）
  - check_p0_alert:        P0 执行率连续 2 日 <100% → P1 级告警

测试覆盖要求：
  - 每个公开函数至少 1 条正向 + 1 条边界测试
  - finalize 状态转换覆盖全部合法路径（已执行/部分执行/放弃/错过/待填）+ 保留既有 final_result
  - calc 覆盖正/负/零（执行率 0% / 50% / 100% / 无触发 None）
  - check_p0_alert 覆盖连续 2 日 / 单日 / 无触发 / 100% 中断
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
    check_p0_alert,
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


# ============================================================
# parse_p0_signals
# ============================================================

class TestParseP0Signals:
    def test_single_signal_multiple_checkpoints(self):
        """单信号多检查点 → 1 条记录，checkpoints 全保留，trigger_time 取首次。"""
        md = _mk_p0_section([
            "| SIG-20260907-02 | 工商银行(601398) | 减仓（1/3锁利） | 11:05 | 触发时点 | 🚨已触发 | 待填 | — |",
            "| SIG-20260907-02 | 工商银行(601398) | 减仓（1/3锁利） | 11:05 | 13:30检查 | 🚨已触发未执行 | 待填 | — |",
            "| SIG-20260907-02 | 工商银行(601398) | 减仓（1/3锁利） | 11:05 | 14:45截止 | 已过期（未响应） | 错过 | 未执行（错过） |",
        ])
        records = parse_p0_signals(md, '2026-09-07')
        assert len(records) == 1
        rec = records[0]
        assert rec['signal_id'] == 'SIG-20260907-02'
        assert rec['name'] == '工商银行(601398)'
        assert rec['op_type'] == '减仓（1/3锁利）'
        assert rec['trigger_time'] == '11:05'
        assert len(rec['checkpoints']) == 3
        assert rec['checkpoints'][-1]['checkpoint'] == '14:45截止'
        assert rec['checkpoints'][-1]['user_action'] == '错过'

    def test_two_signals(self):
        """两条 P0 信号 → 2 条记录。"""
        md = _mk_p0_section([
            "| SIG-20260907-02 | 工商银行(601398) | 减仓（1/3锁利） | 11:05 | 触发时点 | 🚨已触发 | 待填 | — |",
            "| SIG-20260907-03 | 半导体ETF(512480) | 纪律解除评估 | 13:34 | 触发时点 | 🚨已触发 | 待填 | — |",
        ])
        records = parse_p0_signals(md, '2026-09-07')
        assert len(records) == 2
        ids = {r['signal_id'] for r in records}
        assert ids == {'SIG-20260907-02', 'SIG-20260907-03'}

    def test_empty_section(self):
        """空节（表头无数据行）→ 空列表。"""
        md = _mk_p0_section([])
        assert parse_p0_signals(md, '2026-09-07') == []

    def test_missing_section(self):
        """无 `## P0 执行追踪` 节 → 空列表（不抛异常）。"""
        md = "## 信号总表\n\n| 优先级 | 状态 |\n|---|:---:|\n| P0 | 待执行 |\n"
        assert parse_p0_signals(md, '2026-09-07') == []

    def test_strip_markdown_bold(self):
        """单元格中的 ** 加粗标记应被剥离（对齐信号总表解析惯例）。"""
        md = _mk_p0_section([
            "| SIG-20260907-02 | 工商银行(601398) | 减仓（1/3锁利） | 11:05 | 触发时点 | **🚨已触发** | **待填** | — |",
        ])
        records = parse_p0_signals(md, '2026-09-07')
        assert records[0]['checkpoints'][0]['status'] == '🚨已触发'
        assert records[0]['checkpoints'][0]['user_action'] == '待填'


# ============================================================
# finalize_p0_result
# ============================================================

def _mk_rec(signal_id: str, actions: list[str], existing_final: str = '') -> dict:
    """构造一条 P0 记录：actions = 各检查点用户操作；existing_final = 已有最终结果。"""
    return {
        'signal_id': signal_id,
        'name': '工商银行(601398)',
        'op_type': '减仓（1/3锁利）',
        'trigger_time': '11:05',
        'checkpoints': [
            {'checkpoint': f'c{i}', 'status': '🚨已触发未执行', 'user_action': a, 'final_result': ''}
            for i, a in enumerate(actions)
        ],
        'final_result': existing_final or '',
    }


class TestFinalizeP0Result:
    def test_executed(self):
        """用户操作=已执行 → 最终结果 已执行。"""
        recs = finalize_p0_result([_mk_rec('SIG-A', ['待填', '已执行'])])
        assert recs[0]['final_result'] == '已执行'

    def test_partial_executed_counts_as_executed(self):
        """用户操作=部分执行 → 最终结果 已执行（部分执行按已执行口径）。"""
        recs = finalize_p0_result([_mk_rec('SIG-B', ['部分执行'])])
        assert recs[0]['final_result'] == '已执行'

    def test_abandoned(self):
        """用户操作=放弃 → 最终结果 未执行（放弃）（显式放弃为合法终态）。"""
        recs = finalize_p0_result([_mk_rec('SIG-C', ['放弃'])])
        assert recs[0]['final_result'] == '未执行（放弃）'

    def test_missed(self):
        """用户操作=错过 → 最终结果 未执行（错过）。"""
        recs = finalize_p0_result([_mk_rec('SIG-D', ['错过'])])
        assert recs[0]['final_result'] == '未执行（错过）'

    def test_all_pending_is_missed(self):
        """全程 待填（触发未执行也未放弃）→ 未执行（错过）——零容忍，不做结果论豁免。"""
        recs = finalize_p0_result([_mk_rec('SIG-E', ['待填', '待填'])])
        assert recs[0]['final_result'] == '未执行（错过）'

    def test_preserves_existing_final_result(self):
        """已存在最终结果（如盘中已标 已过期）→ 保留，不覆盖。"""
        recs = finalize_p0_result([_mk_rec('SIG-F', ['错过'], existing_final='已过期（14:45截止未执行）')])
        assert recs[0]['final_result'] == '已过期（14:45截止未执行）'


# ============================================================
# calc_p0_execution_rate
# ============================================================

class TestCalcP0ExecutionRate:
    def test_zero_triggered_returns_none(self):
        """无 P0 触发 → rate=None（边界：0/0 无意义）。"""
        summary = calc_p0_execution_rate([])
        assert summary['triggered'] == 0
        assert summary['executed'] == 0
        assert summary['rate'] is None
        assert summary['unexecuted_ids'] == []

    def test_zero_rate(self):
        """1 触发 0 执行 → 0.0%。"""
        recs = finalize_p0_result([_mk_rec('SIG-20260907-02', ['待填', '错过'])])
        summary = calc_p0_execution_rate(recs)
        assert summary['triggered'] == 1
        assert summary['executed'] == 0
        assert summary['rate'] == 0.0
        assert 'SIG-20260907-02' in summary['unexecuted_ids']

    def test_half_rate(self):
        """2 触发 1 执行 → 50.0%。"""
        recs = finalize_p0_result([
            _mk_rec('SIG-A', ['已执行']),
            _mk_rec('SIG-B', ['错过']),
        ])
        summary = calc_p0_execution_rate(recs)
        assert summary['rate'] == 50.0
        assert summary['executed'] == 1
        assert summary['unexecuted_ids'] == ['SIG-B']

    def test_full_rate(self):
        """2 触发 2 执行 → 100.0%。"""
        recs = finalize_p0_result([
            _mk_rec('SIG-A', ['已执行']),
            _mk_rec('SIG-B', ['部分执行']),
        ])
        summary = calc_p0_execution_rate(recs)
        assert summary['rate'] == 100.0
        assert summary['unexecuted_ids'] == []

    def test_works_without_pre_finalize(self):
        """calc 内部自动 finalize——即使传入未 finalize 的原始记录也能正确计算。"""
        recs = [_mk_rec('SIG-A', ['待填', '错过'])]
        summary = calc_p0_execution_rate(recs)
        assert summary['rate'] == 0.0


# ============================================================
# merge_p0_daily
# ============================================================

def _mk_store() -> dict:
    return {'_schema': '1.0', '_updated': '', 'daily': {}}


class TestMergeP0Daily:
    def test_add_new_date(self):
        """新日期 → 并入 daily。"""
        store = merge_p0_daily(_mk_store(), '2026-09-08', {'triggered': 1, 'executed': 1, 'rate': 100.0})
        assert store['daily']['2026-09-08']['rate'] == 100.0
        assert store['_updated'] == '2026-09-08'

    def test_overwrite_existing_idempotent(self):
        """同日重复写入 → 覆盖而非累积（幂等），daily 键数不变。"""
        store = merge_p0_daily(_mk_store(), '2026-09-08', {'triggered': 1, 'executed': 0, 'rate': 0.0})
        store = merge_p0_daily(store, '2026-09-08', {'triggered': 1, 'executed': 1, 'rate': 100.0})
        assert len(store['daily']) == 1
        assert store['daily']['2026-09-08']['rate'] == 100.0

    def test_preserves_other_dates(self):
        """写入新日期不影响既有日期条目。"""
        store = merge_p0_daily(_mk_store(), '2026-09-07', {'triggered': 1, 'executed': 0, 'rate': 0.0})
        store = merge_p0_daily(store, '2026-09-08', {'triggered': 1, 'executed': 1, 'rate': 100.0})
        assert len(store['daily']) == 2
        assert store['daily']['2026-09-07']['rate'] == 0.0
        assert store['daily']['2026-09-08']['rate'] == 100.0


# ============================================================
# check_p0_alert
# ============================================================

class TestCheckP0Alert:
    def test_two_consecutive_below_100_alerts(self):
        """连续 2 日 <100% → P1 告警，streak=2。"""
        store = _mk_store()
        merge_p0_daily(store, '2026-09-07', {'triggered': 1, 'executed': 0, 'rate': 0.0})
        merge_p0_daily(store, '2026-09-08', {'triggered': 2, 'executed': 1, 'rate': 50.0})
        result = check_p0_alert(store)
        assert result['alert'] is True
        assert result['streak'] == 2

    def test_three_consecutive_below_100(self):
        """连续 3 日 <100% → 告警，streak=3。"""
        store = _mk_store()
        for d, r in [('2026-09-05', 0.0), ('2026-09-06', 50.0), ('2026-09-07', 0.0)]:
            merge_p0_daily(store, d, {'triggered': 1, 'executed': 0, 'rate': r})
        result = check_p0_alert(store)
        assert result['alert'] is True
        assert result['streak'] == 3

    def test_single_day_below_100_no_alert(self):
        """仅 1 日 <100% → 不告警，streak=1。"""
        store = _mk_store()
        merge_p0_daily(store, '2026-09-08', {'triggered': 1, 'executed': 0, 'rate': 0.0})
        result = check_p0_alert(store)
        assert result['alert'] is False
        assert result['streak'] == 1

    def test_100_percent_breaks_streak(self):
        """100% 日中断连续 <100% → 不告警；trailing streak=0（最近一日为 100%）。"""
        store = _mk_store()
        merge_p0_daily(store, '2026-09-07', {'triggered': 1, 'executed': 0, 'rate': 0.0})
        merge_p0_daily(store, '2026-09-08', {'triggered': 1, 'executed': 1, 'rate': 100.0})
        result = check_p0_alert(store)
        assert result['alert'] is False
        assert result['streak'] == 0
        assert result['max_streak'] == 1  # 历史 run 仍被记录，但最近一日 100% 不构成连续告警

    def test_no_triggered_days(self):
        """无任何触发日（全部 rate=None）→ 不告警，streak=0。"""
        store = _mk_store()
        merge_p0_daily(store, '2026-09-07', {'triggered': 0, 'executed': 0, 'rate': None})
        result = check_p0_alert(store)
        assert result['alert'] is False
        assert result['streak'] == 0


# ============================================================
# 端到端集成（parse → finalize → calc）
# ============================================================

class TestEndToEnd:
    def test_one_executed_one_missed_rate_50(self):
        """真实格式 md：1 条已执行 + 1 条错过 → 50.0%。"""
        md = _mk_p0_section([
            "| SIG-20260907-02 | 工商银行(601398) | 减仓（1/3锁利） | 11:05 | 触发时点 | 🚨已触发 | 待填 | — |",
            "| SIG-20260907-02 | 工商银行(601398) | 减仓（1/3锁利） | 11:05 | 13:30检查 | 🚨已触发未执行 | 已执行 | — |",
            "| SIG-20260907-03 | 半导体ETF(512480) | 纪律解除评估 | 13:34 | 触发时点 | 🚨已触发 | 错过 | — |",
        ])
        recs = parse_p0_signals(md, '2026-09-07')
        assert len(recs) == 2
        summary = calc_p0_execution_rate(recs)
        assert summary['triggered'] == 2
        assert summary['executed'] == 1
        assert summary['rate'] == 50.0
