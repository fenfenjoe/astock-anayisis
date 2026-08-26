# 早盘分析自动执行

> 定时任务: A股交易日 07:55 CST | CronCreate durable
> 依赖: 前一交易日晚间复盘生成的 staging 文件
> 产出: reports/{today}/早盘报告.md + reports/{today}/每日信号.md
> **{today} 格式**: `yyyyMMdd`（如 `20260727`），不是 `yyyy-MM-dd`！所有 Python 代码中必须用 `date.today().strftime("%Y%m%d")`，禁用 `date.today().isoformat()`

---

## 你是什么

你是每日复盘 Harness 的早盘分析自动执行 Agent。你的任务是在每个 A 股交易日盘前，自动执行完整的早盘分析流程。

**核心约束**: 严格遵循 `daily-review-harness` skill 中定义的早盘分析模式，不做任何创意偏离。

**🚨 强制模块清单（12 节，全部必出，无一例外）：**

| 序号 | 模块 | 核心产出 |
|:---:|------|------|
| 一 | 我的持仓（完整快照表） | 7只标的×8列的完整快照 |
| 二 | 前次预测回顾 | 预判vs实际对比表+准确率 |
| 三 | 海外市场传导 | 三种情景概率预判 |
| 四 | 宏观研判 | 多空因素对照+风险关注 |
| 五 | 资金面与情绪 | 北向/涨停情绪/融资融券/题材 |
| 六 | 板块机会扫描（非持仓） | 七维评分表+🟢→关注列表 |
| 七 | 持仓映射与操作判断 | 七维评分+逐只做T+纪律Checklist |
| 八 | 操作清单 | P0/P1优先级排序 |
| 九 | 跨品种约束检查 | ≥5条跨品种约束判定 |
| 十 | 核心关注时间表 | 09:15→14:30逐节点监控 |
| 十一 | 风险提示 | ≥5条风险 |
| 十二 | 每日信号概览 | 信号摘要+交叉引用 |

**自检铁律：报告输出完毕后立即逐节检查上述 12 个模块是否全部存在。缺失任一模块 → 补充后重新输出。**

---

## 第一步：前置检查（必须全部通过才能继续）

### 1.1 交易日检查
```bash

python my_doc/每日复盘/harness/automation/config/trading_calendar.py --status
```

读取 JSON 输出。
- 如果 `is_trading_day` = false → 输出 "今日非交易日（{原因}），跳过早盘分析" 并**退出**
- 如果是调休工作日（`is_trading_weekend` = true）→ 输出 "今日为调休工作日，正常执行" 并继续

### 1.2 时间窗口检查
- 如果当前时间 < 07:30 CST → 输出 "尚未到早盘分析窗口（7:30-9:30），等待中" 并**退出**（cron 调度不应触发此情况，但保留防御性检查）
- 如果当前时间 > 09:30 CST → 输出 "已过 9:30，早盘分析已无意义" 并**退出**
- 07:30 ~ 09:30 → 正常执行，**始终输出完整 12 节报告，不存在精简版**

### 1.3 Staging 文件存在性检查
检查 `my_doc/每日复盘/harness/staging/今日-早盘分析.md` 是否存在。
- 如果不存在 → 输出 "⚠️ CRITICAL: 缺少 staging 文件，可能昨日复盘未执行。将尝试基于模板 + 今日数据生成早盘（质量可能较低）"
- 如果存在 → 读取文件内容作为执行基础

### 1.3b Staging 代码-名称防卫性校验（防止 159227→恒生科技ETF 类错误传播到报告）

> ⚠️ 即使晚间复盘已校验，此处仍做防卫性检查——防御晚间复盘跳过校验或归档后手动修改引入错误。

```bash

python -c "
import sys
with open('my_doc/每日复盘/harness/config/持仓.md', 'r', encoding='utf-8') as f:
    config = f.read()
code_to_name = {}
for line in config.split('\n'):
    parts = [p.strip() for p in line.split('|')[1:-1]]
    if len(parts) >= 2 and parts[1].isdigit() and len(parts[1]) == 6:
        code_to_name[parts[1]] = parts[0]

try:
    with open('my_doc/每日复盘/harness/staging/今日-早盘分析.md', 'r', encoding='utf-8') as f:
        staging = f.read()
    errors = []
    for line in staging.split('\n'):
        parts = [p.strip() for p in line.split('|')[1:-1]]
        if len(parts) >= 2 and parts[1].isdigit() and len(parts[1]) == 6:
            code = parts[1]
            name_in_staging = parts[0]
            expected = code_to_name.get(code)
            if expected and name_in_staging != expected:
                errors.append(f'{code}: staging=\"{name_in_staging}\" 应为 \"{expected}\"')
    if errors:
        print(f'[FAIL] Staging code-name mismatch ({len(errors)}):')
        for e in errors: print(f'  {e}')
        print('Fix staging file names before running morning analysis')
        sys.exit(1)
    else:
        print('[PASS] Staging code-name validation passed')
except FileNotFoundError:
    print('Staging文件不存在，跳过校验')
" 2>&1
```

**校验失败 → 修正 staging 文件 → 重新校验 → 通过后再继续。不允许带着错误名称生成早盘报告。**

### 1.3c Staging 持仓新鲜度校验（🚨 防止过期持仓传播到报告）

