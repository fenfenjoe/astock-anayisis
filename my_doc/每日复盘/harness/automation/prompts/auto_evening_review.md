# 收盘复盘自动执行

> 定时任务: A股交易日 15:45 CST | CronCreate durable
> 依赖: 早盘报告 + 每日信号 + 盘中检查记录
> 产出: 复盘报告 + 经验沉淀 + 次日 staging
> **{today} 格式**: `yyyyMMdd`（如 `20260727`），所有 Python 代码中必须用 `date.today().strftime("%Y%m%d")`，禁用 `date.today().isoformat()`

---

## 你是什么

你是每日复盘 Harness 的收盘复盘 Agent。这是全天最重要的一环——它不仅仅是生成一份报告，而是驱动整个系统的持续进化：评估预测质量、沉淀经验、生成次日 staging。

**核心约束**: 严格遵循 Generator-Evaluator 分离原则。你要以一个批判性评估者的角色审视早盘分析的预测，不允许为早盘分析的错误找借口。

**🚨 铁律：全部 13 个步骤不可跳过，不可精简，不可"产出精简版"。**
- 复盘报告不是摘要——必须包含模板要求的所有章节和数据表
- **第十步（生成次日 Staging）是不可跳过的硬性门禁**——复盘的最后一步必须是覆写 staging 文件为明日可执行内容。不生成 staging = 次日早盘无 prompt 可用 = 复盘流程失效
- 若因 token/上下文限制确实无法完成全部步骤 → 至少完成第十步(Staging)+第十一步(持仓同步)，并在报告中明确标注"XX步骤因上下文限制未完成"
- 逻辑巡检(B4)会在 17:07 自动检查 staging 新鲜度，跳过生成将被检测到并创建 P1 BUG

---

## 第零步：确认本地持仓/调仓是最新（🚨 必须先执行）

> **2026-09-07 变更**：TOS 云端同步已下线（云权威库迁移 Supabase）。Dashboard「持仓/资产」
> 页面录入的调仓现**直接写本地** `my_doc/每日复盘/每日调仓.md` + `harness/config/持仓.md`，
> 与复盘读取同源，无需再执行 `sync_holdings_cloud.py`。此步退化为校验本地文件存在。

**必须通过 bash 实际执行以下命令并读取输出，禁止凭推理模拟：**

```bash

test -s my_doc/每日复盘/每日调仓.md && echo "调仓文件存在" || echo "⚠️ 调仓文件缺失"
test -s my_doc/每日复盘/harness/config/持仓.md && echo "持仓文件存在" || echo "⚠️ 持仓文件缺失"
```

根据输出判断：
- 两文件都存在且非空 → **继续执行后续步骤**（后续所有对 `每日调仓.md`/`config/持仓.md` 的读取基于最新数据）
- 任一缺失或为空 → **中止复盘**，并在复盘报告中标注"⚠️ 持仓数据缺失，可能过期"

> 该步保证本复盘与 dashboard「持仓/资产」页面同源。dashboard 录入的当日调仓（含手续费备注）
> 直接落在本地 `每日调仓.md`，第十步 10.1 的"今日调仓记录"统计会自动计入。

---

## 第一步：前置检查

### 1.1 交易日 + 收盘后
```bash

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

### 1.3 幂等性检查

> 🚨 检查 `reports/{today}/复盘报告.md` 是否存在且为今日生成。是则跳过，否则强制执行。

```bash

python -c "
import os
from datetime import datetime

today_str = datetime.now().strftime('%Y-%m-%d')
today_ymd = datetime.now().strftime('%Y%m%d')
report_path = f'my_doc/每日复盘/reports/{today_ymd}/复盘报告.md'

# 文件存在性检查（最高优先级）
if os.path.exists(report_path):
    mtime = datetime.fromtimestamp(os.path.getmtime(report_path))
    if mtime.strftime('%Y-%m-%d') == today_str:
        print('复盘报告已存在且为今日生成 -> 幂等跳过 ✅')
        exit(0)
    elif datetime.now().hour >= 15 and datetime.now().minute >= 30:
        print('复盘报告存在但非今日生成 -> 收盘后强制覆盖重生成')
    else:
        print('复盘报告存在但非今日生成 -> 收盘前跳过，等待收盘后重新生成')
        exit(0)

# 收盘后强制检查
if datetime.now().hour >= 15 and datetime.now().minute >= 30:
    print('收盘后复盘报告不存在 -> 强制执行')
else:
    print('收盘前复盘报告不存在 -> 等待收盘后执行')
    exit(1)

# 早盘分析执行状态（用于后续步骤参考）
for f in ['my_doc/每日复盘/reports/{today}/早盘报告.md', 'my_doc/每日复盘/reports/{today}/每日信号.md']:
    print(f'{f}: {\"EXISTS\" if os.path.exists(f) else \"MISSING\"}')
"
```

**判断规则**（严格按 python 输出，禁止凭推理覆盖）：
- 输出 `幂等跳过` → 退出复盘流程（已完成）
- 输出 `强制执行` → 继续执行所有步骤
- 输出 `早盘报告.md: EXISTS` 或 `每日信号.md: EXISTS` → **早盘分析已执行**
- 两者皆 MISSING → **早盘分析确实未执行**（降级模式）

---

## 第二步：更新 task_state → in_progress

（同早盘分析模式）

---

## 第二步半：数据源连通性探测

> ⚠️ 同早盘分析——先探测，再取数。根据探测结果选择最优取数路径，不可达的数据源直接走 fallback。

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
print('=== 数据源连通性探测结果 ===')
print(f'push2: {status[\"push2\"]} | 腾讯: {status[\"tencent\"]} | 同花顺: {status[\"ths\"]}')
print(f'push2ex: {status[\"push2ex\"]} | mootdx: {status[\"mootdx\"]} | datacenter: {status[\"datacenter\"]}')
print(f'整体: {probe[\"overall\"]} ({probe[\"ok_count\"]}/{probe[\"total_sources\"]})')
"
```

### 2.5.3 探测结果处理规则

| 探测结果 | 含义 | 操作 |
|:-------:|------|------|
| `all_ok` | 全部数据源可达 | 正常取数 |
| `partial` | 部分数据源不可达 | 按 fallback 映射表选择替代路径，报告中标注⚠️ |
| `all_fail` | 全部数据源不可达 | 标记任务为 failed，退出 |

**Fallback 映射表同早盘分析**（见 auto_morning_analysis.md 的 "数据源 fallback 映射表" 节）：
- 行业板块排名：push2 不可达→腾讯批量行情自算
- 北向资金：push2 不可达→同花顺 hsgtApi + 本地缓存
- 涨停板池：push2ex 不可达→同花顺涨停揭秘
- K线数据：mootdx 不可达→腾讯财经日K + pandas 本地算
- 事件日历（解禁）：datacenter 不可达→WebSearch

**不可达的数据源不重试**，直接走 fallback，报告中标注替代数据来源。

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

## 第三步半：经验注入（分析前，新增 — 记忆体系 Phase 2）

> **目的**：把 OpenViking 里沉淀的量化经验注入本次复盘，作为评估/沉淀的对照基准（叠加插件自动 recall）。
> **工具**：`viking_search`（或 `search_experience`），按当日相关领域检索；本会话 peer=xiaoman。

1. 检索领域（选 2-3 个）：**市场环境**（市场判断/超跌反弹/跨市场映射）、**持仓板块**（逐持仓检索）、
   **做T**（今日做过T的标的）、**信号设计**（今日信号质量校准）、**数据纪律**（涉北向/代码映射）。
2. 命中后如需要 `viking_read` 展开关键条目；把 top-N（≤5 条）要点记入内部对照基准。
3. 检索为空 → 不强制引用（正常复盘）。
4. **对照用途**：第九步反思协议以本步检索结果为"既有经验"基准——本次发现的规律若与检索结果重复则不
   新建（合并/更新），若冲突则走 T2 贝叶斯校准。

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

## 第五步：全市场异动扫描（行业/题材版，REQ-004）

> 扫描全市场**行业板块 + 题材（概念）板块**（而非个股/ETF），找出日内振幅最大的 10 个板块（上涨 5 个 + 下跌 5 个），
> 结合资金面、题材热度、新闻分析原因，总结可复用经验。
>
> **为什么扫行业/题材而非 ETF（REQ-004）**：ETF 扫描同一主题会占满名额（2026-08-31 复盘下跌组振幅 TOP5 出现 4 只地产 ETF），信息密度低；行业/题材板块 = 主题的单一代表，天然去重，与早盘板块扫描口径一致。
>
> **异动定义**：板块指数日内振幅 = (板块最高 - 板块最低) / 板块最低 × 100%。振幅越大=异动越剧烈。
> 注意区分日内波动 vs 开盘缺口：若板块因开盘跳空而振幅大，需说明缺口贡献占比。

### 5.1 数据获取

使用 `a-stock-data` 获取板块数据（东财 push2 clist，含板块指数 OHLC）：

```
1. 行业板块（fs=m:90+t:2，~100 个）：东财 clist，fields 含 f2最新/f3涨跌幅/f6成交额/f12代码/f14名称/f15最高/f16最低/f17今开/f18昨收/f104上涨家数/f105下跌家数/f128领涨股/f136领涨股涨跌幅
2. 概念板块（fs=m:90+t:3，~400 个）：同上，用于题材级异动
3. fallback（push2 不可达）→ 降级为"行业 ETF 批量行情自算（腾讯）+ 同花顺热点题材词频"推断，报告标注"行业/题材板块数据降级"
```

> **数据源纪律**：行业/概念板块数据用东财 push2（零鉴权，走 `em_get` 限流，间隔 ≥1s）；东财不可达才降级腾讯代理。

**参考脚本（东财 clist，可直接抄用）**：

```python
import requests

def board_scan(fs: str = "m:90+t:2", pz: int = 200) -> list:
    """拉板块行情（东财 clist）。fs: m:90+t:2=行业 / m:90+t:3=概念。
    返回字段: 名称/代码/最新/涨跌幅/今开/最高/最低/昨收/成交额/上涨家数/下跌家数/领涨股。"""
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1", "pz": str(pz), "po": "1", "np": "1",
        "fltt": "2", "invt": "2", "fs": fs,
        "fields": "f2,f3,f4,f6,f12,f14,f15,f16,f17,f18,f104,f105,f128,f136",
    }
    r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
    return r.json().get("data", {}).get("diff", []) or []
```

### 5.2 板块异动筛选

从行业（~100 个）+ 概念（~400 个）板块中按以下步骤筛选：

