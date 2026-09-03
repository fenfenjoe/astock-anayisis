"""
Staging 生成验证 — 每日复盘 B8 瘦身（从 auto_evening_review.md 11.3 下沉）

校验 staging 文件内容是否正确生成：大小充足 / 含目标执行日期 / 含今日生成标记。
纯函数：不读写磁盘（内容由调用方/prompt 脚本读取后传入）。
"""

import re
from datetime import datetime


def verify_staging_content(content: str, tomorrow: str, today_str: str, path_label: str = '') -> list:
    """校验单份 staging 内容。
    content: 文件内容
    tomorrow: 目标执行日期 'YYYY-MM-DD'（staging 必须包含）
    today_str: 今日日期 'YYYY-MM-DD'（staging 必须含今日生成标记，防止旧文件）
    path_label: 文件标识（用于错误信息）
    返回错误列表（空=通过）。"""
    errors = []

    if len(content) < 500:
        errors.append(f'TOO SMALL: {path_label} 仅 {len(content)} 字符 — staging 生成不完整')
        return errors

    if tomorrow not in content:
        dates = _dates_in(content)
        dates_str = ', '.join(dates[:5]) if dates else '无日期'
        errors.append(f'WRONG DATE: {path_label} 应包含执行日期 {tomorrow}，实际日期: {dates_str}')

    # 今日生成标记（防旧文件未被覆盖）
    has_today = (today_str in content) or ('/'.join(today_str.split('-')[1:]) in content)
    if not has_today:
        dates = _dates_in(content)
        dates_str = ', '.join(dates[:5]) if dates else '无日期'
        errors.append(f'STALE: {path_label} 缺少今日生成日期 {today_str}，可能仍是旧文件未覆盖。文件内日期: {dates_str}')

    return errors


def verify_staging_file(path: str, tomorrow: str, today_str: str) -> tuple:
    """校验单个 staging 文件（读取磁盘）。返回 (errors: list, meta: dict)。"""
    import os
    from datetime import datetime

    meta = {}
    if not os.path.exists(path):
        return [f'MISSING: {path} — 文件不存在，Step 11.1/11.2 可能未执行'], meta

    stat = os.stat(path)
    meta['size_kb'] = round(stat.st_size / 1024, 1)
    meta['chars'] = stat.st_size
    mtime = datetime.fromtimestamp(stat.st_mtime)
    meta['mtime'] = mtime.strftime('%Y-%m-%d %H:%M')
    meta['hours_ago'] = round((datetime.now() - mtime).total_seconds() / 3600, 1)

    errors = verify_staging_content(open(path, encoding='utf-8').read(), tomorrow, today_str, path)

    # mtime 新鲜度（文件修改时间必须在今天）
    if mtime.date() < datetime.strptime(today_str, '%Y-%m-%d').date():
        errors.append(f'STALE_MTIME: {path} 最后修改于 {meta["mtime"]}（{meta["hours_ago"]}h前），不在今天——Step 11.1/11.2未执行！')

    return errors, meta


def _dates_in(content: str) -> list:
    return re.findall(r'\d{4}-\d{2}-\d{2}', content)


def check_review_staging(task_state: dict, staging_results: list, tomorrow: str) -> list:
    """复盘后 staging 新鲜度检查（从 auto_logic_inspect B4 下沉）。
    task_state: 解析后的 task_state dict（tasks.evening_review.status/executed_at/completed_at）
    staging_results: [{path, content, mtime(datetime), size, missing}] 由调用方读取
    tomorrow: 明日日期 'YYYY-MM-DD'
    返回失败列表（空=通过）。evening_review 未完成 → 豁免返回 []。

    BUG-007 修复（2026-09-01）：时间比对基准从 completed_at 改为 executed_at——
    staging 文件在复盘流程 11.1/11.2 生成（发生在 completed_at 之前），mtime < completed_at
    是正常现象，用 completed_at 作基准恒报 STALE 假阳性。正确语义：staging 必须在
    本次复盘开始（executed_at）之后被刷新。executed_at 缺失时跳过时间比对（内容检查仍生效）。"""
    er = task_state.get('tasks', {}).get('evening_review', {})
    if er.get('status') != 'completed':
        return []  # evening_review 未完成，staging 新鲜度豁免

    failures = []
    er_start_time = er.get('executed_at')
    today_str = tomorrow  # 用于"未来日期"判断的基准（明日即最新）

    for r in staging_results:
        if r.get('missing'):
            failures.append(f'MISSING: {r["path"]}')
            continue

        mtime = r.get('mtime')
        if er_start_time and mtime is not None:
            try:
                er_time = datetime.fromisoformat(er_start_time)
                if mtime < er_time:
                    failures.append(
                        f'STALE: {r["path"]} mtime={mtime.strftime("%Y-%m-%d %H:%M")} '
                        f'< evening_review开始={er_start_time}')
                    continue
            except (ValueError, TypeError):
                pass  # 无法解析时间戳，跳过时间比对

        content = r.get('content', '')
        dates = _dates_in(content[:500])
        if tomorrow not in dates:
            future_dates = [d for d in dates if d > today_str]
            if not future_dates:
                failures.append(
                    f'OUTDATED: {r["path"]} 文件内日期={dates[:3]} '
                    f'不含明日({tomorrow})或未来日期，疑似未刷新')

        if r.get('size', 0) < 500:
            failures.append(f'TOO_SMALL: {r["path"]} 仅{r.get("size", 0)}字节，疑似未填充内容')

    return failures


