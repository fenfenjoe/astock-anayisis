# 进化周报（每周五收盘后）

> 触发：每周五 17:30（task_schedule.json: evolution_weekly）| 自进化框架周度全景
> 产出：`my_doc/每日复盘/reports/weekly/{YYYY-MM-DD}_进化周报.md`（机器解析/阅读；2026-10 回退：仅 .md，Dashboard 以 markdown 渲染）
> 内容六节：指标概览 / 目标进度 / REQ进展 / 对照验证 / 负反馈 / 下周建议

## 一、数据准备（必须执行，禁止凭推理模拟）

```bash
python -X utf8 -c "
import json, sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.evolution_report import build_evolution_report, render_markdown
from lib.signal_quality_history import load_history as load_sq
from lib.report_quality import load_scores as load_rq
from lib.gap_analysis import parse_goals
from datetime import date

today = date.today().isoformat()
goals = parse_goals(open('evolution/config/goals.md', encoding='utf-8').read())
sq = load_sq()
rq = load_rq()

# REQ 列表：从 steering/open/ 扫描（含状态）
import os
reqs = []
for d in ['my_doc/每日复盘/harness/automation/steering/open']:
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if f.startswith('REQ-'):
                txt = open(os.path.join(d, f), encoding='utf-8').read()
                m = __import__('re').search(r'状态\*{0,2}[:：]\s*\*{0,2}([A-Z_]+)', txt)
                reqs.append({'id': f.replace('.md',''), 'title': f, 'status': m.group(1) if m else 'UNKNOWN'})

# 验证日志：从 automation/logs/ 扫描最近 REQ 验证记录（简化：空，由 Agent 从 REQ 处理记录补）
verifications = []

report = build_evolution_report(goals, sq, rq, reqs, verifications, today=today)
md = render_markdown(report)
open(f'my_doc/每日复盘/reports/weekly/{today}_进化周报.md', 'w', encoding='utf-8').write(md)
print('进化周报 md 已生成，六节数据:')
print('  gaps:', [(g['id'], g['status'], g.get('gap')) for g in report['gaps']])
print('  req_stats:', report['req_stats'])
print('  feedback:', report['feedback'])
print('  suggestions:', len(report['suggestions']))
"
```

## 二、对照验证补全（P2：到期 REQ 前后对比）

> 扫描 IMPLEMENTED 状态的 REQ，用 `lib.req_evolution` 的 `due_for_verification` 判断观察期是否到期；
> 到期的用 `evaluate_improvement` 做前后对比，把结果**追加进验证日志**（供负反馈追踪）。

```bash
python -X utf8 -c "
import sys, os, re
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.req_evolution import parse_evolution_fields, due_for_verification, evaluate_improvement, suggest_action
from lib.signal_quality_history import load_history
from lib.report_quality import load_scores
from datetime import date

sq = load_history(); rq = load_scores(); today = date.today().isoformat()
open_dir = 'my_doc/每日复盘/harness/automation/steering/open'
for f in sorted(os.listdir(open_dir)):
    if not f.startswith('REQ-'): continue
    txt = open(os.path.join(open_dir, f), encoding='utf-8').read()
    st = re.search(r'状态\*{0,2}[:：]\s*\*{0,2}([A-Z_]+)', txt)
    if not st or st.group(1) != 'IMPLEMENTED': continue
    ev = parse_evolution_fields(txt)
    impl = re.search(r'实施日期\*{0,2}[:：]\s*\*{0,2}(\d{4}-\d{2}-\d{2})', txt)
    if not impl or not ev['observation_weeks'] or not due_for_verification(impl.group(1), ev['observation_weeks'], today):
        continue
    # 前后对比（用信号质量历史或报告质量，按 ev['field']）
    before, after = ev['baseline'], None
    if ev['source'] is None and ev['field']:
        pass  # 简化：基线用 REQ 里的基线值；after 从历史快照取近 4 周均值
    print(f'REQ {f[:-3]}: 观察期到期，需前后对比验证（baseline={ev[\"baseline\"]}）')
"
```

> Agent 注意：上一步输出"观察期到期"的 REQ，用真实历史快照做 before/after 对比
> （`evaluate_improvement`），把结果 `{req_id, eval_result}` 追加进进化周报"四、对照验证结果"，
> 并同步到 REQ 文件处理记录。

## 四、验证（必须）

```bash
python -X utf8 -c "
import os
from datetime import date
d = date.today().isoformat()
md = f'my_doc/每日复盘/reports/weekly/{d}_进化周报.md'
ok = True
if not os.path.exists(md): print('❌ 进化周报.md 缺失'); ok = False
else: print(f'✅ 进化周报.md: {md} ({os.path.getsize(md)} bytes)')
print('进化周报产出', 'OK' if ok else 'FAIL')
"
```

> 📄 **输出说明（2026-10 回退）**：进化周报仅产出 `.md`（Dashboard 以 markdown 渲染），
> 不再产出 `.html` 版本；scheduler 已恢复 markdown 优先入库（无需人工操作）。
