# A股 ETF 策略回测框架 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 A 股真实数据上回测 4 个 ETF 策略（买入持有/双动量/均线趋势/60-40），输出含指标与可视化的回测报告。

**Architecture:** 自研向量化回测引擎（pandas/numpy）。数据层走东财 push2his 前复权日K（`em_get` 限流防封 + parquet 缓存）。策略只产目标权重信号，引擎统一处理信号滞后/成本/净值。TDD 先红后绿。

**Tech Stack:** Python 3.11.4, pandas 3.0.3, numpy 1.26.4, matplotlib（需装）, pytest（需装）, requests, mootdx 0.11.7

## Global Constraints

- **数据铁律**：行情数据一律走东财 push2his `fqt=1` 前复权日K（已验证 510300 返回 3424 根 2012-05-28 至今），禁止估算/编造。失败须明确报错。
- **东财防封**：所有东财请求走 `em_get()`，串行限流 `EM_MIN_INTERVAL=1.0s` + 随机抖动 + Keep-Alive session + 429/5xx 退避重试（403 不重试）。
- **信号滞后 1 日**：`target_weights.shift(1)` — t 日收盘算信号，t+1 日收盘执行，杜绝前视偏差。
- **复权**：东财 `fqt=1` 已前复权，收益直接算。
- **公共起始对齐**：多资产策略取所有标的公共首个交易日，缺口记 NaN 不外推。
- **成本**：佣金万2.5（最低5元，初始100万可忽略）+ ETF免印花税 + 滑点万1，单边≈0.035%。
- **编码**：Windows 控制台 GBK，所有脚本开头 `sys.stdout.reconfigure(encoding='utf-8', errors='replace')`，打印禁用 ✓/✗ 等 GBK 无法编码字符，用 `[OK]/[FAIL]`。
- **临时脚本**：一次性取数脚本用 `_*.py`，跑完即删。
- **目录**：所有代码在 `E:\ideaworkspace\astock-anayisis\etf-strategies\` 下。
- **初始资金**：1,000,000。

---

## File Structure

```
etf-strategies/
  backtest/
    __init__.py
    em_client.py     # em_get 限流客户端（复用 SKILL.md helper）
    data.py          # get_kline() 东财前复权日K + parquet 缓存
    cost.py          # Cost 成本模型
    engine.py        # backtest() 向量化引擎 + BacktestResult
    metrics.py       # 指标计算
    reporting.py     # markdown + matplotlib 报告
    strategies/
      __init__.py
      base.py        # Strategy 基类
      buy_hold.py    # S1
      dual_momentum.py  # S2
      ma_trend.py    # S3
      portfolio_6040.py  # S6
  tests/
    __init__.py
    conftest.py      # 合成价格 fixture
    test_em_client.py
    test_data.py
    test_cost.py
    test_engine.py
    test_metrics.py
    test_strategies.py
  run_backtest.py    # 入口
  cache/             # parquet 缓存（gitignore）
  pytest.ini
```

---

## Task 1: 脚手架 + em_get 限流客户端

**Files:**
- Create: `etf-strategies/backtest/__init__.py`（空）
- Create: `etf-strategies/backtest/em_client.py`
- Create: `etf-strategies/tests/__init__.py`（空）
- Create: `etf-strategies/tests/test_em_client.py`
- Create: `etf-strategies/pytest.ini`
- Create: `etf-strategies/cache/.gitkeep`

**Interfaces:**
- Produces: `em_get(url, params=None, headers=None, timeout=15, **kwargs) -> requests.Response`；`EM_SESSION`；`EM_MIN_INTERVAL`；`eastmoney_kline(code, start='20120101', end='20261231') -> list[dict]`

- [ ] **Step 1: 安装依赖**

```bash
cd /e/ideaworkspace/astock-anayisis/etf-strategies
pip install matplotlib pytest
```
Expected: Successfully installed。

- [ ] **Step 2: 写 pytest.ini**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
```

- [ ] **Step 3: 写失败测试 test_em_client.py**

```python
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from backtest.em_client import em_get, EM_SESSION, EM_MIN_INTERVAL, eastmoney_kline

def test_em_get_returns_response():
    """em_get 能拿到东财响应（真实网络，标记 slow）"""
    r = em_get("https://push2his.eastmoney.com/api/qt/stock/kline/get",
               params={"secid":"1.510300","klt":"101","fqt":"1",
                       "fields1":"f1,f2,f3,f4,f5,f6",
                       "fields2":"f51,f52,f53,f54,f55,f56,f57,f58",
                       "beg":"20260101","end":"20261231"},
               headers={"Referer":"https://quote.eastmoney.com/"}, timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert len(d["data"]["klines"]) > 0

def test_eastmoney_kline_parses():
    """eastmoney_kline 解析为 dict 列表，含 date/open/close"""
    rows = eastmoney_kline("510300", start="20260101", end="20260630")
    assert len(rows) > 0
    assert "date" in rows[0] and "close" in rows[0]
    assert isinstance(rows[0]["close"], float)

def test_em_min_interval_is_positive():
    assert EM_MIN_INTERVAL >= 1.0
```

