"""
signal_tracking.py 新函数测试 — 信号文件解析 → 追踪库写入链路

BUG-XXX 修复验证：
  - parse_signal_markdown: 每日信号.md → 可追踪信号记录
  - merge_new_signals: 新信号去重并入追踪库
  - settle_due_signals: 到期信号结算
  - update_aggregation: aggregates 兼容字段

覆盖:
  - 只追踪已触发/已执行/部分执行信号，忽略已过期/已废弃
  - 不同列序格式兼容（14列/13列/8列）
  - 触发价提取（当前X/开盘X/裸数字）
  - 去重合并（幂等）
  - 到期结算（高紧急度2日/低紧急度到预期收益日）
"""

import json
import sys
from pathlib import Path

import pytest

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from signal_tracking import (
    parse_signal_markdown,
    merge_new_signals,
    settle_due_signals,
    update_aggregation,
)


# ============================================================
# 样本 markdown（模拟每日信号.md）
# ============================================================

def _mk_md(rows: list[str]) -> str:
    """用 14 列标准格式组装 信号总表 + 盘中验证记录 markdown"""
    header = (
        "| 优先级 | 标的 | 触发条件 | 操作类型 | 状态 | 方向 | 紧急度 | 升级条件 | 预期收益日 | 有效时段 | 仓位 | 操作来源 | 生成依据 | 信号ID |\n"
        "|:---:|------|----------|:------:|:---:|:---:|:---:|--------|:---:|----------|:---:|:------:|----------|--------|\n"
    )
    total = header + "\n".join(rows) + "\n"
    verify = (
        "## 盘中验证记录\n\n"
        "| 验证时间 | 信号ID | 标的 | 操作类型 | 仓位 | 当前状态 | 关键数据 | 判断 |\n"
        "|----------|--------|------|:------:|:---:|:------:|----------|------|\n"
        "| 10:00 | SIG-20260805-02 | 银行ETF(512800) | 减仓 | -1,000份 | 已触发 | 当前0.798 | 触发 |\n"
        "| 10:00 | SIG-20260805-04 | 黄金ETF(518880) | 减仓 | -500份 | 已触发 | 开盘8.482 | 触发 |\n"
    )
    return f"## 信号总表\n\n{total}\n---\n\n{verify}\n"


_SAMPLE_ROWS = [
    "| P0 | 银行ETF(512800) | 跌破0.80 | 减仓 | 已触发 | 卖出 | 高 | — | — | 全天 | -1,100份 | 早盘分析 | 测试 | SIG-20260805-02 |",
    "| P1 | 黄金ETF(518880) | 涨破8.50 | 减仓 | 已执行 | 卖出 | 高 | — | — | 全天 | -500份 | 早盘分析 | 测试 | SIG-20260805-04 |",
    "| P1 | 电网ETF(159326) | 冲高1.70 | 止盈 | 已过期 | 卖出 | 高 | — | — | 全天 | -1,000份 | 早盘分析 | 测试 | SIG-20260805-03 |",
    "| P2 | 创业板ETF(159915) | 突破 | 观察 | 已废弃 | 买入 | 低 | X | 2026-08-14 | 全天 | — | 早盘分析 | 测试 | SIG-20260805-05 |",
]


# ============================================================
# parse_signal_markdown
# ============================================================

