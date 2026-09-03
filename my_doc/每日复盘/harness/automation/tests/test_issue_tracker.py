"""
工单（BUG/REQ）创建辅助 测试套件 — REQ-004

被测源码:
  - lib/issue_tracker.py  — 工单编号分配 / 同主题去重 / 工单正文渲染

覆盖要点:
  - next_ticket_id: 正常递增 / 空索引 / 跨前缀互不干扰 / 非数字容错
  - dedup_find: 同主题命中 / 无匹配 / 状态过滤 / 大小写容错
  - render_bug_markdown / render_req_markdown: 字段齐全渲染 / 缺字段降级
"""

import pytest
from lib.issue_tracker import (
    next_ticket_id,
    dedup_find,
    render_bug_markdown,
    render_req_markdown,
)


# ============================================================
# next_ticket_id
# ============================================================

class TestNextTicketId:
    def test_next_after_existing(self):
        """索引含 BUG-016 → 下一个为 BUG-017"""
        index = "| BUG-016 | P1 | 复盘读取过期持仓 | OPEN |\n| BUG-012 | P2 | 解析失败 | FIXED |"
        assert next_ticket_id(index, 'BUG') == 'BUG-017'

    def test_empty_index_uses_default(self):
        """空索引 → 从 001 开始"""
        assert next_ticket_id('', 'BUG') == 'BUG-001'
        assert next_ticket_id(None, 'REQ') == 'REQ-001'

    def test_prefix_independent(self):
        """BUG 与 REQ 编号互不干扰"""
        index = "| REQ-004 | IMPLEMENTED |\n| BUG-016 | OPEN |"
        assert next_ticket_id(index, 'BUG') == 'BUG-017'
        assert next_ticket_id(index, 'REQ') == 'REQ-005'

    def test_skips_non_numeric(self):
        """非数字编号（如 BUG-XXX）跳过不参与计算"""
        index = "| BUG-XXX | 待定 |\n| BUG-016 | OPEN |"
        assert next_ticket_id(index, 'BUG') == 'BUG-017'

    def test_zero_padding(self):
        """编号补零为 3 位"""
        assert next_ticket_id('| BUG-9 | OPEN |', 'BUG') == 'BUG-010'


# ============================================================
# dedup_find
# ============================================================

class TestDedupFind:
    BUG_INDEX = (
        "| BUG-ID | 标题 |\n"
        "|--------|------|\n"
        "| BUG-016 | P1 复盘读取过期持仓：dashboard TOS 云端只写云端 | OPEN |\n"
        "| BUG-012 | P2 解析失败 | FIXED |\n"
    )

    def test_match_open_topic(self):
        """同主题（关键词命中 OPEN 工单）→ 返回该工单 ID"""
        assert dedup_find(self.BUG_INDEX, 'BUG', ['持仓', '云端']) == 'BUG-016'

    def test_no_match_returns_none(self):
        """无同主题 → None"""
        assert dedup_find(self.BUG_INDEX, 'BUG', ['黄金ETF 成本复权']) is None

    def test_manual_review_still_deduped(self):
        """MANUAL_REVIEW 工单视为待处理，参与去重"""
        index = "| BUG-021 | P2 数据源降级：push2 不可达 | MANUAL_REVIEW |"
        assert dedup_find(index, 'BUG', ['push2', '数据源']) == 'BUG-021'

    def test_fixed_ticket_not_deduped(self):
        """FIXED 工单不参与去重（状态过滤）→ None"""
        assert dedup_find(self.BUG_INDEX, 'BUG', ['解析失败']) is None

    def test_keyword_case_insensitive(self):
        """关键词忽略大小写（英文关键词）"""
        index = "| BUG-020 | P2 push2 probe failed | OPEN |"
        assert dedup_find(index, 'BUG', ['PUSH2']) == 'BUG-020'

    def test_empty_index(self):
        """空索引 → None"""
        assert dedup_find('', 'BUG', ['数据源']) is None


# ============================================================
# render_bug_markdown
# ============================================================

class TestRenderBugMarkdown:
    def test_full_fields_render(self):
        """必填字段齐全 → 包含关键标记行"""
        md = render_bug_markdown({
            'id': 'BUG-017',
            'title': '数据源降级：push2 不可达',
            'component': 'lib/',
            'severity': 'P2',
            'auto_fix_eligible': False,
            'expected': 'push2 可达',
            'actual': '探测 push2=❌',
            'affected_files': ['lib/data_source_probe.py'],
        })
        assert '# BUG-017: 数据源降级：push2 不可达' in md
        assert '- **状态**: OPEN' in md
        assert '- **auto_fix_eligible**: false' in md
        assert '- **预期行为**: push2 可达' in md
        assert '`lib/data_source_probe.py`' in md

    def test_missing_fields_default(self):
        """缺字段 → 降级默认值，不抛异常"""
        md = render_bug_markdown({'id': 'BUG-018'})
        assert '# BUG-018: (未命名问题)' in md
        assert '- **严重程度**: P2' in md
        assert '（待定位）' in md


# ============================================================
# render_req_markdown
# ============================================================

class TestRenderReqMarkdown:
    def test_full_fields_render(self):
        """必填字段齐全 → 包含核心章节"""
        md = render_req_markdown({
            'id': 'REQ-005',
            'title': '异动扫描加题材联动',
            'priority': 'P2',
            'scope': '收盘复盘',
            'description': '行业/题材扫描需叠加资金面联动归因。',
            'expected_result': '异动原因分析覆盖资金面。',
        })
        assert '# REQ-005: 异动扫描加题材联动' in md
        assert '## 需求描述' in md
        assert '## 期望结果' in md
        assert '## 开发流程（强制）' in md
        assert '1. brainstorming' in md

    def test_minimal_fields(self):
        """仅 id → 其余默认值，不抛异常"""
        md = render_req_markdown({'id': 'REQ-006'})
        assert '# REQ-006: (未命名需求)' in md
        assert '- **状态**: OPEN' in md
