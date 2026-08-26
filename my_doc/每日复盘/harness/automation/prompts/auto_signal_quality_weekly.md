# 信号质量周报（每周三收盘后）

> 触发：每周三 16:30（task_schedule.json: signal_quality_weekly）| 上周五触发的信号 T+3=本周三，上周数据完整

## 一、数据读取

读取 `config/signal_tracking.json`，统计**上周一至上周五触发**的信号（`trigger_date` 在上周区间）。

## 二、周度指标（调用 lib/signal_quality.py）

```bash
python -X utf8 -c "
import json, sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.signal_quality import generate_quality_dashboard
from datetime import date
db = json.load(open('my_doc/每日复盘/harness/automation/config/signal_tracking.json', encoding='utf-8'))
# 上周信号（按 trigger_date 过滤，上周一~周五）
import datetime
today = date.today()
last_mon = today - datetime.timedelta(days=today.weekday() + 7)
last_fri = last_mon + datetime.timedelta(days=4)
week = [s for s in db['signals'] if last_mon.isoformat() <= s.get('trigger_date','') <= last_fri.isoformat()]
settled = [s for s in week if s.get('status') == 'settled']
print(json.dumps(generate_quality_dashboard(week, settled, today.isoformat()), ensure_ascii=False, indent=1))
print('上周信号数:', len(week), '已结算:', len(settled))
" 2>&1
```

## 三、周报输出（reports/weekly/信号质量周报.md）

1. **本周指标表**（同复盘仪表盘：触发率/达成率/盈亏比/方向准确率/持有天数/偏差/期望价值/最大亏损）
2. **信号价值排名**：按 `pnl` 排序已结算信号，标记 TOP 值得保留的信号类型 vs 该淘汰的
3. **环比上周**：与上周周报指标对比（读上一份周报或累计值）
4. **校准建议**：
   - P1 周触发率 <40% → 条件过严/类型需调整的具体建议
   - 目标达成率 <50% → 目标价设定校准
   - 预期vs实际偏差 → 生成者校准
   - 保留/淘汰/调整信号类型决策（如"农业延续验证类信号已连续 N 周 0 触发，建议移除"）
5. **沉淀经验**：将可复用结论追加到 `harness/experience/投资经验.md` 信号设计章节