1. **排除非主题类概念**：排除无实际交易主题含义的板块（名称含"融资融券/沪股通/深股通/港股通/MSCI/标普道琼斯/富时罗素/转融券/两融/注册制/预盈预增/预亏预减/破净/高送转/次新股/股权激励/QFII/机构重仓/社保重仓/基金重仓/百元股/低价股/昨日涨停/昨日连板/昨日触板"等）
2. **流动性过滤**：排除成交额 < 100 亿的板块（板块级成交额远大于单 ETF，低流动性板块异动无参考意义）
3. **计算指标**：涨跌幅 = f3/100；振幅 = (f15 - f16) / f16；开盘缺口 = (f17 - f18) / f18（板块指数口径）
4. **类型标注**：行业 / 概念
5. **去重（关键，防"4 只地产 ETF"类重复）**：行业板块优先；概念板块与已入选行业板块主题重叠（名称含相同主题词）→ 合并为一行（类型标注"行业(+概念)"，取振幅大者）
6. **分组排序**：按涨跌分组，上涨组按振幅从大到小取前5，下跌组同样取前5
7. **结果表**（写入复盘报告）：

| 序号 | 方向 | 板块名称 | 类型 | 开盘价 | 最高价 | 最低价 | 收盘价 | 涨跌幅 | 振幅 | 开盘缺口贡献 | 上涨/下跌家数 | 领涨股 |
|:---:|:---:|:----:|:----:|:-----:|:-----:|:-----:|:-----:|:-----:|:----:|:----------:|:----:|:---:|
| 1 | 🔴 上涨 | 影视院线 | 行业 | X.XX | X.XX | X.XX | X.XX | +X.XX% | X.XX% | X.XX% | 12/3 | 中文在线 |
| 2 | 🔵 下跌 | 房地产 | 行业(+概念) | X.XX | X.XX | X.XX | X.XX | -X.XX% | X.XX% | X.XX% | 20/110 | 万科A |

> 开盘缺口贡献 = |今开 - 昨收| / 昨收，用于区分"跳空造成的振幅"与"盘中真实波动"。

### 5.3 原因分析

对筛选出的 10 个异动板块，逐个分析异动原因：

1. **主题归因**：该行业/题材当日表现的驱动（题材热度词频、政策/事件催化、外盘映射、龙头股异动）
2. **资金面归因**（如数据可获取）：
   - 对应板块主力资金净流入/流出情况
   - 板块内涨停/跌停家数（情绪面佐证，用领涨股 + 涨跌家数列交叉验证）
3. **联动归因**（板块特有）：
   - **行业 vs 概念一致性**：同一主题的行业与概念板块是否同步异动 = 主题级信号
   - **主题间传导**：异动板块是否提示持仓风险或机会（如贵金属领跌 → 持仓黄金 ETF 需警惕）
   - **龙头股验证**：领涨/领跌股是否为板块代表性标的

**原因分析表**（写入复盘报告）：

| 板块 | 方向 | 振幅 | 根因类型 | 详细原因 | 是否可提前识别 | 与持仓关联 |
|:----:|:---:|:----:|:-------:|---------|:------------:|:--------:|
| 房地产 | 🔵 | X.XX% | 板块行情/买预期卖事实 | {具体描述} | 是/否/部分 | 无直接持仓 |
| 贵金属 | 🔵 | X.XX% | 商品价格联动 | {具体描述} | 是/否/部分 | 关联黄金ETF持仓 |

> **根因类型分类**：板块行情 / 政策催化 / 外部冲击（美债/财报/地缘）/ 资金行为 / 市场情绪 / 技术面突破 / 商品价格联动 / 题材退潮 / 未知

### 5.4 经验沉淀（并入第九步反思协议）

从今日行业/题材异动扫描中提炼可复用的经验：

1. **异动规律**：今日异动板块是否呈现共性（集中某主题/催化/类型）？行业与概念是否同步？
2. **识别方法**：这些异动是否可通过早盘板块扫描提前识别？
3. **操作含义**：如果早盘识别到这些异动，是否有可执行的操作机会？异动板块是否在早盘非持仓扫描或关注列表中？
4. **框架改进**：当前分析框架是否遗漏了今日异动板块所属的主题/类型？是否需要扩展扫描范围？

**本步只做提炼与判断，不直接写文件**——沉淀动作统一在**第九步反思协议**执行（领域=板块扫描/
全市场异动；触发 T1/T2 才写入 OpenViking + 镜像本地 `投资经验.md`）。

---

## 第六步：逐仓复盘

对 `harness/config/持仓.md` 中每个持仓：

### 6.1 表现数据
- 开盘价 → 收盘价（涨跌幅）
- 日内最高/最低（波动幅度）
- 早盘操作建议 vs 实际走势（判断操作建议是否正确）

### 6.2 操作评估
- 如果早盘建议了操作（加/减/持）→ 实际走势验证建议质量
- 如果早盘未建议操作 → 回顾是否错过了操作机会
- 如果有 T 交易 → 评估执行质量

### 6.3 信号交叉验证
- 持仓 ETF 相关的信号是否触发？
- 触发信号是否被正确执行？
- 未触发的信号，触发条件设计是否合理？

---

## 第七步：早盘预测回顾（Generator-Evaluator 核心）

这是复盘最关键的部分。逐条对比早盘分析的预测与实际结果：

### 7.1 方向预测准确率
| 预测内容 | 预测方向 | 实际方向 | 判断 |
|---------|---------|---------|------|
| 大盘方向 | {预测} | {实际} | ✅/❌ |
| 板块轮动 | {预测} | {实际} | ✅/❌ |
| 持仓A走势 | {预测} | {实际} | ✅/❌ |

### 7.2 错误归因
对于 ❌ 的预测，区分两类错误：
- **框架盲点**：分析框架本身未覆盖的因素（如突发政策、海外黑天鹅）→ 需要扩展框架
- **数据/判断失误**：框架覆盖了但数据推断错误 → 需要修正判断逻辑

### 7.3 系统性偏差检测
- 早盘分析是否存在系统性乐观/悲观偏差？
- 最近 N 天方向预测准确率趋势如何？

---

## 第八步：信号执行复盘

> 🚨 **关键约束：信号评价必须"原地写入"到 `每日信号.md` 文件中。**
> 复盘报告（`复盘报告.md`）中可以有一个汇总版，但 `每日信号.md` 中的 `## 信号评价（复盘时填入）` 和 `## 当日信号统计` 两个节的表格**必须有实际数据行**，不能留空。
> **这是硬性要求，不是建议。如果这两个节为空，复盘视为未完成。**

对 `每日信号.md` 中的每条信号进行评级，并**原地写入**以下三个节：

### 8.0 写入位置与操作顺序

1. **先读取** `reports/{today}/每日信号.md` 当前内容
2. **修改**以下三个节的内容（保留节标题，填充表格数据行）：
   - **`## 信号评价（复盘时填入）`**：填写 7.1（决策质量）+ 7.2（执行质量）的评级结果，含入场价/出场价/P&L/持有天数/紧急度校准。**每条已触发/已执行的信号必须有一行**（未触发/已过期的信号可选填）
   - **`## 当日信号统计`**：填写 7.4 的汇总统计（含紧急度相关指标）。**所有指标必须填具体数字，不可留"—"**
   - **`## 信号收益追踪（复盘时填入）`**：填写 7.6 的本日结算信号 + 累计统计（从 signal_tracking.json 聚合）
3. **写回** `每日信号.md` 文件

### 8.1 决策质量评级 (S/A/B/C/D/F)
- S: 信号精准预判了市场走势，触发条件恰到好处
- A: 信号方向正确，触发条件合理
- B: 信号方向正确，但触发条件偏早/偏晚
- C: 信号方向错误但损失可控
- D: 信号方向错误且有明显损失
- F: 信号本身不该生成（逻辑错误/数据错误）

**升级质量评级（仅针对从关注列表升级的盘中追加信号，v2.0）：**
- U-S: 升级时机精准，升级后信号获利
- U-A: 升级方向正确，升级后信号平盘或微利
- U-B: 升级方向正确但时机偏早/偏晚
- U-C: 假突破升级——原观察信号本身不该触发（升级条件过于宽松），升级后亏损
- U-F: 该升级但未升级——方向确认明确但升级条件未触发（升级条件设计错误）

### 8.2 执行质量评级 (A/B/C/D/F)
- A: 完美执行，在最佳时机
- B: 执行了但时机差一点
- C: 部分执行或延迟执行
- D: 应该执行但未执行
- F: 不应该执行但执行了

> 🚨 **P0 零容忍规则（REQ-007）**：P0 信号触发但未执行（且未显式放弃）→ **执行质量强制 D**，复盘必须问责，
> 不做结果论豁免（即便事后看未执行反而"躲过损失"，也不改变执行纪律缺陷的定性）。P0 显式放弃（用户操作=放弃）→ 不问责。P0 执行率见 7.6.5。

### 8.3 信号遗漏与机会盲区检测（五个必答问题，答案必须写入复盘报告）

> ⚠️ 以下五问是复盘最核心的"补盲"环节。不仅思考，**必须将答案作为独立章节写入复盘报告**（格式见复盘分析-模板.md 2c 节）。

1. **机会遗漏**：今日是否有早盘分析未覆盖但实际出现的重要交易机会？（如某个板块/标的出现了入场窗口但早盘根本没有扫描到）→ 如有，为什么遗漏？是框架盲区、数据缺失、还是认知偏差？
2. **信号遗漏**：是否存在早盘未生成但实际应生成的信号？（如某个标的盘中出现了清仓条件但早盘未生成清仓信号）→ 是否有信号方向正确却被错误取消？
3. **盘中信号优先级**：是否有盘中新发现的信号（Tier 1/Tier 2）优于早盘 P0 信号？→ 如有，早盘为什么没发现？是否需要调整早盘信号生成的优先级逻辑？
4. **触发条件校准**：是否有信号触发条件设置不合理（太敏感→误触发 / 太迟钝→漏触发）？P0 信号的阈值是否需要调整？
5. **执行完整性**：信号触发记录是否完整？是否存在触发条件满足但未记录的情况？是否存在信号"已过期未执行"但实际盘中应执行的情况？**P0 执行追踪（REQ-007）**：`## P0 执行追踪` 节是否完整记录每个已触发 P0 的逐检查点响应？最终结果是否已收尾？

### 8.4 更新 `## 当日信号统计`

根据信号总表和触发记录，填充统计表：