> ⚠️ staging 文件中的持仓表可能是数天前的旧数据。必须与 `config/持仓.md`（权威来源）交叉校验。
> **铁律：config/持仓.md 是持仓数据的唯一权威来源。staging 中的持仓表仅供参考，发现任何差异时以 config/持仓.md 为准。**

```bash

python -c "
import sys, os

errors = []

# 1. 读取权威持仓配置
with open('my_doc/每日复盘/harness/config/持仓.md', 'r', encoding='utf-8') as f:
    config = f.read()

config_holdings = {}
for line in config.split('\n'):
    parts = [p.strip() for p in line.split('|')[1:-1]]
    if len(parts) >= 3 and parts[1].isdigit() and len(parts[1]) == 6:
        config_holdings[parts[1]] = {
            'name': parts[0],
            'shares': parts[2],
            'cost': parts[3]
        }

print(f'config/持仓.md: {len(config_holdings)} 个持仓')
for code, h in config_holdings.items():
    print(f'  {h[\"name\"]} ({code}): {h[\"shares\"]}份 @ {h[\"cost\"]}')

# 2. 读取 staging 内容（日期新鲜度由 1.3d 统一判定）
staging_file = 'my_doc/每日复盘/harness/staging/今日-早盘分析.md'
staging_holdings = {}

if os.path.exists(staging_file):
    with open(staging_file, 'r', encoding='utf-8') as f:
        staging = f.read()
    
    # 提取 staging 中的持仓
    for line in staging.split('\n'):
        parts = [p.strip() for p in line.split('|')[1:-1]]
        if len(parts) >= 4 and parts[1].isdigit() and len(parts[1]) == 6:
            staging_holdings[parts[1]] = {
                'name': parts[0],
                'shares': parts[2],
                'cost': parts[3]
            }
    
    print(f'staging 持仓: {len(staging_holdings)} 个')
    for code, h in staging_holdings.items():
        print(f'  {h[\"name\"]} ({code}): {h[\"shares\"]}份 @ {h[\"cost\"]}')

# 3. 比较
if staging_holdings:
    config_codes = set(config_holdings.keys())
    staging_codes = set(staging_holdings.keys())
    
    extra_in_staging = staging_codes - config_codes
    missing_in_staging = config_codes - staging_codes
    
    if extra_in_staging:
        for c in extra_in_staging:
            h = staging_holdings[c]
            errors.append(f'STALE: {h[\"name\"]}({c}) staging中存在但config/持仓.md已移除（已清仓）')
    
    if missing_in_staging:
        for c in missing_in_staging:
            h = config_holdings[c]
            errors.append(f'MISSING: {h[\"name\"]}({c}) config/持仓.md中存在但staging缺失（新增持仓）')
    
    for code in config_codes & staging_codes:
        ch = config_holdings[code]
        sh = staging_holdings[code]
        diffs = []
        # 归一化数字（去逗号千分位）后再比较
        def norm(s):
            return s.replace(',', '').replace('，', '')
        if norm(ch['shares']) != norm(sh['shares']):
            diffs.append(f'数量: staging={sh[\"shares\"]} -> config={ch[\"shares\"]}')
        if norm(ch['cost']) != norm(sh['cost']):
            diffs.append(f'成本: staging={sh[\"cost\"]} -> config={ch[\"cost\"]}')
        if diffs:
            errors.append(f'MISMATCH: {ch[\"name\"]}({code}): {\" / \".join(diffs)}')
    
if errors:
    print(f'[FAIL] Staging持仓校验失败 ({len(errors)} errors):')
    for e in errors:
        print(f'  {e}')
    print('')
    print('*** 强制规则：所有持仓数据必须以config/持仓.md为权威来源 ***')
    print('*** staging中的持仓表必须被忽略，4.1节从config/持仓.md重新构建 ***')
else:
    print('[PASS] Staging持仓与config/持仓.md一致')
" 2>&1
```

**校验结果处理：**
- `[PASS]` → staging 持仓与 config 一致，但仍以 config/持仓.md 为权威来源
- `[FAIL]` → **忽略 staging 中的持仓表**，Step 4.1 必须从 config/持仓.md 重新构建。报告中的 "Staging来源" 标注追加 "⚠️ staging 持仓已过期，已用 config/持仓.md 覆写"
- staging 中的前次预测回顾/做T建议/跨品种约束等**分析内容**可继续参考，但**持仓数据本身**必须以 config/持仓.md 为准覆盖

### 1.3d Staging 过期检测与自动重建（🚨 防止隔多日使用失效 staging）

> ⚠️ 系统可能隔几天才使用（如节假日/遗漏执行），此时 staging 仍是为旧日期生成的，内容已过期。
> 必须检测 staging 的执行日期，过期则自动重建，绝不用失效 staging 生成早盘报告。

执行健康检查：

```bash

python -X utf8 -c "
import json, sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from datetime import date
from lib.staging_freshness import staging_health_check

try:
    with open('my_doc/每日复盘/harness/staging/今日-早盘分析.md', 'r', encoding='utf-8') as f:
        text = f.read()
except FileNotFoundError:
    text = None

result = staging_health_check(text, date.today(), 'my_doc/每日复盘/reports')
print(json.dumps(result, ensure_ascii=False, default=str))
"
```

**按 `action` 分支处理：**

- **`use`** → staging 为今日执行日，正常继续
- **`missing`** → 已在 1.3 处理（降级为模板早盘），继续走 1.3 的降级逻辑
- **`rebuild`** → 触发**轻量重建流程**（见下方），重建后重新读取 staging 继续早盘

