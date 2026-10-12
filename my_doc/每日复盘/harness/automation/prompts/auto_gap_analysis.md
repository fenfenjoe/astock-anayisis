# 差距分析（每周一 12:27）

> 触发：task_schedule.json `gap_analysis`（每周一）
> 角色：**差距分析器（Gap Analyzer）**——连接结算器（P0a/P0b）与改进执行器（REQ）。
> 输入：goals.md 机器结算定义 + 近 4 周历史快照（signal_quality_history / report_quality_history）
> 输出：差距报告（gaps + 定向 REQ 建议）→ 生成定向 REQ 到 steering/open/

## 一、读取目标与历史

```bash
python -X utf8 -c "
import sys, json
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
sys.path.insert(0, 'my_doc/每日复盘/harness/automation/lib')
from gap_analysis import parse_goals, build_gap_report
from signal_quality_history import load_history as load_sq
from report_quality import load_scores as load_rq

goals_md = open('evolution/config/goals.md', encoding='utf-8').read()
goals = parse_goals(goals_md)
sq = load_sq()   # signal_quality_history.json
rq = load_rq()   # report_quality_history.json
report = build_gap_report(goals, sq, rq, min_gap=5.0)
print(json.dumps(report, ensure_ascii=False, indent=1))
print('---')
print('信号质量快照周数:', len(sq), '| 报告质量分数数:', len(rq))
" 2>&1
```

## 二、解读差距报告

对输出中每条 gap：
- **status=shortfall**：缺口 = target - current。缺口 ≥ min_gap（5.0）→ 需进化；缺口小 → 观察
- **status=met**：达标，无需动作
- **status=no_data**：无样本 → 高权重（≥20）目标需排查结算链路；低权重观察

**归因要求**（对要建 REQ 的差距）：
1. 拉该维度近 4 周趋势（同 field 的 weekly 值序列），判断是"持续短板"还是"单周波动"
2. 结合最近一期 `reports/weekly/信号质量周报.md` 的归因结论（如"P0 执行机制失效""早盘退潮周条件未满足"）
3. 持续短板（≥2 周未改善）→ 才建定向 REQ；单周波动 → 不建（防进化噪音）

## 三、生成定向 REQ

按 `my_doc/每日复盘/harness/automation/steering/REQ_TEMPLATE.md` 格式，为每条**持续短板**创建 `REQ-{NNN}.md` 到 `steering/open/`，并更新 `REQ_INDEX.md`：

```markdown
---
title: "[GAP] {目标名} 缺口 {gap}"
priority: P{0|1|2}        # 按权重：≥25% → P0；≥20% → P1；其他 P2
关联指标: {metric id}: {field}
基线值:   {current}       # 近4周均值
预期改善: {target}        # 目标值
---
## 差距背景
{归因：为什么差，趋势证据}

## 预期措施
{1-3 条可执行措施，指向目标方向}

## 验收
{验证器} 该指标达到 {target}，连续 2 周确认
```

- **建单前置检查**（bash）：
  ```bash
  grep -n "REQ-" "my_doc/每日复盘/harness/automation/steering/REQ_INDEX.md" | head -30
  ```
  同主题 OPEN/IN_PROGRESS 已存在 → 只追加处理记录，不重复建单（去重铁律）。
- **编号**：用 `lib.issue_tracker.next_ticket_id` 计算，防撞号。
- **金钱/金融/安全/删除类措施**：`MANUAL_REVIEW` 标记，交人工。

## 三·五、待验证 REQ 对照验证（P2）

> 对 **IMPLEMENTED 且观察期到期** 的 REQ 做前后对比验证，这是进化闭环的"对照验证"环节。

1. **扫描**：读取 `steering/REQ_INDEX.md`，找出状态=IMPLEMENTED 且处理记录含"观察期开始"的 REQ（或人工标记待验证的）。
2. **解析契约**（bash）：
   ```bash
   python -X utf8 -c "
   import sys, json
   sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
   sys.path.insert(0, 'my_doc/每日复盘/harness/automation/lib')
   from req_evolution import parse_evolution_fields
   from signal_quality_history import load_history
   md = open('my_doc/每日复盘/harness/automation/steering/open/REQ-{NNN}.md', encoding='utf-8').read()
   fields = parse_evolution_fields(md)
   sq = load_history()
   print(json.dumps(fields, ensure_ascii=False))
   print('历史周数:', len(sq))
   " 2>&1
   ```
3. **前后对比**：
   - `before` = 基线值（REQ 记录的实施前均值）
   - `after` = `extract_window(sq, field, observation_weeks)`（最近 N 周均值）
   - `eval = evaluate_improvement(before, after, 'higher', expected)`
4. **决策**（suggest_action）：
   - `close` → REQ 状态改 CLOSED，处理记录追加"对照验证：改善（before→after）"，沉淀经验
   - `extend` → 数据不足，处理记录追加"观察期延长 4 周"
   - `rollback` → REQ 标记"无效进化"，处理记录追加"对照验证：无改善（before→after）→ 建议回滚"，**回滚交人工执行**（MANUAL_REVIEW，自动化不改代码）
5. **输出**：差距周报增加"待验证 REQ 表"（REQ / 关联指标 / before / after / 判定 / 动作）

## 四、输出差距周报

写 `my_doc/每日复盘/reports/weekly/差距分析周报.md`：
1. 各目标差距表（id / 名称 / 目标 / 当前 / 缺口 / 状态）
2. 本周建单的定向 REQ 列表（编号 + 标题 + 关联指标 + 基线）
3. 无差距/达标目标一览（说明"维持"）

## 五、执行日志

按惯例写 `automation/logs/gap_analysis_{date}.md`：差距表 + 建单记录 + 未建单原因。
