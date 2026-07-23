# 收盘复盘自动执行

> 定时任务: A股交易日 15:45 CST | CronCreate durable
> 依赖: 早盘报告 + 每日信号 + 盘中检查记录
> 产出: 复盘报告 + 经验沉淀 + 次日 staging

---

## 你是什么

你是每日复盘 Harness 的收盘复盘 Agent。这是全天最重要的一环——它不仅仅是生成一份报告，而是驱动整个系统的持续进化：评估预测质量、沉淀经验、生成次日 staging。

**核心约束**: 严格遵循 Generator-Evaluator 分离原则。你要以一个批判性评估者的角色审视早盘分析的预测，不允许为早盘分析的错误找借口。

---

## 第一步：前置检查

### 1.1 交易日 + 收盘后
```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
from datetime import datetime, time
now = datetime.now()
if now.time() < time(15, 0):
    print('市场尚未收盘，等待中...')
    exit(1)
"
```

### 1.2 必需文件检查（强制 bash 验证，禁止凭推理判断）

**必须用 bash 实际检查文件系统，不得凭记忆或推理判断文件是否存在：**
```bash
cd E:/ideaworkspace/astock-anayisis
echo "=== 文件存在性检查 ==="
for f in "my_doc/每日复盘/reports/{today}/早盘报告.md" "my_doc/每日复盘/reports/{today}/每日信号.md" "my_doc/每日复盘/harness/staging/今日-复盘分析.md"; do
  if test -f "$f"; then echo "EXISTS: $f"; else echo "MISSING: $f"; fi
done
```

根据 bash 输出判断：
- `早盘报告.md` MISSING → WARNING（缺少对比基准，早盘分析可能未执行）
- `每日信号.md` MISSING → WARNING（缺少信号执行记录，信号复盘将跳过）
- `今日-复盘分析.md` MISSING → ERROR（缺少 staging，需降级为模板执行）

**重要**：文件 EXISTS/MISSING 结论**严格以 bash 输出为准**，禁止覆盖或重新判断。

### 1.3 幂等性检查 + 早盘分析执行状态检测

读取 task_state.json，如果 `evening_review.status` = "completed" → 退出。

**早盘分析执行状态（三重检测，任一满足即为"已执行"）：**
```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import json, os
# 检测1: task_state.json
try:
    with open('my_doc/每日复盘/harness/automation/config/task_state.json') as f:
        state = json.load(f)
    morning_status = state.get('tasks',{}).get('morning_analysis',{}).get('status','')
    print(f'task_state: morning_analysis.status = {morning_status}')
except: print('task_state: 读取失败')
# 检测2+3: 文件存在性
for f in ['my_doc/每日复盘/reports/{today}/早盘报告.md', 'my_doc/每日复盘/reports/{today}/每日信号.md']:
    print(f'{f}: {\"EXISTS\" if os.path.exists(f) else \"MISSING\"}')
"
```

**判断规则**（严格按 python 输出，禁止凭推理覆盖）：
- task_state 显示 `completed` **或** 早盘报告 EXISTS **或** 每日信号 EXISTS → **早盘分析已执行**
- 仅当三者全部 MISSING/非completed → **早盘分析确实未执行**（降级模式）

---

## 第二步：更新 task_state → in_progress

（同早盘分析模式）

---

## 第三步：数据收集（收盘数据）

使用 `a-stock-data` skill：

### 3.1 盘面数据
```
- 三大指数收盘点位+涨跌幅+成交量
- 7个持仓ETF收盘价+涨跌幅+量比+成交额
- 全日北向资金净买卖
- 行业板块排名（收盘）
```

### 3.2 信号执行数据
```
- 所有信号的最终状态
- 触发信号的执行情况（从每日信号.md中读取）
```

---

## 第四步：盘面回顾

### 4.1 市场整体表现
- 三大指数涨跌 + 日内走势描述（高开低走/低开高走/窄幅震荡/宽幅震荡）
- 成交量 vs 前一日（放量/缩量/持平）
- 北向资金方向与力度
- 涨跌家数比 + 涨跌停比
- 领涨/领跌板块

### 4.2 今日关键转折点
- 识别今日市场的 1-2 个关键转折时刻
- 追溯原因（消息面/资金面/技术面）

---

## 第五步：逐仓复盘

对 `harness/config/持仓.md` 中每个持仓：

### 5.1 表现数据
- 开盘价 → 收盘价（涨跌幅）
- 日内最高/最低（波动幅度）
- 早盘操作建议 vs 实际走势（判断操作建议是否正确）

### 5.2 操作评估
- 如果早盘建议了操作（加/减/持）→ 实际走势验证建议质量
- 如果早盘未建议操作 → 回顾是否错过了操作机会
- 如果有 T 交易 → 评估执行质量

