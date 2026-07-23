# 策略转化与回测

> 触发方式: 人工审查绿灯候选后手动触发
> 用途: 将外部策略源码转化为 etf-strategies 框架的 Strategy 子类，测试 + 回测 + 注册

---

## 前提

本 prompt 需要接收一个具体的候选策略（从 strategy_scan_weekly.md 产出）。触发时附上候选策略的 YAML 信息：

```yaml
# [在此粘贴候选策略的 YAML — 由人工在触发时填入]
```

---

## 任务角色

你是量化策略工程师。你的任务是将外部平台的策略代码转化为本项目 etf-strategies 回测框架中可直接运行的 Strategy 子类。

---

## 第一步：读取现有框架代码（理解模式）

在执行转化前，先阅读以下关键文件以理解当前框架规范：

1. `etf-strategies/backtest/strategies/base.py` — Strategy 基类接口
2. `etf-strategies/backtest/strategies/momentum_rotation.py` — 动量轮动策略（S4，最标准的转化参考）
3. `etf-strategies/backtest/strategies/rsrs_momentum.py` — RSRS动量策略（S18，复杂策略转化参考）
4. `etf-strategies/backtest/data.py` — 数据层 API（load_prices 用法）
5. `.claude/skills/quant-strategy-discovery/SKILL.md` 第 4 节 — 代码转化模板

---

## 第二步：转化策略代码

### 2.1 平台 API 映射

如果源码来自聚宽等平台，将平台特定 API 映射到本项目框架：

| 聚宽 API | 本项目等价 |
|----------|-----------|
| `attribute_history(security, count, unit, fields)` | `prices[etf].iloc[-count:]` |
| `get_price(security, start, end, frequency, fields)` | `prices[etf]` (已由 load_prices 预加载) |
| `order_target_value(security, value)` | 设置权重 = value / total_nav |
| `context.portfolio.positions` | 通过 `weights` DataFrame 管理 |
| `get_trade_days(start, end)` | 使用 prices 的 index（已对齐交易日） |

### 2.2 通用评分公式模板

根据策略的核心公式选择模板：

**模板 A: 年化收益 × R²**（动量轮动类）
```python
log_prices = np.log(prices[etf])
slope, intercept = np.polyfit(np.arange(len(log_prices)), log_prices, 1)
annual_return = np.exp(slope * 250) - 1
r_squared = 1 - (ss_res / ss_tot)
score = annual_return * (r_squared ** 2)
```

**模板 B: 简单动量**（N日收益率）
```python
momentum = prices[etf].iloc[-1] / prices[etf].iloc[-lookback] - 1
score = momentum
```

**模板 C: 多因子加权**（自定义权重）
```python
score = (
    w1 * factor1_normalized +
    w2 * factor2_normalized +
    w3 * factor3_normalized
)
```

**模板 D: 效率比**
```python
net_change = abs(prices[etf].iloc[-1] - prices[etf].iloc[0])
path = np.sum(np.abs(np.diff(prices[etf])))
score = net_change / path if path > 0 else 0
```

### 2.3 创建策略文件

路径: `etf-strategies/backtest/strategies/{snake_case_name}.py`