def check_sections(content: str, required_sections: list, min_after_chars: int = 50,
                   path_label: str = '') -> list:
    """检查章节存在性 + 节后非空（从 auto_logic_inspect B1/B2/C1/C2/C3 下沉）。
    required_sections: 章节关键词列表，或 (keyword, desc) 元组列表（desc 用于错误信息）
    返回错误列表（空=通过）。"""
    failures = []
    for item in required_sections:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            section, desc = item[0], item[1]
        else:
            section, desc = item, item
        if section not in content:
            failures.append(f'MISSING: 「{desc}」({section})')
        else:
            idx = content.index(section)
            after = content[idx + len(section):idx + len(section) + 500]
            if len(after.strip()) < min_after_chars:
                failures.append(f'EMPTY: 「{desc}」({section})')
    return failures


def _section_after(content: str, keyword: str) -> str:
    """定位含 keyword 的章节之后的文本（直到下一个标题或结尾）。

    定位优先级：① 标题行（行首 #，如 `### 9/1 核心变量`）→ ② 独立短行（如 `核心变量`）。
    回退规则要求该行去除空白后长度接近 keyword（≤ keyword 长度+12），避免命中正文长句
    （BUG-011：核心教训正文含"仍是核心变量"导致裸 split 切分点错误）。
    返回空串 = 未定位到章节。
    """
    lines = (content or '').split('\n')
    start = None
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith('#') and keyword in s:
            start = i + 1
            break
    if start is None:
        for i, line in enumerate(lines):
            s = line.strip().lstrip('#').strip()
            if keyword in s and len(s) <= len(keyword) + 12:
                start = i + 1
                break
    if start is None:
        return ''
    out = []
    for line in lines[start:]:
        if line.strip().startswith('#'):
            break
        out.append(line)
    return '\n'.join(out)


def check_lessons_and_vars(content: str, min_lessons: int = 2, min_vars: int = 3) -> list:
    """复盘 staging 核心教训≥2 / 核心变量≥3 检查（从 B2 下沉）。

    BUG-011 修复（2026-09-01）：
    - 章节定位改为标题行优先（`### 9/1 核心变量`），杜绝正文"核心变量"字样干扰切分
    - 变量计数正则支持 `- 🔑 **` 前缀（8/31 起 staging 用 🔑 标记核心变量）"""
    failures = []
    lesson_text = _section_after(content, '核心教训')
    if lesson_text:
        lesson_count = len(re.findall(r'^\s*\d+\.\s*\*\*', lesson_text, re.M))
        if lesson_count < min_lessons:
            failures.append(f'核心教训不足: 仅{lesson_count}条（需要≥{min_lessons}条）')
    var_text = _section_after(content, '核心变量')
    if var_text:
        var_count = len(re.findall(r'^\s*-\s*(?:🔑\s*)?\*\*', var_text, re.M))
        if var_count < min_vars:
            failures.append(f'核心变量不足: 仅{var_count}个（需要≥{min_vars}个）')
    return failures


def check_etf_code_names(config_content: str, staging_content: str, path_label: str = '') -> list:
    """ETF 代码-名称交叉校验（staging vs config/持仓.md，从 B3 下沉）。"""
    code_to_name = {}
    for line in config_content.split('\n'):
        parts = [p.strip() for p in line.split('|')[1:-1]]
        if len(parts) >= 2 and parts[1].isdigit() and len(parts[1]) == 6:
            code_to_name[parts[1]] = parts[0]

    errors = []
    for line in staging_content.split('\n'):
        parts = [p.strip() for p in line.split('|')[1:-1]]
        if len(parts) >= 2 and parts[1].isdigit() and len(parts[1]) == 6:
            code = parts[1]
            name_in_config = code_to_name.get(code)
            if name_in_config and parts[0] != name_in_config:
                errors.append(f'{path_label}: 代码{code} staging="{parts[0]}" config="{name_in_config}"')
    return errors
