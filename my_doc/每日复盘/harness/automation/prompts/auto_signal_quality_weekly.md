# 信号质量周报（每周三收盘后）

> 触发：每周三 16:30（task_schedule.json: signal_quality_weekly）| 上周五触发的信号 T+3=本周三，上周数据完整

## 一、数据读取

读取**云库 `signal_tracking` 表**（`lib/signal_tracking_cloud.load_signals`，云库不可达降级本地 JSON 缓存），统计**上周一至上周五触发**的信号（`trigger_date` 在上周区间）。

## 二、周度指标（调用 lib/signal_quality.py）

```bash
python -X utf8 -c "
import json, sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.signal_quality import generate_quality_dashboard
from lib.signal_tracking_cloud import load_signals
from datetime import date
signals = load_signals()  # 云库优先，本地 JSON 兜底
# 上周信号（按 trigger_date 过滤，上周一~周五）
import datetime
today = date.today()
last_mon = today - datetime.timedelta(days=today.weekday() + 7)
last_fri = last_mon + datetime.timedelta(days=4)
week = [s for s in signals if last_mon.isoformat() <= s.get('trigger_date','') <= last_fri.isoformat()]
settled = [s for s in week if s.get('status') == 'settled']
print(json.dumps(generate_quality_dashboard(week, settled, today.isoformat()), ensure_ascii=False, indent=1))
print('上周信号数:', len(week), '已结算:', len(settled))
" 2>&1
```

## 三、周报输出（reports/weekly/信号质量周报.md）

1. **本周指标表**（同复盘仪表盘：触发率/达成率/盈亏比/方向准确率/持有天数/偏差/期望价值/最大亏损）
2. **P0 执行率（REQ-007）**：读取 `config/p0_tracking.json` 的 `daily`，统计上周 P0 执行率均值 + 连续 <100% 天数；连续 ≥2 日 <100% → P1 级告警（输出到周报头部）。调用 `lib/p0_tracking.check_p0_alert`
3. **信号价值排名**：按 `pnl` 排序已结算信号，标记 TOP 值得保留的信号类型 vs 该淘汰的
4. **环比上周**：与上周周报指标对比（读上一份周报或累计值）
5. **校准建议**：
   - P1 周触发率 <40% → 条件过严/类型需调整的具体建议
   - 目标达成率 <50% → 目标价设定校准
   - 预期vs实际偏差 → 生成者校准
   - 保留/淘汰/调整信号类型决策（如"农业延续验证类信号已连续 N 周 0 触发，建议移除"）
6. **沉淀经验**：将可复用结论按**事件驱动**沉淀到 OpenViking（本会话 peer=xiaoman）——
   - 触发 T1（新规律：本周信号质量揭示新的信号设计规律）→ `viking_remember`（category=experiences，
     按 `_schema.md` 模板：领域=信号设计，置信度默认中，证据链记本周指标）；
   - 触发 T2（旧信号设计经验被本周数据证伪/校准）→ 更新对应条目证据链 + 贝叶斯置信度；
   - 两者皆无 → 跳过；
   - 过渡期镜像：写入 OpenViking 后同步追加到本地 `harness/experience/投资经验.md` 信号设计章节。
