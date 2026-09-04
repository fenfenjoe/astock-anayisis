---
name: quant-strategy-discovery
description: 量化策略发现与转化 — 从国内量化平台（聚宽/BigQuant/SuperMind/优矿/米筐/GitHub）搜索、提取、转化高收益策略到本项目的ETF回测框架，含平台导航、搜索模式、策略解析、代码转化模板、回测集成全流程。
origin: custom
version: 1.0.0
---

# 量化策略发现与转化 SKILL V1.0

从国内量化社区发现策略 → 提取核心逻辑 → 转化为 `etf-strategies` 框架代码 → 回测验证。

---

## 一、平台速查表

### 1.1 主要策略来源

| 平台 | 入口 | 特点 | 可访问性 |
|------|------|------|---------|
| **聚宽 JoinQuant** | `joinquant.com/view/community/list` | 策略天梯、一键克隆、500+精华 | ⚠️ 需登录看源码 |
| **BigQuant** | `bigquant.com/square/ai` | AI策略广场、StockRanker、策略商城 | ⚠️ 需登录克隆 |
| **SuperMind** | `quant.10jqka.com.cn/view/community` | 同花顺生态、爱问财NL选股 | ⚠️ 白名单分享 |
| **GitHub** | 搜索 `joinquant` `ricequant` `量化策略` | 开源策略源码、可直接克隆 | ✅ 可访问 |
| **知乎** | 搜索"量化策略" | 高质量策略文章+源码 | ✅ 可访问 |
| **CSDN** | 搜索"聚宽 策略" | 大量策略教程+代码 | ✅ 可访问 |
| **掘金** | 搜索"ETF 轮动" | 技术向策略文章 | ✅ 可访问 |

### 1.2 GitHub 推荐仓库

| 仓库 | 内容 | 亮点 |
|------|------|------|
| `HiRenyi/EasyQuant` | 28个验证策略源码 | ETF轮动+小市值，有回测指标 |
| `goldcoast/quanStrategy` | ETF动量轮动专项 | MACD+动量+市场情绪 |
| `neoo726/joinquant2qmt` | ETF轮动+排行榜分配 | 含夏普/回撤指标 |
| `08zhangyi/multi-factor-gm-wind-joinquant` | 多因子框架 | 单因子研究+行业轮动 |
| `thuquant/awesome-quant` | 量化资源索引 | 中国量化资源大全 |

---

## 二、策略搜索模式

### 2.1 搜索关键词模板

按策略类型选择：

```
# ETF/指数轮动
"聚宽 ETF 轮动 策略 源码 年化 夏普"
"ETF momentum rotation joinquant source code"

# 小市值多因子
"聚宽 小市值 策略 完整源码 多因子 年化 回撤"
"small cap multi-factor joinquant strategy"

# 动量/趋势
"joinquant 动量 策略 源码 年化收益×R²"
"dual momentum ETF rotation China A-share"

# AI/机器学习
"BigQuant StockRanker 策略 年化 源码"
"AI quantitative strategy A-share ETF backtest"

# 行业轮动
"聚宽 行业轮动 策略 源码 夏普"
"sector rotation A-share ETF strategy code"
```

### 2.2 策略评估标准

搜索到策略后，按以下标准筛选：

| 维度 | 绿灯（推荐转化） | 黄灯（谨慎） | 红灯（跳过） |
|------|----------------|-------------|------------|
| 年化收益 | 15-50% | 50-100% | >100%（过拟合嫌疑） |
| 夏普比率 | 0.8-2.0 | 2.0-3.5 | >3.5（数据挖掘嫌疑） |
| 回测周期 | 5年+ | 3-5年 | <3年（样本不足） |
| 最大回撤 | <30% | 30-50% | >50% |
| 逻辑可解释性 | 清晰可描述 | 部分黑箱 | 完全不可解释 |
| 参数数量 | 2-4个 | 5-8个 | >8个（过拟合风险） |
| 代码可用性 | 完整源码 | 核心代码片段 | 仅有文字描述 |

---

## 三、策略逻辑提取模板

从任意平台提取策略核心逻辑，填写：