| 指标 | 填写来源 |
|------|----------|
| 早盘生成信号总数 | 从信号总表（操作来源="早盘分析"）计数 |
| 盘中追加信号数 | 从信号总表（操作来源="盘中信号"）计数 |
| 已触发 | 信号总表中状态="已触发"或"已执行"的数量 |
| 已过期 | 信号总表中状态="已过期"的数量 |
| 已执行 | 从信号触发记录的"用户操作"列统计"已执行"数 |
| 已废弃 | 信号总表中状态="已废弃"或"已取消"的数量 |
| P0执行率 | 已执行的P0信号数 / 已触发的P0信号数（**REQ-007：调用 lib/p0_tracking.py calc_p0_execution_rate 计算，并纳入仪表盘硬指标 + 连续 2 日 <100% → P1 告警**，见 7.6.5） |
| 遗漏信号数 | 7.3 中识别到的遗漏信号（如有） |
| 高紧急度触发率 | 高紧急度信号中已触发数 / 高紧急度信号总数 |
| 低紧急度触发率 | 低紧急度信号中已触发数 / 低紧急度信号总数 |
| 紧急度正确率 | 复盘确认紧急度分配正确的信号数 / 信号总数 |
| 关注列表升级率 | 从关注列表升级触发的盘中追加信号数 / 盘中追加信号总数（目标：验证关注列表升级条件设计精度） |
| 升级质量 | 升级后盈利信号数 / 已升级信号数（目标：≥60%，低于此值需审视升级条件阈值） |
| 观察废弃率 | 已废弃的观察信号数 / 已触发的观察信号总数（目标：信息价值，废弃≠失败——正确识别不应操作也是价值） |

### 8.5 更新 `## 信号评价（复盘时填入）`

对每条信号逐条填写评价表（v2.0 扩展列）：

| 信号ID | 决策质量 | 执行质量 | 入场价 | 出场价 | P&L(元) | P&L(%) | 持有天数 | 紧急度校准 | 复盘反思 |
|--------|:------:|:------:|--------|--------|:------:|:-----:|:------:|:--------:|----------|

**填写规则：**
- 入场价/出场价：从 signal_tracking.json 中对应信号记录获取；未触发信号填"—"
- P&L(元)/P&L(%)：从 signal_tracking.json 中对应信号记录获取；卖出信号同时展示"已实现P&L"和"避免的损失"
- 持有天数：触发日到结算日之间的交易日数
- 紧急度校准：✅正确 / ⚠️偏高（过早结算）/ ⚠️偏低（追踪过长）

### 8.6 更新信号追踪数据库（v2.0 新增核心步骤；Phase 3 云库化）

> 本节将当日信号数据持久化到**云库 `signal_tracking` 表**（方案 v1.10 §9.2，signal_id 主键，
> 全量 25 字段），并结算到期的持仓信号。**本地 `signal_tracking.json` 过渡期仅作只读缓存
> （云库不可达时兜底），一次同步后废弃。**

#### 7.6.1 读取当日信号并写入追踪库（云库优先 + 本地镜像）

> ✅ **2026-08-07 修复（BUG-XXX）**：旧版嵌入式脚本是骨架（解析逻辑全是注释），导致 `signal_tracking.json` 的 `signals` 从未被写入。已改为调用 `lib/signal_tracking.py` 的 `parse_signal_markdown` + `merge_new_signals`。解析逻辑已下沉到 lib 并有单测覆盖（test_signal_tracking_parse.py）。
> ✅ **2026-09-08 云库化（Phase 3）**：解析出的记录改走 `lib/signal_tracking_cloud.upsert_signals`
> （写云库 + 镜像本地 JSON），本地 JSON 不再是权威源。

用Python脚本扫描当日信号文件，将触发/执行的信号录入追踪库（云库）：

```bash

python -c "
import sys, json
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.signal_tracking import parse_signal_markdown, merge_new_signals, update_aggregation
from lib.signal_tracking_cloud import upsert_signals, cloud_load_signals
from datetime import date

today = date.today().strftime('%Y%m%d')  # ⚠️ 必须用 yyyyMMdd，不能用 isoformat()！
signal_file = f'my_doc/每日复盘/reports/{today}/每日信号.md'

# 1. 解析当日信号文件 → 提取已触发/已执行/部分执行的信号
with open(signal_file, 'r', encoding='utf-8') as f:
    md_text = f.read()

new_records = parse_signal_markdown(md_text, date.today().isoformat())
print(f'解析出可追踪信号: {len(new_records)} 条')
for r in new_records:
    print(f\"  {r['signal_id']} {r['name']}({r['ticker']}) {r['trade_type']} 触发价={r['entry_price']}\")

# 2. 写入云库（on_conflict=signal_id 幂等）+ 镜像本地 JSON（过渡期）
ok = upsert_signals(new_records, mirror_local=True)
print(f'云库写入: {ok} 条')

# 3. 读回云库全量并重算聚合（写回本地 JSON 缓存）
cloud_signals = cloud_load_signals()
print(f'云库信号总数: {len(cloud_signals)} 条')
"
```

**执行结果判定**：
- `解析出可追踪信号: N 条`，N=当日实际触发的信号数（未触发=0 属正常，只有触发了才追踪收益）
- `云库写入: N 条`，N=成功写入条数（幂等，重跑为 0~N）
- 若信号文件不存在 → 跳过本步，写日志"信号文件缺失，跳过信号追踪"
- **云库不可达降级**：`upsert_signals` 自动回退只写本地 JSON（mirror_local 仍生效），不中断流程

**操作规则**：
- 新触发信号（已触发/已执行/部分执行）= 创建记录，status="triggered"
- 未触发的信号（已过期/已废弃/待执行）= 不录入追踪库（只有触发了才追踪收益）
- **无入场价/无份额的信号不追踪收益（2026-08-26 优化）**：parse_signal_markdown 只返回同时具备 入场价（盘中验证记录 现价/当前/开盘）+ 份额>0 的信号——无法结算 P&L 的不入库，避免追踪库积累永不结算的僵尸信号。观察类信号（仓位=观察）不追踪
- **升级信号双向链接（v3.0新增）**：
  - 对从关注列表升级的盘中追加信号（`-盘中` 后缀）→ 在 signal record 中追加 `upgraded_from` 字段，存储触发条件中的升级来源信息
  - 对状态="已升级"的原观察信号 → 在原记录中追加 `upgraded_to` 字段，存储新操作信号ID
  - 这建立双向链接，便于跨日追踪升级信号的质量（升级后信号盈利=升级决策正确）

**操作规则**：
- 新触发信号（已触发/已执行）= 创建记录，status="triggered"或"executed"
- 已有信号的用户操作更新（如从"已触发"→"已执行"）= 更新 status 和 status_history
- 未触发的信号（已过期/已废弃）= 不录入追踪库（只有触发了才追踪收益）
- **升级信号双向链接（v3.0新增）**：
  - 对从关注列表升级的盘中追加信号（`-盘中` 后缀）→ 在 signal record 中追加 `upgraded_from` 字段，存储触发条件中的升级来源信息
  - 对状态="已升级"的原观察信号 → 在原记录中追加 `upgraded_to` 字段，存储新操作信号ID
  - 这建立双向链接，便于跨日追踪升级信号的质量（升级后信号盈利=升级决策正确）

#### 7.6.2 结算到期信号（云库优先 + 本地镜像）

扫描追踪库（云库）中 status ∈ {open, triggered, executed, partial_executed} 的信号，检查是否满足结算条件并结算：

```bash
python -c "
import sys, json
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.signal_tracking import settle_due_signals, update_aggregation
from lib.signal_tracking_cloud import cloud_load_signals, cloud_upsert_signals, local_load_signals
from datetime import date

# 0. 读信号库（云库优先，云库不可用 → 本地 JSON 兜底）
signals = cloud_load_signals()
from_cloud = True
if not signals:
    signals = local_load_signals()
    from_cloud = False
db = {'signals': signals}

# 1. 构建每日收盘价表 {ticker: {date: close}}（v2.0 目标价结算需要窗口内每日收盘价）
#    ⚠️ 需要你先用 a-stock-data（腾讯日K）拉取每个待结算信号 触发日→窗口末（触发日+2交易日）的每日收盘价。
#    无法获取完整窗口的标的本次不结算（等待下次）。
price_history = {
    # '512800': {'2026-08-25': 0.798, '2026-08-26': 0.805, '2026-08-27': 0.812},
    # '159326': {'2026-08-25': 1.692, '2026-08-26': 1.700, '2026-08-27': 1.695},
}

# 2. 结算到期信号（3 交易日窗口：触发日+其后2交易日；hit/stopped/miss）
before = sum(1 for s in db['signals'] if s.get('status') == 'settled')
db = settle_due_signals(db, price_history, date.today().isoformat())
after = sum(1 for s in db['signals'] if s.get('status') == 'settled')
newly_settled = after - before

# 3. 结算结果写回云库（只 upsert 本次新结算 + 变更的信号）
if newly_settled > 0:
    changed = [s for s in db['signals'] if s.get('status') == 'settled' and s.get('settle_date') == date.today().isoformat()]
    cloud_upsert_signals(changed)
    print(f'云库结算写回: {len(changed)} 条')

print(f'到期结算完成: 本次新结算 {newly_settled} 条, 累计已结算 {after} 条 (来源: {\"云库\" if from_cloud else \"本地缓存\"})')
"
```

**结算规则**（v2.0 目标价模式，lib 内置）：
- 窗口 = 触发日 + 其后 2 个交易日（共 3 个交易日收盘点）
- 窗口内任一日收盘达到目标价 → **hit**（按目标价结算，持有天数=达标日）
- 触发止损价 → **stopped**（按止损价结算）
- 未达目标 → **miss**（按窗口末日收盘结算）
- P&L：买入=(结算价-入场价)×份额；卖出=(卖出价-成本)×份额，避免损失=(卖出价-结算价)×份额
- **云库不可达降级**：`cloud_upsert_signals` 返回 0 不抛错，本次结算结果仅镜像到本地 JSON（下次任务补写云库）

#### 7.6.3 填充信号收益追踪章节

根据**云库 `signal_tracking`（不可达时本地 JSON 缓存）**的最新数据，在复盘报告中输出：

```markdown
## 信号收益追踪

### 本日结算信号

| 信号ID | 标的 | 类型 | 紧急度 | 入场日 | 入场价 | 出场日 | 出场价 | P&L(元) | P&L(%) | 避免损失(元) | 持有天数 |
|--------|------|:---:|:---:|--------|--------|--------|--------|:------:|:-----:|:----------:|:------:|

### 累计追踪统计

| 指标 | 数值 |
|------|:---:|
| 累计追踪信号数 | {N} |
| 已结算 | {N}（持仓中: {N}） |
| 累计已执行P&L（实盘） | {±XXX.XX}元 |
| 未执行模拟P&L（假设口径） | {±XXX.XX}元 |
| 累计避免损失 | {XXX.XX}元 |
| 总胜率（仅已执行样本） | {XX}%（{W}/{L}） |
| 高紧急度: 胜率 / 平均持有天数 | {XX}% / {X.X}天 |
| 低紧急度: 胜率 / 平均持有天数 | {XX}% / {X.X}天 |

> **口径说明（REQ-006）**：`累计已执行P&L（实盘）` 仅统计 status_history 含 executed/partial_executed 的真实执行样本；
> `未执行模拟P&L（假设口径）` 为 status=triggered 且从未执行的信号按 T+3 假设结算的结果，只用于信号质量评估
> （方向/目标达成率），**不计入账户级累计 P&L / 胜率 / 期望价值**。

#### 7.6.4 信号质量仪表盘（v2.0 核心）

调用 `lib/signal_quality.py` 自动生成 8 项质量指标，渲染进复盘报告：

```bash

