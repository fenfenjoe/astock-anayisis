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
    task_state: 解析后的 task_state dict（tasks.evening_review.status/completed_at）
    staging_results: [{path, content, mtime(datetime), size, missing}] 由调用方读取
    tomorrow: 明日日期 'YYYY-MM-DD'
    返回失败列表（空=通过）。evening_review 未完成 → 豁免返回 []。"""
    er = task_state.get('tasks', {}).get('evening_review', {})
    if er.get('status') != 'completed':
        return []  # evening_review 未完成，staging 新鲜度豁免

    failures = []
    er_completed_time = er.get('completed_at')
    today_str = tomorrow  # 用于"未来日期"判断的基准（明日即最新）

    for r in staging_results:
        if r.get('missing'):
            failures.append(f'MISSING: {r["path"]}')
            continue

        mtime = r.get('mtime')
        if er_completed_time and mtime is not None:
            try:
                er_time = datetime.fromisoformat(er_completed_time)
                if mtime < er_time:
                    failures.append(
                        f'STALE: {r["path"]} mtime={mtime.strftime("%Y-%m-%d %H:%M")} '
                        f'< evening_review完成={er_completed_time}')
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
