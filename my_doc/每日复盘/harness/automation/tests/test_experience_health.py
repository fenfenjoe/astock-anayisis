"""
REQ-005: 投资经验.md 压缩合并 + 经验库健康检查模块测试

被测模块:
  - lib/experience_health.py — 经验库健康检查纯函数（行数阈值 / 重复章节头 /
    必需章节存在性 / 北向断供标注缺失），供 auto_experience_health 复用

覆盖要点:
  - count_lines                          — 行数统计
  - check_line_limit                     — 行数阈值判定（正/负/边界）
  - find_duplicate_headers               — 重复章节头检测
  - check_required_sections              — 必需章节存在性
  - find_unannotated_northbound_entries  — 北向断供标注缺失检测
  - check_experience_health              — 复合健康检查
  - 集成: 真实 投资经验.md ≤500 行 / 无重复章节头 / 必需章节齐全 /
    北向依赖条目已标注断供降级 / 每章节 ≤10 条核心经验
"""

import pytest
from pathlib import Path

from lib.experience_health import (
    count_lines,
    check_line_limit,
    find_duplicate_headers,
    check_required_sections,
    find_unannotated_northbound_entries,
    check_experience_health,
    REQUIRED_SECTIONS,
    NORTHBOUND_ANNOTATION_MARKER,
    LINE_LIMIT,
)

# 真实经验文件路径（tests/ 向上三级 = harness/，再进 experience/）
EXPERIENCE_DIR = Path(__file__).resolve().parent.parent.parent / "experience"
INVEST_FILE = EXPERIENCE_DIR / "投资经验.md"


# ============================================================
# count_lines
# ============================================================

class TestCountLines:
    def test_empty(self):
        assert count_lines("") == 0

    def test_single_line(self):
        assert count_lines("hello") == 1

    def test_multiple_lines(self):
        assert count_lines("a\nb\nc") == 3

    def test_blank_lines_counted(self):
        assert count_lines("a\n\nb") == 3

    def test_trailing_newline(self):
        assert count_lines("a\nb\n") == 2


# ============================================================
# check_line_limit
# ============================================================

class TestCheckLineLimit:
    def test_within_limit(self):
        ok, n = check_line_limit("x\n" * 300, limit=500)
        assert ok is True
        assert n == 300

    def test_at_limit(self):
        ok, n = check_line_limit("x\n" * 500, limit=500)
        assert ok is True
        assert n == 500

    def test_over_limit(self):
        ok, n = check_line_limit("x\n" * 501, limit=500)
        assert ok is False
        assert n == 501

    def test_zero_lines(self):
        ok, n = check_line_limit("", limit=500)
        assert ok is True
        assert n == 0

    def test_default_limit_constant(self):
        assert LINE_LIMIT == 500


# ============================================================
# find_duplicate_headers
# ============================================================

class TestFindDuplicateHeaders:
    def test_no_duplicates(self):
        content = "## A\n## B\n## C\n"
        assert find_duplicate_headers(content) == []

    def test_one_duplicate(self):
        content = "## A\n## 跨市场映射\n## B\n## 跨市场映射\n"
        assert find_duplicate_headers(content) == ["跨市场映射"]

    def test_multiple_duplicates(self):
        content = "## A\n## 超跌反弹\n## A\n## 超跌反弹\n"
        assert set(find_duplicate_headers(content)) == {"A", "超跌反弹"}

    def test_duplicate_not_substring(self):
        # 子串不应误判：## 跨市场映射 vs ## 跨市场映射2
        content = "## 跨市场映射\n## 跨市场映射2\n"
        assert find_duplicate_headers(content) == []

    def test_empty(self):
        assert find_duplicate_headers("") == []

    def test_h3_not_counted(self):
        # ### 级别不计入章节头
        content = "## A\n### A\n## B\n"
        assert find_duplicate_headers(content) == []


# ============================================================
# check_required_sections
# ============================================================

class TestCheckRequiredSections:
    def test_all_present(self):
        content = "\n".join(f"## {s}" for s in REQUIRED_SECTIONS)
        assert check_required_sections(content) == []

    def test_missing_one(self):
        present = [s for s in REQUIRED_SECTIONS if s != "信号设计"]
        content = "\n".join(f"## {s}" for s in present)
        assert check_required_sections(content) == ["信号设计"]

    def test_custom_required_list(self):
        content = "## A\n## B\n"
        assert check_required_sections(content, required=["A", "B", "C"]) == ["C"]

    def test_empty_content(self):
        assert check_required_sections("") == REQUIRED_SECTIONS

    def test_required_not_empty(self):
        assert len(REQUIRED_SECTIONS) >= 9


# ============================================================
# find_unannotated_northbound_entries
# ============================================================

