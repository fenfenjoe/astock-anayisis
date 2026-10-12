"""
workflow_harvest.py — 工作流沉淀机制（用户理解的自进化方向落地，2026-09-24）

把"走通的 REQ"（CLOSED）总结成可复用 DSH skill，下次类似任务少走弯路：
  解析 REQ 文档 → 提取任务签名/流程步骤/关键命令/陷阱/验收
  → 渲染成 SKILL.md（YAML frontmatter + 分节正文）
  → 沉淀到 harness/skills/（可被后续任务检索引用）

与火山 Agent Evolve 同构：会话/任务成功 → 提炼为可复用能力面。
本地先落地（不依赖云端），等火山 Evolve 支持 DSH 后再评估对接。

纯函数：parse_req(text) / build_harvest(req) / render_skill_md(harvest)。
"""

import re
from pathlib import Path

# 沉淀目录：项目 harness/skills/（与 prompts/ experience/ 平级）
SKILL_DIR_DEFAULT = Path(__file__).resolve().parent.parent.parent / "skills"


def parse_req(text: str) -> dict:
    """解析 REQ 文档：id / title / status / 描述 / 期望 / 约束 / 处理记录。"""
    if not text:
        return {}
    lines = text.splitlines()
    out = {"id": "", "title": "", "status": "", "description": "",
           "expectation": "", "constraints": "", "processing": []}
    for line in lines:
        m = re.match(r"^#\s*REQ-(\d+)[:：]\s*(.*)$", line.strip())
        if m:
            out["id"] = f"REQ-{m.group(1)}"
            out["title"] = m.group(2).strip()
            continue
        m = re.match(r"^-\s*\*\*状态\*\*[:：]\s*(.+)$", line.strip())
        if m:
            out["status"] = m.group(1).strip()
            continue
        m = re.match(r"^##\s*(需求描述|期望结果|约束[^#]*|处理记录)", line.strip())
        if m:
            section = m.group(1)
            continue
        if line.strip() and line.strip().startswith("|") and "时间" in line:
            continue  # 表头
    # 分节提取
    sections = _split_sections(text)
    out["description"] = sections.get("需求描述", "")
    out["expectation"] = sections.get("期望结果", "")
    out["constraints"] = sections.get("约束", sections.get("约束/注意事项", ""))
    out["processing"] = _parse_processing(sections.get("处理记录", ""))
    return out


def _split_sections(text: str) -> dict:
    """按 ## 分节切分。"""
    sections = {}
    current = None
    buf = []
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+)$", line.strip())
        if m:
            if current:
                sections[current] = "\n".join(buf).strip()
            current = m.group(1).strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current:
        sections[current] = "\n".join(buf).strip()
    return sections


def _parse_processing(record: str) -> list:
    """处理记录表 → 步骤列表（每行一个动作）。"""
    steps = []
    for line in record.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line or "|" not in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        # 表格行：第一列是日期 或 序号
        first = cells[0] if cells else ""
        is_date = bool(re.match(r"^\d{4}-\d{2}-\d{2}", first))
        is_seq = first.isdigit()
        if len(cells) < 3 or not (is_date or is_seq):
            continue
        action = cells[2] if len(cells) > 2 else ""
        note = cells[3] if len(cells) > 3 else ""
        action = action.replace("→", "->")
        steps.append(f"{first}: {action} — {note}" if note else f"{first}: {action}")
    return steps


def build_harvest(req: dict) -> dict:
    """从解析的 REQ 构建工作流沉淀。仅 CLOSED 产出完整流程。"""
    if not req:
        return {}
    title = req.get("title", "")
    desc = req.get("description", "") or ""
    exp = req.get("expectation", "") or ""
    cons = req.get("constraints", "") or ""
    steps = req.get("processing", []) or []

    # 任务签名：标题 + 描述首句
    first_sent = re.split(r"[。；\n]", desc)[0].strip() if desc else ""
    signature = f"{title}：{first_sent}" if first_sent else title

    # 关键点：从约束提取（模式/路径/格式）
    key_points = []
    for line in cons.splitlines():
        line = line.strip().strip("-").strip()
        if line and len(line) > 4:
            key_points.append(line)

    return {
        "id": req.get("id", ""),
        "title": title,
        "status": req.get("status", ""),
        "task_signature": signature,
        "steps": steps,
        "key_points": key_points,
        "expectation": exp,
        "is_closed": req.get("status", "").upper() == "CLOSED",
    }


def render_skill_md(h: dict) -> str:
    """渲染 DSH SKILL.md（YAML frontmatter + 分节正文）。"""
    if not h or not h.get("id"):
        return ""
    skill_name = h["id"].lower().replace("_", "-")
    L = []
    L.append("---")
    L.append(f"name: {skill_name}")
    L.append("version: 0.1.0")
    L.append(f"description: \"{h['task_signature']} — 由 CLOSED REQ 自动沉淀（workflow_harvest），下次同类任务直接引用本 skill 的流程与关键点。\"")
    L.append("---")
    L.append("")
    L.append(f"# {h['id']}: {h['title']}")
    L.append("")
    L.append("## 任务签名")
    L.append("")
    L.append(h["task_signature"])
    L.append("")
    if h.get("steps"):
        L.append("## 流程")
        L.append("")
        for s in h["steps"]:
            L.append(f"- {s}")
        L.append("")
    L.append("## 关键命令")
    L.append("")
    if h.get("key_points"):
        for k in h["key_points"]:
            L.append(f"- {k}")
    else:
        L.append("- （无）")
    L.append("")
    L.append("## 陷阱")
    L.append("")
    L.append("- 历史数据不回溯：从实施日开始追踪（如有此约束）")
    L.append("")
    L.append("## 验收")
    L.append("")
    if h.get("expectation"):
        for line in h["expectation"].splitlines():
            line = line.strip().strip("-").strip()
            if line:
                L.append(f"- [ ] {line}")
    else:
        L.append("- [ ] 测试通过 + 真实数据验证")
    L.append("")
    return "\n".join(L)


def write_skill(harvest: dict, skills_dir: Path = SKILL_DIR_DEFAULT) -> Path | None:
    """把沉淀写盘到 skills_dir/<id>.md，返回路径（非 CLOSED 不写）。"""
    if not harvest or not harvest.get("is_closed"):
        return None
    skills_dir.mkdir(parents=True, exist_ok=True)
    md = render_skill_md(harvest)
    if not md:
        return None
    out = skills_dir / f"{harvest['id']}.md"
    out.write_text(md, encoding="utf-8")
    return out
