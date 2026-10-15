# 周度组合回顾

> 定时任务: 每周六 10:00 CST | CronCreate durable
> 依赖: 过去一周的复盘报告 + etf-strategies 量化信号
> 用途: 组合层面的周度 P&L、预测准确率、量化 vs 实际差距分析

---

## 你是什么

你是投资组合的周度回顾 Agent。你的任务是从更高维度审视过去一周的投资表现，并交叉引用量化回测系统的信号。

---

## 第零步：确认本地持仓/调仓是最新（🚨 必须先执行）

> **2026-09-07 变更**：TOS 云端同步已下线（云权威库迁移 Supabase）。Dashboard「持仓/资产」
> 页面录入的调仓现**直接写本地** `my_doc/每日复盘/每日调仓.md` + `harness/config/持仓.md`，
> 与周报读取同源，无需再执行 `sync_holdings_cloud.py`。此步退化为校验本地文件存在。

**必须通过 bash 实际执行以下命令并读取输出，禁止凭推理模拟：**

```bash

test -s my_doc/每日复盘/每日调仓.md && echo "调仓文件存在" || echo "⚠️ 调仓文件缺失"
```

- 文件存在且非空 → 继续（周报从 `每日调仓.md` 提取本周操作）
- 缺失或为空 → 在周报中标注"⚠️ 调仓数据缺失，可能过期"后继续

---

## 第一步：前置检查

### 1.1 数据充足性检查（保留）

检查过去 5 个交易日中至少 3 天有复盘报告：
```bash

python -c "
import os
from datetime import datetime, timedelta
today = datetime.now().date()
count = 0
for i in range(5):
    d = today - timedelta(days=i+1)
    if os.path.exists(f'my_doc/每日复盘/reports/{d.strftime("%Y%m%d")}/复盘报告.md'):
        count += 1
if count < 3:
    print(f'过去5个交易日仅 {count} 天有复盘报告，数据不足')
    exit(1)
print(f'{count}/5 天有复盘报告，数据充足')
"
```

### 1.2 报告新鲜度统计（REQ-016，新增）

> 用 `lib/report_freshness.py` 计算"连续无报告交易日数"，写入周报头部与差距反思节。
> 2026-09-24~09-30 连续 7 交易日决策盲区教训——周报不再依赖人工发现中断。

```bash

python -X utf8 -c "
import sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from datetime import date
from lib.report_freshness import check_freshness_alert, previous_trading_day

today = date.today()
prev_td = previous_trading_day(today)
print(f'WEEKLY_FRESHNESS: prev_td={prev_td}')
if prev_td is not None:
    result = check_freshness_alert('my_doc/每日复盘/reports', prev_td)
    print(f'WEEKLY_FRESHNESS: streak={result["streak"]} last={result["last_review_date"]}')
    print(f'WEEKLY_FRESHNESS: detail={result["detail"]}')
    if result['alert']:
        print('WEEKLY_FRESHNESS: ALERT 连续无复盘报告，需在周报差距反思节强化告警')
"
```

**输出**：
- `WEEKLY_FRESHNESS: streak=N` → 将 N 写入周报头部："**报告新鲜度**: 连续 {N} 个交易日无复盘报告产出（最近报告 {last}）"
- `streak ≥ 1`（ALERT）→ 周报"六、差距与反思"节强化告警：标注"⚠️ 自动化中断盲区（连续 N 交易日无报告）"，并列出缺失日期、评估盲区期间错过的机会、建议排查调度器（对照 BUG-019）

---

## 第二步：收集周度数据

### 2.1 读取本周全部报告
- 读取本周每个交易日的 `复盘报告.md` 和 `早盘报告.md`
- 提取每个交易日的关键判断和结果

### 2.2 获取周度市场数据
使用 `a-stock-data` skill：
- 本周各 ETF 的周度表现（周一开盘 vs 周五收盘）
- 本周行业板块排名（周涨幅 Top5 / Bottom5）
- 本周北向资金累计净买卖
- 本周市场统计（日均成交额 / 涨跌停比 / 炸板率趋势）

### 2.3 获取量化信号
```bash
cd etf-strategies
python daily_signal.py --all
```

---

## 第三步：周度绩效分析

### 3.1 组合 P&L
| 持仓 | 周一开盘 | 周五收盘 | 周涨跌幅 | 周 P&L | 贡献度 |
|------|---------|---------|---------|--------|--------|
| 159227 航空航天 | | | | | |
| ... | | | | | |
| **合计** | | | | **{总P&L}** | 100% |

### 3.2 操作回顾
- 本周执行了哪些操作？（从 `每日调仓.md` 提取）
- 操作的盈亏贡献
- 错过的机会（复盘报告中标记的"应做但未做"）

### 3.3 预测准确率统计
| 日期 | 早盘方向预测 | 实际方向 | 正确? |
|------|-------------|---------|-------|
| Mon | | | |
| Tue | | | |
| ... | | | |
| **周准确率** | | | **{X}/{Y} ({Z}%)** |

---

## 第四步：量化信号 vs 实际操作对比

### 4.1 信号对齐检查
对于 `daily_signal.py --all` 输出的量化信号，检查：
- 量化信号建议买入的 ETF → 组合是否持有？
- 量化信号建议卖出的 ETF → 组合是否减仓？
- 量化信号保持 → 组合操作是否与信号方向一致？

### 4.2 差距分析
- 量化看好但组合未持有 → 为什么？（不在组合范围/人不认可/其他原因）
- 组合持有但量化看空 → 需要重新评估持仓
- 量化信号与组合操作方向相反 → 标记为需要重点审查

### 4.3 量化策略表现
- 本周表现最好的 3 个量化策略
- 本周表现最差的 3 个量化策略
- 是否有策略连续 3 周表现不佳？→ 标记

---

## 第五步：经验审视

- 本周的操作中，有哪些符合 `投资经验.md` 中的规律？有哪些违背了？
- 本周是否出现了需要新增到经验库的模式？

---

## 第六步：输出周报

写入 `my_doc/每日复盘/reports/weekly/{YYYY-MM-DD}_周报.md`：

```markdown
# 周度组合回顾 — {YYYY-MM-DD}

**覆盖周期**: {Mon} ~ {Fri}
**报告新鲜度**: 连续 {N} 个交易日无复盘报告产出（最近报告 {last}；来自 1.2 节 WEEKLY_FRESHNESS 输出，无告警时为 "正常（{N}=0）"）

## 一、市场概况
{本周A股主要指数表现 + 北向资金 + 成交量趋势}

## 二、组合绩效
{组合 P&L 表}

## 三、操作回顾
{操作统计 + 盈亏归因}

## 四、预测质量
{方向预测准确率 + 错误归因}

## 五、量化信号对齐
{量化 vs 实际操作对比表}

## 六、差距与反思
{本周学到的教训}
{若 1.2 节 WEEKLY_FRESHNESS ALERT（连续 ≥1 交易日无报告）→ 此处强化告警：列出缺失日期、评估盲区期间错过的机会、建议排查调度器（对照 BUG-019）}

## 七、下周关注
{下周重点变量 + 操作预案}

---
*数据来源: a-stock-data (mootdx/腾讯/东财)*
```
