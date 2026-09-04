---
name: testing
description: ETF回测项目测试增强 — 运行测试、编写新测试、策略验证、Mock数据模式、覆盖率检查、回归测试、与Superpowers TDD集成
origin: custom
version: 1.0.0
---

# ETF 回测项目测试增强 SKILL V1.0

为 `etf-strategies` 项目提供完整的测试能力增强。

---

## 一、测试运行速查

```bash
# 全量测试
cd etf-strategies && python -m pytest tests/ -v

# 仅运行策略测试
python -m pytest tests/test_strategies.py -v

# 运行特定测试函数
python -m pytest tests/test_strategies.py::test_dual_momentum_hold_stock_when_up -v

# 带覆盖率报告
python -m pytest tests/ -v --cov=backtest --cov-report=term-missing

# 失败即停
python -m pytest tests/ -x

# 只运行上次失败的测试
python -m pytest tests/ --lf
```

---

## 二、项目测试架构

```
etf-strategies/
├── tests/
│   ├── conftest.py          # 共享 fixtures：synth_prices, flat_prices
│   ├── test_cost.py         # Cost 对象
│   ├── test_data.py         # 数据层：K线拉取、缓存、多标对齐
│   ├── test_em_client.py    # 东财客户端
│   ├── test_engine.py       # 回测引擎
│   ├── test_metrics.py      # 指标计算
│   └── test_strategies.py   # 全部策略 + 跨策略不变量
└── pytest.ini
```

### 核心 Fixtures（conftest.py）

| Fixture | 用途 | 数据特征 |
|---------|------|---------|
| `synth_prices` | 通用合成价格 | 510300 +1%/日, 511260 +0.1%/日, 10天 |
| `flat_prices` | 平价序列 | 全部 100.0，隔离成本/再平衡算术 |

### 策略测试辅助函数（test_strategies.py）

| 函数 | 用途 |
|------|------|
| `_prices(up_a, n)` | 单/双资产：510300 上涨/下跌 + 现金 |
| `_prices_multi(n)` | 多资产：黄金/纳指/创业板/上证180 不同梯度 |

---

## 三、为新功能编写测试

### 3.1 策略测试模板

```python
from backtest.strategies.my_strategy import MyStrategy

def test_my_strategy_weights_sum_to_one():
    """warmup 期后每行权重和≈1"""
    p = _prices_multi(n=120)
    s = MyStrategy(param1=val1)
    w = s.generate(p)
    valid = w.iloc[50:]
    rowsums = valid.sum(axis=1)
    assert ((rowsums - 1.0).abs() < 1e-6).all()

def test_my_strategy_signal_direction():
    """验证策略信号方向正确"""
    p = _prices(up_a=True)
    s = MyStrategy()
    w = s.generate(p[["510300", "511880"]])
    assert w["510300"].iloc[-1] > 0.5

def test_my_strategy_defensive():
    """验证下跌市中防御行为"""
    p = _prices(up_a=False)
    s = MyStrategy()
    w = s.generate(p[["510300", "511880"]])
    assert w["511880"].iloc[-1] > w["510300"].iloc[-1]
```

### 3.2 跨策略不变量注册

每新增策略必须加入 `test_all_strategies_weights_sum_to_one`：

```python
(MyStrategy(param1=val1), ["518880", "513100", "159915", "510180"]),
```

---

## 四、Mock 与合成数据模式

### 网络请求 Mock

```python
def test_with_mock(monkeypatch):
    fake_data = [{"date": "2026-01-02", "close": 3.52}]
    monkeypatch.setattr("backtest.data.eastmoney_kline", lambda code, **kw: fake_data)
    df = get_kline("510300", start="2026-01-01", end="2026-06-30", refresh=True)
    assert len(df) == 1

def test_real_network_with_skip():
    try:
        df = get_kline("510300", ...)
    except Exception as e:
        pytest.skip(f"网络不可用: {e}")
```