必须遵循的规范：
```python
"""
{策略中文名}

来源: {平台} — {URL}
作者: {作者}
原始回测指标: 年化 {x}%, 夏普 {y}, 最大回撤 {z}%
转化日期: {today}
"""

import numpy as np
import pandas as pd
from .base import Strategy


class {ClassName}(Strategy):
    name = "{short_name}"  # 英文缩写，8字符以内

    def __init__(self, assets=None, **params):
        if assets is not None:
            self.assets = assets
        # 如果策略使用固定ETF池:
        # self.assets = ["513100", "159915", "510180", "518880"]
        self.lookback = params.get("lookback", {default_value})
        # ... 其他参数

    def generate(self, prices: pd.DataFrame) -> pd.DataFrame:
        # 1. 输入验证
        if prices.empty or len(prices.columns) == 0:
            return pd.DataFrame(0.0, index=prices.index, columns=prices.columns)

        weights = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)

        # 2. 按调仓频率生成信号
        # 每日调仓:
        for i in range(self.lookback, len(prices)):
            # 计算评分
            scores = self._calculate_scores(prices.iloc[:i+1])
            # 选最高分
            best = scores.idxmax()
            weights.iloc[i][best] = 1.0

        # 或月度调仓:
        # for month_end in monthly_dates:
        #     ...

        return weights

    def _calculate_scores(self, prices_window: pd.DataFrame) -> pd.Series:
        """计算所有资产的评分"""
        scores = pd.Series(0.0, index=prices_window.columns)
        for etf in prices_window.columns:
            # 核心评分逻辑
            scores[etf] = ...
        return scores

    def get_diagnostics(self, prices: pd.DataFrame) -> dict:
        """返回策略当前内部状态（供 Dashboard 使用）"""
        if len(prices) < self.lookback:
            return {"parameters": {"lookback": self.lookback},
                    "scores": {}, "holdings": self.assets}
        scores = self._calculate_scores(prices)
        return {
            "parameters": {"lookback": self.lookback},
            "scores": {etf: round(float(s), 4) for etf, s in scores.items()},
            "holdings": self.assets
        }
```

---

## 第三步：编写测试

在 `etf-strategies/tests/test_strategies.py` 末尾追加测试函数（至少 3 个）：

```python
class Test{ClassName}:
    """测试 {策略中文名}"""

    def test_weights_sum_to_one(self, sample_prices):
        """权重和 = 1.0（或全零 = 空仓）"""
        from backtest.strategies.{snake_case_name} import {ClassName}
        strat = {ClassName}()
        weights = strat.generate(sample_prices)
        max_deviation = abs(weights.sum(axis=1) - 1.0).max()
        all_cash = abs(weights.sum(axis=1)).max() < 0.01
        assert max_deviation < 0.01 or all_cash, \
            f"权重偏差 {max_deviation:.4f}，非空仓也非满仓"

    def test_weights_index_matches_prices(self, sample_prices):
        """权重 index 与输入 prices 一致"""
        from backtest.strategies.{snake_case_name} import {ClassName}
        strat = {ClassName}()
        weights = strat.generate(sample_prices)
        assert weights.index.equals(sample_prices.index), \
            "权重日期索引与价格不一致"
        assert list(weights.columns) == list(sample_prices.columns), \
            "权重资产列与价格不一致"

    def test_warmup_returns_empty_or_equal(self, sample_prices):
        """Warmup 期逻辑正确"""
        from backtest.strategies.{snake_case_name} import {ClassName}
        strat = {ClassName}()
        weights = strat.generate(sample_prices)
        warmup_len = strat.lookback
        warmup = weights.iloc[:warmup_len]
        # Warmup 期间应为空仓或等权
        is_empty = abs(warmup.sum(axis=1)).max() < 0.01
        is_equal = abs(warmup.sum(axis=1) - 1.0).max() < 0.01
        assert is_empty or is_equal, \
            f"Warmup 期权重异常: 和的范围 {warmup.sum(axis=1).min():.4f} ~ {warmup.sum(axis=1).max():.4f}"

    def test_scores_with_synthetic_trend(self):
        """合成趋势数据 → 策略应选到正确的资产"""
        from backtest.strategies.{snake_case_name} import {ClassName}
        import pandas as pd
        import numpy as np

        # 创建 3 个资产的合成数据：A 趋势向上，B 横盘，C 趋势向下
        dates = pd.date_range("2020-01-01", periods=200, freq="B")
        np.random.seed(42)
        a = 100 * (1 + np.linspace(0, 0.5, 200) + np.random.randn(200) * 0.02)
        b = 100 * (1 + np.random.randn(200) * 0.02)
        c = 100 * (1 - np.linspace(0, 0.3, 200) + np.random.randn(200) * 0.02)
        prices = pd.DataFrame({"A": a, "B": b, "C": c}, index=dates)

        strat = {ClassName}()
        weights = strat.generate(prices)
        scores = strat.get_diagnostics(prices)["scores"]

        # 最佳资产（A）的评分应最高
        assert scores.get("A", -999) == max(scores.values()), \
            f"合成趋势数据中 A 应得分最高，实际: {scores}"
```