```yaml
策略名称: "[策略名]"
来源平台: "[聚宽/BigQuant/GitHub/...]"
来源链接: "[URL]"
策略类型: "[ETF轮动/小市值/均线趋势/多因子/...]"

ETF池:
  - "[代码] # [名称/类型]"
  - ...

核心打分公式: "[数学公式或文字描述]"

关键参数:
  lookback: N        # 动量回看天数
  top_n: N           # 持仓数量
  rebalance: "[daily/monthly/weekly]"
  threshold: N       # 调仓阈值（如有）

风控机制:
  - "[止损/择时空仓/波动率过滤/...]"

原始回测指标:
  annual_return: X%
  sharpe: X.XX
  max_drawdown: -X%
  period: "YYYY-MM ~ YYYY-MM"
```

---

## 四、代码转化模板

### 4.1 策略类文件标准结构

```python
"""S{N}_{策略中文名}：{一句话描述}。

来源：{平台 + 作者 + 链接}
原理：{核心逻辑 2-3 句}

{调仓频率 + 特殊机制说明}。
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from .base import Strategy


class {StrategyClassName}(Strategy):
    """S{N}_{策略中文名}"""

    name = "S{N}_{策略中文名}"

    def __init__(self, {参数列表}):
        {参数赋值}
        self.assets = {ETF代码列表}

    def generate(self, prices):
        """
        prices: 日期×资产 收盘价 DataFrame
        返回: 日期×资产 目标权重 DataFrame (0~1, 每行和≈1)
        """
        # 1. 计算信号
        # 2. 排名选 top_n
        # 3. 构建权重
        # 4. 调仓节奏（resample 或每日直接返回）
        return weights
```

### 4.2 JoinQuant → 本框架 API 映射

| JoinQuant API | 本框架等效 |
|---------------|-----------|
| `attribute_history(etf, N, '1d', ['close'])` | `prices[etf].iloc[-N:]` |
| `get_price(etf, count=N, fields=['close'])` | `prices[etf].iloc[-N:]` |
| `np.polyfit(x, y, 1)` | `np.polyfit(x, y, 1)` (相同) |
| `math.pow(math.exp(slope), 250) - 1` | `np.exp(slope * 250) - 1` |
| `order_target_value(etf, value)` | 权重 := value / total_value |
| `context.portfolio.positions` | 引擎自动管理（滞后1日） |
| `run_daily(trade, '9:30')` | `generate()` 每日信号 + 引擎 shift(1) |
| `g.xxx` (全局参数) | `self.xxx` (实例属性) |

### 4.3 常见打分公式

**公式1: 年化收益 × R² (最常用)**
```python
y = np.log(closes)
x = np.arange(len(y))
slope, intercept = np.polyfit(x, y, 1)
annualized_return = np.exp(slope * 250) - 1
y_pred = slope * x + intercept
ss_res = np.sum((y - y_pred) ** 2)
ss_tot = (len(y) - 1) * np.var(y, ddof=1)
r_squared = 1 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0
score = annualized_return * r_squared
```

**公式2: 简单动量 (收益率排名)**
```python
momentum = closes[-1] / closes[0] - 1
score = momentum  # 或排序后用 rank
```

**公式3: 多因子加权**
```python
score = w1 * factor1 + w2 * factor2 + w3 * factor3
# 因子间需要归一化到相近量级
```

**公式4: 效率比率**
```python
direction = abs(np.log(closes[-1]) - np.log(closes[0]))
volatility = np.sum(np.abs(np.diff(np.log(closes))))
efficiency = direction / volatility if volatility > 0 else 0
score = np.log(closes[-1] / closes[0]) * efficiency
```

---

## 五、回测集成 Checklist

新增策略的标准操作流程：

1. **创建策略文件** `etf-strategies/backtest/strategies/{name}.py`
2. **编写测试** 在 `tests/test_strategies.py` 中添加至少3个测试：
   - 权重和=1
   - 正确选中目标资产
   - warmup期行为正确
3. **运行测试** `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_strategies.py -v`
4. **注册策略** 在 `run_backtest.py` 中：
   - 添加 `from backtest.strategies.{name} import {Class}`
   - 添加到 `strategies` 列表
