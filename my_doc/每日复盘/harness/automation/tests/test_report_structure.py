"""
报告结构回归测试 — REQ-004: 报告去冗余 / 异动扫描行业题材版 / 问题工单化

被测文件（真实文件，只读）:
  - harness/prompts/早盘分析-模板.md      — 报告结构模板（早盘）
  - harness/prompts/复盘分析-模板.md      — 报告结构模板（复盘）
  - automation/prompts/auto_morning_analysis.md — 自动化早盘（第六步报告模板）
  - automation/prompts/auto_evening_review.md   — 自动化复盘（第五步/13.5）
  - automation/prompts/auto_logic_inspect.md    — 逻辑巡检（C1/C3 关键词）

用途: 防止未来模板漂移（删掉的节又加回来、新结构被回退）不被巡检发现。
注意: 文件路径基于本测试文件位置推导（tests/ 的上两级 = harness 根）。
"""

from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent.parent  # harness/
PROMPTS = HARNESS / "prompts"
AUTO = HARNESS / "automation" / "prompts"


def _read(path: Path) -> str:
    assert path.exists(), f"文件不存在: {path}"
    return path.read_text(encoding="utf-8")


# ============================================================
# 早盘分析-模板.md — 去冗余
# ============================================================

class TestMorningTemplate:
    def setup_method(self):
        self.content = _read(PROMPTS / "早盘分析-模板.md")

    def test_holdings_snapshot_removed(self):
        """持仓快照不再作为报告章节"""
        assert "## 一、我的持仓" not in self.content
        assert "## 一、持仓数据（执行输入，不写入报告）" in self.content

    def test_ops_list_removed(self):
        """操作清单不再作为报告章节"""
        assert "## 七、操作清单" not in self.content

    def test_cross_variety_section_removed(self):
        """跨品种约束不再作为报告章节"""
        assert "## 九、跨品种约束检查" not in self.content

    def test_signal_overview_removed(self):
        """每日信号概览不再作为报告章节"""
        assert "## 十二、每日信号概览" not in self.content

    def test_selfcheck_removed(self):
        """12 节自检不再作为报告章节"""
        assert "## 12 节自检" not in self.content

    def test_new_sections_present(self):
        """新增：风险提示 / 报告输出结构与运行提示"""
        assert "## 十、风险提示" in self.content
        assert "## 十一、报告输出结构与运行提示" in self.content
        assert "### 11.2 运行提示与工单提交" in self.content

    def test_signal_generation_section_kept(self):
        """第九节（每日信号生成）保留 —— 一致性检查依赖"""
        assert "## 九、每日信号生成" in self.content
        assert "| 优先级 | 标的 | 触发条件 | 操作类型 | 状态 | 方向 | 紧急度 | 预期触发率 | 目标/止损 | 有效时段 | 仓位 | 信号ID |" in self.content


# ============================================================
# 复盘分析-模板.md — 去冗余 + 异动扫描行业题材版
# ============================================================

class TestReviewTemplate:
    def setup_method(self):
        self.content = _read(PROMPTS / "复盘分析-模板.md")

    def test_strategy_section_removed(self):
        """当前使用的策略不再作为报告章节"""
        assert "## 二、当前使用的策略" not in self.content

    def test_data_caliber_section_removed(self):
        """数据口径不再作为报告章节"""
        assert "## 三、数据口径" not in self.content

    def test_etf_scan_replaced(self):
        """异动扫描改为行业/题材版"""
        assert "全市场异动扫描（ETF 版）" not in self.content
        assert "全市场异动扫描（行业/题材版）" in self.content
        assert "为什么扫行业/题材而非 ETF" in self.content

    def test_issue_ticket_step_present(self):
        """5.5 运行提示与工单提交 存在"""
        assert "### 5.5. 运行提示与工单提交" in self.content
        assert "lib.issue_tracker" in self.content


# ============================================================
# auto_morning_analysis.md — 自动化早盘
# ============================================================

class TestAutoMorning:
    def setup_method(self):
        self.content = _read(AUTO / "auto_morning_analysis.md")

    def test_header_metadata_removed(self):
        """报告模板头部元信息已删除"""
        assert "**生成方式**" not in self.content
        assert "**数据源健康**" not in self.content
        assert "**Staging来源**" not in self.content

    def test_removed_sections_absent(self):
        """已删除的报告章节不在第六步模板中"""
        assert "## 一、我的持仓" not in self.content
        assert "## 八、操作清单" not in self.content
        assert "## 九、跨品种约束检查" not in self.content
        assert "## 十二、每日信号概览" not in self.content
        assert "## 12 节自检" not in self.content

    def test_new_structure_present(self):
        """新 9 节结构 + 运行提示步骤存在"""
        assert "## 八、风险提示" in self.content
        assert "**配套信号文件**" in self.content
        assert "第六步半：问题提示与工单提交" in self.content
        assert "### 6.5.1 问题清单与处理映射" in self.content

    def test_module_checklist_9_sections(self):
        """强制模块清单为 9 节"""
        assert "强制模块清单（9 节" in self.content
        assert "强制模块清单（12 节" not in self.content


# ============================================================
# auto_evening_review.md — 自动化复盘
# ============================================================

class TestAutoEvening:
    def setup_method(self):
        self.content = _read(AUTO / "auto_evening_review.md")

    def test_scan_industry_theme(self):
        """第五步为行业/题材版"""
        assert "## 第五步：全市场异动扫描（行业/题材版" in self.content
        assert "board_scan" in self.content
        assert "m:90+t:2" in self.content
        assert "m:90+t:3" in self.content

    def test_issue_ticket_step(self):
        """13.5 运行提示与工单提交存在"""
        assert "### 13.5 运行提示与工单提交" in self.content

    def test_report_structure_note(self):
        """第十二步标注不再输出策略/口径章节"""
        assert "不输出" in self.content
        assert "行业/题材版" in self.content


# ============================================================
# auto_logic_inspect.md — C1/C3 关键词同步
# ============================================================

class TestLogicInspectKeywords:
    def setup_method(self):
        self.content = _read(AUTO / "auto_logic_inspect.md")

    def test_c1_keywords_synced(self):
        """C1 用新早盘报告章节名（修复 BUG-008 漂移）"""
        assert "('前次预测回顾','预测对比')" in self.content
        assert "('风险提示','风险')" in self.content
        assert "'操作清单','优先级'" not in self.content

    def test_c3_keywords_synced(self):
        """C3 用实际复盘报告章节名（修复 BUG-009 漂移）"""
        assert "('早盘预测回顾','方向对比')" in self.content
        assert "('做T建议复盘','做T对比')" in self.content
        assert "('次日核心关注','次日预案')" in self.content
        assert "'做T预判复盘'" not in self.content