- [ ] **Step 4: 运行测试验证失败**

```bash
cd /e/ideaworkspace/astock-anayisis/etf-strategies && python -m pytest tests/test_em_client.py -v
```
Expected: FAIL `ModuleNotFoundError: No module named 'backtest.em_client'`

- [ ] **Step 5: 实现 em_client.py**

```python
"""东财统一限流客户端 — 复用 a-stock-data SKILL.md 的 em_get helper。
所有东财请求走 em_get()：串行限流 + 会话复用 + 退避重试，防封 IP。"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import time, random, requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
try:
    _adapter = HTTPAdapter(max_retries=Retry(
        total=3, connect=3, backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"]))
    EM_SESSION.mount("https://", _adapter)
    EM_SESSION.mount("http://", _adapter)
except Exception:
    pass

EM_MIN_INTERVAL = 1.0
_em_last_call = [0.0]

def em_get(url, params=None, headers=None, timeout=15, **kwargs):
    """东财统一请求入口：自动节流 + 复用 session + 默认 UA。"""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()

def eastmoney_kline(code, start="20120101", end="20261231"):
    """东财前复权日K。code: 6位ETF代码。返回 list[dict]: date/open/close/high/low/vol/amount/amp。"""
    secid = f"1.{code}" if code.startswith(("5","6")) else f"0.{code}"
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid, "klt": "101", "fqt": "1",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "beg": start, "end": end,
    }
    r = em_get(url, params=params, headers={"Referer": "https://quote.eastmoney.com/"}, timeout=15)
    d = r.json()
    klines = (d.get("data") or {}).get("klines") or []
    rows = []
    for line in klines:
        p = line.split(",")
        if len(p) >= 7:
            rows.append({
                "date": p[0], "open": float(p[1]), "close": float(p[2]),
                "high": float(p[3]), "low": float(p[4]),
                "vol": float(p[5]), "amount": float(p[6]),
                "amp": float(p[7]) if len(p) > 7 and p[7] else 0.0,
            })
    return rows
```

- [ ] **Step 6: 创建空 __init__.py 与 cache 占位**

```bash
cd /e/ideaworkspace/astock-anayisis/etf-strategies
touch backtest/__init__.py tests/__init__.py
mkdir -p cache && touch cache/.gitkeep
```

- [ ] **Step 7: 运行测试验证通过**

```bash
python -m pytest tests/test_em_client.py -v
```
Expected: 3 passed。

- [ ] **Step 8: Commit**

```bash
git init 2>/dev/null; git add -A && git commit -m "feat: scaffolding + em_get client with rate limiting

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: 数据层 get_kline + parquet 缓存

**Files:**
- Create: `etf-strategies/backtest/data.py`
- Create: `etf-strategies/tests/test_data.py`

**Interfaces:**
- Consumes: `eastmoney_kline(code, start, end) -> list[dict]` (Task 1)
- Produces: `get_kline(code, start='2012-05-28', end='2026-07-01', refresh=False) -> pd.DataFrame`（index=DateTime, cols: open/close/high/low/vol/amount, 前复权）；`load_prices(codes, start, end, refresh=False) -> pd.DataFrame`（index=日期, columns=codes, values=收盘价，按公共首末日对齐）

- [ ] **Step 1: 写失败测试 test_data.py**

```python
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
from pathlib import Path
from backtest.data import get_kline, load_prices

def test_get_kline_returns_dataframe():
    df = get_kline("510300", start="2026-01-01", end="2026-06-30", refresh=True)
    assert isinstance(df, pd.DataFrame)
    assert {"open","close","high","low","vol"} <= set(df.columns)
    assert df.index.name == "date"
    assert len(df) > 0
    # 前复权：收盘价为正数
    assert (df["close"] > 0).all()

def test_get_kline_caches(tmp_path, monkeypatch):
    """二次调用走缓存（不重新请求）"""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr("backtest.data.CACHE_DIR", cache_dir)
    df1 = get_kline("510300", start="2026-01-01", end="2026-06-30", refresh=True)
    cache_file = cache_dir / "510300.parquet"
    assert cache_file.exists()
    # 不刷新时应读缓存
    df2 = get_kline("510300", start="2026-01-01", end="2026-06-30", refresh=False)
    assert len(df1) == len(df2)

def test_load_prices_aligns_common_dates():
    """多标的按公共交易日对齐"""
    df = load_prices(["510300","511260"], start="2013-01-01", end="2013-06-30", refresh=True)
    assert list(df.columns) == ["510300","511260"]
    assert df.isna().sum().sum() == 0  # 对齐后无 NaN
    assert len(df) > 0