5. **更新报告** 在 `reporting.py` 中添加策略说明
6. **运行回测** `python run_backtest.py`
7. **验证指标** 检查：
   - 年化收益在合理范围（不与原始策略偏离过大）
   - 回撤不异常
   - 换手率与调仓频率一致
   - 不同策略间可比（同数据窗口）

### 首次获取新ETF数据

新 ETF 代码通过 `load_prices_for_strategy()` 自动从东财拉取并缓存 parquet：
- ETF 上市日期不同会自动对齐（`dropna()`）
- 如果某 ETF 上市较晚，策略回测窗口会相应缩短
- 东财 API 有 1s+ 限流，批量获取多只 ETF 时需等待

---

## 六、策略库索引

### 已实现（16个）

#### 被动/基准类
| # | 策略 | 文件 | 类型 | 年化 | 夏普 | 回撤 | 来源 |
|---|------|------|------|------|------|------|------|
| S1 | 买入持有 | `buy_hold.py` | 被动/基准 | 8.19% | 0.30 | -52.97% | 自研 |
| S5 | 等权组合 | `equal_weight.py` | 因子/等权 | 7.70% | 0.44 | -35.91% | 经典理论 |
| S6 | 60-40股债平衡 | `portfolio_6040.py` | 配置 | 5.71% | 0.45 | -22.00% | 经典配置 |

#### 动量/趋势类
| # | 策略 | 文件 | 类型 | 年化 | 夏普 | 回撤 | 来源 |
|---|------|------|------|------|------|------|------|
| S2 | 双动量 | `dual_momentum.py` | 动量/避险 | 5.60% | 0.39 | -24.58% | Gary Antonacci |
| S3 | 均线趋势 | `ma_trend.py` | 趋势跟踪 | 6.99% | 0.35 | -51.17% | 经典TA |
| S4 | 多资产动量轮动 | `momentum_rotation.py` | 动量轮动 | **33.62%** | **1.21** | -28.51% | JoinQuant post/26142 |
| S8 | 三因子动量轮动 | `three_factor_momentum.py` | 多因子动量 | **34.82%** | **1.27** | -28.51% | 知乎猫哥AI |
| S14 | 动态波动率调整动量 | `adaptive_momentum.py` | 动量/自适应 | — | — | — | JoinQuant @0xtao |
| S15 | 趋势过滤+动量增强 | `rsrs_momentum.py` | 动量/趋势过滤 | — | — | — | JoinQuant @蚂蚁量化 |
| S16 | 金丝雀防御+动量进攻 | `canary_defense.py` | 动量/风险预警 | — | — | — | Meb Faber |

#### 多因子类
| # | 策略 | 文件 | 类型 | 年化 | 夏普 | 回撤 | 来源 |
|---|------|------|------|------|------|------|------|
| S9 | 行业动量轮动 | `industry_momentum.py` | 行业轮动 | 2.95% | 0.14 | -46.03% | 自研 |
| S10 | 低波动因子 | `low_vol.py` | 多因子/低波 | 11.79% | **1.39** | **-9.68%** | 学术低波异象 |
| S12 | 量价情绪多因子 | `sentiment_momentum.py` | 多因子/情绪 | — | — | — | Stanford MS&E 448 |
| S13 | 多因子综合打分 | `multi_factor.py` | 多因子 | — | — | — | JoinQuant ETF加权轮动 |

#### 风险控制类
| # | 策略 | 文件 | 类型 | 年化 | 夏普 | 回撤 | 来源 |
|---|------|------|------|------|------|------|------|
| S7 | 目标波动率 | `target_vol.py` | 风险控制 | 9.55% | 0.57 | -40.90% | 风险预算 |
| S11 | 布林带均值回归 | `bollinger.py` | 均值回归 | 10.78% | 0.47 | -43.62% | 经典TA |

> 指标来源：全量回测 2012-2026（各策略窗口因ETF上市时间不同而异）。"—" 表示待回测。

### 候选池（已调研，待转化）