### 合成价格公式

```
匀速上涨: price[i] = 100 * (1 + r)^i
匀速下跌: price[i] = 100 * (1 - r)^i
震荡:     price[i] = 100 + A * sin(i / period)
多梯度:   每个资产不同 r 值
```

---

## 五、回归测试工作流

```
1. 确保现有测试全绿
   cd etf-strategies && python -m pytest tests/ -v

2. 编写新功能测试（正向/边界/反向/不变量）

3. 运行全量确认无回归
   python -m pytest tests/ -v

4. 检查覆盖率
   python -m pytest tests/ -v --cov=backtest --cov-report=term-missing
```

### 新增策略测试 Checklist

| # | 检查项 | 测试方法 |
|---|--------|---------|
| 1 | 权重每行和=1 | `((rowsums - 1.0).abs() < 1e-6).all()` |
| 2 | 权重在 [0,1] | `(w >= 0).all() and (w <= 1).all()` |
| 3 | Warmup 期等权/现金 | 检查 warmup 行 |
| 4 | 信号方向正确 | 涨市做多、跌市防御 |
| 5 | 参数边界 | 极端 lookback/top_n |
| 6 | 短数据/空数据处理 | rows < warmup |
| 7 | Cash 列存在 | `"511880" in w.columns` |
| 8 | 无未来函数 | 滞后信号验证 |
| 9 | 跨策略注册 | `test_all_strategies_weights_sum_to_one` |
| 10 | 引擎集成 | `backtest(prices, weights)` 正常返回 |

---

## 六、与 Superpowers 集成

| Superpowers 阶段 | 本 skill 补充 |
|-----------------|-------------|
| brainstorming | 确定测试策略（mock/合成数据选择） |
| test-driven-development | 提供测试模板、fixtures 参考 |
| verification-before-completion | 运行全量测试 + 覆盖率 |
| code-review | 检查 Checklist 覆盖率 |

### 触发指令

```
运行全量测试
运行策略测试
检查测试覆盖率
为新策略生成测试
回归测试
```

---

## 七、覆盖目标

| 模块 | 目标 | 风险 |
|------|------|------|
| `cost.py` | 100% | 成本错误→净值错误 |
| `metrics.py` | 100% | 指标口径错误 |
| `engine.py` | 95%+ | 回测逻辑核心 |
| `data.py` | 85%+ | 重点测缓存+解析 |
| `strategies/*.py` | 90%+ | 每策略正+负+不变量 |
| `reporting.py` | 80%+ | 测数据结构 |
| `em_client.py` | 75%+ | mock 测试为主 |

### 盲区覆盖

| 盲区 | 方案 |
|------|------|
| `reporting.py` | 测 `build_summary_table()` 返回值 |
| `daily_signal.py` | 合成数据验证信号方向 |
| `cli.py` | `subprocess.run` 测试 |
| `dashboard/` | sqlite in-memory 测试 |
| 策略注册遗漏 | `test_strategy_registry` 自动发现 |

---

## 八、故障排查

| 症状 | 可能原因 | 解决 |
|------|---------|------|
| 权重和不等于1 | warmup 期处理不当 | 增大 `w.iloc[30:]` |
| 网络测试超时 | 东财 API 不可用 | `pytest.skip` 或 mock |
| 精度断言失败 | 浮点累积误差 | `abs(a-b) < 1e-6` |
| Monkeypatch 无效 | patched 路径错误 | 用 import 后命名空间路径 |
| 信号方向相反 | 合成数据方向搞反 | 检查 `up_a=True/False` |
| ModuleNotFoundError | 策略未注册 | `strategies/__init__.py` 导入 |

### 调试命令

```bash
python -m pytest tests/test_strategies.py::test_xxx -vv --tb=long
python -m pytest tests/test_strategies.py::test_xxx --pdb
python -m pytest tests/ --lf
```