class TestParseSignalMarkdown:
    def test_only_tracks_triggered(self):
        """只追踪已触发/已执行，忽略已过期/已废弃"""
        md = _mk_md(_SAMPLE_ROWS)
        records = parse_signal_markdown(md, '2026-08-05')
        ids = {r['signal_id'] for r in records}
        assert 'SIG-20260805-02' in ids  # 已触发
        assert 'SIG-20260805-04' in ids  # 已执行
        assert 'SIG-20260805-03' not in ids  # 已过期
        assert 'SIG-20260805-05' not in ids  # 已废弃

    def test_priority_urgency_mapping(self):
        md = _mk_md(_SAMPLE_ROWS)
        records = parse_signal_markdown(md, '2026-08-05')
        by_id = {r['signal_id']: r for r in records}
        assert by_id['SIG-20260805-02']['priority'] == 'P0'
        assert by_id['SIG-20260805-02']['urgency'] == 'high'
        assert by_id['SIG-20260805-04']['priority'] == 'P1'

    def test_ticker_extraction(self):
        md = _mk_md(_SAMPLE_ROWS)
        records = parse_signal_markdown(md, '2026-08-05')
        by_id = {r['signal_id']: r for r in records}
        assert by_id['SIG-20260805-02']['ticker'] == '512800'
        assert by_id['SIG-20260805-02']['name'] == '银行ETF'

    def test_trade_type_mapping(self):
        md = _mk_md(_SAMPLE_ROWS)
        records = parse_signal_markdown(md, '2026-08-05')
        by_id = {r['signal_id']: r for r in records}
        # 减仓 → sell
        assert by_id['SIG-20260805-02']['trade_type'] == 'sell'
        assert by_id['SIG-20260805-02']['direction'] == 'sell'

    def test_quantity_parsing(self):
        md = _mk_md(_SAMPLE_ROWS)
        records = parse_signal_markdown(md, '2026-08-05')
        by_id = {r['signal_id']: r for r in records}
        assert by_id['SIG-20260805-02']['shares'] == 1100

    def test_entry_price_from_verify(self):
        """从盘中验证记录提取触发价"""
        md = _mk_md(_SAMPLE_ROWS)
        records = parse_signal_markdown(md, '2026-08-05')
        by_id = {r['signal_id']: r for r in records}
        assert by_id['SIG-20260805-02']['entry_price'] == 0.798  # 当前0.798
        assert by_id['SIG-20260805-04']['entry_price'] == 8.482  # 开盘8.482

    def test_trigger_date(self):
        md = _mk_md(_SAMPLE_ROWS)
        records = parse_signal_markdown(md, '2026-08-05')
        assert all(r['trigger_date'] == '2026-08-05' for r in records)


class TestParseLegacyFormat:
    """旧格式兼容 — 8列（信号ID开头）"""

    def test_legacy_8col(self):
        md = (
            "## 信号总表\n\n"
            "| 信号ID | 优先级 | 标的 | 操作类型 | 触发条件 | 有效时段 | 状态 | 操作来源 |\n"
            "|--------|:---:|------|:------:|----------|----------|:---:|------|\n"
            "| SIG-20260720-01 | P0 | 银行ETF(512800) | 减仓 | 条件 | 全天 | 已执行 | 早盘分析 |\n"
            "| SIG-20260720-02 | P1 | 半导体ETF(512480) | 正T | 条件 | 全天 | 已过期 | 早盘分析 |\n"
        )
        records = parse_signal_markdown(md, '2026-07-20')
        ids = {r['signal_id'] for r in records}
        assert 'SIG-20260720-01' in ids
        assert 'SIG-20260720-02' not in ids


# ============================================================
# merge_new_signals
# ============================================================

class TestMergeNewSignals:
    def test_adds_new(self):
        md = _mk_md(_SAMPLE_ROWS)
        records = parse_signal_markdown(md, '2026-08-05')
        db = {'_schema': '1.0', 'signals': []}
        merge_new_signals(db, records)
        assert len(db['signals']) == 2

    def test_idempotent_dedup(self):
        """重复合并不产生重复记录"""
        md = _mk_md(_SAMPLE_ROWS)
        records = parse_signal_markdown(md, '2026-08-05')
        db = {'_schema': '1.0', 'signals': []}
        merge_new_signals(db, records)
        merge_new_signals(db, records)  # 再次合并
        assert len(db['signals']) == 2

    def test_updates_timestamp(self):
        md = _mk_md(_SAMPLE_ROWS)
        records = parse_signal_markdown(md, '2026-08-05')
        db = {'_schema': '1.0', 'signals': []}
        merge_new_signals(db, records)
        assert db['_updated']

    def test_keeps_existing(self):
        """已有信号保留，不因新合并丢失"""
        existing = [{'signal_id': 'SIG-OLD-01', 'ticker': '510300'}]
        md = _mk_md(_SAMPLE_ROWS)
        records = parse_signal_markdown(md, '2026-08-05')
        db = {'_schema': '1.0', 'signals': existing}
        merge_new_signals(db, records)
        assert len(db['signals']) == 3
        assert db['signals'][0]['signal_id'] == 'SIG-OLD-01'