| 策略 | 来源 | 年化 | 夏普 | 回撤 | 转化难度 |
|------|------|------|------|------|---------|
| ETF加权轮动(动量+质量+双止损) | 韭神~/聚宽 | ~47.9% | 2.57(Sortino) | ~22% | 🟡 需止損模塊 |
| 低相关性ETF趋势轮动 | JoinQuant | ~37% | 1.32 | ~21% | 🟡 需相关矩阵 |
| 波动率动态调整+RSRS | 光大/聚宽 | ~43.5% | 2.27 | -23.3% | 🔴 需high/low数据 |
| 改良全天候(目标年化>8% DD<3%) | 聚宽 | ~8.5% | 1.4 | -2.8% | 🟡 需协方差 |
| 债券ETF轮动(纯债) | 微信公众号 | ~18.2% | 2.09 | -5.4% | 🟢 可快速转化 |
| 宽基轮动(8只ETF) | 微信公众号 | ~52.9% | 1.83 | -23.5% | 🟢 可快速转化 |
| 小市值+ETF轮动(四五月切换) | 聚宽 | ~101.9% | 4.43(Sortino) | -26.7% | 🔴 需股票数据 |

---

## 七、搜索经验总结（2026-07-09 更新）

### 7.1 高效搜索关键词

| 场景 | 推荐关键词 | 命中率 |
|------|-----------|--------|
| 找高夏普ETF策略 | `聚宽 ETF 轮动 高夏普 源码` | ⭐⭐⭐⭐⭐ |
| 找低回撤策略 | `ETF 轮动 低回撤 最大回撤 源码` | ⭐⭐⭐⭐ |
| 找最新策略 | `joinquant ETF momentum 2024 2025` | ⭐⭐⭐⭐ |
| 找GitHub源码 | `GitHub 量化 ETF 策略 夏普 年化 Python` | ⭐⭐⭐ |
| 找A股适配策略 | `A股 ETF 量化策略 回测 年化收益` | ⭐⭐⭐ |

### 7.2 策略评估速查

搜索到策略后，优先看以下指标（按重要性排序）：
1. **夏普比率 > 1.0**（核心门槛，风险调整后收益是否合理）
2. **最大回撤 < 30%**（持有体验，过大回撤实盘无法坚持）
3. **年化收益 20-50%**（合理区间；>100%通常是过拟合或短窗口）
4. **回测周期 ≥ 5年**（至少覆盖一轮牛熊）
5. **调仓频率**（日频→换手率会很高，实际成本可能吃掉收益）
6. **参数数量 2-4个**（参数过多=过拟合风险高）

### 7.3 转化注意事项

- **数据可用性**：确认策略所需数据在本框架中可获得（目前支持 close/open/high/low/vol/amount/amp）
- **调仓频率**：日频策略在实盘中冲击成本会显著拉低收益，建议回测中如实建模（slippage + commission）
- **ETF上市时间**：新ETF上市日期不同，会自动通过 dropna() 对齐 → 回测窗口可能缩短
- **货币ETF兜底**：所有策略应有 `cash="511880"` 作为无信号时的避险选项
- **避免重复**：检查已有策略库，避免实现逻辑高度重复的策略（如多个动量×R²变体）
- **来源标注**：每个策略的 docstring 必须标注来源平台+作者+原始指标，便于后续审计

### 7.4 常见陷阱

| 陷阱 | 表现 | 应对 |
|------|------|------|
| Sortino冒充Sharpe | 聚宽社区默认展示Sortino Ratio（通常比Sharpe高30-50%） | 看原始日收益率自己算Sharpe |
| 短回测窗口 | 2019-2024仅一轮牛市，不能代表全周期 | 要求≥5年或自己回测更长周期 |
| 幸存者偏差 | ETF池中都是事后看表现好的品种 | 加入宽基指数作为对照基准 |
| 过拟合参数 | 调参后年化从20%跳到80% | 怀疑参数>4个的策略，做敏感性分析 |
| 忽略流动性 | 小ETF（日均成交<1000万）回测无摩擦，实盘有价差冲击 | 加入流动性过滤 |
| 未来函数 | 策略中不小心用到了未来数据（如当天high算信号当天执行） | 严格1日滞后（t日信号→t+1日执行） |

---

## 八、快速执行流程