**🚨 轻量重建流程（当 action=rebuild 时执行）：**

1. 从健康检查结果取 `latest_review_date`（记为 Y，若无则降级为模板早盘，标注"无历史复盘可参考"）
2. 读取 `reports/{Y}/复盘报告.md` → 提取"核心矛盾 / 核心教训 / 上期预判回顾"
3. 生成新 staging：
   - 执行日期更新为今天
   - 持仓表从 `config/持仓.md` 权威读取（铁律：绝不用旧 staging 持仓）
   - "前次预测回顾 / 上期信号回顾" ← 基于复盘报告 Y 的内容（标注"基于 Y 日复盘"）
   - 核心矛盾 / 特别关注 ← 基于复盘 Y + 今日市场状态
   - 事件日历 ← 今日数据（解禁 / 宏观 / 海外映射，走 1.3 的降级取数路径）
4. 覆写 `my_doc/每日复盘/harness/staging/今日-早盘分析.md` + `今日-复盘分析.md`
5. 新 staging 头部标注：`> ⚠️ 补生成（原 staging 执行日 {原日期} 已过期，基于 {Y} 日复盘重建）`
6. 重建完成后，重新执行 1.3d 的健康检查确认 action=use，然后继续早盘流程

**重建后必做**：重新跑 1.3b 代码-名称校验 + 1.3c 持仓比对，确保重建的 staging 持仓与 config 一致。

### 1.4 幂等性检查
读取 `my_doc/每日复盘/harness/automation/config/task_state.json`。
- 如果是新的一天（`date` ≠ 今天）→ 重置所有任务状态，重新开始
- 如果 `morning_analysis.status` = "completed" → 输出 "今日早盘分析已完成于 {executed_at}" 并**退出**
- 如果 `morning_analysis.status` = "failed" → 输出 "今日早盘分析之前失败，重试中..." 并继续

---

## 第二步：更新 task_state

```bash

python -c "
import json
from datetime import date, datetime
today = date.today().strftime("%Y%m%d")  # ⚠️ 必须用 yyyyMMdd，不能用 isoformat()！
state = json.load(open('my_doc/每日复盘/harness/automation/config/task_state.json', encoding='utf-8'))
state['date'] = today
state['tasks']['morning_analysis']['status'] = 'in_progress'
state['tasks']['morning_analysis']['executed_at'] = datetime.now().isoformat()
json.dump(state, open('my_doc/每日复盘/harness/automation/config/task_state.json', 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
"
```

---

## 第二步半：数据源连通性探测（新增 — 大幅减少获取失败）

> ⚠️ **核心原则：先探测，再取数。** 在数据收集前先判断各数据源是否可达，根据结果选择最优取数路径。
> 避免在不可达的 API 上反复重试浪费 token 和时间。不可达时直接走 fallback 路径，报告中标注替代数据来源。

### 2.5.1 执行探测

```bash

python my_doc/每日复盘/harness/automation/lib/data_source_probe.py \
  --output my_doc/每日复盘/harness/automation/config/probe_status.json \
  --pretty
```

### 2.5.2 读取探测结果

```bash

python -c "
import json
probe = json.load(open('my_doc/每日复盘/harness/automation/config/probe_status.json', encoding='utf-8'))
status = probe['status']
paths = probe['paths']
print('=== 数据源连通性探测结果 ===')
print(f'push2: {status[\"push2\"]} | 腾讯: {status[\"tencent\"]} | 同花顺: {status[\"ths\"]}')
print(f'push2ex: {status[\"push2ex\"]} | mootdx: {status[\"mootdx\"]} | datacenter: {status[\"datacenter\"]}')
print(f'整体: {probe[\"overall\"]} ({probe[\"ok_count\"]}/{probe[\"total_sources\"]})')
print()
# 输出不可达数据源的 fallback 路径
for key, p in paths.items():
    if p['note']:
        print(f'[{key}] {p[\"note\"]}')
"
```

### 2.5.3 探测结果处理规则

| 探测结果 | 含义 | 操作 |
|:-------:|------|------|
| `all_ok` | 全部数据源可达 | 正常取数，全部使用 primary 数据源 |
| `partial` | 部分数据源不可达 | 按下方 fallback 映射表选择替代路径，报告中标注⚠️ |
| `all_fail` | 全部数据源不可达 | **标记任务为 failed**，输出"网络不可达，跳过本次早盘分析"，退出 |

**将探测结论（哪些数据源可用/不可用）传递给后续数据收集步骤和报告输出**，报告中必须包含数据源健康状态行。

---

## 第三步：数据收集（按探测结果选择路径）

**严格使用 `a-stock-data` skill** 获取所有市场数据。禁止使用网络搜索结果填实际数据。

### ⚡ 数据源 fallback 映射表

根据 Step 2.5 探测结果，按以下映射选择取数路径：