```

- [ ] **Step 2: 运行测试验证失败**

```bash
python -m pytest tests/test_data.py -v
```
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 3: 实现 data.py**

```python
"""数据层：东财前复权日K + parquet 本地缓存。"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
from pathlib import Path
from backtest.em_client import eastmoney_kline

CACHE_DIR = Path(__file__).resolve().parent.parent / "cache"

def get_kline(code, start="2012-05-28", end="2026-07-01", refresh=False):
    """取前复权日K。命中缓存则读 parquet，否则走东财并写缓存。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{code}.parquet"
    if cache_file.exists() and not refresh:
        df = pd.read_parquet(cache_file)
        return df.loc[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
    rows = eastmoney_kline(code, start=start.replace("-", ""), end=end.replace("-", ""))
    if not rows:
        raise RuntimeError(f"东财返回空数据 code={code}（可能被风控，请换网络或稍后重试）")
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    for c in ["open","close","high","low","vol","amount","amp"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.loc[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
    df.to_parquet(cache_file)
    return df

def load_prices(codes, start, end, refresh=False):
    """取多标的收盘价，按公共首末日对齐（dropna 任何含 NaN 的行）。"""
    series = {}
    for c in codes:
        df = get_kline(c, start=start, end=end, refresh=refresh)
        series[c] = df["close"]
    prices = pd.DataFrame(series).dropna()
    return prices
```

- [ ] **Step 4: 运行测试验证通过**

```bash
python -m pytest tests/test_data.py -v
```
Expected: 3 passed。

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: data layer with parquet caching + common-date alignment

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: 成本模型

**Files:**
- Create: `etf-strategies/backtest/cost.py`
- Create: `etf-strategies/tests/test_cost.py`

**Interfaces:**
- Produces: `Cost(commission_rate=2.5e-4, min_commission=5.0, stamp_duty=0.0, slippage=1e-4)`；`Cost.one_way() -> float`（单边总成本率）

- [ ] **Step 1: 写失败测试 test_cost.py**

```python
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from backtest.cost import Cost

def test_default_cost():
    c = Cost()
    assert c.commission_rate == 2.5e-4
    assert c.min_commission == 5.0
    assert c.stamp_duty == 0.0  # ETF 免印花税
    assert c.slippage == 1e-4

def test_one_way_total():
    """单边总成本 = 佣金 + 印花税 + 滑点"""
    c = Cost()
    # 万2.5 + 0 + 万1 = 万3.5 = 3.5e-4
    assert abs(c.one_way() - 3.5e-4) < 1e-10

def test_custom_cost():
    c = Cost(commission_rate=3e-4, slippage=2e-4)
    assert abs(c.one_way() - 5e-4) < 1e-10
```

- [ ] **Step 2: 运行测试验证失败**

```bash
python -m pytest tests/test_cost.py -v
```
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 3: 实现 cost.py**

```python
"""交易成本模型。A股ETF：佣金万2.5最低5元、免印花税、滑点万1。"""
from dataclasses import dataclass

@dataclass
class Cost:
    commission_rate: float = 2.5e-4   # 佣金费率（双边，按成交额）
    min_commission: float = 5.0       # 单笔最低佣金（元）
    stamp_duty: float = 0.0           # 印花税（ETF免）
    slippage: float = 1e-4            # 滑点（单边）

    def one_way(self):
        """单边总成本率（不含最低佣金，按大额近似）。"""
        return self.commission_rate + self.stamp_duty + self.slippage
```

- [ ] **Step 4: 运行测试验证通过**

```bash
python -m pytest tests/test_cost.py -v
```
Expected: 3 passed。

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: cost model (commission + stamp duty + slippage)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: 回测引擎

**Files:**
- Create: `etf-strategies/backtest/engine.py`
- Create: `etf-strategies/tests/conftest.py`
- Create: `etf-strategies/tests/test_engine.py`

**Interfaces:**
- Consumes: `Cost` (Task 3)
- Produces: `BacktestResult`（dataclass: `nav`, `returns`, `weights`, `turnover`）；`backtest(prices, target_weights, cost=None, initial_capital=1e6) -> BacktestResult`

- [ ] **Step 1: 写 conftest.py 合成价格 fixture**

```python
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
import pytest

@pytest.fixture
def synth_prices():
    """合成价格：510300 每日涨1%，511260 每日涨0.1%，共10个交易日。"""
    dates = pd.date_range("2024-01-01", periods=10, freq="B")
    return pd.DataFrame({
        "510300": [100 * (1.01 ** i) for i in range(10)],
        "511260": [100 * (1.001 ** i) for i in range(10)],
    }, index=dates)

@pytest.fixture
def flat_prices():
    """平价序列（无收益无成本影响）：便于测再平衡算术。"""
    dates = pd.date_range("2024-01-01", periods=10, freq="B")
    return pd.DataFrame({
        "510300": [100.0] * 10,
        "511260": [100.0] * 10,
    }, index=dates)
```

- [ ] **Step 2: 写失败测试 test_engine.py**

```python
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from backtest.engine import backtest, BacktestResult
from backtest.cost import Cost

def test_buy_hold_matches_price_relative_return(synth_prices):
    """买入持有：净值 = 价格相对收益"""
    prices = synth_prices[["510300"]]
    weights = pd.DataFrame({"510300": 1.0}, index=prices.index)
    result = backtest(prices, weights, cost=Cost(slippage=0, commission_rate=0))
    # 10日涨1%^10 = 1.01^10 - 1
    expected = 1.01 ** 10
    assert abs(result.nav.iloc[-1] - expected) < 1e-6

def test_signal_lag_prevents_lookahead(synth_prices):
    """信号滞后生效：即使当日给权重，也是次日才执行"""
    prices = synth_prices[["510300"]]
    # 第3日才买入，之前为0
    weights = pd.DataFrame({"510300": 0.0}, index=prices.index)
    weights.iloc[3:] = 1.0
    result = backtest(prices, weights, cost=Cost(slippage=0, commission_rate=0))
    # 净值应 < 全程持有（因为错过了前3日）
    full = backtest(prices, pd.DataFrame({"510300":1.0}, index=prices.index),
                    cost=Cost(slippage=0, commission_rate=0))
    assert result.nav.iloc[-1] < full.nav.iloc[-1]

def test_rebalance_arithmetic(flat_prices):
    """再平衡算术：价格不变时，60/40再平衡不产生收益也不产生大成本"""
    weights = pd.DataFrame({"510300": 0.6, "511260": 0.4}, index=flat_prices.index)
    result = backtest(flat_prices, weights, cost=Cost())
    # 价格不变 → 净值应≈1（仅扣极小成本，但因权重不变成本为0）
    assert abs(result.nav.iloc[-1] - 1.0) < 1e-6

def test_cost_deducted(synth_prices):
    """有成本时净值低于无成本"""
    prices = synth_prices[["510300"]]
    weights = pd.DataFrame({"510300": 1.0}, index=prices.index)
    no_cost = backtest(prices, weights, cost=Cost(slippage=0, commission_rate=0))
    with_cost = backtest(prices, weights, cost=Cost(slippage=1e-4, commission_rate=2.5e-4))
    # 首次建仓扣成本，有成本净值更低
    assert with_cost.nav.iloc[-1] < no_cost.nav.iloc[-1]

def test_returns_result_object(synth_prices):
    prices = synth_prices[["510300"]]
    weights = pd.DataFrame({"510300": 1.0}, index=prices.index)
    result = backtest(prices, weights, cost=Cost(slippage=0, commission_rate=0))
    assert isinstance(result, BacktestResult)
    assert len(result.nav) == len(prices)
    assert result.nav.iloc[0] == 1.0
```

- [ ] **Step 3: 运行测试验证失败**

```bash
python -m pytest tests/test_engine.py -v
```
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 4: 实现 engine.py**

```python
"""向量化回测引擎。策略产目标权重，引擎统一处理信号滞后/成本/净值。"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from dataclasses import dataclass
from backtest.cost import Cost

@dataclass
class BacktestResult:
    nav: pd.Series          # 净值序列（初始=1）
    returns: pd.Series      # 日收益序列
    weights: pd.DataFrame   # 实际持仓权重（已滞后）
    turnover: float         # 年化换手率

def backtest(prices, target_weights, cost=None, initial_capital=1e6):
    """
    prices: 日期×资产 收盘价（前复权）
    target_weights: 日期×资产 目标权重（0~1，每行和≈1）
    信号滞后1日：t日收盘算信号，t+1日收盘执行。
    """
    if cost is None:
        cost = Cost()
    # 对齐
    common = prices.index.intersection(target_weights.index)
    prices = prices.loc[common]
    target_weights = target_weights.loc[common]
    # 信号滞后1日
    held_weights = target_weights.shift(1).fillna(0.0)
    # 日收益
    daily_ret = prices.pct_change().fillna(0.0)
    # 权重变动产生的成本（单边成本率 × 权重变动绝对值）
    weight_change = held_weights.diff().abs().fillna(held_weights.abs())
    cost_rate = cost.one_way()
    daily_cost = (weight_change * cost_rate).sum(axis=1)
    # 组合日收益
    portfolio_ret = (held_weights * daily_ret).sum(axis=1) - daily_cost
    nav = (1 + portfolio_ret).cumprod()
    nav.iloc[0] = 1.0  # 首日为1（首日成本已在 daily_cost 扣除）
    # 年化换手率
    total_turnover = weight_change.sum().sum()
    years = len(prices) / 252
    ann_turnover = total_turnover / years if years > 0 else 0.0
    return BacktestResult(nav=nav, returns=portfolio_ret, weights=held_weights,
                          turnover=ann_turnover)
```

- [ ] **Step 5: 运行测试验证通过**

```bash
python -m pytest tests/test_engine.py -v
```
Expected: 5 passed。

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: vectorized backtest engine with signal lag + cost

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: 指标计算

**Files:**
- Create: `etf-strategies/backtest/metrics.py`
- Create: `etf-strategies/tests/test_metrics.py`

**Interfaces:**
- Consumes: `BacktestResult` (Task 4)
- Produces: `compute_metrics(result, benchmark=None) -> dict`（含 annual_return/annual_vol/sharpe/max_drawdown/calmar/win_rate/turnover）

- [ ] **Step 1: 写失败测试 test_metrics.py**

```python
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from backtest.engine import BacktestResult
from backtest.metrics import compute_metrics

def _make_result(returns):
    nav = (1 + pd.Series(returns)).cumprod()
    nav.iloc[0] = 1.0
    weights = pd.DataFrame({"A": 1.0}, index=nav.index)
    return BacktestResult(nav=nav, returns=pd.Series(returns), weights=weights, turnover=1.0)

def test_metrics_basic():
    # 每日固定涨1%
    rets = [0.0] + [0.01] * 251  # 252个交易日
    r = _make_result(rets)
    m = compute_metrics(r)
    assert abs(m["annual_return"] - (1.01**252 - 1)) < 1e-4
    assert m["annual_vol"] > 0
    assert m["sharpe"] > 0
    assert m["max_drawdown"] <= 0
    assert 0 <= m["win_rate"] <= 1

def test_max_drawdown():
    # 净值 1 -> 1.2 -> 0.9 -> 1.0
    rets = [0.0, 0.2, -0.25, 0.111]
    r = _make_result(rets)
    m = compute_metrics(r)
    # 峰值1.2，谷底0.9，回撤25%
    assert abs(m["max_drawdown"] - (-0.25)) < 1e-6

def test_win_rate():
    # 4个收益日，3正1负 → 胜率0.75
    rets = [0.0, 0.01, 0.02, -0.01, 0.03]
    r = _make_result(rets)
    m = compute_metrics(r)
    assert abs(m["win_rate"] - 0.75) < 1e-6
```

- [ ] **Step 2: 运行测试验证失败**

```bash
python -m pytest tests/test_metrics.py -v
```
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 3: 实现 metrics.py**

```python
"""回测指标计算。"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import numpy as np
import pandas as pd

def compute_metrics(result, benchmark=None, freq=252):
    """计算收益/风险指标。benchmark 可选 BacktestResult 用于超额。"""
    nav = result.nav
    rets = result.returns
    n = len(rets)
    years = n / freq
    # 年化收益
    ann_ret = nav.iloc[-1] ** (1 / years) - 1 if years > 0 else 0.0
    # 年化波动
    ann_vol = rets.std() * np.sqrt(freq) if n > 1 else 0.0
    # 夏普（无风险利率=0）
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
    # 最大回撤
    cummax = nav.cummax()
    drawdown = nav / cummax - 1
    max_dd = drawdown.min()
    # Calmar
    calmar = ann_ret / abs(max_dd) if max_dd < 0 else 0.0
    # 胜率（月度收益>0占比，用日收益近似）
    win_rate = (rets > 0).sum() / max((rets != 0).sum(), 1)
    m = {
        "annual_return": ann_ret,
        "annual_vol": ann_vol,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "calmar": calmar,
        "win_rate": win_rate,
        "turnover": result.turnover,
    }
    if benchmark is not None:
        b_ann = benchmark.nav.iloc[-1] ** (1 / years) - 1 if years > 0 else 0.0
        m["excess_return"] = ann_ret - b_ann
    return m
```

- [ ] **Step 4: 运行测试验证通过**

```bash
python -m pytest tests/test_metrics.py -v
```
Expected: 3 passed。

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: metrics (annual return/vol/sharpe/drawdown/calmar/win rate)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: 策略基类 + 4 策略

**Files:**
- Create: `etf-strategies/backtest/strategies/__init__.py`（空）
- Create: `etf-strategies/backtest/strategies/base.py`
- Create: `etf-strategies/backtest/strategies/buy_hold.py`
- Create: `etf-strategies/backtest/strategies/dual_momentum.py`
- Create: `etf-strategies/backtest/strategies/ma_trend.py`
- Create: `etf-strategies/backtest/strategies/portfolio_6040.py`
- Create: `etf-strategies/tests/test_strategies.py`

**Interfaces:**
- Produces: `Strategy` 基类（`name: str`, `assets: list[str]`, `generate(prices) -> pd.DataFrame`）；`BuyHold`, `DualMomentum`, `MATrend`, `Portfolio6040`

- [ ] **Step 1: 写失败测试 test_strategies.py**

```python
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
from backtest.strategies.buy_hold import BuyHold
from backtest.strategies.dual_momentum import DualMomentum
from backtest.strategies.ma_trend import MATrend
from backtest.strategies.portfolio_6040 import Portfolio6040

def _prices(up_a=True):
    """510300上涨/下跌 + 511260平 + 511880平，300日"""
    dates = pd.date_range("2024-01-01", periods=300, freq="B")
    slope = 1.002 if up_a else 0.998
    return pd.DataFrame({
        "510300": [100 * (slope ** i) for i in range(300)],
        "511260": [100.0] * 300,
        "511880": [100.0] * 300,
    }, index=dates)

def test_buy_hold_weights():
    p = _prices()[["510300"]]
    s = BuyHold()
    w = s.generate(p)
    assert (w == 1.0).all().all()
    assert w.columns.tolist() == ["510300"]

def test_dual_momentum_hold_stock_when_up():
    p = _prices(up_a=True)
    s = DualMomentum(lookback=250)
    w = s.generate(p)
    # 上涨时末期应满仓510300
    assert w["510300"].iloc[-1] == 1.0
    assert w["511880"].iloc[-1] == 0.0

def test_dual_momentum_switch_to_cash_when_down():
    p = _prices(up_a=False)
    s = DualMomentum(lookback=250)
    w = s.generate(p)
    # 下跌时（绝对动量为负）应切货币511880
    assert w["511880"].iloc[-1] == 1.0
    assert w["510300"].iloc[-1] == 0.0

def test_ma_trend_hold_when_ma_above():
    p = _prices(up_a=True)
    s = MATrend(short=20, long=60)
    w = s.generate(p[["510300","511880"]])
    # 上升趋势末期 ma20>ma60 → 持股
    assert w["510300"].iloc[-1] == 1.0

def test_ma_trend_switch_when_ma_below():
    p = _prices(up_a=False)
    s = MATrend(short=20, long=60)
    w = s.generate(p[["510300","511880"]])
    # 下降趋势末期 ma20<ma60 → 切货币
    assert w["511880"].iloc[-1] == 1.0

def test_portfolio_6040_weights():
    p = _prices()[["510300","511260"]]
    s = Portfolio6040()
    w = s.generate(p)
    assert abs(w["510300"].iloc[-1] - 0.6) < 1e-6
    assert abs(w["511260"].iloc[-1] - 0.4) < 1e-6

def test_all_strategies_weights_sum_to_one():
    """每个策略任意一行权重和≈1（信号有效后）"""
    p = _prices(up_a=True)
    for S, assets in [(DualMomentum(250), ["510300","511260","511880"]),
                      (MATrend(20,60), ["510300","511880"]),
                      (Portfolio6040(), ["510300","511260"])]:
        w = S.generate(p[assets])
        # 去掉前面 warmup 期（信号未生成可能为0）
        valid = w.iloc[60:]
        rowsums = valid.sum(axis=1)
        assert ((rowsums - 1.0).abs() < 1e-6).all(), f"{S.name} 权重不和为1"
```

- [ ] **Step 2: 运行测试验证失败**

```bash
python -m pytest tests/test_strategies.py -v
```
Expected: FAIL `ModuleNotFoundError`

- [ ] **Step 3: 实现 base.py**

```python
"""策略基类。策略只产目标权重，不管交易/成本。"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd

class Strategy:
    name: str = "base"
    assets: list = []
    def generate(self, prices: pd.DataFrame) -> pd.DataFrame:
        """prices: 日期×资产 收盘价. 返回: 日期×资产 目标权重(0~1, 每行和≈1)"""
        raise NotImplementedError
```

- [ ] **Step 4: 实现 buy_hold.py**

```python
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
from .base import Strategy

class BuyHold(Strategy):
    name = "S1_买入持有"
    def __init__(self, code="510300"):
        self.code = code
        self.assets = [code]
    def generate(self, prices):
        w = pd.DataFrame(1.0, index=prices.index, columns=self.assets)
        return w
```

- [ ] **Step 5: 实现 dual_momentum.py**

```python
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
from .base import Strategy

class DualMomentum(Strategy):
    """双动量：绝对动量+相对动量。股票动量为负切货币；为正且>债券则持股，否则持债。"""
    name = "S2_双动量"
    def __init__(self, lookback=250, stock="510300", bond="511260", cash="511880"):
        self.lookback = lookback
        self.stock, self.bond, self.cash = stock, bond, cash
        self.assets = [stock, bond, cash]
    def generate(self, prices):
        stock_mom = prices[self.stock].pct_change(self.lookback)
        bond_mom = prices[self.bond].pct_change(self.lookback)
        weights = pd.DataFrame(0.0, index=prices.index, columns=self.assets)
        for i in prices.index:
            sm, bm = stock_mom.loc[i], bond_mom.loc[i]
            if pd.isna(sm) or pd.isna(bm):
                continue
            if sm <= 0:
                weights.loc[i, self.cash] = 1.0       # 绝对动量为负 → 避险
            elif sm > bm:
                weights.loc[i, self.stock] = 1.0     # 相对动量 → 持股
            else:
                weights.loc[i, self.bond] = 1.0      # → 持债
        # 月末调仓：只保留每月最后一个交易日的信号，向前填充
        monthly = weights.resample("ME").last()
        weights = monthly.reindex(prices.index, method="ffill").fillna(0.0)
        return weights
```

- [ ] **Step 6: 实现 ma_trend.py**

```python
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
from .base import Strategy

class MATrend(Strategy):
    """均线趋势：ma20>ma60 持股，否则切货币。月末调仓。"""
    name = "S3_均线趋势"
    def __init__(self, short=20, long=60, stock="510300", cash="511880"):
        self.short, self.long = short, long
        self.stock, self.cash = stock, cash
        self.assets = [stock, cash]
    def generate(self, prices):
        ma_s = prices[self.stock].rolling(self.short).mean()
        ma_l = prices[self.stock].rolling(self.long).mean()
        signal = (ma_s > ma_l).astype(float)  # 1持股 0货币
        weights = pd.DataFrame(0.0, index=prices.index, columns=self.assets)
        weights[self.stock] = signal
        weights[self.cash] = 1 - signal
        # 月末调仓
        monthly = weights.resample("ME").last()
        weights = monthly.reindex(prices.index, method="ffill").fillna(0.0)
        return weights
```

- [ ] **Step 7: 实现 portfolio_6040.py**

```python
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
from .base import Strategy

class Portfolio6040(Strategy):
    """60/40 股债平衡，季末再平衡。"""
    name = "S6_60-40股债平衡"
    def __init__(self, stock="510300", bond="511260", w_stock=0.6, w_bond=0.4):
        self.stock, self.bond = stock, bond
        self.w_stock, self.w_bond = w_stock, w_bond
        self.assets = [stock, bond]
    def generate(self, prices):
        weights = pd.DataFrame(0.0, index=prices.index, columns=self.assets)
        weights[self.stock] = self.w_stock
        weights[self.bond] = self.w_bond
        # 季末再平衡：每季最后一日设定目标，季内保持
        quarterly = weights.resample("QE").last()
        weights = quarterly.reindex(prices.index, method="ffill").fillna(0.0)
        return weights
```

- [ ] **Step 8: 创建 strategies/__init__.py 并运行测试**

```bash
cd /e/ideaworkspace/astock-anayisis/etf-strategies
touch backtest/strategies/__init__.py
python -m pytest tests/test_strategies.py -v
```
Expected: 7 passed。

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "feat: strategy base + 4 strategies (buy-hold/dual-momentum/ma-trend/60-40)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: 报告输出（reporting.py）

**Files:**
- Create: `etf-strategies/backtest/reporting.py`

**Interfaces:**
- Consumes: `BacktestResult` (Task 4), `compute_metrics` (Task 5)
- Produces: `plot_equity_curves(results: dict[str,BacktestResult], path)`；`plot_drawdowns(results, path)`；`render_markdown_report(results: dict, metrics: dict, path)`

- [ ] **Step 1: 实现 reporting.py（无测试，纯输出层）**

```python
"""报告输出：matplotlib 可视化 + markdown 表格。"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from backtest.metrics import compute_metrics

def plot_equity_curves(results, path):
    """权益曲线对比。results: {name: BacktestResult}"""
    plt.figure(figsize=(12, 6))
    for name, r in results.items():
        plt.plot(r.nav.index, r.nav.values, label=name, linewidth=1.5)
    plt.title("ETF Strategy Equity Curves (NAV=1 start)")
    plt.xlabel("Date"); plt.ylabel("NAV"); plt.legend(); plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=120); plt.close()

def plot_drawdowns(results, path):
    """回撤曲线。"""
    plt.figure(figsize=(12, 4))
    for name, r in results.items():
        dd = r.nav / r.nav.cummax() - 1
        plt.fill_between(dd.index, dd.values, 0, label=name, alpha=0.4)
    plt.title("Drawdown")
    plt.xlabel("Date"); plt.ylabel("Drawdown"); plt.legend(); plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=120); plt.close()

def render_markdown_report(results, metrics, path, data_start, data_end):
    """生成 markdown 回测报告。"""
    lines = []
    lines.append("# A股 ETF 策略回测报告\n")
    lines.append(f"> 数据时点：{data_end}（盘后）")
    lines.append(f"> 回测窗口：{data_start} ~ {data_end}")
    lines.append(f"> 数据来源：东财 push2his 前复权日K（`fqt=1`），经 `em_get` 限流防封")
    lines.append(f"> 初始资金：1,000,000 | 成本：佣金万2.5+滑点万1（单边0.035%），ETF免印花税\n")
    lines.append("## 指标对比表（实测）\n")
    lines.append("| 策略 | 年化收益 | 年化波动 | 夏普 | 最大回撤 | Calmar | 胜率 | 年化换手 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for name, m in metrics.items():
        lines.append(f"| {name} | {m['annual_return']:.2%} | {m['annual_vol']:.2%} | "
                     f"{m['sharpe']:.2f} | {m['max_drawdown']:.2%} | {m['calmar']:.2f} | "
                     f"{m['win_rate']:.2%} | {m['turnover']:.1f} |")
    lines.append("\n## 净值曲线\n![equity](equity_curves.png)\n")
    lines.append("## 回撤曲线\n![drawdown](drawdowns.png)\n")
    lines.append("## 风险提示\n")
    lines.append("- 回测好≠实盘好：存在过拟合风险、参数依赖（动量回看250日/均线20-60/月度调仓）。")
    lines.append("- 成本为简化模型，未计入冲击成本（流动性差品种实际更高）。")
    lines.append("- 信号滞后1日已处理前视偏差；前复权已处理分红除权。")
    lines.append("- 本报告区分'实测值'（上表）与'判断'（结论性文字），实测值均来自真实行情。")
    Path = __import__("pathlib").Path
    Path(path).write_text("\n".join(lines), encoding="utf-8")
```

- [ ] **Step 2: Commit**

```bash
git add -A && git commit -m "feat: reporting (matplotlib equity/drawdown + markdown)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: 入口 + 跑回测 + 生成报告

**Files:**
- Create: `etf-strategies/run_backtest.py`

- [ ] **Step 1: 实现 run_backtest.py**

```python
"""回测入口：拉数据 → 跑4策略 → 生成报告。"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from pathlib import Path
from backtest.data import load_prices
from backtest.engine import backtest
from backtest.metrics import compute_metrics
from backtest.strategies.buy_hold import BuyHold
from backtest.strategies.dual_momentum import DualMomentum
from backtest.strategies.ma_trend import MATrend
from backtest.strategies.portfolio_6040 import Portfolio6040
from backtest.reporting import plot_equity_curves, plot_drawdowns, render_markdown_report

START, END = "2012-05-28", "2026-07-01"
OUT_DIR = Path(__file__).resolve().parent

def main():
    print("[1/4] 加载数据...")
    # S1 仅需 510300；S2/S3/S6 需多标的。统一加载全部标的的公共窗口。
    codes = ["510300", "511260", "511880"]
    prices_all = load_prices(codes, start=START, end=END, refresh=False)
    data_start = str(prices_all.index[0].date())
    data_end = str(prices_all.index[-1].date())
    print(f"  公共窗口: {data_start} ~ {data_end}, {len(prices_all)} 交易日")

    print("[2/4] 生成策略信号...")
    strategies = {
        "S1_买入持有": BuyHold("510300"),
        "S2_双动量": DualMomentum(lookback=250),
        "S3_均线趋势": MATrend(short=20, long=60),
        "S6_60-40": Portfolio6040(),
    }

    print("[3/4] 回测...")
    results, metrics = {}, {}
    for name, strat in strategies.items():
        p = prices_all[strat.assets]
        w = strat.generate(p)
        res = backtest(p, w)
        results[name] = res
        bench = results.get("S1_买入持有")
        metrics[name] = compute_metrics(res, benchmark=bench)
        m = metrics[name]
        print(f"  {name}: 年化{m['annual_return']:.2%} 夏普{m['sharpe']:.2f} 回撤{m['max_drawdown']:.2%}")

    print("[4/4] 生成报告...")
    plot_equity_curves(results, OUT_DIR / "equity_curves.png")
    plot_drawdowns(results, OUT_DIR / "drawdowns.png")
    render_markdown_report(results, metrics, OUT_DIR / "03_ETF策略回测报告.md", data_start, data_end)
    print("[done] 报告: 03_ETF策略回测报告.md")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑全部测试**

```bash
python -m pytest tests/ -v
```
Expected: 全部 passed。

- [ ] **Step 3: 跑回测**

```bash
python run_backtest.py
```
Expected: 打印各策略年化/夏普/回撤，生成 `03_ETF策略回测报告.md` + 两张图。

- [ ] **Step 4: 校验报告内容**

```bash
cat 03_ETF策略回测报告.md | head -20
```
验证：含数据时点、来源端点、指标表、图引用、风险提示。

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat: run_backtest entry + generate backtest report

Co-Authored-By: Claude <noreply@anthropic.com>"
```

- [ ] **Step 6: 清理临时脚本（如有）**

```bash
ls _*.py 2>/dev/null && rm -f _*.py && echo "临时脚本已清理" || echo "无临时脚本"
```

---

## Self-Review 记录

- **Spec 覆盖**：§1.2 四策略→Task 6 ✓；§3 数据层→Task 1+2 ✓；§4 引擎→Task 4 ✓；§5 策略规格→Task 6 ✓；§6 指标→Task 5 ✓；§7 报告→Task 7+8 ✓；§8 测试→各 Task 内 ✓；§9 纪律→Global Constraints + Task 4 信号滞后 ✓；§10 分阶段→Task 1-3(P1) 4-5(P2) 6(P3) 7-8(P4) ✓；§11 非目标→未实现 ✓
- **占位符**：无 TBD/TODO，所有代码块完整。
- **类型一致性**：`backtest()` 签名、`BacktestResult` 字段、`Strategy.generate()` 返回类型、`compute_metrics()` 参数在各 Task 间一致 ✓
- **Windows 编码**：所有 .py 头部已加 `sys.stdout.reconfigure`，测试用 `[OK]/[FAIL]` ✓
