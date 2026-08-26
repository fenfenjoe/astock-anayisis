"""
模板一致性检查 — REQ: 每日信号质量闭环 v2.0（B7 架构优化）

检测手动模板/自动化 prompt/SKILL.md 中信号模型关键标记是否一致。
纯函数：不读写磁盘——文件内容由调用方（logic_inspect 脚本）读取后传入。

背景：同一套信号规则曾在 手动模板 + 自动化 prompt + SKILL.md 三处各写一份，
v2.0 同步时自动化层被漏掉（见 progress ledger A 区修复）。本检查让漂移可被自动发现。

按角色分组：
- definer（信号表定义者）：早盘模板/自动化早盘 — 必须含完整 12 列表头 + 核心概念
- consumer（信号表消费者）：盘中/复盘/自动化盘中/自动化复盘/SKILL — 必须含核心概念（不定义表头）
"""

# 核心概念标记（所有文件应有）— v2.0 模型
CORE_MARKERS = [
    '-盘中',        # 盘中追加来源标识
    '预期触发率',   # P1 必填字段
    '目标/止损',    # P1 必填字段
    '关注列表',     # 观察雷达移入早盘报告
]

# 信号表定义标记（仅 definer 应有）— 与早盘模板第九节一致
TABLE_MARKERS = [
    '| 优先级 | 标的 | 触发条件 | 操作类型 | 状态 | 方向 | 紧急度 | 预期触发率 | 目标/止损 | 有效时段 | 仓位 | 信号ID |',
]

# 被检查的文件: (label, path, role)
CHECK_TARGETS = [
    ('早盘模板', 'my_doc/每日复盘/harness/prompts/早盘分析-模板.md', 'definer'),
    ('盘中模板', 'my_doc/每日复盘/harness/prompts/盘中分析-模板.md', 'consumer'),
    ('复盘模板', 'my_doc/每日复盘/harness/prompts/复盘分析-模板.md', 'consumer'),
    ('自动化早盘', 'my_doc/每日复盘/harness/automation/prompts/auto_morning_analysis.md', 'definer'),
    ('自动化盘中', 'my_doc/每日复盘/harness/automation/prompts/auto_intraday_check.md', 'consumer'),
    ('自动化复盘', 'my_doc/每日复盘/harness/automation/prompts/auto_evening_review.md', 'consumer'),
    ('编排层SKILL', '.claude/skills/daily-review-harness/SKILL.md', 'consumer'),
]


def markers_for_role(role: str) -> list:
    """按角色返回应检查的标记集合。"""
    markers = list(CORE_MARKERS)
    if role == 'definer':
        markers.extend(TABLE_MARKERS)
    return markers


def check_markers(content: str, markers: list) -> list:
    """检查单份内容缺失哪些标记。返回缺失标记列表（空=通过）。"""
    return [m for m in markers if m not in content]


def check_consistency(contents: dict, targets: list = None) -> dict:
    """检查多份文件内容的一致性。
    contents: {label: file_content}（label 与 CHECK_TARGETS 的 label 对应）
    targets: 默认 CHECK_TARGETS（(label, path, role) 元组列表）
    返回: {label: {'missing': [...], 'ok': bool}}；所有 ok=True 时 overall=True。"""
    if targets is None:
        targets = CHECK_TARGETS
    result = {}
    for label, _path, role in targets:
        content = contents[label]
        markers = markers_for_role(role)
        missing = check_markers(content, markers)
        result[label] = {'missing': missing, 'ok': not missing}
    all_ok = all(v['ok'] for v in result.values())
    return {'files': result, 'overall': all_ok}


def render_report(consistency: dict) -> str:
    """将一致性检查结果渲染为可读文本（供 logic_inspect 写入报告）。"""
    lines = []
    for label, info in consistency['files'].items():
        if info['ok']:
            lines.append(f"- ✅ {label}: 信号模型标记齐全")
        else:
            lines.append(f"- ❌ {label}: 缺失 {len(info['missing'])} 个标记:")
            for m in info['missing']:
                lines.append(f"    · {m[:60]}")
    lines.append(f"\n**总体: {'✅ 一致' if consistency['overall'] else '❌ 存在漂移（需同步）'}**")
    return '\n'.join(lines)