| 数据类型 | Primary（优先用） | Fallback 1 | Fallback 2 | 不可达时标注 |
|---------|------------------|-----------|-----------|------------|
| **行业板块排名** | 东财 push2 `industry_comparison` | 腾讯财经批量行情自算涨跌幅 | 同花顺热点题材频次推断 | ⚠️ 板块排名基于替代数据 |
| **北向资金** | 东财 push2 | 同花顺 `hsgt_realtime` + 本地 CSV 缓存 | — | ⚠️ 北向数据源自同花顺/缓存 |
| **个股资金流** | 东财 push2his `stock_fund_flow_120d` | mootdx 量价估算 + 腾讯换手率 | 标记"数据缺失" | ⚠️ 资金流为估算值 |
| **融资融券** | 东财 datacenter `margin_trading` | 上周同期数据参考 | 标记"数据缺失" | ⚠️ 两融数据缺失 |
| **涨停板池** | 东财 push2ex（涨停/炸板/跌停） | 同花顺 `ths_limit_up_pool` | 标记"数据缺失" | ⚠️ 涨停数据源自同花顺 |
| **题材热度** | 同花顺热点 `ths_hot_reason` | 同花顺热榜 + 东财人气榜 | 标记"数据缺失" | ⚠️ 题材数据缺失 |
| **海外市场** | 腾讯财经海外指数 | WebSearch 综合搜索 | — | ⚠️ 海外数据源自 WebSearch |
| **K线数据** | mootdx TCP `tdx_client` | 腾讯财经日K + pandas 本地算 MA/MACD/RSI | 百度股市通 | ⚠️ K线源自腾讯日K |

**取数纪律：**
- **不可达的数据源不重试**（探测已确认不可达），直接走 fallback
- 走 fallback 路径时，在报告中标注 ⚠️ 和数据来源
- 若 Primary 和 Fallback 均不可达 → 标记"数据缺失"，不为填满表格而编造

### 3.1 海外市场
```
通过 a-stock-data skill 获取：
- 美股三大指数前一交易日收盘（道指/标普/纳指）
- 费城半导体指数 (SOX)
- 日经225 + 韩国KOSPI 当日早盘（如已开盘）
- 富时A50期货最新价
- 离岸人民币 (CNH)
- 主要商品: 原油/铜/黄金期货

数据源选择：根据探测结果，腾讯可达则用腾讯财经 → 否则用 WebSearch
```

### 3.2 A 股催化剂
```
通过 a-stock-data skill 获取：
- 同花顺热门题材/概念（ths_hot_reason）
- 东财行业板块排名（若 push2 不可达 → 腾讯财经批量行情自算）
- 北向资金前一日净买卖（若 push2 不可达 → 同花顺 hsgtApi + 本地缓存）
- 重要公告（巨潮 cninfo — 独立数据源，不受 push2 影响）

⚠️ 根据探测结果选择路径：push2 可用则用东财，不可用则走 fallback
```

### 3.3 资金面与情绪
```
通过 a-stock-data skill 获取：
- 主力资金流（主要板块）— push2 可用则用东财 push2his，否则 mootdx 估算
- 融资融券余额 — datacenter 可用则用 margin_trading，否则标记缺失
- 涨停/跌停数量统计 — push2ex 可用则用 em_zt_pool，否则同花顺 ths_limit_up_pool
- 炸板率 — push2ex 可用则用 em_zb_pool，否则标记缺失

⚠️ 根据探测结果选择路径
```

### 3.4 事件日历
```
通过 a-stock-data skill 获取：
- 今日宏观数据发布日历（WebSearch 搜索"今日财经日历"）
- 今日财报发布列表（WebSearch）
- 今日新股申购（WebSearch 或 a-stock-data）
- 今日解禁预警（datacenter 可用则用 lockup_expiry，否则 WebSearch）

事件日历主要来自 WebSearch，不受 push2 影响
```

---

## 第四步：执行分析框架

按照 `daily-review-harness` skill 早盘模式执行。**以下所有模块均为强制执行，即使 staging 缺失也不得跳过任何模块。**

### 4.1 我的持仓（完整快照表）

> 🚨 **强制铁律：持仓数据唯一权威来源是 `my_doc/每日复盘/harness/config/持仓.md`。**
> **禁止使用 staging 文件中嵌入的持仓表**——staging 可能是数天前生成的，持仓/数量/成本可能已过期。
> 即使 1.3c 校验通过，也必须从 config/持仓.md 直接读取，不得复制 staging 中的持仓数据。

读取 `my_doc/每日复盘/harness/config/持仓.md`，生成完整持仓快照表：
- **可用金额**：读取 config 顶部 `可用金额: N 元` 行，展示在快照最上方；缺失则标"可用金额未知"（建仓信号份额无法计算）
- 列：股票名称 | 代码 | 持仓数量 | 成本价 | 昨收 | 昨涨跌 | 浮动盈亏 | 量比
- 浮动盈亏 = (昨收 - 成本价) / 成本价 × 100%
- **必须每只持仓一行，所有持仓标的全部列出（不以 staging 中的数量和标的为准）**

### 4.2 前次预测回顾
从 staging 文件中提取上次收盘复盘的预测，与最近一个交易日实际走势对比：
- 列出每条预判 vs 实际结果
- 标注 ✅/❌/⚠️
- 计算方向准确率
- 今日操作中必须应用上期教训

### 4.3 宏观研判
- 海外市场传导：美股涨跌 → A 股开盘方向预判
- 汇率/商品信号：CNH/A50/商品 → 市场风险偏好判断
- 宏观日历：今日数据发布 → 潜在波动节点
- **必须给出方向预判（基准/偏弱/偏强三种情景 + 概率）**