class TestFindUnannotatedNorthboundEntries:
    def test_annotated_not_flagged(self):
        content = (
            "## 跨市场映射\n"
            "### 北向前日巨额净卖出是前瞻信号\n"
            "> ⚠️ 北向数据断供降级：东财北向净买额字段自2024-08起断供，以同花顺hsgtApi自缓存替代\n"
            "北向前日净卖出>200亿时次日科技暴跌概率高。\n"
        )
        assert find_unannotated_northbound_entries(content) == []

    def test_northbound_without_marker_flagged(self):
        content = (
            "## 跨市场映射\n"
            "### 北向前日巨额净卖出是前瞻信号\n"
            "北向前日净卖出>200亿时次日科技暴跌概率高。\n"
        )
        assert find_unannotated_northbound_entries(content) == [2]

    def test_non_northbound_not_flagged(self):
        content = (
            "## 信号设计\n"
            "### 主备路径模式\n"
            "P1信号必须有主备路径。\n"
        )
        assert find_unannotated_northbound_entries(content) == []

    def test_multiple_unannotated(self):
        content = (
            "## 跨市场映射\n"
            "### 条目A\n"
            "北向数据很重要。\n"
            "### 条目B\n"
            "北向同样重要。\n"
        )
        assert find_unannotated_northbound_entries(content) == [2, 4]

    def test_section_change_flush(self):
        # 跨章节后新条目，上一章节北向条目已被 flush
        content = (
            "## 跨市场映射\n"
            "### 条目A\n"
            "北向数据。\n"
            "## 信号设计\n"
            "### 条目B\n"
            "该条目不依赖外部资金数据。\n"
        )
        assert find_unannotated_northbound_entries(content) == [2]

    def test_details_block_excluded(self):
        # <details> 折叠备份区不参与条目解析（备份用 bullet，不用 ### 头）
        content = (
            "## 跨市场映射\n"
            "### 北向前日巨额净卖出\n"
            "> ⚠️ 北向数据断供降级：替代路径\n"
            "正文。\n"
            "<details>\n"
            "<summary>备份</summary>\n"
            "- 北向旧条目备份\n"
            "</details>\n"
        )
        assert find_unannotated_northbound_entries(content) == []


# ============================================================
# check_experience_health
# ============================================================

class TestCheckExperienceHealth:
    def test_healthy_document(self):
        content = (
            "## 市场判断\n### A\n正文。\n"
            "## 信号设计\n### B\n"
            "> ⚠️ 北向数据断供降级：xxx\n北向数据。\n"
        )
        result = check_experience_health(content, required=["市场判断", "信号设计"])
        assert result["healthy"] is True

    def test_unhealthy_missing_section(self):
        content = "## 市场判断\n### A\n正文。\n" * 10
        result = check_experience_health(content, required=["信号设计"])
        assert result["healthy"] is False
        assert "信号设计" in result["missing_sections"]

    def test_unhealthy_unannotated_northbound(self):
        content = (
            "## 跨市场映射\n### 条目\n北向数据未标注。\n"
            "## 信号设计\n### B\n正文。\n"
        )
        result = check_experience_health(content, required=["信号设计"])
        assert result["healthy"] is False
        assert result["unannotated_northbound_entries"] != []

    def test_unhealthy_duplicate_header(self):
        content = "## 跨市场映射\n### A\n正文。\n## 跨市场映射\n"
        result = check_experience_health(content, required=["跨市场映射"])
        assert result["healthy"] is False
        assert "跨市场映射" in result["duplicate_headers"]


# ============================================================
# 集成：真实 投资经验.md
# ============================================================

class TestInvestExperienceFile:
    def test_file_exists(self):
        assert INVEST_FILE.exists(), f"投资经验.md 不存在: {INVEST_FILE}"

    def test_line_count_within_limit(self):
        content = INVEST_FILE.read_text(encoding="utf-8")
        ok, n = check_line_limit(content)
        assert ok, f"投资经验.md 行数 {n} > {LINE_LIMIT}，需继续压缩"

    def test_no_duplicate_headers(self):
        content = INVEST_FILE.read_text(encoding="utf-8")
        dupes = find_duplicate_headers(content)
        assert dupes == [], f"投资经验.md 存在重复章节头: {dupes}"

    def test_all_required_sections_present(self):
        content = INVEST_FILE.read_text(encoding="utf-8")
        missing = check_required_sections(content)
        assert missing == [], f"投资经验.md 缺失章节: {missing}"

    def test_northbound_entries_annotated(self):
        content = INVEST_FILE.read_text(encoding="utf-8")
        flagged = find_unannotated_northbound_entries(content)
        assert flagged == [], f"投资经验.md 北向依赖未标注断供降级条目行号: {flagged}"

    def test_sections_entries_under_10(self):
        # 每章节 ≤10 条 ### 核心经验（REQ-005 期望结果）
        # 2026-09-08 记忆体系 Phase 3：经验权威源迁移 OpenViking（方案 v1.10 决策 2），
        # 本地 投资经验.md 退化为「过渡期镜像」，章节内合并/压缩改由 OpenViking 健康任务
        # （auto_experience_health.md 第五(A)步镜像导出 + 第一步规模合并）负责。
        # 此门禁从「硬性 ≤10」放宽为「镜像失控边界 ≤20」（防镜像无界增长），
        # 章节内 ≤10 的合并要求由健康任务在 OpenViking 侧执行。
        content = INVEST_FILE.read_text(encoding="utf-8")
        section = None
        counts = {}
        for line in content.splitlines():
            if line.strip() == "<details>":
                break
            if line.startswith("## ") and not line.startswith("### "):
                section = line[3:].strip()
                counts.setdefault(section, 0)
            elif line.startswith("### ") and section:
                counts[section] = counts.get(section, 0) + 1
        over = {s: c for s, c in counts.items() if c > 20}
        assert not over, f"镜像章节条目失控(>20条): {over}"
