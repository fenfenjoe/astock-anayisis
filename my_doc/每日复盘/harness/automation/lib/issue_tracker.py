"""
工单（BUG/REQ）创建辅助 — REQ-004: 运行问题工单化

报告生成/自检发现的问题（数据源健康、staging 新鲜度、异常数据等）需要在报告中
简单提示，并提交 BUG/REQ 工单供定时任务（harness_bug_auto_fix / auto_req_implement）
处理。本模块提供纯函数支撑：

- next_ticket_id : 从索引文本计算下一个工单编号（多 Agent 同日建单不撞号）
- dedup_find     : 同主题 OPEN 工单去重查找（防止重复建单）
- render_bug_markdown / render_req_markdown : 按模板渲染工单正文

纯函数：不读写磁盘 —— 索引文本/工单字段由调用方（prompt 中的 bash 脚本）传入。
"""

import re
from datetime import datetime

# BUG 状态集合（与 BUG_INDEX.md 状态口径一致；MANUAL_REVIEW 视为"待处理"，参与去重）
BUG_OPEN_STATUSES = ('OPEN', 'IN_PROGRESS', 'MANUAL_REVIEW')
# REQ 非终态集合（OPEN/IN_PROGRESS 视为待处理）
REQ_OPEN_STATUSES = ('OPEN', 'IN_PROGRESS')


def _parse_id(index_text: str, prefix: str) -> list:
    """从索引文本提取所有 <prefix>-NNN 编号。prefix 如 'BUG' / 'REQ'。"""
    pattern = re.compile(rf'{re.escape(prefix)}-(\d{{1,4}})', re.IGNORECASE)
    nums = []
    for m in pattern.finditer(index_text or ''):
        try:
            nums.append(int(m.group(1)))
        except ValueError:
            continue
    return nums


def next_ticket_id(index_text: str, prefix: str, default: int = 1) -> str:
    """计算下一个工单编号（max 现有编号 + 1）。

    index_text: 索引文件内容（如 BUG_INDEX.md / REQ_INDEX.md 全文）
    prefix: 'BUG' 或 'REQ'
    default: 索引中无任何编号时的起始编号
    返回: f'{prefix}-{NNN:03d}'（NNN 三位，不足补零）。
    """
    nums = _parse_id(index_text, prefix)
    return f'{prefix}-{max(nums) + 1 if nums else default:03d}'


def dedup_find(index_text: str, prefix: str, keywords: list, statuses: tuple = None) -> str:
    """查找索引中是否已有同主题待处理工单（去重）。

    index_text: 索引文件内容
    prefix: 'BUG' 或 'REQ'
    keywords: 主题关键词列表（如 ['数据源', 'push2']）——命中其中任意一个即视为同主题
    statuses: 参与去重的状态集合；None 时默认 BUG 用 OPEN_STATUSES、REQ 用 REQ_OPEN_STATUSES
    返回: 匹配工单 ID（如 'BUG-017'）；无匹配返回 None。
    """
    if statuses is None:
        statuses = BUG_OPEN_STATUSES if prefix.upper() == 'BUG' else REQ_OPEN_STATUSES
    if not index_text:
        return None

    # 按行解析（表格行或列表行），提取 {ID} + {状态}
    for line in (index_text or '').split('\n'):
        if f'{prefix.upper()}-' not in line.upper():
            continue
        id_m = re.search(rf'{re.escape(prefix)}-(\d{{3,4}})', line, re.IGNORECASE)
        if not id_m:
            continue
        ticket_id = f'{prefix}-{int(id_m.group(1)):03d}'
        # 状态：优先取行内 "OPEN/IN_PROGRESS/..." 词元；行内无状态则宽松匹配
        status_m = re.search(r'\b(OPEN|IN_PROGRESS|IMPLEMENTED|CLOSED|FIXED|VERIFIED|WONT_FIX|MANUAL_REVIEW|ADOPTED|REJECTED)\b', line)
        if status_m and status_m.group(1) not in statuses:
            continue
        # 同主题判定：关键词任一命中该行（忽略大小写）
        if any(k and k.lower() in line.lower() for k in keywords if k):
            return ticket_id
    return None