---

## 第四步：注册策略

在以下 3 个文件中注册新策略：

### 4.1 `run_backtest.py`
在策略 import 区域追加：
```python
from backtest.strategies.{snake_case_name} import {ClassName}
```
在 `STRATEGIES` 列表中追加：
```python
    {ClassName}(),
```

### 4.2 `daily_signal.py`
在 import 区域追加：
```python
from backtest.strategies.{snake_case_name} import {ClassName}
```
在 `STRAT_MAP` dict 中追加：
```python
    "S{next_id}": {ClassName}(),
```

### 4.3 `list_strategies.py`
在 import 区域追加：
```python
from backtest.strategies.{snake_case_name} import {ClassName}
```
在 `STRATEGIES` 列表中追加：
```python
    {ClassName},
```

---

## 第五步：运行测试

```bash
cd E:/ideaworkspace/astock-anayisis/etf-strategies
python -m pytest tests/test_strategies.py -v -k "{ClassName}" --tb=short
```

如果失败：
- 读取失败信息
- 修复代码
- 重新运行直到全部通过

最多重试 3 次，3 次后仍失败 → 记录失败原因，中止转化。

---

## 第六步：运行回测

```bash
cd E:/ideaworkspace/astock-anayisis/etf-strategies
python run_backtest.py
```

从输出中提取新策略的指标：
- 年化收益率
- 夏普比率
- 最大回撤
- 胜率
- 换手率
- Calmar 比率

---

## 第七步：更新知识库

在 `strategy_kb.py` 的 `KB` dict 中追加新条目：

```python
    "S{next_id}": {
        "name": "{策略中文名}",
        "category": "{动量型/因子型/风控型/资产配置型/自适应型}",
        "intro": "{策略简介，含来源}",
        "stock_selection": "{选股逻辑}",
        "timing": "{择时逻辑}",
        "factors": ["{因子1}", "{因子2}"],
        "rebalance": "{每日/每周/月度}",
        "advantage": ["{优势1}", "{优势2}"],
        "disadvantage": ["{劣势1}", "{劣势2}"],
        "backtest_params": {
            "start": "{回测起始}",
            "end": "{回测结束}",
            "lookback": {回看期},
            "top_n": {选股数},
            "source": "{来源平台}",
            "source_url": "{来源URL}",
            "original_metrics": {
                "annual_return": "{原始年化}",
                "sharpe": "{原始夏普}",
                "max_drawdown": "{原始最大回撤}"
            }
        }
    },
```

---

## 第八步：生成转化报告

写入 `etf-strategies/automation/archive/{YYYY-MM-DD}/convert_{strategy_name}.md`：

```markdown
# 策略转化报告 — {策略名}

## 来源
- 平台: {平台}
- URL: {链接}
- 作者: {作者}

## 转化过程
- 策略文件: etf-strategies/backtest/strategies/{name}.py
- 策略ID: S{id}
- 测试结果: {通过数}/{总数} PASS
- 转化日期: {today}

## 回测结果对比

| 指标 | 原始数据 | 本项目回测 | 偏差 |
|------|---------|-----------|------|
| 年化收益率 | {orig}% | {ours}% | {diff}% |
| 夏普比率 | {orig} | {ours} | {diff} |
| 最大回撤 | {orig}% | {ours}% | {diff} |
| 胜率 | {orig}% | {ours}% | {diff} |

## 偏差分析
{偏差 >20% 时的分析：ETF池不同？回测区间不同？成本模型不同？}

## 注册清单
- [x] 策略文件创建
- [x] 回测引擎注册 (run_backtest.py)
- [x] 每日信号注册 (daily_signal.py)
- [x] 策略列表注册 (list_strategies.py)
- [x] 知识库更新 (strategy_kb.py)
- [x] 测试通过
- [x] 回测完成
```

---

## 异常处理

- 策略代码逻辑与知识库描述严重不符 → 中止转化，记录原因
- ETF 资产池中的 ETF 数据不可用 → 检查 parquet 缓存，必要时先拉取数据
- 磁盘空间不足 → 清理 archive 中 >90 天的旧报告
