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
    parse_signal_rows_all,
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
        """旧 8 列格式无仓位列 → 份额=0，不可追踪收益"""
        md = (
            "## 信号总表\n\n"
            "| 信号ID | 优先级 | 标的 | 操作类型 | 触发条件 | 有效时段 | 状态 | 操作来源 |\n"
            "|--------|:---:|------|:------:|----------|----------|:---:|------|\n"
            "| SIG-20260720-01 | P0 | 银行ETF(512800) | 减仓 | 条件 | 全天 | 已执行 | 早盘分析 |\n"
            "| SIG-20260720-02 | P1 | 半导体ETF(512480) | 正T | 条件 | 全天 | 已过期 | 早盘分析 |\n"
        )
        records = parse_signal_markdown(md, '2026-07-20')
        # 旧格式无 仓位 列 → shares=0，无法计算收益，不追踪
        assert records == []


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
# settle_due_signals（目标价结算模式：hit/stopped/miss + T+3 窗口）
# ============================================================

class TestSettleDueSignals:
    def test_t3_expiry_miss(self):
        """买入信号 T+3 到期未达目标 → 按 T+3 收盘结算，outcome=miss"""
        db = {'_schema': '1.0', 'signals': [{
            'signal_id': 'SIG-01', 'ticker': '512800', 'trade_type': 'buy',
            'urgency': 'high', 'entry_price': 1.00, 'shares': 1000,
            'target_price': 1.10, 'trigger_date': '2026-07-27', 'status': 'triggered',
        }]}
        hist = {'512800': {'2026-07-27': 1.02, '2026-07-28': 1.04, '2026-07-29': 1.03}}
        settle_due_signals(db, hist, '2026-07-29')
        sig = db['signals'][0]
        assert sig['status'] == 'settled'
        assert sig['outcome'] == 'miss'
        assert sig['settle_price'] == pytest.approx(1.03)  # T+3 收盘
        assert sig['pnl'] == pytest.approx(30.0)
        assert sig['holding_days'] == 3

    def test_t3_target_hit(self):
        """窗口内第2天收盘达到目标 → 达标，按目标价结算，持有天数=2"""
        db = {'_schema': '1.0', 'signals': [{
            'signal_id': 'SIG-02', 'ticker': '512800', 'trade_type': 'buy',
            'urgency': 'high', 'entry_price': 1.00, 'shares': 1000,
            'target_price': 1.10, 'trigger_date': '2026-07-27', 'status': 'triggered',
        }]}
        hist = {'512800': {'2026-07-27': 1.02, '2026-07-28': 1.11, '2026-07-29': 1.05}}
        settle_due_signals(db, hist, '2026-07-29')
        sig = db['signals'][0]
        assert sig['outcome'] == 'hit'
        assert sig['settle_price'] == pytest.approx(1.10)
        assert sig['pnl'] == pytest.approx(100.0)
        assert sig['holding_days'] == 2

    def test_t3_stop_hit(self):
        """窗口内触发止损 → outcome=stopped，按止损价结算"""
        db = {'_schema': '1.0', 'signals': [{
            'signal_id': 'SIG-03', 'ticker': '512800', 'trade_type': 'buy',
            'urgency': 'high', 'entry_price': 1.00, 'shares': 1000,
            'target_price': 1.10, 'stop_price': 0.98,
            'trigger_date': '2026-07-27', 'status': 'triggered',
        }]}
        hist = {'512800': {'2026-07-27': 0.97, '2026-07-28': 1.02, '2026-07-29': 1.05}}
        settle_due_signals(db, hist, '2026-07-29')
        sig = db['signals'][0]
        assert sig['outcome'] == 'stopped'
        assert sig['settle_price'] == pytest.approx(0.98)
        assert sig['pnl'] == pytest.approx(-20.0)
        assert sig['holding_days'] == 1

    def test_t3_target_pct_resolve(self):
        """只有 target_pct 时由触发价换算目标价"""
        db = {'_schema': '1.0', 'signals': [{
            'signal_id': 'SIG-04', 'ticker': '518880', 'trade_type': 'buy',
            'urgency': 'high', 'entry_price': 9.00, 'shares': 500,
            'target_pct': 3.0, 'trigger_date': '2026-07-27', 'status': 'triggered',
        }]}
        hist = {'518880': {'2026-07-27': 9.10, '2026-07-28': 9.30, '2026-07-29': 9.20}}  # 9.30 >= 9.27
        settle_due_signals(db, hist, '2026-07-29')
        sig = db['signals'][0]
        assert sig['outcome'] == 'hit'
        assert sig['settle_price'] == pytest.approx(9.27)  # 9.00 * 1.03
        assert sig['pnl'] == pytest.approx(135.0)

    def test_sell_signal_direction(self):
        """卖出信号：窗口内收盘价 <= 目标价 → 达标（卖对了）"""
        db = {'_schema': '1.0', 'signals': [{
            'signal_id': 'SIG-05', 'ticker': '512800', 'trade_type': 'sell',
            'urgency': 'high', 'entry_price': 1.00, 'cost_basis': 0.90, 'shares': 1000,
            'target_price': 0.95, 'trigger_date': '2026-07-27', 'status': 'triggered',
        }]}
        hist = {'512800': {'2026-07-27': 0.99, '2026-07-28': 0.94, '2026-07-29': 0.96}}
        settle_due_signals(db, hist, '2026-07-29')
        sig = db['signals'][0]
        assert sig['outcome'] == 'hit'
        assert sig['pnl'] == pytest.approx(100.0)  # (1.00-0.90)*1000 卖出本身
        assert sig['avoided_loss'] == pytest.approx(50.0)  # (1.00-0.95)*1000

    def test_not_due_not_settled(self):
        """未到 T+3 → 不结算"""
        db = {'_schema': '1.0', 'signals': [{
            'signal_id': 'SIG-06', 'ticker': '512800', 'trade_type': 'buy',
            'urgency': 'high', 'entry_price': 1.00, 'shares': 1000,
            'target_price': 1.10, 'trigger_date': '2026-07-28', 'status': 'triggered',
        }]}
        hist = {'512800': {'2026-07-28': 1.02, '2026-07-29': 1.03, '2026-07-30': 1.04}}
        settle_due_signals(db, hist, '2026-07-28')  # 今天是触发日
        assert db['signals'][0]['status'] == 'triggered'

    def test_no_target_price_falls_back_t3(self):
        """无目标价 → 退化为 T+3 收盘结算"""
        db = {'_schema': '1.0', 'signals': [{
            'signal_id': 'SIG-07', 'ticker': '512800', 'trade_type': 'buy',
            'urgency': 'high', 'entry_price': 1.00, 'shares': 1000,
            'trigger_date': '2026-07-27', 'status': 'triggered',
        }]}
        hist = {'512800': {'2026-07-27': 1.02, '2026-07-28': 1.04, '2026-07-29': 1.03}}
        settle_due_signals(db, hist, '2026-07-29')
        sig = db['signals'][0]
        assert sig['outcome'] == 'miss'
        assert sig['settle_price'] == pytest.approx(1.03)

    def test_missing_entry_price_not_settled(self):
        """入场价缺失 → 不结算（防幽灵P&L）"""
        db = {'_schema': '1.0', 'signals': [{
            'signal_id': 'SIG-08', 'ticker': '512800', 'trade_type': 'buy',
            'urgency': 'high', 'entry_price': None, 'shares': 1000,
            'target_price': 1.10, 'trigger_date': '2026-07-27', 'status': 'triggered',
        }]}
        hist = {'512800': {'2026-07-27': 1.02, '2026-07-28': 1.11, '2026-07-29': 1.05}}
        settle_due_signals(db, hist, '2026-07-29')
        assert db['signals'][0]['status'] == 'triggered'

    def test_p0_not_settled(self):
        """P0 风控信号不结算（纪律无P&L）"""
        db = {'_schema': '1.0', 'signals': [{
            'signal_id': 'SIG-09', 'ticker': '512800', 'trade_type': 'sell',
            'urgency': 'high', 'priority': 'P0', 'entry_price': 1.00,
            'cost_basis': 0.90, 'shares': 1000, 'target_price': 0.95,
            'trigger_date': '2026-07-27', 'status': 'triggered',
        }]}
        hist = {'512800': {'2026-07-27': 0.99, '2026-07-28': 0.94, '2026-07-29': 0.96}}
        settle_due_signals(db, hist, '2026-07-29')
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