# ============================================================
# settle_due_signals
# ============================================================

class TestSettleDueSignals:
    def test_high_urgency_settles(self):
        """高紧急度：触发超2日 → 结算"""
        db = {'_schema': '1.0', 'signals': [{
            'signal_id': 'SIG-01', 'ticker': '512800', 'trade_type': 'buy',
            'urgency': 'high', 'entry_price': 1.00, 'shares': 1000,
            'trigger_date': '2026-07-27', 'status': 'triggered',
        }]}
        settle_due_signals(db, {'512800': 1.10}, '2026-07-29')
        assert db['signals'][0]['status'] == 'settled'
        assert db['signals'][0]['pnl'] == pytest.approx(100.0)

    def test_low_urgency_at_expiry(self):
        """低紧急度：到预期收益日 → 结算"""
        db = {'_schema': '1.0', 'signals': [{
            'signal_id': 'SIG-02', 'ticker': '518880', 'trade_type': 'sell',
            'urgency': 'low', 'entry_price': 8.00, 'cost_basis': 7.50, 'shares': 500,
            'trigger_date': '2026-07-27', 'expected_return_date': '2026-08-03',
            'status': 'executed',
        }]}
        settle_due_signals(db, {'518880': 8.20}, '2026-08-04')
        sig = db['signals'][0]
        assert sig['status'] == 'settled'
        # 卖出: P&L=(卖价8.00-成本7.50)*500 = 250; 避免损失=(8.00-8.20)*500 = -100
        assert sig['pnl'] == pytest.approx(250.0)
        assert sig['avoided_loss'] == pytest.approx(-100.0)

    def test_not_due_not_settled(self):
        """未到期 → 不结算"""
        db = {'_schema': '1.0', 'signals': [{
            'signal_id': 'SIG-03', 'ticker': '512800', 'trade_type': 'buy',
            'urgency': 'high', 'entry_price': 1.00, 'shares': 1000,
            'trigger_date': '2026-07-28', 'status': 'triggered',
        }]}
        settle_due_signals(db, {'512800': 1.10}, '2026-07-28')
        assert db['signals'][0]['status'] == 'triggered'

    def test_missing_price_not_settled(self):
        """无现价 → 不结算（等待下次）"""
        db = {'_schema': '1.0', 'signals': [{
            'signal_id': 'SIG-04', 'ticker': '999999', 'trade_type': 'buy',
            'urgency': 'high', 'entry_price': 1.00, 'shares': 1000,
            'trigger_date': '2026-07-27', 'status': 'triggered',
        }]}
        settle_due_signals(db, {}, '2026-07-29')
        assert db['signals'][0]['status'] == 'triggered'


# ============================================================
# update_aggregation → aggregates 兼容
# ============================================================

