"""
REQ 状态机与流程门禁 测试套件

被测源码:
  - lib/state_machine.py      — 状态转换 / TDD门禁 / 滞留检测

覆盖要点:
  - 全部合法状态转换路径
  - 非法转换拒绝
  - 终态不可转出
  - 测试文件存在性检查
  - TDD门禁判定逻辑
  - 滞留检测准确性
"""

import pytest
from pathlib import Path
from lib.state_machine import (
    VALID_TRANSITIONS,
    validate_transition,
    check_test_exists,
    tdd_gate_check,
    detect_stuck,
)


# ============================================================
# validate_transition
# ============================================================

class TestValidateTransition:
    def test_all_valid_paths(self):
        """验证所有合法转换路径"""
        valid_pairs = [
            ('OPEN', 'IN_PROGRESS'),
            ('OPEN', 'REJECTED'),
            ('IN_PROGRESS', 'IMPLEMENTED'),
            ('IN_PROGRESS', 'OPEN'),
            ('IN_PROGRESS', 'REJECTED'),
            ('IMPLEMENTED', 'CLOSED'),
            ('IMPLEMENTED', 'IN_PROGRESS'),
            ('IMPLEMENTED', 'REJECTED'),
        ]
        for from_s, to_s in valid_pairs:
            ok, msg = validate_transition(from_s, to_s)
            assert ok is True, f"{from_s} -> {to_s} should be valid, got: {msg}"

    def test_invalid_transition(self):
        """非法转换: IMPLEMENTED -> OPEN"""
        ok, msg = validate_transition('IMPLEMENTED', 'OPEN')
        assert ok is False

    def test_terminal_no_transition(self):
        """终态不可转出: CLOSED -> OPEN"""
        ok, msg = validate_transition('CLOSED', 'OPEN')
        assert ok is False
        assert 'terminal' in msg.lower()

    def test_unknown_status(self):
        """未知状态"""
        ok, msg = validate_transition('UNKNOWN', 'OPEN')
        assert ok is False

    def test_diagram_matches_code(self):
        """VALID_TRANSITIONS 自身一致性: 每个 from 的 to 列表无重复"""
        for from_s, to_list in VALID_TRANSITIONS.items():
            assert len(to_list) == len(set(to_list)), \
                f"Duplicate transitions from {from_s}: {to_list}"


# ============================================================
# check_test_exists
# ============================================================

class TestCheckTestExists:
    def test_file_exists(self, tests_dir):
        """test_REQ_001.py 存在 => True"""
        assert check_test_exists('REQ-001', tests_dir) is True

    def test_file_not_exists(self, tests_dir):
        """test_REQ_999.py 不存在 => False"""
        assert check_test_exists('REQ-999', tests_dir) is False

    def test_id_with_hyphen(self, tests_dir):
        """REQ-ID 含连字符正常处理"""
        result = check_test_exists('REQ-001', tests_dir)
        assert isinstance(result, bool)


# ============================================================
# tdd_gate_check
# ============================================================

class TestTddGateCheck:
    def test_test_exists_and_passes(self, tests_dir):
        """测试存在且通过 => blocked=False"""
        result = tdd_gate_check('REQ-001', tests_dir)
        assert result['test_exists'] is True
        assert result['blocked'] is False

    def test_test_not_exists(self, tests_dir):
        """测试不存在 => blocked=True"""
        result = tdd_gate_check('REQ-999', tests_dir)
        assert result['test_exists'] is False
        assert result['blocked'] is True


# ============================================================
# detect_stuck
# ============================================================

class TestDetectStuck:
    def test_empty_list(self, tests_dir):
        """空列表 => 无滞留"""
        assert detect_stuck([], tests_dir) == []

    def test_one_stuck(self, tests_dir):
        """IMPLEMENTED 但无测试 => 检测到1条滞留"""
        reqs = [{'id': 'REQ-999', 'status': 'IMPLEMENTED', 'created_date': '2026-07-24'}]
        stuck = detect_stuck(reqs, tests_dir)
        assert len(stuck) == 1
        assert stuck[0]['stuck_reason'] is not None

    def test_no_stuck_when_has_test(self, tests_dir):
        """IMPLEMENTED 且有测试 => 无滞留"""
        reqs = [{'id': 'REQ-001', 'status': 'IMPLEMENTED', 'created_date': '2026-07-24'}]
        stuck = detect_stuck(reqs, tests_dir)
        assert len(stuck) == 0

    def test_multiple_stuck(self, tests_dir):
        """多个 IMPLEMENTED 无测试 => 全部检测到"""
        reqs = [
            {'id': 'REQ-998', 'status': 'IMPLEMENTED', 'created_date': '2026-07-20'},
            {'id': 'REQ-999', 'status': 'IMPLEMENTED', 'created_date': '2026-07-21'},
        ]
        stuck = detect_stuck(reqs, tests_dir)
        assert len(stuck) == 2

    def test_open_not_stuck(self, tests_dir):
        """OPEN 状态的 REQ 不被误判为滞留"""
        reqs = [{'id': 'REQ-999', 'status': 'OPEN', 'created_date': '2026-07-24'}]
        stuck = detect_stuck(reqs, tests_dir)
        assert len(stuck) == 0