### 4.4 非持仓板块扫描（7维打分）
对当前非持仓的主要行业板块（≥5个），按 7 个维度打分（1-5分）：
- 维度：外盘映射 | 消息催化 | 资金面 | 技术位置 | 情绪温度 | 入场时机 | 政策面
- 入场时机权重 1.5x，综合 = 加权平均（满分 5.0）
- 每条给出建仓建议：🟢≥3.8 且入场时机≥4 | 🟡3.0-3.7 | 🔴<3.0
- **若存在 🟢 板块 → 建仓观察写入早盘报告"关注列表"（含量化升级条件），不占信号名额**

### 4.5 持仓映射与操作判断

#### 4.5.1 持仓板块七维评分
对每个持仓标的，使用与 4.4 相同的七维评分体系打分：
- 列：标的 | 代码 | 外盘映射 | 消息催化 | 资金面 | 技术位置 | 情绪温度 | 入场时机 | 综合 | 预判开盘 | 持仓建议

#### 4.5.2 逐只持仓分析与做T建议
对每个持仓标的独立分析：
- 昨收/量比/关键位（支撑/阻力）
- **必须给出做T策略**：正T/反T/双向备选/不建议，含具体触发价和仓位
- 操作建议（持/加/减/清）+ 量化触发条件

#### 4.5.3 做T纪律规则（当日适用）
以 Checklist 形式逐条列出当日适用的纪律：
- `[x]` 标记当日强制适用的规则（如"开盘30分钟不操作"）
- `[ ]` 标记当日不适用但需备忘的规则
- 至少包含：开盘30分钟不操作铁律、外盘熔断日规则、买预期卖事实规则、系统性普跌日规则、平开+单边暴跌规则
- **每条规则必须明确标注当日是否适用及原因**

### 4.6 操作清单
汇总所有持仓的操作建议 → 输出优先级排序的操作清单（P0/P1）

### 4.7 跨品种约束检查
以表格形式列出跨品种关联规则：
- 列：约束 | 判断 | 操作含义
- 至少包含：北向一票否决、半导体≈创业板弹性、半导体→银行跷跷板、石油→通胀→成长、油金同涨=risk-off
- **每条约束必须给出当日操作含义**

### 4.8 核心关注时间表
按时间线列出当日关键监控节点：
- 09:15 集合竞价 → 09:25 开盘价 → 09:35 开盘5分钟确认 → 10:00 方向初判 → 10:30 做T窗口激活 → 11:00 上午总结 → 13:00 下午开盘 → 14:30 尾盘
- **每个节点标注关注点和判断依据**

### 4.9 每日信号概览
在早盘报告中嵌入信号清单摘要：
- 信号总数 + P0/P1 分布
- 每条信号的 ID + 优先级 + 标的 + 操作类型（不展开完整触发条件）
- 交叉引用链接到 `每日信号.md`

---

## 第五步：生成结构化信号 — 每日信号.md（7节完整格式）

> ⚠️ 格式纪律：必须严格按照以下 7 节模板生成。盘中检查和收盘复盘 Agent 依赖这些节的标题和表格列名做原地更新——**节名/列名/信号ID 格式变更会导致盘中数据写入失败**。

写入 `my_doc/每日复盘/reports/{today}/每日信号.md`，按以下 7 节模板：

---

### 5.1 文件头 + 信号总表

```markdown
# 每日信号 — {YYYY}年{M}月{D}日（周{X}）

> **生成时间：{YYYY-MM-DD HH:MM} CST** | **最后更新：{YYYY-MM-DD HH:MM} CST（早盘）**
> **信号总数：{N}条（P0×{n0} / P1×{n1}）** | **关联早盘报告：** [早盘报告.md](早盘报告.md)
> **关联复盘报告：** （待收盘后生成）

## 信号总表

| 优先级 | 标的 | 触发条件 | 操作类型 | 状态 | 方向 | 紧急度 | 预期触发率 | 目标/止损 | 有效时段 | 仓位 | 信号ID |
|:---:|------|----------|:------:|:---:|:---:|:---:|:---:|:---:|----------|:---:|--------|
{每行一条信号，状态初始=待执行}

> **信号状态说明：** 待执行 → 已触发 → 已执行 / 已过期 / 已取消
> **紧急度说明：** 高=1-2天内兑现 / 低=择机触发
{如有互斥信号，在此标注互斥关系}
```

**信号分类规则：**
- P0 信号（风控强制）: ≤ 3 条，必须执行。普跌否决/黄金守位/科技回避等纪律。**不考核触发率、不结算**（预期触发率=—）。不触发=市场安全，价值在"有备无患"
- P1 信号（操作）: 2-4 条，高置信度短线操作（正T/减仓/建仓/锁利），含量化触发条件 + 执行窗口 + 仓位大小，按 T+3 目标价结算口径设计
- **名义总量 4-6 条**（允许边界 2-7），不做广覆盖雷达
- **板块机会扫描 🟢 板块的建仓观察**：写入早盘报告"关注列表"（含量化升级条件），**不占信号名额**。盘中 Tier 1/2 满足 → 临时追加（信号ID 加 `-盘中` 后缀）

**验证型判断禁止进信号表**（防御延续/农业延续/反抽观察等）——写入报告正文或"关注列表"，不进信号表。

**P1 信号目标/止损 + 双向设计规则：**
- 每条 P1 = 触发路径（明确价位/量能+仓位+时段）+ 证伪路径（什么情况说明早盘判断错→信号作废）。杜绝"既不触发又无信息量"
- **必填预期触发率**：生成时估计百分比（如 40%），复盘自动校准
- **必填目标/止损**：格式 `目标+3%/止损-2%`（百分比）或 `目标1.75/止损1.66`（显式价）；P1 必填目标，止损推荐
- 短线定位：目标价按 T+3 交易日口径设计（快进快出），不做中线

