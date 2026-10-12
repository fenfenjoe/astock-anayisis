"""
进化周报生成器 — P2（自进化框架周度全景）

聚合六节数据 → 周报（markdown 版，供自动化解析 + 人工阅读）：
  一、本周指标概览   （signal_quality + report_quality 近 4 周 vs 目标）
  二、目标达成进度   （每个 goal 的 current/target/gap/status）
  三、REQ 进展       （OPEN/IN_PROGRESS/IMPLEMENTED/CLOSED 统计）
  四、对照验证结果   （到期 REQ 的 before/after/improved/action）
  五、负反馈状态     （连续无改善 REQ → halt，标红）
  六、下周建议       （差距归因 + 定向 REQ 建议）

纯函数：build_evolution_report(data...) → dict；render_markdown(report) → str。
数据源（历史快照/REQ列表/验证日志）由调用方 prompt 传入；本模块不读写磁盘。

（2026-10 回退：不再产出 HTML 版，Dashboard 以 markdown 渲染；历史 HTML 说明已移除。）
"""

from datetime import date


def _gap_of(goals: dict, sq_history: list, rq_history: list, today: str):
    """计算目标差距（复用框架引擎 gaps.compute_gaps）。"""
    import sys
    from pathlib import Path

    _DSH = Path.home() / ".dsh"
    if str(_DSH) not in sys.path:
        sys.path.insert(0, str(_DSH))
    from evolve.engine.gaps import compute_gaps
    return compute_gaps(goals, sq_history, rq_history)


def _req_stats(reqs: list) -> dict:
    total = len(reqs)
    by_status = {}
    for r in reqs:
        st = (r.get('status') or 'UNKNOWN').upper()
        by_status[st] = by_status.get(st, 0) + 1
    return {'total': total, 'by_status': by_status}


def build_evolution_report(goals: dict, sq_history: list, rq_history: list,
                           reqs: list, verifications: list,
                           today: str = None) -> dict:
    """组装进化周报六节数据。"""
    ts = today or date.today().isoformat()
    gaps = _gap_of(goals, sq_history, rq_history, ts)

    # 负反馈（跨轮次）
    import sys
    from pathlib import Path

    _DSH = Path.home() / ".dsh"
    if str(_DSH) not in sys.path:
        sys.path.insert(0, str(_DSH))
    from evolve.engine.verify import track_feedback
    feedback = track_feedback(verifications)

    # 建议（缺口显著 → REQ 建议；halt → 人工裁定）
    suggestions = []
    for g in gaps:
        if g['status'] == 'shortfall' and (g['gap'] or 0) >= 5.0:
            suggestions.append({
                'id': g['id'], 'name': g['name'], 'gap': g['gap'],
                'kind': 'req', 'text': f"目标 {g['name']} 缺口 {g['gap']}，建议创建定向 REQ",
            })
    for rid, st in feedback.items():
        if st['status'] == 'halt':
            suggestions.append({
                'id': rid, 'name': rid, 'gap': None,
                'kind': 'halt',
                'text': f"REQ {rid} 连续 {st['no_improve_streak']} 轮无改善，建议人工裁定回滚/换方向",
            })

    return {
        'date': ts,
        'metrics': {
            'sq': sq_history[-4:],
            'rq': rq_history[-4:],
        },
        'gaps': gaps,
        'req_stats': _req_stats(reqs),
        'verifications': verifications,
        'feedback': feedback,
        'suggestions': suggestions,
    }


def render_markdown(r: dict) -> str:
    """渲染进化周报 markdown（六节）。"""
    L = []
    L.append(f"# 进化周报 · {r['date']}")
    L.append("")
    L.append(f"> 生成时间：{r['date']} ｜ 自进化框架周度全景（结算→差距→REQ→验证→负反馈）")
    L.append("")

    # 一、本周指标概览
    L.append("## 一、本周指标概览")
    L.append("")
    sq = r['metrics']['sq']
    rq = r['metrics']['rq']
    if sq:
        L.append("| 周 | 命中率 | 触发率 |")
        L.append("|----|--------|--------|")
        for s in sq:
            dims = s.get('dims', {}).get('overall', {})
            L.append(f"| {s.get('week_key','')} | {dims.get('target_hit_rate','—')} | {dims.get('trigger_rate','—')} |")
    else:
        L.append("（暂无信号质量快照）")
    L.append("")
    if rq:
        L.append(f"报告质量分（近 {len(rq)} 期）：" + " → ".join(str(x.get('total', '—')) for x in rq))
    else:
        L.append("（暂无报告质量记录）")
    L.append("")

    # 二、目标达成进度
    L.append("## 二、目标达成进度")
    L.append("")
    L.append("| 目标 | 当前 | 目标值 | 缺口 | 状态 |")
    L.append("|------|------|--------|------|------|")
    for g in r['gaps']:
        gap_txt = f"{g['gap']}" if g['gap'] is not None else '—'
        L.append(f"| {g['name']} | {g['current'] if g['current'] is not None else '—'} | "
                 f"{g['target'] if g['target'] is not None else '—'} | {gap_txt} | {g['status']} |")
    L.append("")

    # 三、REQ 进展
    L.append("## 三、REQ 进展")
    L.append("")
    st = r['req_stats']
    L.append(f"REQ 总数：{st['total']} ｜ " + "，".join(f"{k}: {v}" for k, v in sorted(st['by_status'].items())))
    L.append("")

    # 四、对照验证结果
    L.append("## 四、对照验证结果")
    L.append("")
    if r['verifications']:
        L.append("| REQ | 判定 | 建议 |")
        L.append("|-----|------|------|")
        for v in r['verifications']:
            act = {'improved': 'close', 'no_change': 'rollback', 'insufficient': 'extend'}.get(v.get('eval_result'), '—')
            L.append(f"| {v.get('req_id','')} | {v.get('eval_result','')} | {act} |")
    else:
        L.append("（本周无到期 REQ 验证）")
    L.append("")

    # 五、负反馈状态
    L.append("## 五、负反馈状态")
    L.append("")
    if r['feedback']:
        L.append("| REQ | 连续无改善轮次 | 状态 |")
        L.append("|-----|--------------|------|")
        for rid, fb in r['feedback'].items():
            status_txt = "🔴 **halt（建议人工裁定）**" if fb['status'] == 'halt' else "🟢 normal"
            L.append(f"| {rid} | {fb['no_improve_streak']} | {status_txt} |")
    else:
        L.append("（无进行中 REQ 的负反馈记录）")
    L.append("")

    # 六、下周建议
    L.append("## 六、下周建议")
    L.append("")
    if r['suggestions']:
        for s in r['suggestions']:
            L.append(f"- **[{s['kind']}]** {s['text']}")
    else:
        L.append("（无显著差距或负反馈，维持现状观察）")
    L.append("")

    return "\n".join(L)