def render_bug_markdown(fields: dict) -> str:
    """按 BUG_TEMPLATE.md 渲染 BUG 工单正文。fields 缺失字段自动降级为默认值。

    必填建议字段: id / title / component / severity / status / auto_fix_eligible /
    found_at / found_by / expected / actual / affected_files
    可选字段: violates / source_req / steps / impact / fix_suggestion / test_evidence / notes
    """
    now = datetime.now().strftime('%Y-%m-%dT%H:%M')
    f = {
        'id': fields.get('id', 'BUG-NNN'),
        'title': fields.get('title', '(未命名问题)'),
        'component': fields.get('component', 'prompts/'),
        'severity': fields.get('severity', 'P2'),
        'violates': fields.get('violates', ''),
        'status': fields.get('status', 'OPEN'),
        'auto_fix_eligible': fields.get('auto_fix_eligible', False),
        'fix_reason': fields.get('fix_reason', ''),
        'found_at': fields.get('found_at', now),
        'found_by': fields.get('found_by', '报告生成自检'),
        'source_req': fields.get('source_req', 'N/A'),
        'expected': fields.get('expected', ''),
        'actual': fields.get('actual', ''),
        'steps': fields.get('steps', []),
        'affected_files': fields.get('affected_files', []),
        'impact': fields.get('impact', ''),
        'fix_suggestion': fields.get('fix_suggestion', ''),
        'test_evidence': fields.get('test_evidence', ''),
        'notes': fields.get('notes', []),
    }
    lines = [
        f'# {f["id"]}: {f["title"]}',
        '',
        f'- **组件**: {f["component"]}',
        f'- **严重程度**: {f["severity"]}',
        f'- **违反的正确性定义**: {f["violates"] if f["violates"] else "无"}',
        f'- **状态**: {f["status"]}',
        f'- **auto_fix_eligible**: {"true" if f["auto_fix_eligible"] else "false"}',
    ]
    if f['fix_reason']:
        lines.append(f'  - 判定理由：{f["fix_reason"]}')
    lines += [
        f'- **发现时间**: {f["found_at"]}',
        f'- **发现方式**: {f["found_by"]}',
        f'- **来源 REQ**: {f["source_req"]}',
        f'- **预期行为**: {f["expected"]}',
        f'- **实际行为**: {f["actual"]}',
        '- **复现步骤**:',
    ]
    for i, step in enumerate(f['steps'] or ['（在报告生成/自检过程中复现）'], start=1):
        lines.append(f'  {i}. {step}')
    lines += ['- **受影响文件**:']
    for af in f['affected_files'] or ['（待定位）']:
        lines.append(f'  - `{af}`')
    lines += [
        f'- **潜在影响**: {f["impact"] if f["impact"] else "影响后续报告生成质量"}',
        f'- **建议修复**: {f["fix_suggestion"] if f["fix_suggestion"] else "（待分析）"}',
        '',
        '## 测试证据',
        '```',
        f'{f["test_evidence"] if f["test_evidence"] else "（暂无自动化测试证据）"}',
        '```',
        '',
        '## 附注',
    ]
    for note in f['notes'] or []:
        lines.append(f'- {note}')
    return '\n'.join(lines)


def render_req_markdown(fields: dict) -> str:
    """按 REQ_TEMPLATE.md 渲染 REQ 工单正文。fields 缺失字段自动降级为默认值。

    必填建议字段: id / title / created_at / priority / scope / status /
    description / expected_result / constraints
    """
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    f = {
        'id': fields.get('id', 'REQ-NNN'),
        'title': fields.get('title', '(未命名需求)'),
        'created_at': fields.get('created_at', now),
        'priority': fields.get('priority', 'P2'),
        'scope': fields.get('scope', '其他'),
        'status': fields.get('status', 'OPEN'),
        'description': fields.get('description', ''),
        'expected_result': fields.get('expected_result', ''),
        'constraints': fields.get('constraints', ''),
    }
    lines = [
        f'# {f["id"]}: {f["title"]}',
        '',
        f'- **创建时间**: {f["created_at"]}',
        f'- **优先级**: {f["priority"]}',
        f'- **影响范围**: {f["scope"]}',
        f'- **状态**: {f["status"]}',
        '',
        '## 开发流程（强制）',
        '',
        '> 本需求实施**必须走 superpowers 流程**。不要在生成需求后直接裸写代码。',
        '',
        '实施时严格按以下顺序执行：',
        '',
        '```',
        '1. brainstorming   — 探索方案空间，不跳入单一实现',
        '2. writing-plans   — 写出详细实施计划（含文件清单、API/数据结构变更）',
        '3. TDD             — 先写测试，再写代码',
        '4. executing-plans — 按计划逐步实施',
        '5. code-review     — 自查 + 修复',
        '```',
        '',
        '**铁律：**',
        '- 禁止跳过 TDD — 没有测试的需求不得推进到 IMPLEMENTED',
        '- 禁止跳过 brainstorming — 不假思索的实现 = 返工',
        '- 涉及 A 股数据的，仍走 `a-stock-data` skill',
        '',
        '## 需求描述',
        '',
        f'{f["description"]}',
        '',
        '## 期望结果',
        '',
        f'{f["expected_result"]}',
        '',
        '## 测试交付物',
        '',
        '> 以下清单在 TDD 步骤（auto_req_implement 第 3 步）中填写，在第 3.5 步门禁中验证。',
        '',
        f'- [ ] 测试文件: `harness/automation/tests/test_{f["id"].replace("-", "_")}.py`',
        '- [ ] TDD 门禁通过: `python -m pytest harness/automation/tests/ -v`',
        '',
        '## 约束/注意事项',
        '',
        f'{f["constraints"] if f["constraints"] else "（无）"}',
        '',
        '## 处理记录',
        '',
        '| 时间 | 操作 | 备注 |',
        '|------|------|------|',
        f'| {now} | 创建 | 报告生成/自检发现，自动提交 |',
    ]
    return '\n'.join(lines)