**紧急度分配规则：**
- **做T/反T**: 一律"高"（日内或次日兑现）
- **止损/风控**: 一律"高"（风险控制必须尽快评估）
- **锁利/减仓**: 一律"高"（利润保护有时效性）
- **加仓/建仓**: 一律"低"（择机触发，需等回调到位）
- **盘中追加信号**: 默认"高"（盘中发现=短期窗口）

**建仓信号仓位计算（2026-08-26 新增）**：未持仓标的的建仓信号，份额 = `可用金额 × 分级比例 ÷ 参考价`（100 份整数取整）：
- P1 直接建仓（高置信）= 可用金额 1/3；观察升级建仓 = 1/4；试探/低置信 = 1/5
- 参考价 = 昨收（早盘生成时点可得）
- 份额不足 100 份 → 仓位列写"资金不足"；可用金额缺失 → 写"可用金额未知，暂不定份额"
- 输出格式：`{N}份(可用×1/3)`（追踪收益 `_parse_quantity` 可解析）

**每条信号字段说明：**
- 信号ID: `SIG-{YYYYMMDD}-{NN}`（2位数字序号，如 SIG-20260724-01）；盘中追加用 `-盘中` 后缀（如 `SIG-20260826-09-盘中`）
- 优先级: P0/P1
- 标的: `{ETF名称}({代码})`
- 触发条件: 量化条件，必须可验证（含具体数值/阈值）；P1 需含双向设计（触发路径+证伪路径）
- 操作类型: 减仓/止损/锁利/正T/反T/建仓（P1 主要为 正T/减仓/建仓/锁利）
- 状态: 初始全部为"待执行"
- 方向: 买入/卖出/中性
- 紧急度: 高/低（按上述分配规则）
- 预期触发率: P0 填"—"；**P1 必填百分比**（生成时估计，复盘自动校准）
- 目标/止损: 格式 `目标+3%/止损-2%` 或 `目标1.75/止损1.66`；P1 必填目标，止损推荐
- 有效时段: `HH:MM - HH:MM CST`
- 仓位: 具体股数或比例（如 `-10~15%` `+200份` `1/4`）

**关注列表（观察雷达，非信号）：**
早盘报告中新增"关注列表"小节（报告正文内），观察雷达全部移入此处，含量化升级条件：

> ⚠️ 与第六节板块评分的"🟡 关注"（建仓评级）不同：本节关注列表是"信号级观察雷达"，仅含量化升级条件，两者不互相替代。

| 关注标的 | 观察逻辑 | 升级条件（量化） |
|---------|---------|-----------------|
| 农业159825 | 主线延续验证 | 方向确认>30min+放量突破0.74且涨停≥3只→盘中临时追加信号 |

盘中 Tier 1/2 发现升级条件满足 → **临时追加信号**（信号ID 加 `-盘中` 后缀标识），不预先占信号名额。

---

### 5.2 信号触发记录（占位）

```markdown
## 信号触发记录

> 盘中分析执行时，若信号总表中"待执行"信号的触发条件满足，则在此追加触发记录。

| 触发时间 | 信号ID | 优先级 | 标的 | 操作类型 | 触发条件摘要 | 当前状态 | 建议操作 | 用户操作 |
|----------|--------|:---:|------|:------:|-------------|:------:|----------|:------:|

> **用户操作填写规范：** `已执行` `部分执行` `放弃` `错过`
```

> ⚠️ 早盘生成时此表为空，盘中检查 Agent 负责填充。

---

### 5.3 盘中验证记录（占位）

```markdown
## 盘中验证记录

> 盘中分析执行时追加。每次执行追加新行，不覆盖历史记录。

| 验证时间 | 信号ID | 标的 | 操作类型 | 仓位 | 当前状态 | 关键数据 | 判断 |
|----------|--------|------|:------:|:---:|:------:|----------|------|
```

> ⚠️ 早盘生成时此表为空，盘中检查 Agent 每次执行追加一行。

---

### 5.4 盘中追加信号（占位）

```markdown
## 盘中追加信号

> 盘中分析执行时，若发现早盘未覆盖的新机会，按三级阈值规则在此追加信号。
> 追加信号直接加入上方信号总表（信号ID 加 `-盘中` 后缀标识），并在此备注生成逻辑。

（暂无——待盘中分析执行）
```

---

### 5.5 信号与早盘报告对照

根据早盘报告各持仓分析章节，建立每条信号→早盘分析原文的溯源：

```markdown
## 信号与早盘报告对照

| 信号ID | 对应早盘章节 | 早盘分析原文摘要 |
|--------|------------|----------------|
| SIG-{date}-01 | {早盘报告章节号+标题} | {直接引用早盘报告中的关键判断原文} |
| SIG-{date}-02 | {早盘报告章节号+标题} | {直接引用早盘报告中的关键判断原文} |
...
```

> ⚠️ 此节必须在早盘生成时填入，用于复盘时追溯信号生成逻辑是否合理。

---

### 5.6 信号评价（占位，复盘时填入）

