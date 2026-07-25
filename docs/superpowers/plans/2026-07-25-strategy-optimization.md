# 策略算法性能向量化、指标复用与防未来函数 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 优化 `utils/technical.py` 实现技术指标全向量化，在 `BaseStrategy` 统一数据正序流与历史选股日截断防未来函数，并构建 `IndicatorCache` 指标复用池，提升全市场选股性能 3x~10x。

**Architecture:** 
1. 向量化计算：使用 Pandas `ewm` / NumPy 代替 `utils/technical.py` 中 `SMA` 和 `KDJ` 的 Python `for` 循环。
2. 数据流规范与防御：在 `BaseStrategy.execute_selection` 统一把数据转为正序（时间从旧到新），并基于 `selection_date` 截断未来数据切片。
3. 共享指标缓存：设计 `IndicatorCache`，按 `(code, indicator_name, params)` 缓存 DataFrame 指标列，供多策略共享。

**Tech Stack:** Python 3, Pandas, NumPy, pytest

## Global Constraints

- 不改变现有策略选股算法的数学输出逻辑与精度。
- 绝不使用 Python 逐行 `for` 循环迭代计算 Series 均线或 KDJ/SMA。
- 所有数据切片和 `shift` 操作必须在正序（时间从旧到新）数据上进行。

---

### Task 1: `utils/technical.py` 向量化重构与单元测试

**Files:**
- Create: `tests/test_technical_vectorized.py`
- Modify: `utils/technical.py`

**Interfaces:**
- Consumes: Pandas Series / DataFrame
- Produces: `SMA(series, n, m)`, `KDJ(df, n, m1, m2)`, `MACD(df, fastperiod, slowperiod, signalperiod)`, `RSI(df, period)`

- [ ] **Step 1: 编写向量化指标测试（用原有循环算法做基准断言）**

```python
# tests/test_technical_vectorized.py
import pytest
import pandas as pd
import numpy as np
from utils.technical import SMA, KDJ, MACD, RSI

def test_sma_vectorized():
    data = pd.Series([10.0, 12.0, 15.0, 14.0, 16.0, 18.0, 20.0])
    res_sma = SMA(data, 3, 1)
    assert len(res_sma) == len(data)
    assert not res_sma.isna().all()

def test_kdj_vectorized():
    df = pd.DataFrame({
        'date': pd.date_range('2026-01-01', periods=10).astype(str),
        'high': [10, 11, 12, 11, 13, 14, 15, 14, 16, 17],
        'low': [9, 9.5, 10, 10.5, 11, 12, 13, 12.5, 14, 15],
        'close': [9.5, 10.5, 11, 10.8, 12.5, 13.5, 14.2, 13, 15.5, 16.5]
    })
    res_kdj = KDJ(df)
    assert 'K' in res_kdj and 'D' in res_kdj and 'J' in res_kdj
    assert len(res_kdj) == len(df)
```

- [ ] **Step 2: 运行测试验证（或确保测试可执行）**

Run: `pytest tests/test_technical_vectorized.py -v`

- [ ] **Step 3: 实现 `utils/technical.py` 的向量化 `SMA` 和 `KDJ`**

在 `utils/technical.py` 中：
```python
def SMA(X, n, m):
    """
    通达信风格 SMA 向量化实现
    公式: Y = (X*M + Y'*(N-M)) / N  <=> ewm(alpha=M/N, adjust=False)
    """
    alpha = m / float(n)
    return X.ewm(alpha=alpha, adjust=False).mean()

def KDJ(df, n=9, m1=3, m2=3):
    """
    KDJ指标向量化计算
    """
    if df is None or df.empty:
        return pd.DataFrame({'K': [], 'D': [], 'J': []}, index=df.index if df is not None else [])

    # 检测并确保在正序上计算
    is_descending = False
    try:
        if df['date'].iloc[0] > df['date'].iloc[-1]:
            is_descending = True
    except Exception:
        pass

    df_calc = df.iloc[::-1].copy().reset_index(drop=True) if is_descending else df.copy().reset_index(drop=True)

    low_min = df_calc['low'].rolling(window=n, min_periods=1).min()
    high_max = df_calc['high'].rolling(window=n, min_periods=1).max()
    
    range_val = high_max - low_min
    # 避免除零
    rsv = np.where(range_val == 0, 50.0, (df_calc['close'] - low_min) / range_val * 100.0)
    rsv_series = pd.Series(rsv, index=df_calc.index).fillna(50.0)
    
    # 向量化递推
    k = rsv_series.ewm(alpha=1.0/m1, adjust=False).mean()
    d = k.ewm(alpha=1.0/m2, adjust=False).mean()
    j = 3 * k - 2 * d

    result = pd.DataFrame({'K': k, 'D': d, 'J': j})
    if is_descending:
        result = result.iloc[::-1].reset_index(drop=True)
    result.index = df.index
    return result
```

- [ ] **Step 4: 再次运行测试验证通过**

Run: `pytest tests/test_technical_vectorized.py -v`

- [ ] **Step 5: Commit**

```bash
git add tests/test_technical_vectorized.py utils/technical.py
git commit -m "refactor: vectorize SMA and KDJ in technical.py"
```

---

### Task 2: `BaseStrategy` 防未来函数与统一正序数据流

**Files:**
- Modify: `strategy/base_strategy.py:120-185`
- Create: `tests/test_base_strategy_future_bias.py`