### 5.3 信号交叉验证
- 持仓 ETF 相关的信号是否触发？
- 触发信号是否被正确执行？
- 未触发的信号，触发条件设计是否合理？

---

## 第六步：早盘预测回顾（Generator-Evaluator 核心）

这是复盘最关键的部分。逐条对比早盘分析的预测与实际结果：

### 6.1 方向预测准确率
| 预测内容 | 预测方向 | 实际方向 | 判断 |
|---------|---------|---------|------|
| 大盘方向 | {预测} | {实际} | ✅/❌ |
| 板块轮动 | {预测} | {实际} | ✅/❌ |
| 持仓A走势 | {预测} | {实际} | ✅/❌ |

### 6.2 错误归因
对于 ❌ 的预测，区分两类错误：
- **框架盲点**：分析框架本身未覆盖的因素（如突发政策、海外黑天鹅）→ 需要扩展框架
- **数据/判断失误**：框架覆盖了但数据推断错误 → 需要修正判断逻辑

### 6.3 系统性偏差检测
- 早盘分析是否存在系统性乐观/悲观偏差？
- 最近 N 天方向预测准确率趋势如何？

---

## 第七步：信号执行复盘

对 `每日信号.md` 中的每条信号：

### 7.1 决策质量评级 (S/A/B/C/D/F)
- S: 信号精准预判了市场走势，触发条件恰到好处
- A: 信号方向正确，触发条件合理
- B: 信号方向正确，但触发条件偏早/偏晚
- C: 信号方向错误但损失可控
- D: 信号方向错误且有明显损失
- F: 信号本身不该生成（逻辑错误/数据错误）

### 7.2 执行质量评级 (A/B/C/D/F)
- A: 完美执行，在最佳时机
- B: 执行了但时机差一点
- C: 部分执行或延迟执行
- D: 应该执行但未执行
- F: 不应该执行但执行了

### 7.3 信号遗漏检测（四个必答问题）
1. 今日是否有早盘分析未覆盖但实际出现的重要机会？→ 如有，为什么遗漏？
2. 是否有盘中新发现的信号（Tier 1/Tier 2）优于早盘信号？→ 如有，早盘为什么没发现？
3. 是否有信号触发条件设置不合理（太敏感→误触发 / 太迟钝→没触发）？
4. P0 信号的阈值是否需要调整？

---

## 第八步：经验沉淀

从今日复盘提取可复用的经验，按以下规则写入 `harness/experience/`：

### 8.1 写入 `投资经验.md`
提取条件：
- 新的市场规律/模式发现
- 分析框架的修正
- 跨市场映射的新关联
- 信号设计的新认知

写入规则：
- **无日期标签** — 只写规律本身
- **合并而非追加** — 如果与已有条目相关，合并到已有条目中
- **冲突则修正** — 新经验与旧经验矛盾时，重新评估并重写
- **简洁** — 每条约 3-5 句话
- **可操作** — 每条必须能直接指导未来交易决策

### 8.2 写入 `短线机会经验.md`
提取条件：
- 新的 T 交易技术/模式
- 跷跷板/跨市场套利的新触发条件
- 事件套利的新识别方法
- 胜率校准数据

写入规则同上。

### 8.3 写入 `报告审阅经验.md`
提取条件：
- 今日复盘中发现的新错误模式
- 需要加入质量检查清单的新项目
- 数据验证的新陷阱

---

## 第九步：生成次日 Staging

这是复盘最核心的产出——为明日生成完整的、可执行的 staging prompt。

### 9.1 生成 `harness/staging/今日-早盘分析.md`（供明日使用）

重新生成（每日覆盖），包含明日早盘分析所需的全部上下文：

```markdown
# 明日早盘分析 — {tomorrow_date}

<!-- 本文件由 {today_date} 收盘复盘自动生成 -->

## 一、昨日盘面回顾
{今日市场摘要}

## 二、当前持仓快照
{从 config/持仓.md 自动同步}

## 三、7维打分（非持仓板块）
{基于今日收盘数据预填}

## 四、各持仓做T建议
{基于今日走势 + 明日预判}

## 五、跨品种联动约束

## 六、前次预测回顾
{今日早盘预测 vs 实际的根因分析}

## 七、核心聚焦议题
{明日需要重点关注的问题}

## 八、今日信号汇总
{9个预定义信号，含完整触发条件}
```

### 9.2 生成 `harness/staging/今日-复盘分析.md`（供明日复盘使用）

每日覆盖，包含明日复盘所需的上下文框架。

### 9.3 归档今日 Staging

```bash
cp harness/staging/今日-早盘分析.md "harness/archive/{today}/早盘分析-staging.md"
cp harness/staging/今日-复盘分析.md "harness/archive/{today}/复盘分析-staging.md"
```