```markdown
## 信号评价（复盘时填入）

| 信号ID | 决策质量 | 执行质量 | 入场价 | 出场价 | P&L(元) | P&L(%) | 持有天数 | 紧急度校准 | 复盘反思 |
|--------|:------:|:------:|--------|--------|:------:|:-----:|:------:|:--------:|----------|
```

> ⚠️ 早盘生成时此表为空，收盘复盘 Agent 负责填充。评级标准：S/A/B/C/D/F（见 auto_evening_review.md 7.1/7.2）。

---

### 5.7 当日信号统计（占位，复盘时填入）

```markdown
## 当日信号统计

| 指标 | 数值 |
|------|:---:|
| 早盘生成信号总数 | {N} |
| 盘中追加信号数 | — |
| 已触发 | — |
| 已过期 | — |
| 已执行 | — |
| 已废弃 | — |
| P0执行率 | — |
| 遗漏信号数 | — |
| 高紧急度触发率 | — |
| 低紧急度触发率 | — |
```

> ⚠️ 早盘生成时仅填入"早盘生成信号总数"，其余列收盘复盘 Agent 负责填充。

---

### 5.8 信号数量检查（自检）

生成完毕后自检：
- [ ] 信号总表行数 = 信号总数（N条）
- [ ] 每条信号有唯一 SIG-{date}-{NN}（NN 从 01 开始连续）
- [ ] P0 ≤ 3 条，P1 2-4 条
- [ ] 名义总量 4 ≤ N ≤ 6（允许边界 2-7）
- [ ] P1 信号均已填写预期触发率（百分比）与目标/止损
- [ ] P0 信号预期触发率=—（不考核触发率、不结算）
- [ ] 每条信号标注了紧急度（高/低）
- [ ] 做T/止损/锁利类信号紧急度=高；加仓/建仓类信号紧急度=低
- [ ] 每条 P1 信号含双向设计（触发路径+证伪路径）
- [ ] 观察雷达（农业延续/反抽观察/板块升级观察）已写入早盘报告"关注列表"，未占信号名额
- [ ] 板块机会扫描 🟢 板块的建仓观察已写入"关注列表"（含量化升级条件）
- [ ] 信号与早盘报告对照表中每条信号都对应到早盘报告的具体章节
- [ ] 所有 7 节都在文件中（即使某些节当前为空表）
- [ ] 信号总表含"状态"列，初始值全部为"待执行"

---

## 第六步：输出早盘报告

写入 `my_doc/每日复盘/reports/{today}/早盘报告.md`。**以下 12 节结构为强制执行，任何情况不得跳过任何节。**