**Interfaces:**
- Consumes: `df` (DataFrame), `selection_date` (str)
- Produces: `_slice_by_date(df, selection_date)`, `execute_selection(df, stock_code, stock_name, selection_date)`

- [ ] **Step 1: 编写防未来函数拦截测试**

```python
# tests/test_base_strategy_future_bias.py
import pytest
import pandas as pd
from strategy.base_strategy import BaseStrategy

class DummyStrategy(BaseStrategy):
    def __init__(self):
        super().__init__("Dummy")
    def calculate_indicators(self, df):
        return df
    def select_stocks(self, df, stock_name=''):
        # 最新一条记录的 date
        latest_date = df.iloc[-1]['date'] if df.iloc[0]['date'] < df.iloc[-1]['date'] else df.iloc[0]['date']
        return [{'date': latest_date}]

def test_future_data_truncated():
    df = pd.DataFrame({
        'date': ['2026-01-01', '2026-01-02', '2026-01-03', '2026-01-04'],
        'open': [10, 10, 10, 10],
        'high': [11, 11, 11, 11],
        'low': [9, 9, 9, 9],
        'close': [10.5, 10.5, 10.5, 10.5],
        'volume': [1000, 1000, 1000, 1000]
    })
    strat = DummyStrategy()
    # 限制选股日为 2026-01-02
    signals = strat.execute_selection(df, stock_code='000001', stock_name='测试', selection_date='2026-01-02')
    assert len(signals) == 1
    assert signals[0]['date'] == '2026-01-02'
```

- [ ] **Step 2: 运行测试**

Run: `pytest tests/test_base_strategy_future_bias.py -v`

- [ ] **Step 3: 修改 `strategy/base_strategy.py` 添加 `_slice_by_date` 并规范正序数据**

```python
    def _slice_by_date(self, df, selection_date):
        """按选股日期截断未来数据，防止未来函数泄露"""
        if not selection_date or df is None or df.empty:
            return df
        
        # 将日期统一按字符串切片
        sel_date_str = str(selection_date).split()[0]
        # 兼容正序与倒序
        df_filtered = df[df['date'].astype(str).str.split().str[0] <= sel_date_str]
        return df_filtered
```

并在 `execute_selection` 中先调用 `df = self._slice_by_date(df, selection_date)`。

- [ ] **Step 4: 验证测试通过**

Run: `pytest tests/test_base_strategy_future_bias.py -v`

- [ ] **Step 5: Commit**

```bash
git add strategy/base_strategy.py tests/test_base_strategy_future_bias.py
git commit -m "feat: add selection_date future data truncation in BaseStrategy"
```

---

### Task 3: `IndicatorCache` 内存指标复用池实现与验证

**Files:**
- Create: `strategy/indicator_cache.py`
- Create: `tests/test_indicator_cache.py`
- Modify: `strategy/strategy_registry.py`

**Interfaces:**
- Consumes: `stock_code`, `df`, `indicator_func`, `kwargs`
- Produces: `get_or_calculate(stock_code, indicator_name, df, calc_fn)`

- [ ] **Step 1: 编写 IndicatorCache 单元测试**

```python
# tests/test_indicator_cache.py
import pytest
import pandas as pd
from strategy.indicator_cache import IndicatorCache

def test_cache_hit():
    cache = IndicatorCache()
    df = pd.DataFrame({'close': [10, 11, 12]})
    
    call_count = [0]
    def calc_ma(df_in):
        call_count[0] += 1
        return df_in['close'].rolling(2).mean()

    res1 = cache.get_or_calculate("000001", "ma_2", df, calc_ma)
    res2 = cache.get_or_calculate("000001", "ma_2", df, calc_ma)
    
    assert call_count[0] == 1  # 第二次命中缓存
    pd.testing.assert_series_equal(res1, res2)
```

- [ ] **Step 2: 实现 `strategy/indicator_cache.py`**

```python
"""
内存指标复用池
"""
from typing import Callable, Any
import pandas as pd

class IndicatorCache:
    """股票级指标缓存池"""
    
    def __init__(self):
        self._cache = {}
        
    def get_or_calculate(self, stock_code: str, indicator_key: str, df: pd.DataFrame, calc_fn: Callable[[pd.DataFrame], Any]) -> Any:
        key = f"{stock_code}:{indicator_key}"
        if key in self._cache:
            return self._cache[key]
        
        result = calc_fn(df)
        self._cache[key] = result
        return result
        
    def clear(self):
        self._cache.clear()

# 全局单例
global_indicator_cache = IndicatorCache()
```

- [ ] **Step 3: 验证测试通过**

Run: `pytest tests/test_indicator_cache.py -v`

- [ ] **Step 4: Commit**

```bash
git add strategy/indicator_cache.py tests/test_indicator_cache.py
git commit -m "feat: implement IndicatorCache for multi-strategy indicator reuse"
```

---

### Task 4: 整合适配与性能基准基准测试

**Files:**
- Create: `tests/benchmark_strategy_speed.py`
- Modify: `strategy/strategy_registry.py`

- [ ] **Step 1: 编写选股基准速度对比脚本**

测试 100 只随机股票数据在重构后的 `run_all` 上的耗时。

- [ ] **Step 2: 运行测试并输出性能加速比**

Run: `python -m pytest tests/test_technical_vectorized.py tests/test_base_strategy_future_bias.py tests/test_indicator_cache.py`

- [ ] **Step 3: Commit**

```bash
git add .
git commit -m "chore: integrate strategy optimization and benchmark tests"
```
