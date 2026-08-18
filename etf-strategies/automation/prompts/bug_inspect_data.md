# BUG 数据质量巡检（交易日盘前）

> 定时任务: 交易日 08:00 CST | CronCreate durable
> 用途: 缓存新鲜度 → 除权除息检测 → 跨源交叉验证 → 确保信号生成的数据基础可靠

---

## 任务角色

你是量化系统的数据质量守门员。在每日信号和早盘分析运行前，确保数据基础是可靠的。

---

## 前置检查：是否交易日

```bash

python my_doc/每日复盘/harness/automation/config/trading_calendar.py
```

如果 `is_trading_day` = false → 输出 "今日非交易日，跳过数据质量巡检" 并退出。

---

## 第一步：缓存新鲜度检查

检查 `etf-strategies/cache/` 下所有 parquet 文件的最后修改时间：

```bash
cd etf-strategies
python -c "
import os, glob
from datetime import datetime, timedelta

cache_dir = 'cache'
yesterday = datetime.now().date() - timedelta(days=1)
stale_files = []

for f in glob.glob(f'{cache_dir}/*.parquet'):
    mtime = datetime.fromtimestamp(os.path.getmtime(f)).date()
    if mtime < yesterday:
        stale_files.append(f'{f} (last: {mtime})')

if stale_files:
    print('STALE CACHE FILES:')
    for f in stale_files:
        print(f'  {f}')
    print(f'Total: {len(stale_files)} stale')
else:
    print('OK: 所有缓存文件新鲜')
"
```

如果有过期文件 > 24h → BUG（严重程度: MEDIUM）

---

## 第二步：除权除息/异常价格检测

对每个活跃策略使用的 ETF（从 strategy_kb.py 提取），检查最近 5 个交易日是否有异常价格跳动：

```bash
cd etf-strategies
python -c "
import pandas as pd, glob, os

etfs = ['510300','510500','510180','159915','512480','512800','512880',
        '512010','512660','513100','518880','511260','511880','159697','159326','159227']

for f in glob.glob('cache/*.parquet'):
    code = os.path.basename(f).replace('.parquet','')
    if code in etfs:
        df = pd.read_parquet(f)
        if len(df) >= 5:
            recent = df.iloc[-5:]
            pct_changes = recent['close'].pct_change().dropna()
            jumps = pct_changes[abs(pct_changes) > 0.15]  # 15% 单日跳动
            if len(jumps) > 0:
                for date, chg in jumps.items():
                    print(f'WARNING: {code} on {date.date()}: {chg:.2%} price jump')
"
```

如果有 >15% 的单日价格跳动：
- 可能是除权除息（ETF 分红或拆分）→ 标记为 INFO，不需要修复
- 可能是数据错误 → 标记为 BUG（严重程度: HIGH），需要重新拉取数据

---

## 第三步：跨源价格交叉验证

随机抽取 3 个 ETF（覆盖不同类型：宽基/行业/跨境），对比东财数据与腾讯财经数据的收盘价：

使用 `a-stock-data` skill 获取腾讯财经的收盘价数据，与 parquet 缓存的东财数据对比：

- 如果差异 < 0.1% → OK
- 如果差异 0.1% - 0.5% → WARNING（记录但不算 BUG）
- 如果差异 > 0.5% → BUG（严重程度: HIGH）

---

## 第四步：活跃策略 ETF 数据完整性

检查所有活跃策略（在 daily_signal.py STRAT_MAP 中注册的）使用的 ETF 是否都有数据：

```bash
cd etf-strategies
python -c "
import pandas as pd, glob, os, sys
from datetime import datetime, timedelta

# 收集所有策略使用的 ETF
all_etfs = set()
from list_strategies import STRATEGIES
for s in STRATEGIES:
    try:
        if hasattr(s, 'assets'):
            all_etfs.update(s.assets)
    except:
        pass

# 检查每个 ETF 的缓存
missing_data = []
for etf in all_etfs:
    cache_file = f'cache/{etf}.parquet'
    if not os.path.exists(cache_file):
        missing_data.append(f'{etf}: 无缓存文件')
    else:
        df = pd.read_parquet(cache_file)
        last_date = df.index[-1].date()
        if (datetime.now().date() - last_date).days > 3:
            missing_data.append(f'{etf}: 最后数据日期={last_date}（>3天前）')

if missing_data:
    print('DATA INCOMPLETE:')
    for m in missing_data:
        print(f'  {m}')
    sys.exit(1)
else:
    print(f'OK: 所有 {len(all_etfs)} 个活跃 ETF 数据完整')
"
```

---

## 第五步：生成 BUG 报告

（格式同 bug_inspect_code.md）

**auto_fix_eligible 判定**：
- 缓存过期需要重新拉取 → `true`（自动执行 `a-stock-data` 重拉）
- 跨源价差 >0.5% 需排查根因 → `false`（需判断哪个源正确）
- 数据缺失需补拉 → `true`（自动执行数据拉取）
- 异常价格跳动疑似除权 → `false`（需判断是除权还是数据错误）

---

## 第六步：更新 BUG_INDEX.md

（同代码巡检）

---

## 第七步：输出控制台摘要

```
=== 数据质量巡检报告 {YYYY-MM-DD} ===
缓存新鲜度: {OK / N个过期}
异常价格检测: {OK / N个异常}
跨源验证: {OK / N个不一致 > 0.5%}
数据完整性: {OK / N个缺失}

{如果一切正常：数据质量门通过，早盘分析和信号生成可以安全执行}
{如果有异常：问题列表 + 是否阻塞信号生成}
```

---

## 决策逻辑

- 如果有 CRITICAL 级数据问题（如多个活跃 ETF 数据缺失）→ **阻塞**本日信号生成，输出 "数据质量门未通过，信号生成中止"
- 如果仅有 MEDIUM 级问题（如 1-2 个非活跃 ETF 过期）→ 输出 WARNING，不阻塞
- 如果 HIGH 级问题（如跨源价差 >0.5%）→ 标记为 BUG，但信号生成仍继续（使用东财源），在信号报告中附加数据质量备注
