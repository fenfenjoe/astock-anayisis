"""
REQ-009 TDD 门禁测试 — OpenViking 经验库补全迁移健康函数

被测模块: lib/openviking_health.py（REQ-009 新增）
覆盖:
  - REQUIRED_DOMAINS:              必需领域定义（投资 9 / 短线 4 / 审阅 8 = 21）
  - parse_metadata:                解析条目 `## 元数据` 节 → dict（含 置信度 兜底提取）
  - check_metadata_complete:       校验 领域/状态/置信度/首次沉淀/最近更新 5 字段完整性
  - check_domain_completeness:     领域缺失检测（返回缺失列表）
  - compute_confidence_distribution: 置信度 高/中/低 分布统计 + 高占比
  - detect_stale:                  最近更新 > 90 天 过时检测
  - apply_t2_update:               贝叶斯 T2 置信度更新（中→高需 2+ 次独立验证；
                                   单次证伪 中→低；低被再证伪 → deprecated）

测试覆盖要求：
  - 每个公开函数至少 1 条正向 + 1 条边界测试
  - 涉及计算的函数测试正/负/零（置信度分布高/中/低/空）
  - 涉及状态转换的函数测试全部合法路径 + 至少 1 条非法路径（apply_t2_update）
"""

import sys
from pathlib import Path

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from openviking_health import (
    REQUIRED_DOMAINS,
    REQUIRED_METADATA_FIELDS,
    parse_metadata,
    check_metadata_complete,
    check_domain_completeness,
    compute_confidence_distribution,
    detect_stale,
    apply_t2_update,
)


# ============================================================
# REQUIRED_DOMAINS
# ============================================================

class TestRequiredDomains:
    def test_three_categories(self):
        assert set(REQUIRED_DOMAINS.keys()) == {"投资", "短线", "审阅"}

    def test_invest_9(self):
        inv = REQUIRED_DOMAINS["投资"]
        assert len(inv) == 9
        for d in ["市场判断", "跨市场映射", "开盘前评估", "数据纪律",
                  "早盘纪律设计", "策略纪律", "宏观数据公布日", "超跌反弹", "信号设计"]:
            assert d in inv

    def test_shortterm_4(self):
        st = REQUIRED_DOMAINS["短线"]
        assert len(st) == 4
        for d in ["做T", "跷跷板套利", "跨市场套利", "事件套利"]:
            assert d in st

    def test_review_8(self):
        rv = REQUIRED_DOMAINS["审阅"]
        assert len(rv) == 8
        for d in ["审阅流程", "数据核验清单", "逻辑一致性检查", "完整性检查",
                  "格式标准", "常见错误模式", "修正原则", "每日信号审阅清单"]:
            assert d in rv

    def test_total_21(self):
        total = sum(len(v) for v in REQUIRED_DOMAINS.values())
        assert total == 21

    def test_no_duplicates_within_category(self):
        for cat, domains in REQUIRED_DOMAINS.items():
            assert len(domains) == len(set(domains)), f"{cat} 领域有重复"


# ============================================================
# parse_metadata
# ============================================================

_META_FULL = """## 元数据（供检索与融会贯通）
- 来源：evening_review
- 领域：做T
- 状态：active
- 关联：viking://.../A股市场判断投资经验.md
- 首次沉淀：2026-09-09 | 最近更新：2026-09-09
"""

_META_WITH_CONF = _META_FULL + """
## Reflect
- 置信度：中
"""


class TestParseMetadata:
    def test_full_metadata(self):
        md = parse_metadata(_META_FULL)
        assert md["领域"] == "做T"
        assert md["状态"] == "active"
        assert md["来源"] == "evening_review"
        assert md["首次沉淀"] == "2026-09-09"
        assert md["最近更新"] == "2026-09-09"
        assert "关联" in md

    def test_no_metadata_section(self):
        content = "## Situation\n- 场景\n## Approach\n- 方法\n## Reflect\n- 校准\n"
        md = parse_metadata(content)
        assert md == {}

    def test_confidence_fallback_from_reflect(self):
        md = parse_metadata(_META_WITH_CONF)
        assert md["置信度"] == "中"

    def test_confidence_from_metadata_section(self):
        content = _META_FULL + "## 元数据\n- 置信度：高\n"
        md = parse_metadata(content)
        assert md["置信度"] == "高"

    def test_missing_value_not_added(self):
        content = "## 元数据\n- 状态：active\n- 首次沉淀：2026-09-09 | 最近更新：\n"
        md = parse_metadata(content)
        assert md["状态"] == "active"
        # 最近更新 空值 → 键存在但值为空
        assert "最近更新" in md
        assert md["最近更新"] == ""


# ============================================================
# check_metadata_complete
# ============================================================

