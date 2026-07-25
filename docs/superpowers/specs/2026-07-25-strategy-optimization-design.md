# 策略算法性能向量化、指标复用与防未来函数重构设计方案

**日期**: 2026-07-25  
**分支**: `feature/code-optimization`  

---

## 1. 背景与目标

当前量化系统在进行全市场 4000+ 只股票选股分析时，存在以下两大核心瓶颈与隐患：
1. **计算性能瓶颈**：
   * `utils/technical.py` 中的 `SMA` 和 `KDJ` 等通达信指标采用了 Python 的 `for` 循环逐行计算，运行耗时极高。
   * 各策略在分析单只股票时重复进行 DataFrame 升序/降序排序以及基础技术指标（MA, MACD, KDJ, RSI）的重复计算。
2. **防未来函数与数据边界风险**：
   * 部分策略混用正序与倒序数据，在调用 `shift(1)` 时容易误取未来日期的 K 线。
   * 缺乏对 `selection_date` 的强制数据截断，回测或指定历史日期选股时存在未来数据泄露风控漏洞。

**目标**：
* 选股算法性能提升 **3x~10x**。
* 彻底消除指标计算中的 Python 行循环。
* 策略运行过程实现 0 未来数据泄露、0 数据方向混用错位。

---

## 2. 详细设计方案

### 2.1 模块一：`utils/technical.py` 向量化重构

摒弃 Python 逐行循环，全面采用 Pandas `ewm` 和 NumPy 矩阵操作实现通达信指标算法：

#### 1) `SMA(X, n, m)` 向量化公式
通达信 `SMA(X, N, M)` 的递归公式为：\( Y_i = \frac{X_i \cdot M + Y_{i-1} \cdot (N - M)}{N} \)。  
这等价于 Smoothing Factor（衰减因子） \(\alpha = \frac{M}{N}\) 的指数加权移动平均（EWMA）。  
**向量化实现**：
```python
def SMA(series: pd.Series, n: int, m: int = 1) -> pd.Series:
    alpha = m / float(n)
    return series.ewm(alpha=alpha, adjust=False).mean()
```

#### 2) `KDJ(df, n=9, m1=3, m2=3)` 向量化公式
利用 `rolling` 提取 lowest_low 和 highest_high 后，采用向量化 `SMA` 递推计算 K 值与 D 值：
```python
low_min = df['low'].rolling(window=n, min_periods=1).min()
high_max = df['high'].rolling(window=n, min_periods=1).max()
range_val = (high_max - low_min).replace(0, np.nan)
rsv = ((df['close'] - low_min) / range_val * 100).fillna(50.0)

k = rsv.ewm(alpha=1/m1, adjust=False).mean()
d = k.ewm(alpha=1/m2, adjust=False).mean()
j = 3 * k - 2 * d
```

---

### 2.2 模块二：`BaseStrategy` 统一规范与防未来函数防护

在 `strategy/base_strategy.py` 的 `BaseStrategy` 基类中建立强制数据拦截与规范流：

1. **`_slice_by_date(df, selection_date)` 拦截未来数据**：
   在任何指标计算之前，若传入了 `selection_date`，强制执行 `df = df[df['date'] <= selection_date]`，彻底切除选股日之后的所有数据。

2. **统一内部数据流为正序（Ascending: 时间从旧到新）**：
   * 输入的 `df` 统一转为时间正序（旧 -> 新）。
   * 所有 `shift(1)` 明确代表“前一交易日”，避免倒序数据下 `shift(1)` 取到“未来交易日”的重大漏洞。
   * 选股逻辑判断时，最新交易日统一为正序 Dataframe 的最后一列（`iloc[-1]`）。

3. **异常处理机制强化**：
   * 增强数据完整性校验（K线最少周期数、全 0 成交量、空 DataFrame）。

---

### 2.3 模块三：全局 `IndicatorCache` 内存指标复用池

设计 `IndicatorCache` 管理器，在全市场多策略扫描时缓存计算结果：

* **缓存键设计**：`(stock_code, indicator_name, params_hash)` 或挂载在 `df.attrs['_indicator_cache']`。
* **常用共享指标**：
  * MA (5, 10, 20, 60, 120, 250)
  * MACD (12, 26, 9)
  * KDJ (9, 3, 3)
  * RSI (14)
* **复用流程**：当策略 A 计算了股票 `000001` 的 MACD 指标后，策略 B 直接从缓存获取，无需重新对该股票做 Pandas 向量化计算。

---

## 3. 受影响文件清单

| 文件路径 | 修改类型 | 职责描述 |
| :--- | :--- | :--- |
| `utils/technical.py` | 重构 | 实现 SMA/KDJ 向量化，优化 MA/MACD/RSI 性能 |
| `strategy/base_strategy.py` | 增强 | 实现日期截断防护、统一正序数据流、接入指标缓存 |
| `utils/cache_manager.py` / `strategy/indicator_cache.py` | 新增/增强 | 实现股票选股级别的内存指标复用池 |
| `strategy/parallel_strategy_executor.py` | 优化 | 接入指标缓存与高效数据准备逻辑 |
| `strategy/*.py`（核心策略） | 适配 | 兼容正序数据与向量化指标调用 |

---

## 4. 验证与测试计划

1. **计算正确性与等价性测试**：
   * 针对 `utils/technical.py` 中的 `SMA` 和 `KDJ` 新旧计算结果对比测试，确保输出精度完全一致（误差 < $10^{-6}$）。
2. **防未来函数防泄露测试**：
   * 使用包含未来日期的历史切片数据，验证 `_slice_by_date` 能否 100% 截断未来数据，对比加/不加未来数据时的选股结果是否一致。
3. **选股性能对比测试**：
   * 针对 4000+ 股票的全市场运行耗时进行 Benchmark 基准测试（优化前 vs 优化后）。