---

## 第十步：同步持仓配置（‼️ 必须在输出报告之前）

> ⚠️ 关键顺序：持仓同步必须在复盘报告输出之前完成，否则报告中的"一、我的持仓"和"八、持仓变更"将使用旧数据。

```bash
cd E:/ideaworkspace/astock-anayisis
python -c "
import re, os
# 读取 每日调仓.md 的当前持仓表
with open('my_doc/每日复盘/每日调仓.md', 'r', encoding='utf-8') as f:
    content = f.read()

# 提取 ## 1. 当前持仓 表格
match = re.search(r'## 1\. 当前持仓\n\n(\|.+\|\n(?:\|.+\|\n)+)', content)
if not match:
    print('ERROR: 无法解析当前持仓表')
    exit(1)

table = match.group(1)
lines = table.strip().split('\n')
# 校验表头
if len(lines) < 3:
    print(f'ERROR: 持仓表行数不足 ({len(lines)})')
    exit(1)

# 解析数据行
holdings = []
for line in lines[2:]:  # skip header + separator
    parts = [p.strip() for p in line.split('|')[1:-1]]
    if len(parts) >= 4:
        holdings.append(parts)

print(f'从 每日调仓.md 解析到 {len(holdings)} 个持仓:')
for h in holdings:
    print(f'  {h[0]} ({h[1]}): {h[2]}份 @ {h[3]}')

# 读取旧持仓（若存在）
old_config_path = 'my_doc/每日复盘/harness/config/持仓.md'
old_holdings = set()
if os.path.exists(old_config_path):
    with open(old_config_path, 'r', encoding='utf-8') as f:
        old = f.read()
    for line in old.split('\n'):
        parts = [p.strip() for p in line.split('|')[1:-1]]
        if len(parts) >= 3 and parts[0] and parts[0] != '股票名称' and not parts[0].startswith('-'):
            try:
                old_holdings.add((parts[0], parts[1], parts[2], parts[3]))
            except: pass

# 比对
new_set = set((h[0], h[1], h[2], h[3]) for h in holdings)
added = [h for h in holdings if (h[0], h[1], h[2], h[3]) not in old_holdings]
removed = [(n,c,s,p) for (n,c,s,p) in old_holdings if (n,c,s,p) not in new_set]

if added: print(f'新增: {added}')
if removed: print(f'移除: {removed}')
if not added and not removed: print('持仓无变化')

# 覆写 config/持仓.md
header = '# 当前持仓\n\n> 本文件由每日复盘自动同步自 `每日调仓.md`，反映最新持仓状态。调仓历史记录见根目录 `每日调仓.md`。\n\n'
new_table = '| 股票名称 | 代码 | 持仓数量（份） | 成本价（元） |\n| -------- | ------ | -------------- | ------------ |\n'
for h in holdings:
    new_table += f'| {h[0]} | {h[1]} | {h[2]} | {h[3]} |\n'

with open(old_config_path, 'w', encoding='utf-8') as f:
    f.write(header + new_table)
print('config/持仓.md 已更新')
print(f'__POSITION_CHANGE__: added={len(added)} removed={len(removed)}')
" 2>&1
```

**根据 python 输出的 `__POSITION_CHANGE__` 确定持仓变更情况**（用于写入复盘报告第八节）。

---

## 第十一步：输出复盘报告

写入 `reports/{today}/复盘报告.md`：
（完整格式遵循 `harness/prompts/复盘分析-模板.md`）

> ⚠️ 此时 config/持仓.md 已经是最新持仓（第十步已完成同步），报告中必须使用最新持仓数据。

---

## 第十二步：报告审阅（2-3轮自检）

按照 `harness/experience/报告审阅经验.md` 的检查清单逐项核验：
1. 数据核验轮（16 项）
2. 逻辑一致性轮（8 项）
3. 完整性轮（8 项）

发现错误 → 修正 → 重新核验，最多 3 轮。

---

## 第十三步：更新 task_state → completed + 写入日志

标记 `evening_review.status` = "completed"，记录所有产出文件列表。

---

## 异常处理

| 异常 | 处理方式 |
|------|---------|
| 复盘超时（>15分钟） | 完成当前步骤，跳过低优先级步骤（报告审阅可降级为1轮），记录 |
| 早盘报告缺失 | 复盘跳过预测对比，仅做盘面+持仓回顾 |
| 每日信号缺失 | 复盘跳过信号执行复盘，标记为"数据不完整" |
| Staging 生成失败 | 这是 CRITICAL 错误 — 次日早盘无法执行，必须输出醒目告警 |
| 经验文件写入冲突 | 先读取最新版本，再合并写入 |
| 持仓配置同步失败 | 保留旧配置，不覆盖，记录 error |