class TestCheckMetadataComplete:
    def test_complete(self):
        ok, missing = check_metadata_complete(
            {"领域": "做T", "状态": "active", "置信度": "中",
             "首次沉淀": "2026-09-09", "最近更新": "2026-09-09"}
        )
        assert ok is True
        assert missing == []

    def test_missing_all(self):
        ok, missing = check_metadata_complete({})
        assert ok is False
        assert set(missing) == set(REQUIRED_METADATA_FIELDS)

    def test_missing_single(self):
        ok, missing = check_metadata_complete(
            {"领域": "做T", "状态": "active", "置信度": "中",
             "首次沉淀": "2026-09-09", "最近更新": ""}
        )
        assert ok is False
        assert missing == ["最近更新"]

    def test_empty_value_treated_missing(self):
        ok, missing = check_metadata_complete(
            {"领域": "", "状态": "active", "置信度": "中",
             "首次沉淀": "2026-09-09", "最近更新": "2026-09-09"}
        )
        assert ok is False
        assert missing == ["领域"]

    def test_required_fields_constant(self):
        assert set(REQUIRED_METADATA_FIELDS) == {
            "领域", "状态", "置信度", "首次沉淀", "最近更新"
        }


# ============================================================
# check_domain_completeness
# ============================================================

class TestCheckDomainCompleteness:
    def test_all_present(self):
        all_domains = [d for v in REQUIRED_DOMAINS.values() for d in v]
        assert check_domain_completeness(all_domains) == []

    def test_missing_review_4(self):
        """审阅领域缺 4 项（REQ-009 实测场景）。"""
        present = [
            "市场判断", "跨市场映射", "开盘前评估", "数据纪律", "早盘纪律设计",
            "策略纪律", "宏观数据公布日", "超跌反弹", "信号设计",
            "做T", "跷跷板套利", "跨市场套利", "事件套利",
            "审阅流程", "数据核验清单", "格式标准", "修正原则",
        ]
        missing = check_domain_completeness(present)
        assert set(missing) == {"完整性检查", "常见错误模式", "逻辑一致性检查", "每日信号审阅清单"}

    def test_empty_present(self):
        missing = check_domain_completeness([])
        assert len(missing) == 21

    def test_extra_domains_ignored(self):
        present = ["市场判断", "做T", "非必需领域X"]
        missing = check_domain_completeness(present)
        assert "非必需领域X" not in missing
        assert "市场判断" not in missing

    def test_custom_required(self):
        missing = check_domain_completeness(["做T"], required=["做T", "事件套利"])
        assert missing == ["事件套利"]

    def test_unknown_domain_not_in_required_ok(self):
        """未知领域（如 自动化执行规范）不算必需缺失。"""
        missing = check_domain_completeness(["自动化执行规范"])
        assert "自动化执行规范" not in missing


# ============================================================
# compute_confidence_distribution
# ============================================================

class TestComputeConfidenceDistribution:
    def test_all_mid(self):
        entries = [{"置信度": "中"}] * 4
        dist = compute_confidence_distribution(entries)
        assert dist["高"] == 0
        assert dist["中"] == 4
        assert dist["低"] == 0
        assert dist["total"] == 4
        assert dist["high_pct"] == 0.0
        assert dist["low_pct"] == 0.0

    def test_mixed(self):
        entries = [
            {"置信度": "高"}, {"置信度": "中"}, {"置信度": "低"},
            {"置信度": "中"}, {"置信度": "高"},
        ]
        dist = compute_confidence_distribution(entries)
        assert dist["高"] == 2
        assert dist["中"] == 2
        assert dist["低"] == 1
        assert dist["high_pct"] == 40.0
        assert dist["low_pct"] == 20.0

    def test_empty(self):
        dist = compute_confidence_distribution([])
        assert dist["total"] == 0
        assert dist["high_pct"] == 0.0
        assert dist["low_pct"] == 0.0

    def test_unknown_confidence_not_counted_in_high(self):
        entries = [{"置信度": "中"}, {"置信度": None}, {}]
        dist = compute_confidence_distribution(entries)
        assert dist["total"] == 3
        assert dist["unknown"] == 2
        assert dist["high_pct"] == 0.0

    def test_high_20_percent_boundary(self):
        entries = [{"置信度": "高"}] + [{"置信度": "中"}] * 4
        dist = compute_confidence_distribution(entries)
        assert dist["high_pct"] == 20.0  # 边界：=20% 不触发 <20% 告警

    def test_high_below_20_percent(self):
        entries = [{"置信度": "高"}] + [{"置信度": "中"}] * 9
        dist = compute_confidence_distribution(entries)
        assert dist["high_pct"] == 10.0


# ============================================================
# detect_stale
# ============================================================

def _dated_entry(d: str, name: str = "经验A") -> dict:
    return {"最近更新": d, "name": name}