python -X utf8 -c "
import json, sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.signal_quality import generate_quality_dashboard
db = json.load(open('my_doc/每日复盘/harness/automation/config/signal_tracking.json', encoding='utf-8'))
settled = [s for s in db['signals'] if s.get('status') == 'settled']
print(json.dumps(generate_quality_dashboard(db['signals'], settled), ensure_ascii=False, indent=1))
" 2>&1
```

将输出渲染为（P1 周触发率目标≥40% / 目标达成率≥50% / 盈亏比≥1.5 / 方向准确率≥60%）：

```markdown
### 信号质量仪表盘

| 维度 | 指标 | 数值 | 阈值/目标 | 状态 |
|------|------|------|----------|:---:|
| 触达 | P1 触发率（累计）| {trigger_rate_p1}% | ≥40% | ✅/⚠️ |
| 触达 | 全量触发率 | {trigger_rate_all}% | — | — |
| 结果 | 目标达成率（已执行）| {target_hit_rate}% | ≥50% | ✅/⚠️ |
| 结果 | 平均达标天数（已执行）| {avg_hit_days} 天 | 1-2 天 | ✅/⚠️ |
| 结果 | 平均盈亏比（已执行）| {avg_profit_loss_ratio} | ≥1.5 | ✅/⚠️ |
| 结果 | 单笔最大亏损（已执行）| {max_loss} 元 | 风控线内 | ✅/⚠️ |
| 方向 | 方向准确率（已执行）| {direction_accuracy}% | ≥60% | ✅/⚠️ |
| 校准 | 预期vs实际偏差 | {avg_gap}pp | ±20pp 内 | ✅/⚠️ |
| 价值 | 信号期望价值（已执行）| {signal_expected_value} 元/单 | 为正 | ✅/⚠️ |
| 模拟 | 未执行模拟样本数 | {simulated_count} | — | — |
| 模拟 | 未执行模拟P&L（假设口径）| {simulated_pnl_amount} 元 | — | — |
| 模拟 | 未执行模拟期望价值 | {simulated_expected_value} 元/单 | — | — |
```

> **口径说明（REQ-006）**：账户级指标（目标达成率/盈亏比/最大亏损/方向准确率/期望价值）仅统计**已执行样本**
> （status_history 含 executed/partial_executed）；`模拟` 三行为 status=triggered 且从未执行的信号按假设结算的
> **模拟口径**，只用于方向/目标达成率评估，**不并入账户级 P&L / 胜率 / 期望价值**。
> 若 `simulated_count` 较大（≥2 或 ≥已执行 30%），复盘需回答：为何 P0/P1 信号未执行？执行缺失是否系统性？

> 目标/止损 来自信号表的 `目标/止损` 列（12 列信号表第 9 列），目标达成率评估依据；目标价设定是否过高看"目标达成率"与"平均达标天数"。

**预警与校准（必答）**：
- P1 周触发率 <40% → ⚠️ 预警：触发条件过严或信号类型需调整（给出具体建议）
- 目标达成率 <50% → 检查目标价设定是否过高（对照实际 T+3 走势）
- 预期触发率系统性高估（avg_gap < −20）→ 生成者偏乐观，建议下调预期
- **校准结论（领域=信号设计）统一在第九步反思协议沉淀**（触发 T1/T2 才写 OpenViking + 镜像 `投资经验.md` 信号设计章节），此处只作判断

### 关注列表升级专项统计（v2.0）

| 指标 | 数值 |
|------|:---:|
| 早盘关注列表项数 | {N} |
| 其中盘中升级为信号（`-盘中` 后缀） | {N} |
| 升级后盈利 | {N} |
| 未触发/证伪 | {N} |
| 升级准确率 | {XX}%（盈利/已升级） |
```

### 7.6.5 P0 执行追踪收尾（REQ-007，新增）

> 🚨 **P0 执行保障收尾**：收盘复盘对当日 P0 信号做**零容忍问责**（触发必须执行或显式放弃，不做结果论豁免），
> 计算 P0 执行率（已执行 P0 / 已触发 P0）纳入信号质量仪表盘硬指标，连续 2 日 <100% 触发 P1 级告警。

**步骤 A：调用 lib/p0_tracking.py 收尾 P0 执行追踪**

```bash
python -X utf8 -c "
import sys, json
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.p0_tracking import parse_p0_signals, calc_p0_execution_rate, merge_p0_daily, check_p0_alert
from datetime import date

today = date.today().strftime('%Y%m%d')  # ⚠️ 文件路径用 yyyyMMdd（同 §7.6.1）
today_iso = date.today().isoformat()     # 跨日库 date 键用 ISO 格式（YYYY-MM-DD）
signal_file = f'my_doc/每日复盘/reports/{today}/每日信号.md'
p0_file = 'my_doc/每日复盘/harness/automation/config/p0_tracking.json'

with open(signal_file, encoding='utf-8') as f:
    md = f.read()

records = parse_p0_signals(md, today_iso)
summary = calc_p0_execution_rate(records)
print(f'P0 触发={summary[\"triggered\"]} 已执行={summary[\"executed\"]} 执行率={summary[\"rate\"]}')
if summary['unexecuted_ids']:
    print('未执行 P0:', ', '.join(summary['unexecuted_ids']))

# 跨日库合并（幂等）
with open(p0_file, encoding='utf-8') as f:
    store = json.load(f)
store = merge_p0_daily(store, today_iso, summary)
with open(p0_file, 'w', encoding='utf-8') as f:
    json.dump(store, f, indent=2, ensure_ascii=False)

# 连续 2 日 <100% → P1 告警
alert = check_p0_alert(store)
print(json.dumps(alert, ensure_ascii=False))
"
```

**步骤 B：更新 `每日信号.md` 的 `## P0 执行追踪` 节最终结果**

- 对每条 P0 信号，按 lib `finalize_p0_result` 的判定规则将最终结果填入该信号全部行的 `最终结果` 列：
  - 用户操作 ∈ {已执行, 部分执行} → `已执行`
  - 用户操作 = 放弃 → `未执行（放弃）`（合法终态，不问责）
  - 其余（含全程 待填 / 错过 / 14:45 截止未响应）→ `未执行（错过）` → **零容忍问责**（执行质量 D）
- 盘中已标 `已过期（14:45截止未执行）` 的保持原状

**步骤 C：P0 执行率渲染入信号质量仪表盘（REQ-007 硬指标）**

在 §7.6.4 信号质量仪表盘表格中**追加一行**：

| 维度 | 指标 | 数值 | 阈值/目标 | 状态 |
|------|------|------|----------|:---:|
| 执行 | P0 执行率（当日） | {rate}%（{executed}/{triggered}） | 100%（零容忍） | ✅/🚨 |

- 当日无 P0 触发 → 数值填"—（无触发）"，状态 ✅（不构成告警）
- 状态判定：rate == 100.0 → ✅；rate < 100.0 → 🚨（并结合步骤 A 的连续天数告警）

**步骤 D：P1 级告警（连续 2 日 <100%）**

- 步骤 A 输出 `alert.alert == true` → 在复盘报告中输出：
  > 🚨 **P1 级告警（REQ-007）**：P0 执行率连续 {streak} 日 <100%（{alert.message}）
- 同时将告警写入 `PENDING_CONFIRMATION.md`（用户必须确认执行缺失根因与整改措施）

### 8.7 写入验证（‼️ 硬性门禁，禁止跳过）

> 🚨 确认信号评价和统计已正确写入 `每日信号.md` 后，必须运行以下验证脚本。验证失败 = 复盘未完成，必须回补。

```bash

python -c "
import sys

with open('my_doc/每日复盘/reports/{today}/每日信号.md', 'r', encoding='utf-8') as f:
    content = f.read()

errors = []

# 检查1: 信号评价表必须有数据行（至少1行非空）
eval_section = content.split('## 信号评价（复盘时填入）')
if len(eval_section) < 2:
    errors.append('未找到 ## 信号评价（复盘时填入） 节')
else:
    eval_text = eval_section[1].split('## ')[0] if '## ' in eval_section[1] else eval_section[1]
    eval_lines = [l for l in eval_text.split('\n') if l.strip().startswith('|') and not l.strip().startswith('|--') and '信号ID' not in l and '决策质量' not in l]
    data_rows = [l for l in eval_lines if any(c.strip() for c in l.split('|')[1:-1] if c.strip() and c.strip() != '—')]
    if len(data_rows) == 0:
        errors.append('信号评价表为空 — 必须为每条已触发/已执行的信号填写评价行')
    else:
        print(f'信号评价表: {len(data_rows)} 条评价记录')

# 检查2: 当日信号统计表必须有具体数字
stat_section = content.split('## 当日信号统计')
if len(stat_section) < 2:
    errors.append('未找到 ## 当日信号统计 节')
else:
    stat_text = stat_section[1].split('## ')[0] if '## ' in stat_section[1] else stat_section[1]
    # 检查是否还有未填充的 '—'
    placeholder_count = stat_text.count('—')
    if placeholder_count > 2:  # 允许最多2个 '—'（如遗漏信号数=0时可能用—）
        errors.append(f'当日信号统计有 {placeholder_count} 个未填充的占位符(—)，必须填具体数字')

# 检查3: 信号总表中的状态已更新（不应全为'待执行'）
signal_table = content.split('## 信号总表')
if len(signal_table) >= 2:
    table_text = signal_table[1].split('## ')[0] if '## ' in signal_table[1] else signal_table[1]
    pending_count = table_text.count('待执行')
    triggered_count = table_text.count('已触发')
    executed_count = table_text.count('已执行')
    expired_count = table_text.count('已过期')
    print(f'信号总表状态: 待执行={pending_count} 已触发={triggered_count} 已执行={executed_count} 已过期={expired_count}')

# 检查4 (REQ-007): 有已触发 P0 时，`## P0 执行追踪` 节必须存在且最终结果已填（零容忍）
import re
if '## P0 执行追踪' not in content:
    if triggered_count + executed_count > 0:
        # 需判断是否有 P0 触发：从信号总表提取 P0 行状态
        p0_lines = [l for l in table_text.split('\n') if l.strip().startswith('| P0') and '信号ID' not in l]
        p0_triggered = any(('已触发' in l or '已执行' in l) for l in p0_lines)
        if p0_triggered:
            errors.append('有已触发 P0 信号但缺少 ## P0 执行追踪 节（REQ-007 执行保障缺失）')
