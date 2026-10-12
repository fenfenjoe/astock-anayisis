"""
workflow_harvest.py 测试 — 工作流沉淀机制（用户理解的自进化方向落地）

把走通的 REQ（CLOSED）总结成可复用 skill，下次类似任务少走弯路。
覆盖: REQ 解析 → 提取任务签名/流程/关键命令/陷阱/验收 → 渲染 DSH SKILL.md
"""

import sys
from pathlib import Path

import pytest

LIB_DIR = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(LIB_DIR))

from workflow_harvest import (
    parse_req,
    build_harvest,
    render_skill_md,
    SKILL_DIR_DEFAULT,
)


CLOSED_REQ = """# REQ-001: 信号收益追踪系统

- **创建时间**: 2026-07-24
- **优先级**: P1(高)
- **影响范围**: 收盘复盘
- **状态**: CLOSED

## 需求描述

当前每日信号系统缺少跨日收益追踪机制。信号在日内触发/过期后即被归档，
无法追踪触发了的信号实际带来了多少收益。

## 期望结果

- `signal_tracking.json` 持久化追踪所有已触发信号的P&L
- 每日复盘自动更新追踪库，结算到期信号

## 约束/注意事项

- 历史信号不回溯，从实施日开始追踪
- 追踪库使用JSON格式，遵循现有 task_state.json 模式

## 处理记录

| 时间 | 操作 | 备注 |
|------|------|------|
| 2026-07-24 | 创建 | CHAT.md 驱动，方案已完成并实施 |
| 2026-07-24 | 推进→IMPLEMENTED | 代码已实施（signal_tracking.json + auto_evening_review §7.6） |
| 2026-07-27 | 补测 | 创建 lib/signal_tracking.py + tests/test_REQ_001.py (25条测试全部通过) |
| 2026-07-27 | 推进→CLOSED | 测试通过(25/25) + 复盘数据确认功能正常。闭环完成。 |
"""

OPEN_REQ = """# REQ-010: P0 触发后条件反转的"显式放弃"确认交互

- **状态**: OPEN

## 需求描述

待实施。
"""


class TestParseReq:
    def test_parse_closed_req(self):
        r = parse_req(CLOSED_REQ)
        assert r["id"] == "REQ-001"
        assert r["title"] == "信号收益追踪系统"
        assert r["status"] == "CLOSED"

    def test_parse_open_req(self):
        r = parse_req(OPEN_REQ)
        assert r["id"] == "REQ-010"
        assert r["status"] == "OPEN"

    def test_parse_malformed(self):
        assert parse_req("") == {}
        assert parse_req("# no fields")["id"] == ""


class TestBuildHarvest:
    def test_harvest_task_signature(self):
        h = build_harvest(parse_req(CLOSED_REQ))
        assert h["task_signature"]  # 一句话任务签名
        assert "信号" in h["task_signature"] or "追踪" in h["task_signature"]

    def test_harvest_steps_from_processing(self):
        h = build_harvest(parse_req(CLOSED_REQ))
        # 从处理记录提取流程（创建→实施→补测→闭环）
        assert any("创建" in s or "实施" in s or "测试" in s for s in h["steps"])

    def test_harvest_key_commands(self):
        h = build_harvest(parse_req(CLOSED_REQ))
        # 约束里的模式（JSON/task_state.json）应进关键点
        assert any("json" in k.lower() or "task_state" in k.lower() for k in h["key_points"])

    def test_harvest_closed_only(self):
        # OPEN REQ 不产出可执行 skill（缺流程）
        h = build_harvest(parse_req(OPEN_REQ))
        assert not h["steps"]


class TestRenderSkill:
    def test_render_has_frontmatter(self):
        h = build_harvest(parse_req(CLOSED_REQ))
        md = render_skill_md(h)
        assert md.startswith("---")
        assert "name:" in md
        assert "description:" in md

    def test_render_has_sections(self):
        h = build_harvest(parse_req(CLOSED_REQ))
        md = render_skill_md(h)
        assert "## 任务签名" in md
        assert "## 流程" in md
        assert "## 关键命令" in md
        assert "## 陷阱" in md
        assert "## 验收" in md

    def test_render_skill_name_slug(self):
        h = build_harvest(parse_req(CLOSED_REQ))
        md = render_skill_md(h)
        assert "req-001" in md.splitlines()[1]  # name: req-001-信号收益追踪


class TestSkillDir:
    def test_default_dir(self):
        # 默认沉淀目录：项目 harness/skills/
        assert SKILL_DIR_DEFAULT.name == "skills"