_VERIFY_HEADER = (
    "| 验证时间 | 信号ID | 标的 | 操作类型 | 仓位 | 当前状态 | 关键数据 | 判断 |\n"
    "|----------|--------|------|:------:|:---:|:------:|----------|------|\n"
)

def _vrow(signal_id: str, name: str, op: str, qty: str, key_data: str,
          status: str = '已触发') -> str:
    """组装一条盘中验证记录行（真实格式：关键数据以 '现价X.XXX' 开头）"""
    return f"| 10:00 | {signal_id} | {name} | {op} | {qty} | {status} | {key_data} | 触发 |"

def _mk_new_md(rows: list[str], verify: list[str] | None = None) -> str:
    md = f"## 信号总表\n\n{_NEW_COL_HEADER + chr(10).join(rows)}\n"
    if verify:
        md += f"\n## 盘中验证记录\n\n{_VERIFY_HEADER + chr(10).join(verify)}\n"
    return md


class TestParseMarkdownBoldStatus:
    """BUG-012: 盘中信号总表状态列带 markdown 加粗（**已触发**）时解析失败"""

    def test_bold_triggered_status_parsed(self):
        """**已触发** → 正确解析为已触发信号"""
        md = _mk_new_md([
            "| P1 | 电网ETF(159326) | 站上1.70 | 正T | **已触发** | 买入 | 高 | 40 | 目标+3%/止损-2% | 10:30-11:30 | 1,975份 | SIG-20260826-06 |",
        ], verify=[
            _vrow('SIG-20260826-06', '电网ETF(159326)', '正T', '1,975份', '现价1.70'),
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        assert len(records) == 1
        assert records[0]['signal_id'] == 'SIG-20260826-06'
        assert records[0]['status'] == 'triggered'
        assert records[0]['entry_price'] == pytest.approx(1.70)

    def test_bold_executed_status_parsed(self):
        """**已执行** → 正确解析"""
        md = _mk_new_md([
            "| P1 | 电网ETF(159326) | 站上1.70 | 正T | **已执行** | 买入 | 高 | 40 | 目标+3%/止损-2% | 10:30-11:30 | 1,975份 | SIG-20260826-06 |",
        ], verify=[
            _vrow('SIG-20260826-06', '电网ETF(159326)', '正T', '1,975份', '现价1.70'),
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        assert len(records) == 1
        assert records[0]['status'] == 'triggered'

    def test_bold_expired_status_not_tracked(self):
        """**已过期** → 不追踪（与纯文本行为一致）"""
        md = _mk_new_md([
            "| P1 | 电网ETF(159326) | 站上1.70 | 正T | **已过期** | 买入 | 高 | 40 | 目标+3%/止损-2% | 10:30-11:30 | 1,975份 | SIG-20260826-06 |",
        ], verify=[
            _vrow('SIG-20260826-06', '电网ETF(159326)', '正T', '1,975份', '现价1.70'),
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        assert records == []


class TestParseNewColumns:
    def test_expected_trigger_rate(self):
        md = _mk_new_md([
            "| P1 | 电网ETF(159326) | 站上1.70 | 正T | 已触发 | 买入 | 高 | 40 | 目标+3%/止损-2% | 10:30-11:30 | 1,975份 | SIG-20260826-06 |",
        ], verify=[
            _vrow('SIG-20260826-06', '电网ETF(159326)', '正T', '1,975份', '现价1.70'),
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        assert records[0]['expected_trigger_rate'] == 40.0

    def test_expected_trigger_rate_pct_form(self):
        """预期触发率 '40%' 格式 → 40.0"""
        md = _mk_new_md([
            "| P1 | 电网ETF(159326) | 站上1.70 | 正T | 已触发 | 买入 | 高 | 40% | 目标+3%/止损-2% | 10:30-11:30 | 1,975份 | SIG-20260826-06 |",
        ], verify=[
            _vrow('SIG-20260826-06', '电网ETF(159326)', '正T', '1,975份', '现价1.70'),
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        assert records[0]['expected_trigger_rate'] == 40.0

    def test_expected_trigger_rate_dash(self):
        """预期触发率为 — → None（覆盖 —→None 解析路径；P0 带价+份额仍入库）"""
        md = _mk_new_md([
            "| P0 | 全持仓ETF(510300) | 普跌否决 | 风控 | 已触发 | 卖出 | 高 | — | — | 9:30-10:00 | 1,000份 | SIG-20260826-01 |",
        ], verify=[
            _vrow('SIG-20260826-01', '全持仓ETF(510300)', '风控', '1,000份', '现价1.234'),
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        assert len(records) == 1
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
        ], verify=[
            _vrow('SIG-20260826-06', '电网ETF(159326)', '正T', '1,975份', '现价1.70'),
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
        ], verify=[
            _vrow('SIG-20260826-06', '电网ETF(159326)', '正T', '1,975份', '现价1.70', status='已执行'),
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        rec = records[0]
        assert rec['target_price'] == 1.75
        assert rec['stop_price'] == 1.66
        assert rec['target_pct'] is None

    def test_target_only(self):
        """只有目标无止损"""
        md = _mk_new_md([
            "| P1 | 农业ETF(159825) | 放量突破0.74 | 建仓 | 已触发 | 买入 | 低 | 30 | 目标0.76 | 10:30后 | 1,000份 | SIG-20260826-05 |",
        ], verify=[
            _vrow('SIG-20260826-05', '农业ETF(159825)', '建仓', '1,000份', '现价0.74'),
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        rec = records[0]
        assert rec['target_price'] == 0.76
        assert rec['stop_price'] is None


# ============================================================
# 收益追踪过滤（2026-08-26 优化：无入场价/无份额的信号不追踪收益）
# ============================================================

class TestReturnTrackableFilter:
    """任务4（2026-09-14）：信号只要 份额>0 即入库；entry_price 不再作为硬门槛
    （买入价由复盘"录入交易"回填，触发价由盘中写云库；盘中验证记录若存在仍提取为触发价）。"""

    def test_no_entry_price_not_tracked(self):
        """已触发且无任何价格来源 → 仍入库（份额>0 即可；entry_price 待回填）"""
        md = _mk_new_md([
            "| P1 | 电网ETF(159326) | 站上1.70 | 正T | 已触发 | 买入 | 高 | 40 | 目标+3%/止损-2% | 10:30-11:30 | 1,975份 | SIG-20260826-06 |",
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        # 任务4 变更：不再因缺 entry_price 丢弃信号；只要求份额>0
        assert len(records) == 1
        assert records[0]['entry_price'] is None
        assert records[0]['shares'] == 1975

    def test_no_shares_not_tracked(self):
        """有价格但仓位=观察(0份) → 不追踪（无实际持仓，P&L 恒为 0）"""
        md = _mk_new_md([
            "| P2 | 有色512400 | 放量企稳 | 企稳观察 | 已触发 | 观察 | 低 | — | — | 10:30后 | 观察 | SIG-20260826-08 |",
        ], verify=[
            _vrow('SIG-20260826-08', '有色512400', '企稳观察', '观察', '现价1.972(+4.01%)量比2.40'),
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        assert records == []

    def test_trackable_signal_kept(self):
        """有价格 + 份额 → 正常追踪（entry_price 取自盘中验证记录）"""
        md = _mk_new_md([
            "| P1 | 电网ETF(159326) | 站上1.70 | 正T | 已触发 | 买入 | 高 | 40 | 目标+3%/止损-2% | 10:30-11:30 | 1,975份 | SIG-20260826-06 |",
        ], verify=[
            _vrow('SIG-20260826-06', '电网ETF(159326)', '正T', '1,975份', '现价1.708(+0.7%)量比1.2'),
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        assert len(records) == 1
        assert records[0]['entry_price'] == pytest.approx(1.708)
        assert records[0]['shares'] == 1975

    def test_xianjia_price_extraction_priority(self):
        """真实 现价X.XXX 格式被提取（当前→现价→开盘→裸数字 优先级）"""
        md = _mk_new_md([
            "| P1 | 电网ETF(159326) | 站上1.70 | 正T | 已触发 | 买入 | 高 | 40 | 目标+3%/止损-2% | 10:30-11:30 | 1,975份 | SIG-20260826-06 |",
        ], verify=[
            _vrow('SIG-20260826-06', '电网ETF(159326)', '正T', '1,975份', '现价9.553(+0.21%)>9.20 ✅，量比0.89缩量'),
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        assert len(records) == 1
        assert records[0]['entry_price'] == pytest.approx(9.553)


# ============================================================
# parse_signal_rows_all（2026-09-15 BUG-FIX：早盘信号云库入库）
# ============================================================

class TestParseSignalRowsAll:
    def test_includes_pending_rows(self):
        """未触发/已触发/已执行/已过期 都要解析出来（云库入库含全部状态）——
        与 parse_signal_markdown 只追已触发不同（v3.0：已过期→expired 也入云库，
        供盘中状态变更后同步 Dashboard）。"""
        md = _mk_md(_SAMPLE_ROWS)
        records = parse_signal_rows_all(md, '2026-08-05')
        by_id = {r['signal_id']: r for r in records}
        # _SAMPLE_ROWS: 02=已触发, 04=已执行, 03=已过期, 05=已废弃(跳过)
        assert 'SIG-20260805-02' in by_id
        assert 'SIG-20260805-04' in by_id
        assert by_id['SIG-20260805-03']['status'] == 'expired'  # v3.0 已过期也入库
        assert 'SIG-20260805-05' not in by_id   # 已废弃不入库

    def test_status_mapping_en(self):
        """中文状态 → 英文内部值（open/triggered/executed）"""
        md = _mk_new_md([
            "| P0 | 黄金ETF(518880) | 跌破8.80 | 减仓 | 待执行 | 卖出 | 高 | 40 | 目标8.5/止损8.9 | 09:30-14:30 | 20% | SIG-20260915-01 |",
            "| P1 | 农业ETF(159825) | 回踩0.72 | 建仓 | 已触发 | 买入 | 低 | 50 | 目标0.78/止损0.70 | 全天 | 1/4 | SIG-20260915-03 |",
        ])
        records = parse_signal_rows_all(md, '2026-09-15')
        by_id = {r['signal_id']: r for r in records}
        assert by_id['SIG-20260915-01']['status'] == 'open'
        assert by_id['SIG-20260915-03']['status'] == 'triggered'
        assert all(r['trigger_date'] == '2026-09-15' for r in records)
        assert all(r['source'] == 'morning_analysis' for r in records)

    def test_pending_row_cloud_mapping(self):
        """待执行信号 to_row 后 signal_date 正确落云库列（trigger_date→signal_date）"""
        from signal_tracking_cloud import to_row
        md = _mk_new_md([
            "| P0 | 黄金ETF(518880) | 跌破8.80 | 减仓 | 待执行 | 卖出 | 高 | 40 | 目标8.5/止损8.9 | 09:30-14:30 | 20% | SIG-20260915-01 |",
        ])
        records = parse_signal_rows_all(md, '2026-09-15')
        row = to_row(records[0])
        assert row['signal_date'] == '2026-09-15'
        assert row['status'] == 'open'
        assert row['priority'] == 'P0'
        assert row['source'] == 'morning_analysis'


# ============================================================
# v3.0 14 列信号表（交易价/目标价/止损价）—— 2026-09 用户需求
# ============================================================

_V3_HEADER = (
    "| 优先级 | 标的 | 触发条件 | 操作类型 | 状态 | 方向 | 紧急度 | 预期触发率 | 交易价 | 目标价 | 止损价 | 有效时段 | 仓位 | 信号ID |\n"
    "|:---:|------|----------|:------:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|----------|:---:|--------|\n"
)


def _mk_v3_md(rows: list[str], verify: list[str] | None = None) -> str:
    md = f"## 信号总表\n\n{_V3_HEADER + chr(10).join(rows)}\n"
    if verify:
        md += f"\n## 盘中验证记录\n\n{_VERIFY_HEADER + chr(10).join(verify)}\n"
    return md


class TestParseV3Format:
    """v3.0：交易价/目标价/止损价 三列（买入三列必填，卖出仅交易价）"""

    def test_buy_signal_three_prices(self):
        """买入信号：交易价/目标价/止损价 全部提取"""
        md = _mk_v3_md([
            "| P1 | 电网ETF(159326) | 站上1.70 | 正T | 已触发 | 买入 | 高 | 40 | 1.70 | 1.75 | 1.66 | 10:30-11:30 | 1,975份 | SIG-20260826-06 |",
        ], verify=[
            _vrow('SIG-20260826-06', '电网ETF(159326)', '正T', '1,975份', '现价1.70'),
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        assert len(records) == 1
        rec = records[0]
        assert rec['trade_price'] == pytest.approx(1.70)
        assert rec['target_price'] == pytest.approx(1.75)
        assert rec['stop_price'] == pytest.approx(1.66)

    def test_sell_signal_only_trade_price(self):
        """卖出信号：仅交易价，目标价/止损价为 —"""
        md = _mk_v3_md([
            "| P1 | 黄金ETF(518880) | 跌破8.80 | 减仓 | 已触发 | 卖出 | 高 | 40 | 8.80 | — | — | 09:30-14:30 | -500份 | SIG-20260826-07 |",
        ], verify=[
            _vrow('SIG-20260826-07', '黄金ETF(518880)', '减仓', '-500份', '现价8.79'),
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        assert len(records) == 1
        rec = records[0]
        assert rec['trade_price'] == pytest.approx(8.80)
        assert rec['target_price'] is None
        assert rec['stop_price'] is None

    def test_target_stop_pct_in_v3(self):
        """目标价/止损价 支持百分比写法（+3% / -2%）"""
        md = _mk_v3_md([
            "| P1 | 电网ETF(159326) | 站上1.70 | 正T | 已触发 | 买入 | 高 | 40 | 1.70 | +3% | -2% | 10:30-11:30 | 1,975份 | SIG-20260826-06 |",
        ], verify=[
            _vrow('SIG-20260826-06', '电网ETF(159326)', '正T', '1,975份', '现价1.70'),
        ])
        records = parse_signal_markdown(md, '2026-08-26')
        rec = records[0]
        assert rec['trade_price'] == pytest.approx(1.70)
        assert rec['target_pct'] == 3.0
        assert rec['stop_pct'] == -2.0
        assert rec['target_price'] is None

    def test_v3_status_untouched_open(self):
        """未触发（初始状态）→ open；已过期 → expired（parse_signal_rows_all 含过期行）"""
        md = _mk_v3_md([
            "| P0 | 黄金ETF(518880) | 跌破8.80 | 减仓 | 未触发 | 卖出 | 高 | 40 | 8.80 | — | — | 09:30-14:30 | 20% | SIG-20260916-01 |",
            "| P1 | 农业ETF(159825) | 回踩0.72 | 建仓 | 已触发 | 买入 | 低 | 50 | 0.72 | 0.78 | 0.70 | 全天 | 1/4 | SIG-20260916-03 |",
            "| P1 | 通信ETF(515880) | 站上0.68 | 建仓 | 已过期 | 买入 | 高 | 30 | 0.68 | 0.71 | 0.66 | 全天 | 1/4 | SIG-20260916-04 |",
        ])
        records = parse_signal_rows_all(md, '2026-09-16')
        by_id = {r['signal_id']: r for r in records}
        assert by_id['SIG-20260916-01']['status'] == 'open'
        assert by_id['SIG-20260916-03']['status'] == 'triggered'
        assert by_id['SIG-20260916-04']['status'] == 'expired'
        assert by_id['SIG-20260916-04']['trade_price'] == pytest.approx(0.68)

    def test_v3_trade_price_in_cloud_row(self):
        """v3 trade_price 经 to_row 落云库 trade_price 列"""
        from signal_tracking_cloud import to_row
        md = _mk_v3_md([
            "| P1 | 电网ETF(159326) | 站上1.70 | 正T | 已触发 | 买入 | 高 | 40 | 1.70 | 1.75 | 1.66 | 10:30-11:30 | 1,975份 | SIG-20260826-06 |",
        ])
        records = parse_signal_rows_all(md, '2026-08-26')
        row = to_row(records[0])
        assert row['trade_price'] == pytest.approx(1.70)
        assert row['target_price'] == pytest.approx(1.75)
        assert row['stop_price'] == pytest.approx(1.66)


class TestStatusEnum:
    """状态枚举：expired 加入；未触发 → open"""

    def test_enum_contains_expired(self):
        from signal_tracking import ENUM_STATUS
        assert 'expired' in ENUM_STATUS
        assert 'open' in ENUM_STATUS

    def test_assert_accepts_expired_and_trade_price(self):
        from signal_tracking import assert_valid_signal_record
        rec = assert_valid_signal_record({
            'signal_id': 'SIG-20260916-01', 'status': 'expired',
            'trade_price': 0.68, 'target_price': 0.71,
        })
        assert rec['status'] == 'expired'
        assert rec['trade_price'] == 0.68

    def test_assert_rejects_invalid_status(self):
        from signal_tracking import assert_valid_signal_record
        import pytest as _pytest
        with _pytest.raises(ValueError):
            assert_valid_signal_record({'signal_id': 'SIG-1', 'status': 'bogus'})


class TestResolveTargetPriceFallback:
    """目标价换算基准：entry → trigger → trade_price 兜底"""

    def test_pct_resolves_from_trade_price(self):
        from signal_tracking import _resolve_target_price
        target, stop = _resolve_target_price({
            'trade_price': 1.70, 'target_pct': 3.0, 'stop_pct': -2.0,
        })
        assert target == pytest.approx(1.751)
        assert stop == pytest.approx(1.666)

    def test_explicit_price_wins(self):
        from signal_tracking import _resolve_target_price
        target, stop = _resolve_target_price({
            'trade_price': 1.70, 'target_price': 1.75, 'target_pct': 5.0,
            'stop_price': 1.66, 'stop_pct': -1.0,
        })
        assert target == pytest.approx(1.75)
        assert stop == pytest.approx(1.66)


# ============================================================
# parse_trigger_records_from_md — 信号触发记录节解析（2026-09-24 新增）
# 早盘生成信号时预填"第一条生成记录"（内容=生成原因），盘中触发时追加"已触发"记录，
# 本函数把 `## 信号触发记录` 节解析为 cloud_upsert_trigger_records 可用的记录列表。
# ============================================================

def _mk_trigger_md(rows: list[str]) -> str:
    header = (
        "## 信号触发记录\n\n"
        "| 触发时间 | 信号ID | 优先级 | 标的 | 操作类型 | 触发条件摘要 | 当前状态 | 建议操作 | 用户操作 |\n"
        "|----------|--------|:---:|------|:------:|-------------|:------:|----------|:------:|\n"
    )
    return header + "\n".join(rows) + "\n"


class TestParseTriggerRecordsFromMd:
    """parse_trigger_records_from_md：解析信号触发记录节 → 云表记录。"""

    def test_parses_generation_record(self):
        from signal_tracking import parse_trigger_records_from_md
        md = _mk_trigger_md([
            "| 07:55 | SIG-20260924-01 | P1 | 通信ETF(515880) | 建仓 | "
            "北向资金持续净流入+通信板块涨停潮+技术面放量突破 | 已生成 | 按 7,500 份建仓 | — |",
        ])
        recs = parse_trigger_records_from_md(md, '2026-09-24')
        assert len(recs) == 1
        r = recs[0]
        assert r['signal_id'] == 'SIG-20260924-01'
        assert r['trigger_date'] == '2026-09-24'
        assert r['trigger_time'] == '07:55'
        assert r['priority'] == 'P1'
        assert r['ticker'] == '515880'
        assert r['name'] == '通信ETF'
        assert r['action_type'] == '建仓'
        assert '北向资金' in r['condition']
        assert '涨停潮' in r['condition']
        assert r['status'] == '已生成'
        assert r['suggest']
        assert 'result' in r

    def test_parses_trigger_record(self):
        from signal_tracking import parse_trigger_records_from_md
        md = _mk_trigger_md([
            "| 10:32 | SIG-20260924-01 | P1 | 通信ETF(515880) | 建仓 | "
            "现价 0.714 ≥ 交易价 0.71 触发 | 已触发 | 按 7,500 份建仓 | 已执行 |",
        ])
        recs = parse_trigger_records_from_md(md, '2026-09-24')
        assert len(recs) == 1
        assert recs[0]['status'] == '已触发'
        assert recs[0]['result'] == '已执行'
        assert recs[0]['trigger_time'] == '10:32'

    def test_parses_multiple_and_sorts(self):
        from signal_tracking import parse_trigger_records_from_md
        md = _mk_trigger_md([
            "| 10:32 | SIG-20260924-02 | P1 | 创新药ETF(159992) | 建仓 | 条件B | 已触发 | 建议B | — |",
            "| 07:55 | SIG-20260924-01 | P1 | 通信ETF(515880) | 建仓 | 条件A | 已生成 | 建议A | — |",
        ])
        recs = parse_trigger_records_from_md(md, '2026-09-24')
        assert len(recs) == 2
        assert {r['signal_id'] for r in recs} == {'SIG-20260924-01', 'SIG-20260924-02'}

    def test_skips_empty_and_separator(self):
        from signal_tracking import parse_trigger_records_from_md
        md = _mk_trigger_md([])  # 空表（仅表头+分隔线）
        assert parse_trigger_records_from_md(md, '2026-09-24') == []

    def test_skips_placeholder_text(self):
        from signal_tracking import parse_trigger_records_from_md
        md = (
            "## 信号触发记录\n\n"
            "> 早盘生成时此表为空，盘中检查 Agent 负责填充。\n\n"
            "| 触发时间 | 信号ID | 优先级 | 标的 | 操作类型 | 触发条件摘要 | 当前状态 | 建议操作 | 用户操作 |\n"
            "|----------|--------|:---:|------|:------:|-------------|:------:|----------|:------:|\n"
            "| — | — | — | — | — | — | — | — | — |\n"
        )
        assert parse_trigger_records_from_md(md, '2026-09-24') == []

    def test_missing_today_defaults(self):
        from signal_tracking import parse_trigger_records_from_md
        import datetime
        md = _mk_trigger_md([
            "| 07:55 | SIG-20260924-01 | P1 | 通信ETF(515880) | 建仓 | 原因 | 已生成 | 建议 | — |",
        ])
        recs = parse_trigger_records_from_md(md)
        assert recs[0]['trigger_date'] == datetime.date.today().isoformat()

    def test_skips_row_without_signal_id(self):
        from signal_tracking import parse_trigger_records_from_md
        md = _mk_trigger_md([
            "| 07:55 | — | P1 | 通信ETF(515880) | 建仓 | 原因 | 已生成 | 建议 | — |",
        ])
        assert parse_trigger_records_from_md(md, '2026-09-24') == []