class TestDetectStale:
    def test_old_entry_stale(self):
        entries = [_dated_entry("2026-01-01", "旧经验")]
        stale = detect_stale(entries, max_days=90, ref_date="2026-09-09")
        assert len(stale) == 1
        assert stale[0]["name"] == "旧经验"

    def test_recent_entry_not_stale(self):
        entries = [_dated_entry("2026-08-15", "新经验")]
        stale = detect_stale(entries, max_days=90, ref_date="2026-09-09")
        assert stale == []

    def test_missing_date_skipped(self):
        entries = [_dated_entry("", "无日期"), {}]
        stale = detect_stale(entries, max_days=90, ref_date="2026-09-09")
        assert stale == []

    def test_exactly_90_days_not_stale(self):
        # 2026-06-11 → 2026-09-09 = 90 天，边界不算过时（>90 才过时）
        entries = [_dated_entry("2026-06-11")]
        stale = detect_stale(entries, max_days=90, ref_date="2026-09-09")
        assert stale == []

    def test_over_90_days_stale(self):
        entries = [_dated_entry("2026-06-10")]
        stale = detect_stale(entries, max_days=90, ref_date="2026-09-09")
        assert len(stale) == 1

    def test_default_ref_date_today(self):
        # 不传 ref_date → 用今天；日期太旧必过时
        entries = [_dated_entry("2000-01-01")]
        stale = detect_stale(entries)
        assert len(stale) == 1


# ============================================================
# apply_t2_update（贝叶斯 T2 置信度更新）
# ============================================================

class TestApplyT2Update:
    def test_verify_mid_to_high_with_2_verifications(self):
        """单次验证事件但累计 2+ 次独立验证 → 中 → 高。"""
        r = apply_t2_update("中", evidence_type="verify", verify_count=2)
        assert r["confidence"] == "高"
        assert r["changed"] is True

    def test_verify_mid_with_1_verification_stays_mid(self):
        """累计 1 次验证 → 中 保持不变（不一次打满）。"""
        r = apply_t2_update("中", evidence_type="verify", verify_count=1)
        assert r["confidence"] == "中"
        assert r["changed"] is False

    def test_verify_high_stays_high(self):
        r = apply_t2_update("高", evidence_type="verify", verify_count=3)
        assert r["confidence"] == "高"
        assert r["changed"] is False

    def test_verify_low_stays_low(self):
        """低置信度单次验证不直接回中（证据不足）。"""
        r = apply_t2_update("低", evidence_type="verify", verify_count=1)
        assert r["confidence"] == "低"
        assert r["changed"] is False

    def test_falsify_mid_to_low(self):
        """单次证伪 → 中 → 低（不删除）。"""
        r = apply_t2_update("中", evidence_type="falsify")
        assert r["confidence"] == "低"
        assert r["changed"] is True
        assert r["status_change"] is None  # 仅降级，不废弃

    def test_falsify_low_to_deprecated(self):
        """低置信度再被证伪 → 状态 deprecated。"""
        r = apply_t2_update("低", evidence_type="falsify")
        assert r["confidence"] == "低"
        assert r["status_change"] == "deprecated"
        assert r["changed"] is True

    def test_falsify_high_to_low(self):
        """高置信度单次证伪 → 低（单次证伪不直接废弃但大幅降级）。"""
        r = apply_t2_update("高", evidence_type="falsify")
        assert r["confidence"] == "低"
        assert r["changed"] is True

    def test_invalid_evidence_type_raises(self):
        """非法路径：未知 evidence_type → ValueError。"""
        import pytest as _pytest
        with _pytest.raises(ValueError):
            apply_t2_update("中", evidence_type="banana")

    def test_invalid_confidence_raises(self):
        """非法路径：未知置信度 → ValueError。"""
        import pytest as _pytest
        with _pytest.raises(ValueError):
            apply_t2_update("极高", evidence_type="verify", verify_count=2)


# ============================================================
# 集成：REQ-009 期望结果场景还原
# ============================================================

class TestReq009Scenario:
    def test_full_workflow_req009(self):
        """还原 09-09 健康检查场景：8 领域缺失 + 40 条全中置信度。

        ① 领域完整性：present 缺 8 项 → missing 恰为 REQ-009 列出的 8 个领域
        ② 置信度健康：40 条全中 → high_pct=0% <20% → 触发验证不足告警
        ③ T2 落地：某条经验 2+ 次独立验证 → 中→高
        ④ 过时检测：旧条目（>90 天）→ stale
        """
        # ① 领域完整性（还原缺失 8 领域：present 覆盖 09-09 已存在条目领域）
        present = [
            "市场判断", "开盘前评估", "数据纪律", "早盘纪律设计", "策略纪律",
            "超跌反弹", "信号设计", "板块机会扫描",
            "跷跷板套利", "跨市场套利",
            "审阅流程", "数据核验清单", "格式标准", "修正原则",
        ]
        missing = check_domain_completeness(present)
        assert set(missing) == {
            "跨市场映射", "宏观数据公布日", "做T", "事件套利",
            "逻辑一致性检查", "完整性检查", "常见错误模式", "每日信号审阅清单",
        }

        # ② 置信度健康（40 条全中 → high_pct 0%）
        entries = [{"置信度": "中"}] * 40
        dist = compute_confidence_distribution(entries)
        assert dist["total"] == 40
        assert dist["high_pct"] == 0.0
        assert dist["high_pct"] < 20.0  # 触发"验证性复盘不足"告警条件

        # ③ T2 落地：2+ 次独立验证 → 中 → 高
        r = apply_t2_update("中", evidence_type="verify", verify_count=2)
        assert r["confidence"] == "高"

        # ④ 过时检测
        stale = detect_stale([{"最近更新": "2026-03-01"}], max_days=90, ref_date="2026-09-09")
        assert len(stale) == 1