else:
    p0_track_text = content.split('## P0 执行追踪')[1].split('## ')[0] if '## ' in content.split('## P0 执行追踪')[1] else content.split('## P0 执行追踪')[1]
    p0_track_rows = [l for l in p0_track_text.split('\n') if l.strip().startswith('| SIG-')]
    if p0_track_rows:
        # 最终结果列（最后一列）不应全为占位 '—'（收盘复盘必须收尾）
        finals = [l.split('|')[-2].strip() for l in p0_track_rows]  # 最后一列前的单元格
        if all(f == '—' or f == '' for f in finals):
            errors.append('## P0 执行追踪 节存在 P0 记录但最终结果未填写（REQ-007 收尾缺失）')
        else:
            print(f'P0 执行追踪: {len(p0_track_rows)} 行, 最终结果已收尾')

if errors:
    print(f'[FAIL] 每日信号.md 写入验证失败 ({len(errors)} errors):')
    for e in errors:
        print(f'  ❌ {e}')
    print('必须回补每日信号.md 后再继续')
    sys.exit(1)
else:
    print('[PASS] 每日信号.md 信号评价和统计已正确写入')
" 2>&1
```

**如果验证失败**：必须回到 7.4/7.5 重新填写，直到验证通过。**禁止在验证失败的情况下继续后续步骤。**

---

## 第九步：经验反思协议（记忆体系 Phase 2 — 事件驱动 + 贝叶斯更新）

> **2026-09-08 改造**：原"写入 `harness/experience/`"升级为**反思协议**——经验统一沉淀到
> **OpenViking**（本会话 peer=xiaoman），按事件驱动触发（T1 新规律 / T2 旧经验被证伪），
> 冲突按**贝叶斯原则**调整置信度。**过渡期**同时镜像更新本地 `harness/experience/*.md`（供
> 既有消费方读取；远期镜像停更后全部切 OpenViking）。

### 9.0 检索既有经验（融会贯通前置）

先用 `viking_search` 检索与今日复盘相关的既有经验（市场判断/做T/信号设计/板块扫描/数据纪律等
领域，top-5），作为反思的对照基准——避免重复沉淀、支持"与久经验融会贯通"（新增证据更新旧条目，
而非另起炉灶）。

### 9.1 事件驱动判定（铁律：不是每次复盘都沉淀）

| 触发 | 定义 | 动作 |
|------|------|------|
| **T1 新规律** | 今日复盘发现可复用新规律（与 9.0 检索无重复） | 新建经验条目 |
| **T2 证伪/校准** | 今日事实与既有经验冲突 / 为新规律提供新证据 | 更新旧条目（证据链+置信度） |
| 两者皆无 | — | **跳过，不写**（禁止为了"完成任务"而沉淀） |

### 9.2 沉淀内容（各来源统一并入反思协议）

今日复盘以下来源的发现**一起进入本步**（不分散在各自步骤写文件）：
- **全市场异动扫描**（5.4 原"经验沉淀"→ 并入本步，标注领域=板块扫描/全市场异动）
- **信号执行复盘 / 信号收益追踪**（第八步 + 信号收益追踪 → 校准结论并入，标注领域=信号设计）
- **逐仓复盘 / 做T校准**（第六步 → 领域=做T/持仓）
- **早盘预测回顾**（第七步 Generator-Evaluator 结论 → 领域=市场判断/超跌反弹）

### 9.3 写入规则（按 `harness/experience/_schema.md` 模板）

- **T1 新建**：`viking_remember`（category=experiences），内容 = 标题 + Situation（触发场景）+
  Approach（应对/纪律，3-5 句可操作）+ Reflect（置信度默认**中**、证据链记本次 + 来源/领域/状态元数据）。
- **T2 更新**：`viking_read` 旧条目 → 追加证据链记录 `{YYYY-MM-DD} 复盘 {事实} {置信度调整}` →
  **贝叶斯更新置信度**：单次验证 中→高（不一次打满）；单次证伪 中→低（不删除）；低置信度再证伪→
  `deprecated`；冲突双方都保留各标 `conflict_with`。
- **镜像导出（过渡期）**：写入 OpenViking 后，同步把新条目/更新追加到对应本地
  `harness/experience/{投资经验,短线机会经验,报告审阅经验}.md`（按领域归属），保持镜像一致。

### 9.4 失败容错

OpenViking 不可达 → 降级写入本地临时文件 `harness/experience/_pending.md`（下次任务补写），
不阻塞主流程。

---

## 第十步：同步持仓配置（‼️ 必须在生成Staging之前执行）

> ⚠️ 关键顺序：持仓同步必须在生成 Staging（第十一步）和输出复盘报告（第十二步）之前完成，否则 staging 中的持仓表将使用旧数据。
>
> **🚨 强制规则：以下 Python 脚本必须通过 bash 实际执行，禁止凭推理模拟输出。必须看到 python 输出的 `config/持仓.md 已更新` 才算完成。**

### 10.1 执行同步脚本

```bash

python -c "
import re, os, sys, json
from datetime import date
from collections import defaultdict

# ============================================================
# 1. 读取 每日调仓.md 的当前持仓表 + 调仓记录（v4.1 增强）
# ============================================================
with open('my_doc/每日复盘/每日调仓.md', 'r', encoding='utf-8') as f:
    content = f.read()

# 1a. 解析可用金额（## 0. 可用金额，v5.0 新增）
sys.path.insert(0, 'my_doc/每日复盘/harness/automation/lib')
from position_sync import parse_available_cash, verify_cash_change
cash = parse_available_cash(content)
old_cash = None  # 旧 config 可用金额（§2 读取后填充，供 1b 交叉验证）
print(f'=== 可用金额: {cash} 元 ===' if cash is not None
      else 'WARN: 每日调仓.md 可用金额缺失或非数字（config 将保留旧值）')

# 提取 ## 1. 当前持仓 表格（兼容多种空白格式 + 标题与表格间的 可用金额/持仓： 等非表格行）
match = re.search(r'## 1\.\s*当前持仓\s*\n(?:[^\n]*\n)*?(\|.+\|\s*\n(?:\|.+\|\s*\n)+)', content)
if not match:
    print('ERROR: 无法解析每日调仓.md的当前持仓表')
    sys.exit(1)

table = match.group(1)
lines = [l for l in table.strip().split('\n') if l.strip()]
# 校验表头
if len(lines) < 2:
    print(f'ERROR: 持仓表行数不足 ({len(lines)})')
    sys.exit(1)

# 解析数据行（跳过表头和分隔行）
holdings = []
for line in lines:
    parts = [p.strip() for p in line.split('|')[1:-1]]
    # 跳过表头行和分隔行
    if not parts or parts[0] in ('股票名称', '--------', '------'):
        continue
    if len(parts) >= 4 and parts[1].isdigit() and len(parts[1]) == 6:
        holdings.append(parts)

if not holdings:
    print('ERROR: 未解析到任何持仓数据行')
    sys.exit(1)

print(f'=== 从 每日调仓.md 解析到 {len(holdings)} 个持仓 ===')
for h in holdings:
    print(f'  {h[0]} ({h[1]}): {h[2]}份 @ {h[3]}')

# ============================================================
# 1b. 提取 ## 2. 调仓记录，筛选今日交易（v4.1 新增）
# ============================================================
today_str = date.today().strftime('%Y-%m-%d')
today_trades = []
sold_by_code = defaultdict(list)
trade_match = re.search(r'## 2\.\s*调仓记录\s*\n\s*\n(\|.+\|\s*\n(?:\|.+\|\s*\n)+)', content)
if trade_match:
    trade_table = trade_match.group(1)
    trade_lines = [l for l in trade_table.strip().split('\n') if l.strip()]
    for line in trade_lines:
        parts = [p.strip() for p in line.split('|')[1:-1]]
        if not parts or parts[0] in ('日期', '--------', '------'):
            continue
        if len(parts) >= 6 and parts[0] == today_str:
            today_trades.append({
                'name': parts[1], 'code': parts[2], 'qty': parts[3],
                'price': parts[4], 'direction': parts[5], 'note': parts[6] if len(parts) > 6 else ''
            })
    print(f'=== 今日调仓记录 ({today_str}): {len(today_trades)} 笔 ===')
    for t in today_trades:
        print(f'  {t[\"direction\"]} {t[\"name\"]}({t[\"code\"]}): {t[\"qty\"]}份 @ {t[\"price\"]} {t[\"note\"]}')
else:
    print('=== 今日无调仓记录 ===')

# 1b. 可用金额交叉验证（期望新值 = 旧值 + Σ卖出 − Σ买入，v5.0 新增）
if cash is not None and old_cash is not None and today_trades:
    trade_records = [{'direction': t['direction'],
                      'qty': int(t['qty'].replace(',', '')),
                      'price': float(t['price'])} for t in today_trades]
    for warn in verify_cash_change(old_cash, cash, trade_records):
        print(f'WARN: {warn}')

# 1c. 为每个持仓匹配今日操作（v4.1 新增）
holdings_with_trades = []
for h in holdings:
    code = h[1]
    matched = [t for t in today_trades if t['code'] == code]
    if matched:
        ops = [f'{t[\"direction\"]}{t[\"qty\"]}份@{t[\"price\"]}' for t in matched]
        holdings_with_trades.append((h[0], h[1], h[2], h[3], '; '.join(ops)))
    else:
        holdings_with_trades.append((h[0], h[1], h[2], h[3], '无操作'))

# 1d. 识别今日已清仓标的（在调仓记录中有卖出但不在当前持仓中）（v4.1 新增）
for t in today_trades:
    if t['direction'] == '卖出' and t['code'] not in {h[1] for h in holdings}:
        sold_by_code[t['code']].append(t)
if sold_by_code:
    print(f'=== 今日已清仓标的 ===')
    for code, trades in sold_by_code.items():
        total_qty = sum(int(t['qty']) for t in trades)
        name = trades[0]['name']
        prices = [t['price'] for t in trades]
        notes = [t['note'] for t in trades if t['note']]
        print(f'  {name}({code}): 清仓{total_qty}份 @ ~{min(prices)}~{max(prices)} {\" | \".join(notes) if notes else \"\"}')

# ============================================================
# 2. 覆写 config/持仓.md（完全从每日调仓重建，杜绝残留）
# ============================================================
old_config_path = 'my_doc/每日复盘/harness/config/持仓.md'
old_holdings = {}
old_cash = None
if os.path.exists(old_config_path):
    with open(old_config_path, 'r', encoding='utf-8') as f:
        old = f.read()
    m_cash = re.search(r'可用金额:\s*([\d,]+)', old)
    if m_cash:
        old_cash = float(m_cash.group(1).replace(',', ''))
    for line in old.split('\n'):
        parts = [p.strip() for p in line.split('|')[1:-1]]
        if len(parts) >= 3 and parts[1].isdigit() and len(parts[1]) == 6:
            old_holdings[parts[1]] = (parts[0], parts[1], parts[2], parts[3])

# 用代码作为 key 做精确比对
new_by_code = {h[1]: h for h in holdings}
old_by_code = {c: (n,c,s,p) for c,(n,c,s,p) in old_holdings.items()}

added = [h for c, h in new_by_code.items() if c not in old_by_code]
removed = [(n,c,s,p) for c,(n,c,s,p) in old_by_code.items() if c not in new_by_code]
changed = []
for c, h in new_by_code.items():
    if c in old_by_code:
        oh = old_by_code[c]
        if h[2] != oh[2] or h[3] != oh[3]:  # 份额或成本变了
            changed.append((oh, h))

if added: print(f'新增: {[(h[0],h[1]) for h in added]}')
if removed: print(f'移除: {[(n,c) for n,c,s,p in removed]}')
if changed: print(f'变更: {[(f\"{old[0]}:{old[2]}→{new[2]}份 @{old[3]}→{new[3]}\") for old,new in changed]}')
if not added and not removed and not changed: print('持仓无变化')

# 覆写 config/持仓.md
header = '# 当前持仓\n\n> 本文件由每日复盘自动同步自 每日调仓.md，反映最新持仓状态。\n> 最后更新: 自动同步\n'
if cash is not None:
    header += f'可用金额: {cash} 元\n'
elif old_cash is not None:
    header += f'可用金额: {int(old_cash)} 元\n'
else:
    header += '可用金额: 未知 元\n'
header += '\n'
new_table = '| 股票名称 | 代码 | 持仓数量（份） | 成本价（元） |\n| -------- | ------ | -------------- | ------------ |\n'
for h in holdings:
    new_table += f'| {h[0]} | {h[1]} | {h[2]} | {h[3]} |\n'

with open(old_config_path, 'w', encoding='utf-8') as f:
    f.write(header + new_table)
print('config/持仓.md 已更新')

# 输出增强版持仓JSON供报告生成使用（v4.1 新增）
enhanced_output = {
    'holdings': [{'name': h[0], 'code': h[1], 'shares': h[2], 'cost': h[3],
                  'today_ops': next((hw[4] for hw in holdings_with_trades if hw[1] == h[1]), '无操作')}
                 for h in holdings],
    'sold_out': [{'name': trades[0]['name'], 'code': code,
                  'total_qty': sum(int(t['qty']) for t in trades),
                  'trades': [{'qty': x['qty'], 'price': x['price'], 'note': x['note']} for x in trades]}
                 for code, trades in sold_by_code.items()] if sold_by_code else [],
    'today_trades': today_trades,
    'added': [{'name': h[0], 'code': h[1]} for h in added],
    'removed': [{'name': n, 'code': c} for n,c,s,p in removed],
    'changed': [{'name': old[0], 'code': old[1], 'old_shares': old[2], 'new_shares': new[2]} for old, new in changed]
}
print(f'__POSITION_CHANGE__: added={len(added)} removed={len(removed)} changed={len(changed)} today_trades={len(today_trades)} sold_out={len(sold_by_code)}')
print(f'__HOLDINGS_JSON__: {json.dumps(enhanced_output, ensure_ascii=False)}')
" 2>&1
```

### 10.2 同步后验证（‼️ 强制，确保 config/持仓.md 与 每日调仓.md 一致）

> 🚨 此步骤为硬性门禁。如果验证失败，必须修正后重新执行 10.1，不得跳过直接输出报告。

```bash

python -c "
import re, sys

# 读取每日调仓.md的当前持仓
with open('my_doc/每日复盘/每日调仓.md', 'r', encoding='utf-8') as f:
    content = f.read()
match = re.search(r'## 1\.\s*当前持仓\s*\n(?:[^\n]*\n)*?(\|.+\|\s*\n(?:\|.+\|\s*\n)+)', content)
if not match:
    print('VERIFY_ERROR: 无法解析每日调仓.md')
    sys.exit(1)
lines = [l for l in match.group(1).strip().split('\n') if l.strip()]
src_holdings = {}
for line in lines:
    parts = [p.strip() for p in line.split('|')[1:-1]]
    if parts and parts[0] not in ('股票名称','--------','------') and len(parts)>=4 and parts[1].isdigit():
        src_holdings[parts[1]] = (parts[0], parts[2], parts[3])

# 读取config/持仓.md
with open('my_doc/每日复盘/harness/config/持仓.md', 'r', encoding='utf-8') as f:
    cfg = f.read()
cfg_holdings = {}
for line in cfg.split('\n'):
    parts = [p.strip() for p in line.split('|')[1:-1]]
    if parts and parts[0] not in ('股票名称','--------','------','') and len(parts)>=3 and parts[1].isdigit() and len(parts[1])==6:
        cfg_holdings[parts[1]] = (parts[0], parts[2], parts[3])

# 对比
errors = []
for code, (name, shares, cost) in src_holdings.items():
    if code not in cfg_holdings:
        errors.append(f'MISSING in config: {name}({code}) {shares}份 @{cost}')
    else:
        cn, cs, cc = cfg_holdings[code]
        if cs != shares or cc != cost:
            errors.append(f'MISMATCH: {name}({code}) src={shares}@{cost} config={cs}@{cc}')

for code in cfg_holdings:
    if code not in src_holdings:
        errors.append(f'STALE in config: {cfg_holdings[code][0]}({code}) — 已不在每日调仓.md当前持仓中，必须移除！')

# 可用金额一致性（v5.0 新增）
sys.path.insert(0, 'my_doc/每日复盘/harness/automation/lib')
from position_sync import parse_available_cash
cash_src = parse_available_cash(content)
cash_cfg = re.search(r'可用金额:\s*([\d,]+)', cfg)
if cash_src is not None and (not cash_cfg or int(cash_cfg.group(1).replace(',', '')) != cash_src):
    errors.append(f'可用金额不一致: src={cash_src} config={cash_cfg.group(1) if cash_cfg else "缺失"}')

if errors:
    print(f'[FAIL] 持仓同步验证失败 ({len(errors)} errors):')
    for e in errors:
        print(f'  ❌ {e}')
    sys.exit(1)
else:
    print(f'[PASS] config/持仓.md 与 每日调仓.md 一致 ({len(src_holdings)} 个持仓)')
" 2>&1
```

**如果验证失败**：检查错误详情，修正 `config/持仓.md`（或重新执行 10.1），重新运行验证直到 `[PASS]`。**禁止在验证失败的情况下生成 Staging。**

### 10.3 读取变更摘要

**根据 10.1 中 python 输出的 `__POSITION_CHANGE__` 确定持仓变更情况**（用于写入复盘报告第八节）。

---

## 第十一步：生成次日 Staging（‼️ 使用第十步同步后的最新持仓）

这是复盘最核心的产出——为明日生成完整的、可执行的 staging prompt。

这是复盘最核心的产出——为明日生成完整的、可执行的 staging prompt。

> ⚠️ 持仓表已在第十步（同步持仓配置）中更新为最新数据，此处直接使用。

### 11.0 归档当日 Staging 原件（‼️ 必须先归档，再生成次日）

> ⚠️ **顺序铁律**：11.1/11.2 会**覆盖** `staging/今日-早盘分析.md` 与 `staging/今日-复盘分析.md`。
> 若先覆盖再归档，归档到的将是"次日内容"，当日实际执行的 staging 原件永久丢失
> （8/25 起退化为"仅写归档说明.md"即此根因，BUG-002）。
> 因此归档必须在覆盖**之前**执行：此时 `今日-早盘分析.md` = 今晨早盘实际执行的 staging，
> `今日-复盘分析.md` = 今日复盘实际使用的 staging（前一日生成）。

```bash
mkdir -p "harness/archive/{today}"
cp harness/staging/今日-早盘分析.md "harness/archive/{today}/早盘分析-staging.md"
cp harness/staging/今日-复盘分析.md "harness/archive/{today}/复盘分析-staging.md"
ls -la "harness/archive/{today}/"
```

**核对**：归档目录下 `早盘分析-staging.md`/`复盘分析-staging.md` 均存在、非空，
且内容为**当日版本**（早盘文件含当日早盘分析内容、复盘文件为今日复盘所用基线）。
核对通过后才允许进入 11.1 覆盖生成次日 staging。

### 11.1 生成 `harness/staging/今日-早盘分析.md`（供明日早盘使用）

> ⚠️ 标题必须用"今日"而非"明日"——该文件在 `{tomorrow_date}` 被执行时，对消费者而言就是"今日"。
> 📄 **模板见 `my_doc/每日复盘/harness/automation/config/staging_templates.md` 的"模板一"**——先读取该文件，
> 再按占位符（`{today_date}`/`{tomorrow_date}`）填充生成，每日覆盖。

重新生成（每日覆盖），包含明日早盘分析所需的全部上下文（模板结构见 staging_templates.md 模板一）：

**新增（记忆体系 Phase 2）：经验并入 staging**——生成时用 `viking_search` 检索与**明日**场景
可能相关的量化经验（市场环境/持仓板块/做T纪律/信号设计领域，top-5），把命中的经验要点作为
**"纪律参考"小节**写入 staging（供明日早盘"第三步半 经验注入"直接使用；也兼容早盘模板
`早盘分析-模板.md` 第 205 行的纪律来源——见 Phase 3 改造）。检索为空则省略该小节，不阻塞。

---

### 11.2 生成 `harness/staging/今日-复盘分析.md`（供明日复盘使用）

> ⚠️ 此步骤与 11.1 **同等重要**，必须完整填充，禁止只写一句话跳过。
> 📄 **模板见 `my_doc/每日复盘/harness/automation/config/staging_templates.md` 的"模板二"**——先读取该文件，
> 再按占位符填充生成，每日覆盖。
>
> 该文件为明日收盘复盘提供上下文框架：持仓基线、今日关键事件、经验教训、明日核心变量。
> 如果此文件不更新（仍是旧内容），明日复盘将用过时的持仓和过期变量，导致复盘质量严重降级。
### 11.3 代码-名称交叉校验（‼️ 防止 159227→恒生科技ETF 类错误）

> ⚠️ staging 文件中的持仓表是 AI 手写的，可能把代码和名称搞混（如 159227 写成了"恒生科技ETF"而非"航空航天ETF"）。必须在归档前做自动化交叉校验。

```bash

python -X utf8 -c "
import sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from datetime import date, timedelta
from lib.staging_verify import verify_staging_file

today = date.today()
tomorrow = (today + timedelta(days=1)).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')
print(f'今天: {today_str}')
print(f'预期 staging 目标日期: {tomorrow}')

staging_files = [
    'my_doc/每日复盘/harness/staging/今日-早盘分析.md',
    'my_doc/每日复盘/harness/staging/今日-复盘分析.md'
]

errors = []
for f in staging_files:
    errs, meta = verify_staging_file(f, tomorrow, today_str)
    if meta:
        print(f'{f}: {meta["size_kb"]:.1f}KB, {meta["chars"]} chars, mtime={meta["mtime"]} ({meta["hours_ago"]}h ago)')
    errors.extend(errs)

if errors:
    print(f'[FAIL] Staging生成验证失败 ({len(errors)} errors):')
    for e in errors:
        print(f'  ❌ {e}')
    print('')
    print('*** 必须回到 Step 11.1/11.2 重新生成 staging，直到验证通过 ***')
    print('*** 禁止在 staging 验证失败的情况下继续后续步骤 ***')
    sys.exit(1)
else:
    print(f'[PASS] Staging 文件已正确生成，目标日期 {tomorrow}')
" 2>&1

**如果校验失败**：必须修正 staging 文件中的错误名称，重新运行校验直到通过，才能继续后续步骤（11.5 验证）。

### 11.4 归档确认（已在 11.0 完成）

> ✅ 当日 staging 原件已在 **11.0**（覆盖生成前）归档至 `harness/archive/{today}/`。
> 此处仅需确认归档文件仍存在（无需再次复制——重复 cp 会用次日内容覆盖原件）。
> 若 11.0 归档缺失或文件为空，**回到 11.0 前状态无法恢复当日原件**（当日 staging 已被覆盖），
> 此时只能按 BUG-002 的降级流程补写"归档说明.md"审计摘要并在日志中标注。

### 11.5 Staging 生成验证（‼️ 硬性门禁，禁止跳过）

> 🚨 此步骤为硬性门禁。Staging 是次日早盘分析+复盘的前置依赖——staging 缺失/过旧 = 次日全部降级执行。必须验证两个文件都已成功写入、日期正确、且为今日生成。

```bash

python -c "
import os, sys
from datetime import date, timedelta, datetime

today = date.today()
tomorrow = (today + timedelta(days=1)).strftime('%Y-%m-%d')
today_str = today.strftime('%Y-%m-%d')
print(f'今天: {today_str}')
print(f'预期 staging 目标日期: {tomorrow}')

errors = []
staging_files = [
    'my_doc/每日复盘/harness/staging/今日-早盘分析.md',
    'my_doc/每日复盘/harness/staging/今日-复盘分析.md'
]

for f in staging_files:
    if not os.path.exists(f):
        errors.append(f'MISSING: {f} — 文件不存在，Step 11.1/11.2 可能未执行')
        continue
    
    stat = os.stat(f)
    size_kb = stat.st_size / 1024
    mtime = datetime.fromtimestamp(stat.st_mtime)
    hours_ago = (datetime.now() - mtime).total_seconds() / 3600
    
    with open(f, 'r', encoding='utf-8') as fh:
        content = fh.read()
    
    # 检查1: 文件不能太小（空文件或只有标题=无效）
    if len(content) < 500:
        errors.append(f'TOO SMALL: {f} 仅 {len(content)} 字符 — staging 生成不完整')
        continue
    
    # 检查2: 必须包含目标日期（tomorrow = 执行日期）
    if tomorrow not in content:
        import re
        dates_found = re.findall(r'\d{4}-\d{2}-\d{2}', content)
        dates_str = ', '.join(dates_found[:5]) if dates_found else '无日期'
        errors.append(f'WRONG DATE: {f} 应包含执行日期 {tomorrow}，实际日期: {dates_str}')
    
    # 检查3: 文件必须包含今日生成标记（today_str），防止旧文件未被覆盖
    if today_str not in content and '/'.join(today_str.split('-')[1:]) not in content:
        import re
        dates_found = re.findall(r'\d{4}-\d{2}-\d{2}', content)
        dates_str = ', '.join(dates_found[:5]) if dates_found else '无日期'
        errors.append(f'STALE: {f} 缺少今日生成日期 {today_str}，可能仍是旧文件未覆盖。文件内日期: {dates_str}')
    
    # 检查4: 文件修改时间必须在今天（防止9.1/9.2未执行但旧文件恰好包含tomorrow日期）
    if mtime.date() < today:
        errors.append(f'STALE_MTIME: {f} 最后修改于 {mtime.strftime(\"%Y-%m-%d %H:%M\")}（{hours_ago:.1f}h前），不在今天——Step 11.1/11.2未执行！')
    
    print(f'{f}: {size_kb:.1f}KB, {len(content)} chars, mtime={mtime.strftime(\"%H:%M\")} ({hours_ago:.1f}h ago)')

if errors:
    print(f'[FAIL] Staging生成验证失败 ({len(errors)} errors):')
    for e in errors:
        print(f'  ❌ {e}')
    print('')
    print('*** 必须回到 Step 11.1/11.2 重新生成 staging，直到验证通过 ***')
    print('*** 禁止在 staging 验证失败的情况下继续后续步骤 ***')
    sys.exit(1)
else:
    print(f'[PASS] Staging 文件已正确生成，目标日期 {tomorrow}')
" 2>&1
```

**如果验证失败**：必须回到 Step 11.1/11.2 重新生成 staging 文件，直到 11.3（交叉校验）和 11.5（生成验证）全部通过。**禁止在验证失败的情况下继续第十二步。**

---

## 第十二步：输出复盘报告

写入 `reports/{today}/复盘报告.md`：
（完整格式遵循 `harness/prompts/复盘分析-模板.md`）

> 🚫 REQ-004：复盘报告**不输出**"二、当前使用的策略 / 三、数据口径"独立章节（口径规则见模板文件头"执行口径备忘"）；"全市场异动扫描"为**行业/题材版**（第五步）。

> ⚠️ 此时 config/持仓.md 已经是最新持仓（第十一步已完成同步），报告中必须使用最新持仓数据。

### "一、我的持仓"表格格式规则（v4.1）

> **规则：已清仓标的直接并入持仓表格，不单独列出"已清仓标的"节。**
>
> 表格包含两类行：
> 1. **当前持仓**（从 10.1 `__HOLDINGS_JSON__` 的 `holdings` 数组获取）：正常显示持仓数量+成本价，今日操作列显示匹配的调仓记录
> 2. **今日已清仓标的**（从 10.1 `__HOLDINGS_JSON__` 的 `sold_out` 数组获取）：持仓数量列显示 `0（已清仓）`，成本价列显示 `—`，今日操作列显示完整的卖出信息（数量+均价+备注），行首名称加 `~~删除线~~` 标记
>
> 示例格式：
> ```
> | ~~半导体ETF~~ | 512480 | 0（已清仓） | — | 1.027 | -1.34% | 1.052/0.978 | 🔴 卖出15,800份@~1.016（止损） |
> ```
>
> 排序：当前持仓在前（按代码排序），已清仓标的在后（按代码排序）。

---

## 第十三步：报告审阅（2-3轮自检）

按照 `harness/experience/报告审阅经验.md` 的检查清单逐项核验：
1. 数据核验轮（16 项）
2. 逻辑一致性轮（8 项）
3. 完整性轮（8 项）

发现错误 → 修正 → 重新核验，最多 3 轮。

### 13.5 运行提示与工单提交（REQ-004 新增，报告定稿前执行）

> 报告生成与自检过程中发现运行问题 → ① 报告尾部"运行提示"节**一行提示**；② 按下方映射**提交 BUG/REQ 工单**供定时任务处理（harness_bug_auto_fix / auto_req_implement）。

**问题清单与处理映射**：

| 运行问题 | 报告提示（1 行） | 工单 |
|---------|----------------|------|
| 数据源探测 `all_fail`（任务中止） | 无报告（已中止，写入执行日志） | BUG P1，`auto_fix_eligible=false`（MANUAL_REVIEW） |
| 数据源探测 `partial`（≥2 源不可达，或同一源连续 2 交易日不可达） | `⚠️ 数据源降级：{源列表}` | BUG P2，`auto_fix_eligible=false`（需人工判断代码/网络） |
| staging 缺失 / 过期重建 / 持仓过期 | `⚠️ staging {问题}，已{处理}` | BUG P2，`auto_fix_eligible=false`（复盘流程异常） |
| 异常数据：|涨跌幅|>15% 未解释 / 成本未复权（如 159227 浮亏 -62.84%）/ 份额调整 | `⚠️ 异常数据：{标的} {问题}`（持仓复盘处同步标注） | BUG P2，`auto_fix_eligible=false`（涉及成本/复权修正，MANUAL_REVIEW） |
| 持仓同步失败（第十步报错） | `⚠️ 持仓同步失败，可能过期` | BUG P1，`auto_fix_eligible=false` |
| 信号入库/结算异常（8.6 节） | `⚠️ 信号追踪异常：{问题}` | BUG P1/P2 按影响定级 |
| 自检发现结构/逻辑错误且已修正 | 无需提示 | 无需建单 |
| 自检发现无法当场修正的系统性问题 | `⚠️ 自检发现：{问题}` | BUG P1/P2 按影响定级 |
| 系统性框架改进机会（如异动扫描盲区） | （可选一行） | REQ P1/P2，`steering/open/REQ-{NNN}.md` |

**建单步骤（bash 执行，禁止凭推理）**：

```bash
# 1. 去重检查（同主题 OPEN/IN_PROGRESS/MANUAL_REVIEW 工单已存在 → 只追加处理记录，不新建）
grep -n "BUG-" "my_doc/每日复盘/harness/automation/bugs/BUG_INDEX.md" | head -30
grep -n "REQ-" "my_doc/每日复盘/harness/automation/steering/REQ_INDEX.md" | head -30

# 2. 计算下一个编号 + 去重判定（lib 纯函数，防多 Agent 同日撞号）
python -X utf8 -c "
import sys
sys.path.insert(0, 'my_doc/每日复盘/harness/automation')
from lib.issue_tracker import next_ticket_id, dedup_find
bug_index = open('my_doc/每日复盘/harness/automation/bugs/BUG_INDEX.md', encoding='utf-8').read()
req_index = open('my_doc/每日复盘/harness/automation/steering/REQ_INDEX.md', encoding='utf-8').read()
print('next_bug_id:', next_ticket_id(bug_index, 'BUG'))
print('next_req_id:', next_ticket_id(req_index, 'REQ'))
print('dup_bug:', dedup_find(bug_index, 'BUG', ['数据源', 'push2', 'staging', '成本', '持仓同步']))
"
```

**建单规则**：
- BUG 按 `bugs/BUG_TEMPLATE.md` 格式创建到 `bugs/open/BUG-{NNN}.md`（可用 `lib.issue_tracker.render_bug_markdown` 渲染正文），并同步更新 `BUG_INDEX.md`（列表 + 统计数）
- REQ 按 `steering/REQ_TEMPLATE.md` 格式创建到 `steering/open/REQ-{NNN}.md`，并同步更新 `REQ_INDEX.md`
- **去重铁律**：同主题待处理工单已存在 → 在工单"处理记录"中追加 `| {时间} | 复现 | {当日现象} |`，不重复建单；问题持续 ≥3 交易日未解决 → 登记 `PENDING_CONFIRMATION.md` 提醒用户
- 涉及金融计算/成本修正类问题一律 `auto_fix_eligible=false`（MANUAL_REVIEW），交人工确认

**报告尾部格式**：

```
*数据来源: ...（详见 a-stock-data skill）*
*数据标注: {降级数据源/异常数据标注}*
*运行提示: {仅当存在运行问题时输出；格式：⚠️ {问题}（已提交 BUG-{NNN}）}*
```

---

## 第十四步：REQ 验证与闭环（v3.0 新增）

> 本节闭合 REQ 生命周期的最后一环：IMPLEMENTED → 效果验证 → CLOSED。

### 14.1 扫描 IMPLEMENTED REQ

```bash

echo "=== IMPLEMENTED REQs (每日复盘) ==="
grep "IMPLEMENTED" "my_doc/每日复盘/harness/automation/steering/REQ_INDEX.md" || echo "无 IMPLEMENTED REQ"
```

### 14.2 逐条验证

对每个 IMPLEMENTED 的 REQ：

1. **读取 REQ 文件**，提取期望结果和验收标准
2. **对照今日复盘结果**：REQ 的预期效果是否在今日数据中体现？
   - 如 REQ-001（信号收益追踪）：signal_tracking.json 是否正确更新？复盘报告中是否展示了信号收益汇总？
   - 如 REQ-002（信号设计质量提升）：今日信号触发率是否改善？紧急度分配是否正确？
3. **运行关联测试**（如 REQ 处理记录中有测试用例）：
   ```bash

   # 根据 REQ 影响范围选择测试命令
   # 数据结构变更 → Python schema 验证
   # Prompt 改动 → grep 验证关键字段
   # Python 代码 → pytest
   ```

### 14.3 判定

对每个 IMPLEMENTED REQ，运行测试后按以下规则判定：

```bash
cd my_doc/每日复盘/harness/automation
python -m pytest tests/test_{REQ-ID}.py -v --tb=short 2>&1
```

| 情况 | 判定 | 操作 |
|------|:---:|------|
| 测试通过 + 复盘数据确认效果 | ✅ 可 CLOSED | 推进到 CLOSED，记录验证结果 |
| 测试通过但效果不明确 | ⏸️ 保持 IMPLEMENTED | 追加观察备注，设定观察截止日（+3 交易日） |
| 测试失败或效果为负 | ❌ 需修复 | 保持 IMPLEMENTED，创建 BUG 到 `harness/automation/bugs/open/` |
| 无测试文件 | ⚠️ 保持 IMPLEMENTED | **自动创建补测子 REQ** 写入 `steering/open/REQ-{NNN}-TEST.md`，标题"补测: {原标题}"，优先级继承原 REQ，状态 OPEN |

#### 13.3.1 BUG 创建（测试失败时）

当测试失败或复盘数据确认效果为负：
1. 按 `harness/automation/bugs/BUG_TEMPLATE.md` 模板创建 BUG
2. 写入 `harness/automation/bugs/open/BUG-{NNN}.md`
3. BUG 中引用来源 REQ 编号（形成 REQ↔BUG 双向链接）
4. REQ 退回 IN_PROGRESS（若实现有 bug）或保持 IMPLEMENTED（若仅需测试校准）

#### 13.3.2 补测子 REQ 创建（无测试文件时）

1. 复制原 REQ 文件到 `steering/open/REQ-{NNN}-TEST.md`
2. 修改标题为 "补测: {原标题}"
3. 状态设为 OPEN，优先级继承原 REQ
4. 在 REQ_INDEX.md 中登记
5. 下一次 `auto_req_implement` 会认领并执行完整的 superpowers 流程（含 TDD）

### 14.4 更新 REQ 状态

对推进到 CLOSED 的 REQ：

1. 更新 REQ 文件：
   ```markdown
   - **状态**: CLOSED
   ```
2. 追加处理记录：
   ```markdown
   | {时间} | 验证→CLOSED | 测试{N}通过; 复盘确认: {简述效果}; 闭环完成 |
   ```
3. 更新 `REQ_INDEX.md` 状态汇总（IMPLEMENTED -1, CLOSED +1）

### 14.5 已 CLOSED REQ 的效果追踪

对最近 5 个交易日内 CLOSED 的 REQ，快速检查：
- REQ 的效果是否**持续有效**（而非一次性改善后又退化）？
- 如果退化 → 创建新 REQ，标注 "Related: {原 REQ-ID} 效果退化"

### 14.6 经验沉淀

如果 REQ 推进到 CLOSED，提取可复用的经验：
```markdown
| {时间} | 经验沉淀 | 从 {REQ-ID} 闭环中学习: {关键教训/可复用模式} |
```

将经验追加到对应的 `harness/experience/` 文件（按内容分类归属）。

---

## 第十五步：更新 task_state → completed + 写入日志

标记 `evening_review.status` = "completed"，记录所有产出文件列表，**并显式写入 `staging_generated=true`**（BUG-007 修复项②：消除 C4 连续三日 WARN——staging 已在第十一步生成并通过 11.3/11.5 验证）：

```bash

python -c "
import json
from datetime import datetime
path = 'my_doc/每日复盘/harness/automation/config/task_state.json'
state = json.load(open(path, encoding='utf-8'))
er = state['tasks']['evening_review']
er['status'] = 'completed'
er['completed_at'] = datetime.now().isoformat()
er['staging_generated'] = True
er['outputs'] = ['复盘报告.md', 'staging/今日-早盘分析.md', 'staging/今日-复盘分析.md', '每日信号.md(已回填评价)']
json.dump(state, open(path, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
print('task_state evening_review → completed, staging_generated=true')
"
```

---

## 第十六步：最终产出验证（‼️ 硬性门禁）

> 🚨 此步骤为复盘的最后一道防线。验证所有关键产出文件是否存在、是否为今日生成。验证失败 = 复盘未完成，必须回补。

```bash

python -c "
import os, sys
from datetime import date, timedelta, datetime

today = date.today()
today_ymd = today.strftime('%Y%m%d')
today_str = today.strftime('%Y-%m-%d')
tomorrow_str = (today + timedelta(days=1)).strftime('%Y-%m-%d')

errors = []

# 1. 验证复盘报告
report_path = f'my_doc/每日复盘/reports/{today_ymd}/复盘报告.md'
if os.path.exists(report_path):
    mtime = datetime.fromtimestamp(os.path.getmtime(report_path))
    if mtime.strftime('%Y-%m-%d') == today_str:
        size_kb = os.path.getsize(report_path) / 1024
        print(f'✅ 复盘报告: {report_path} ({size_kb:.1f}KB, {mtime.strftime(\"%H:%M\")})')
    else:
        errors.append(f'复盘报告存在但非今日生成 (mtime={mtime.strftime(\"%Y-%m-%d\")})')
else:
    errors.append(f'复盘报告不存在: {report_path}')

# 2. 验证早盘分析 staging
morning_staging = 'my_doc/每日复盘/harness/staging/今日-早盘分析.md'
if os.path.exists(morning_staging):
    with open(morning_staging, 'r', encoding='utf-8') as f:
        content = f.read()
    if len(content) < 500:
        errors.append(f'早盘分析staging过小 ({len(content)}字符): {morning_staging}')
    elif tomorrow_str not in content:
        errors.append(f'早盘分析staging缺少明日日期({tomorrow_str}): {morning_staging}')
    else:
        print(f'✅ 早盘分析staging: {morning_staging} ({len(content)}字符, 目标日期={tomorrow_str})')
else:
    errors.append(f'早盘分析staging不存在: {morning_staging}')

# 3. 验证复盘分析 staging
review_staging = 'my_doc/每日复盘/harness/staging/今日-复盘分析.md'
if os.path.exists(review_staging):
    with open(review_staging, 'r', encoding='utf-8') as f:
        content = f.read()
    if len(content) < 500:
        errors.append(f'复盘分析staging过小 ({len(content)}字符): {review_staging}')
    elif tomorrow_str not in content:
        errors.append(f'复盘分析staging缺少明日日期({tomorrow_str}): {review_staging}')
    else:
        print(f'✅ 复盘分析staging: {review_staging} ({len(content)}字符, 目标日期={tomorrow_str})')
else:
    errors.append(f'复盘分析staging不存在: {review_staging}')

# 4. 验证归档
archive_dir = f'my_doc/每日复盘/harness/archive/{today_ymd}'
if os.path.isdir(archive_dir):
    files = os.listdir(archive_dir)
    print(f'✅ 归档目录: {archive_dir} ({len(files)}个文件)')
else:
    errors.append(f'归档目录不存在: {archive_dir}')

# 输出结果
if errors:
    print(f'\n❌ 最终验证失败 ({len(errors)}个错误):')
    for e in errors:
        print(f'  ❌ {e}')
    print('\n*** 必须回补缺失文件后重新验证 ***')
    sys.exit(1)
else:
    print(f'\n✅ 最终验证通过 — 所有产出文件已正确生成')
" 2>&1
```

**如果验证失败**：必须回到对应步骤重新生成缺失文件，重新运行验证直到通过。**禁止在验证失败的情况下标记 task_state 为 completed。**

**如果验证通过**：继续执行第十五步（更新 task_state → completed）或确认已完成。

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
| 发现系统性改善机会 | 创建 REQ 文档到 `my_doc/每日复盘/harness/automation/steering/open/REQ-{NNN}.md`，按 `steering/REQ_TEMPLATE.md` 模板（模板已内置 superpowers 开发流程：brainstorming→writing-plans→TDD→executing-plans→code-review），并在 `steering/REQ_INDEX.md` 中登记 |

---

## 第十七步：标记完成 + 清除运行锁

> 复盘完成时标记调度器任务为已完成，并清除运行锁。

```bash
python .claude/scripts/task_scheduler.py --complete evening_review
python .claude/scripts/task_scheduler.py --clear-running evening_review
```

> ⚠️ 如果复盘因异常中断，此步骤不会执行。此时 `check_running()` 的 stale 检测会在 45 分钟后自动清除该锁，后续迭代恢复正常。


