"""
REQ 状态机与流程门禁 — 支撑 TDD 门禁、滞留检测、状态转换验证

纯计算 + subprocess（仅 run_tests），不修改任何数据文件。
"""

import subprocess
import sys
from pathlib import Path
from typing import Union


# ============================================================
# 状态机
# ============================================================

VALID_TRANSITIONS = {
    'OPEN':        ['IN_PROGRESS', 'REJECTED'],
    'IN_PROGRESS': ['IMPLEMENTED', 'OPEN', 'REJECTED'],
    'IMPLEMENTED': ['CLOSED', 'IN_PROGRESS', 'REJECTED'],
    'CLOSED':      [],
    'ADOPTED':     [],
    'REJECTED':    [],
}


def validate_transition(from_status: str, to_status: str) -> tuple:
    """验证 REQ 状态转换是否合法。

    Returns:
        (is_valid: bool, message: str)
    """
    if from_status not in VALID_TRANSITIONS:
        return (False, f"Unknown status: {from_status!r}")

    allowed = VALID_TRANSITIONS[from_status]

    if not allowed:
        return (False, f"Status {from_status!r} is a terminal state, no transitions allowed")

    if to_status not in allowed:
        return (False, f"Invalid transition {from_status!r} -> {to_status!r}. Allowed: {allowed}")

    return (True, '')


# ============================================================
# TDD 门禁
# ============================================================

def check_test_exists(req_id: str, tests_dir: str) -> bool:
    """检查指定 REQ 的测试文件是否存在。

    Args:
        req_id: 如 "REQ-001"
        tests_dir: tests/ 目录的绝对路径

    Returns:
        True 如果 test_{REQ-ID}.py 存在
    """
    test_file = Path(tests_dir) / f"test_{req_id}.py"
    return test_file.exists()


def run_tests(req_id: str, tests_dir: str) -> tuple:
    """运行指定 REQ 的测试。

    Args:
        req_id: 如 "REQ-001"
        tests_dir: tests/ 目录的绝对路径

    Returns:
        (passed: bool, output: str)
    """
    test_file = f"test_{req_id}.py"
    test_path = Path(tests_dir) / test_file

    if not test_path.exists():
        return (False, f"Test file not found: {test_path}")

    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', str(test_path), '-v', '--tb=short'],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(Path(tests_dir).parent),
        )
        passed = result.returncode == 0
        return (passed, result.stdout + result.stderr)
    except subprocess.TimeoutExpired:
        return (False, 'Test execution timed out after 60s')
    except Exception as e:
        return (False, f'Failed to run tests: {e}')


def tdd_gate_check(req_id: str, tests_dir: str) -> dict:
    """TDD 门禁：检查测试文件是否存在 + 测试是否通过。

    Returns:
        {
            'test_exists': bool,
            'test_pass': bool,
            'output': str,
            'blocked': bool,
        }
    """
    exists = check_test_exists(req_id, tests_dir)

    if not exists:
        return {
            'test_exists': False,
            'test_pass': False,
            'output': f'Test file test_{req_id}.py not found in {tests_dir}',
            'blocked': True,
        }

    passed, output = run_tests(req_id, tests_dir)

    return {
        'test_exists': True,
        'test_pass': passed,
        'output': output,
        'blocked': not passed,
    }


# ============================================================
# 滞留检测
# ============================================================

def detect_stuck(req_index: list[dict], tests_dir: str) -> list[dict]:
    """检测 IMPLEMENTED 但缺少测试的滞留 REQ。

    Args:
        req_index: REQ 列表，每条含 {id, status, created_date, ...}
        tests_dir: tests/ 目录路径

    Returns:
        滞留 REQ 列表，每条追加 stuck_reason 字段
    """
    stuck = []
    for req in req_index:
        if req.get('status') != 'IMPLEMENTED':
            continue

        req_id = req.get('id', '')
        has_test = check_test_exists(req_id, tests_dir)

        if not has_test:
            item = dict(req)
            item['stuck_reason'] = 'IMPLEMENTED but no test file found'
            stuck.append(item)

    return stuck