class TestAggregatesCompat:
    def test_aggregates_fields_present(self):
        md = _mk_md(_SAMPLE_ROWS)
        records = parse_signal_markdown(md, '2026-08-05')
        db = {'_schema': '1.0', 'signals': []}
        merge_new_signals(db, records)
        db = update_aggregation(db)
        agg = db['aggregates']
        assert 'total_signals_tracked' in agg
        assert 'win_rate' in agg
        assert 'by_urgency' in agg
        assert 'by_priority' in agg

    def test_aggregates_counts(self):
        md = _mk_md(_SAMPLE_ROWS)
        records = parse_signal_markdown(md, '2026-08-05')
        db = {'_schema': '1.0', 'signals': []}
        merge_new_signals(db, records)
        db = update_aggregation(db)
        assert db['aggregates']['total_signals_tracked'] == 2
        # 2条 sell 高紧急度
        assert db['aggregates']['by_urgency']['high']['count'] == 2

    def test_aggregation_also_present(self):
        """原 aggregation 字段仍保留（向后兼容）"""
        md = _mk_md(_SAMPLE_ROWS)
        records = parse_signal_markdown(md, '2026-08-05')
        db = {'_schema': '1.0', 'signals': []}
        merge_new_signals(db, records)
        db = update_aggregation(db)
        assert 'aggregation' in db
        assert db['aggregation']['by_urgency']['high']['count'] == 2


# ============================================================
# 新列解析（v2.0 信号质量闭环）
# ============================================================

_NEW_COL_HEADER = (
    "| 优先级 | 标的 | 触发条件 | 操作类型 | 状态 | 方向 | 紧急度 | 预期触发率 | 目标/止损 | 有效时段 | 仓位 | 信号ID |\n"
    "|:---:|------|----------|:------:|:---:|:---:|:---:|:---:|--------|:---:|:---:|--------|\n"
)

def _mk_new_md(rows: list[str]) -> str:
    return f"## 信号总表\n\n{_NEW_COL_HEADER + chr(10).join(rows)}\n"


class TestParseNewColumns:
    def test_expected_trigger_rate(self):
        md = _mk_new_md([
            "| P1 | 电网ETF(159326) | 站上1.70 | 正T | 已触发 | 买入 | 高 | 40 | 目标+3%/止损-2% | 10:30-11:30 | 1,975份 | SIG-20260826-06 |",
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        assert records[0]['expected_trigger_rate'] == 40.0

    def test_expected_trigger_rate_dash(self):
        """P0 预期触发率为 — → None（覆盖 —→None 解析路径）"""
        md = _mk_new_md([
            "| P0 | 全持仓ETF(510300) | 普跌否决 | 风控 | 已触发 | 卖出 | 高 | — | — | 9:30-10:00 | 0 | SIG-20260826-01 |",
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        assert len(records) == 1  # 已触发需追踪
        rec = records[0]
        assert rec['priority'] == 'P0'
        assert rec['expected_trigger_rate'] is None
        assert rec['target_pct'] is None
        assert rec['stop_pct'] is None
        assert rec['target_price'] is None
        assert rec['stop_price'] is None

    def test_target_pct_parsing(self):
        md = _mk_new_md([
            "| P1 | 电网ETF(159326) | 站上1.70 | 正T | 已触发 | 买入 | 高 | 40 | 目标+3%/止损-2% | 10:30-11:30 | 1,975份 | SIG-20260826-06 |",
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        rec = records[0]
        assert rec['target_pct'] == 3.0
        assert rec['stop_pct'] == -2.0
        assert rec['target_price'] is None
        assert rec['stop_price'] is None

    def test_target_price_parsing(self):
        """显式价格格式"""
        md = _mk_new_md([
            "| P1 | 电网ETF(159326) | 站上1.70 | 正T | 已执行 | 买入 | 高 | 40 | 目标1.75/止损1.66 | 10:30-11:30 | 1,975份 | SIG-20260826-06 |",
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        rec = records[0]
        assert rec['target_price'] == 1.75
        assert rec['stop_price'] == 1.66
        assert rec['target_pct'] is None

    def test_target_only(self):
        """只有目标无止损"""
        md = _mk_new_md([
            "| P1 | 农业ETF(159825) | 放量突破0.74 | 建仓 | 已触发 | 买入 | 低 | 30 | 目标0.76 | 10:30后 | 观察 | SIG-20260826-05 |",
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        rec = records[0]
        assert rec['target_price'] == 0.76
        assert rec['stop_price'] is None