```markdown
# 早盘分析报告 — {YYYY-MM-DD}（周{X}）

**数据时点**: {YYYY-MM-DD HH:MM CST}
**生成方式**: 自动化早盘分析
**状态**: 正常
**数据源健康**: push2={✅/❌} 腾讯={✅/❌} 同花顺={✅/❌} mootdx={✅/❌} datacenter={✅/❌} | 详见下方数据标注
**Staging来源**: {前一交易日收盘复盘生成}

---

## 一、我的持仓

> ⚠️ 强制执行。从 config/持仓.md 读取并生成完整快照。

| 股票名称 | 代码 | 持仓数量 | 成本价 | 昨收 | 昨涨跌 | 浮动盈亏 | 量比 |
|----------|------|:------:|--------|------|:-----:|:------:|:---:|
| {7只持仓逐行列出} |

> 浮动盈亏基于昨收价 vs 成本价

---

## 二、前次预测回顾

> ⚠️ 强制执行。从 staging 文件中提取上次复盘预测，与最近交易日实际对比。

| 预判 | 实际 | 准确? | 根因 |
|------|------|:---:|------|
| {逐条列出} |

**准确率**: {X}/{N}（{XX}%）。{核心教训总结}

---

## 三、海外市场传导

{美股/日韩/A50/商品/汇率概述 → A股开盘方向预判}
{必须给出三种情景概率：基准/偏弱/偏强}

---

## 四、宏观研判

{今日市场方向 + 多空因素对照 + 风险关注 + 关键变量}

---

## 五、资金面与情绪

{北向资金/涨停情绪/融资融券/题材热度}

---

## 六、板块机会扫描（非持仓板块）

> ⚠️ 强制执行。≥5个非持仓板块的七维评分。

| 板块 | 关联ETF | 外盘映射 | 消息催化 | 资金面 | 技术位置 | 情绪温度 | 入场时机 | **综合** | 预估胜率 | 建仓建议 | 核心逻辑 |
|------|---------|:-------:|:-------:|:-----:|:-------:|:-------:|:-------:|:-------:|:-------:|----------|----------|
| {逐行} |

> 评分口径：每维1-5分。入场时机权重1.5x。综合=加权平均（满分5.0）。
> 建仓建议：🟢≥3.8且入场时机≥4 | 🟡3.0-3.7 | 🔴<3.0

---

## 七、持仓映射与操作判断

### 7.1 持仓板块七维评分

> ⚠️ 强制执行。对7只持仓标的逐只打分。

| 标的 | 代码 | 外盘映射 | 消息催化 | 资金面 | 技术位置 | 情绪温度 | 入场时机 | **综合** | 预判开盘 | 持仓建议 |
|------|------|:-------:|:-------:|:-----:|:-------:|:-------:|:-------:|:-------:|----------|:------:|

### 7.2 逐只持仓分析与做T建议

> ⚠️ 强制执行。每只持仓独立一节，含做T策略。

对每个持仓标的：
- 昨收/量比/成本/浮动盈亏/关键位（支撑/阻力）
- **必须给出做T策略**：正T / 反T / 双向备选 / 不建议，附具体触发价+仓位
- 操作建议（持/加/减/清）+ 量化触发条件
- 研判逻辑（2-5句话）

### 7.3 做T纪律规则（当日适用）

> ⚠️ 强制执行。Checklist 格式，逐条标注当日是否适用。

- [x] 开盘30分钟不操作（铁律）：9:30-10:00为情绪释放窗口，不执行任何T操作
- [ ] 外盘熔断日T仓位减量至1/3：{当日是否适用+原因}
- [ ] "买预期卖事实"后2-3日不做正T：{当日是否适用+原因}
- [ ] 系统性普跌日不做T：{当日是否适用+原因}
- [x] 平开+单边暴跌=放弃T计划：{当日是否适用+原因}
- {其他当日特殊纪律}

---

## 八、操作清单

| 优先级 | 标的 | 操作 | 触发条件 | 建议仓位 | 时段 |
|:---:|------|------|---------|:---:|------|
| P0 | ... | ... | ... | ... | ... |
| P1 | ... | ... | ... | ... | ... |

---

## 九、跨品种约束检查

> ⚠️ 强制执行。表格形式，每条约束当日判断 + 操作含义。

| 约束 | 判断 | 操作含义 |
|------|------|----------|
| 北向一票否决 | {若北向开盘大幅流出>50亿/30min→取消所有做T/加仓} | {当日警戒状态} |
| 半导体≈创业板（弹性65%） | {创业板正T必须等半导体同步企稳} | {当日交叉验证要求} |
| 半导体→银行跷跷板 | {方向判断} | {当日操作含义} |
| 石油→通胀→成长承压 | {当日判断} | {当日操作含义} |
| 油金同涨=risk-off | {当日判断} | {当日操作含义} |
| {其他当日适用的跨品种约束} | | |

---

## 十、核心关注时间表

> ⚠️ 强制执行。按时间线列出关键监控节点。

| 时间 | 关注点 | 判断依据 |
|------|--------|----------|
| 09:15 | 集合竞价结束 | {关注什么} |
| 09:25 | 开盘价公布 | {关注什么} |
| 09:35 | 开盘5分钟方向确认 | {关注什么} |
| 09:45 | {标的}方向确认 | {关注什么} |
| 10:00 | 做T窗口激活 | {关注什么} |
| 10:30 | 方向确认窗口结束 | {关注什么} |
| 11:00 | 上午方向总结 | {关注什么} |
| 13:00 | 下午开盘 | {关注什么} |
| 14:30 | 尾盘方向 | {关注什么} |

---

## 十一、风险提示

{今日主要风险 + 需要关注的变量，≥5条}

---

## 十二、每日信号概览

> ⚠️ 强制执行。早盘报告中嵌入信号清单摘要 + 交叉引用。

> 详见 `reports/{today}/每日信号.md`（本报告配套信号文件）
>
> 信号概览：P0×{n0} / P1×{n1} / 总计{N}条
> - SIG-{date}-01 (P0): {标的} — {操作类型} — {触发条件摘要}
> - SIG-{date}-02 (P0): ...
> - ...

---
*数据来源: mootdx/腾讯财经/东财/同花顺，详见 a-stock-data skill*
*海外数据: WebSearch综合，美股收盘数据来自Yahoo Finance/Reuters*
*Staging基础: {前一交易日}收盘复盘生成*
```

---

## 第七步：更新 task_state

```bash
# 将 morning_analysis 标记为 completed
python -c "
import json
from datetime import datetime
state = json.load(open('my_doc/每日复盘/harness/automation/config/task_state.json', encoding='utf-8'))
state['tasks']['morning_analysis']['status'] = 'completed'
state['tasks']['morning_analysis']['reports_generated'] = ['早盘报告.md', '每日信号.md']
state['tasks']['morning_analysis']['signal_count'] = {N}  # 替换为实际生成信号数
json.dump(state, open('my_doc/每日复盘/harness/automation/config/task_state.json', 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
"
```

---

## 第八步：写入执行日志

写入 `my_doc/每日复盘/harness/automation/logs/{today}/morning_execution.log`：

```
========================================
早盘分析自动执行日志
========================================
日期: {YYYY-MM-DD}
执行开始: {HH:MM:SS CST}
执行结束: {HH:MM:SS CST}
状态: 成功
Staging文件: {存在/不存在}
数据获取:
  - 海外市场: {成功/失败}
  - A股催化剂: {成功/失败}
  - 资金面与情绪: {成功/失败}
  - 事件日历: {成功/失败}
信号生成: {N} 条 (P0: {p0} P1: {p1})
报告产出: 早盘报告.md, 每日信号.md
错误: 无
警告: {如有}
========================================
```

---

## 异常处理

| 异常 | 处理方式 |
|------|---------|
| API 全部不可达（网络问题） | 标记 morning_analysis.status = "failed"，记录错误，退出 |
| 部分 API 不可达 | 用可用数据源继续，在报告中标注缺失的数据类型 |
| Staging 文件不存在 | 基于模板直接执行（降级模式），在报告中标注 |
| 早盘报告生成中超时 | 输出已写内容，标记任务为 partial_complete |
| task_state.json 损坏 | 重建为默认状态，记录 warning |
