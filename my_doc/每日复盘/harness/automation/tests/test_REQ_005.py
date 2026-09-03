"""
REQ-005 TDD 门禁入口 — 复用 test_experience_health.py 完整测试套件

REQ-005 测试交付物指定测试文件为 test_experience_health.py（对应被测模块
lib/experience_health.py，供 auto_experience_health 复用）。此处提供 REQ-ID
命名规范（test_REQ_005.py）的薄封装，以满足 auto_req_implement 第 3.5 步
TDD 门禁 check_test_exists('REQ-005') 的要求。

注意: pytest 默认不收集跨模块 import 的测试类，故对每个测试类做一次空子类化，
使测试在本模块命名空间中被收集（继承全部 test_* 方法）。
"""

import sys
from pathlib import Path

# 确保可导入同目录的 test_experience_health.py（pytest 对多文件并跑时
# 不保证 tests/ 在 sys.path 中）
_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

from test_experience_health import (
    TestCountLines,
    TestCheckLineLimit,
    TestFindDuplicateHeaders,
    TestCheckRequiredSections,
    TestFindUnannotatedNorthboundEntries,
    TestCheckExperienceHealth,
    TestInvestExperienceFile,
)


class TestCountLinesGate(TestCountLines):
    pass


class TestCheckLineLimitGate(TestCheckLineLimit):
    pass


class TestFindDuplicateHeadersGate(TestFindDuplicateHeaders):
    pass


class TestCheckRequiredSectionsGate(TestCheckRequiredSections):
    pass


class TestFindUnannotatedNorthboundEntriesGate(TestFindUnannotatedNorthboundEntries):
    pass


class TestCheckExperienceHealthGate(TestCheckExperienceHealth):
    pass


class TestInvestExperienceFileGate(TestInvestExperienceFile):
    pass
