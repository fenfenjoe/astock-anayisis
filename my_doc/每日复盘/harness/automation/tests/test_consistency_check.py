"""
consistency_check.py 测试 — 信号模型一致性检查（按角色分组）
覆盖: 标记缺失检测 / 角色分组 / 多文件一致性 / 报告渲染
"""

import sys
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from consistency_check import (
    CORE_MARKERS,
    TABLE_MARKERS,
    CHECK_TARGETS,
    markers_for_role,
    check_markers,
    check_consistency,
    render_report,
)

# definer 通过样本：核心 + 表头
_DEFINER_OK = """
| 优先级 | 标的 | 触发条件 | 操作类型 | 状态 | 方向 | 紧急度 | 预期触发率 | 目标/止损 | 有效时段 | 仓位 | 信号ID |
盘中追加信号用 -盘中 后缀标识
P1 必填预期触发率 + 目标/止损
观察雷达移入关注列表
P0 风控 ≤3
"""

# consumer 通过样本：核心概念（无表头）
_CONSUMER_OK = """
盘中追加信号用 -盘中 后缀标识
P1 必填预期触发率 + 目标/止损
观察雷达移入关注列表
"""


class TestMarkersForRole:
    def test_definer_has_table(self):
        m = markers_for_role('definer')
        assert TABLE_MARKERS[0] in m
        assert len(m) == len(CORE_MARKERS) + len(TABLE_MARKERS)

    def test_consumer_no_table(self):
        m = markers_for_role('consumer')
        assert TABLE_MARKERS[0] not in m
        assert m == CORE_MARKERS


class TestCheckMarkers:
    def test_definer_all_present(self):
        assert check_markers(_DEFINER_OK, markers_for_role('definer')) == []

    def test_consumer_all_present(self):
        assert check_markers(_CONSUMER_OK, markers_for_role('consumer')) == []

    def test_missing_core_marker(self):
        content = _CONSUMER_OK.replace('关注列表', '观察列表')
        missing = check_markers(content, markers_for_role('consumer'))
        assert '关注列表' in missing

    def test_definer_missing_table(self):
        content = _DEFINER_OK.replace('| 优先级 | 标的 | 触发条件 | 操作类型 | 状态 | 方向 | 紧急度 | 预期触发率 | 目标/止损 | 有效时段 | 仓位 | 信号ID |', '')
        missing = check_markers(content, markers_for_role('definer'))
        assert TABLE_MARKERS[0] in missing

    def test_consumer_table_not_required(self):
        """consumer 缺表头不算漂移"""
        assert check_markers(_CONSUMER_OK, markers_for_role('consumer')) == []

    def test_empty_content(self):
        assert len(check_markers('', markers_for_role('definer'))) == len(CORE_MARKERS) + len(TABLE_MARKERS)


class TestCheckConsistency:
    def test_all_ok(self):
        contents = {}
        for label, _p, role in CHECK_TARGETS:
            contents[label] = _DEFINER_OK if role == 'definer' else _CONSUMER_OK
        res = check_consistency(contents)
        assert res['overall'] is True
        assert all(v['ok'] for v in res['files'].values())

    def test_one_drift(self):
        contents = {}
        for label, _p, role in CHECK_TARGETS:
            contents[label] = _DEFINER_OK if role == 'definer' else _CONSUMER_OK
        contents['自动化早盘'] = '旧格式 14 列，无关注列表'  # definer 漂移
        res = check_consistency(contents)
        assert res['overall'] is False
        assert res['files']['自动化早盘']['ok'] is False
        assert res['files']['早盘模板']['ok'] is True


class TestRenderReport:
    def test_all_ok_text(self):
        contents = {}
        for label, _p, role in CHECK_TARGETS:
            contents[label] = _DEFINER_OK if role == 'definer' else _CONSUMER_OK
        text = render_report(check_consistency(contents))
        assert '✅ 一致' in text

    def test_drift_text(self):
        contents = {}
        for label, _p, role in CHECK_TARGETS:
            contents[label] = _DEFINER_OK if role == 'definer' else _CONSUMER_OK
        contents['自动化盘中'] = '旧格式 14 列信号表'
        text = render_report(check_consistency(contents))
        assert '❌ 存在漂移' in text
        assert '❌ 自动化盘中' in text
        assert '预期触发率' in text
