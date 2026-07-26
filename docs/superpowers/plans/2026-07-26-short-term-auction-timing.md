# 超短线竞价择时策略 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `ShortTermAuctionTimingStrategy` 择时策略并集成至 `TimingStrategyFactory`，提供硬止损 (-3.5%)、动态止盈 (+6.0%) 和最长持股限制 (2天)。

**Architecture:** 
1. 新建 `trading/short_term_auction_timing.py` 继承 `TimingStrategy`。
2. 更新 `trading/timing_strategies.py` 中的 `TimingStrategyFactory` 支持 `"short_term_auction"`。
3. 单元测试 `tests/test_short_term_auction_timing.py` 验证择时功能。

**Tech Stack:** Python 3, Pandas, NumPy, unittest

## Global Constraints

- 遵循 `TimingStrategy` 统一接口规范。
- 止盈、止损、最大持股天数参数完全支持配置化。

---

### Task 1: 实现 `ShortTermAuctionTimingStrategy` 并集成工厂与单元测试

**Files:**
- Create: `trading/short_term_auction_timing.py`
- Modify: `trading/timing_strategies.py`
- Create: `tests/test_short_term_auction_timing.py`

**Interfaces:**
- Consumes: `df` (DataFrame), `position` (dict), `cash` (float)
- Produces: `TimingResult` with `is_buy`, `is_sell`, `message`, `trade_type`

- [ ] **Step 1: 编写单元测试**

```python
# tests/test_short_term_auction_timing.py
import unittest
import pandas as pd
from trading.timing_strategies import TimingStrategyFactory
from trading.short_term_auction_timing import ShortTermAuctionTimingStrategy

class TestShortTermAuctionTiming(unittest.TestCase):
    def test_factory_creation(self):
        strategy = TimingStrategyFactory.create_strategy("short_term_auction", {})
        self.assertIsInstance(strategy, ShortTermAuctionTimingStrategy)

    def test_stop_loss_trigger(self):
        strategy = ShortTermAuctionTimingStrategy({'stop_loss_ratio': 0.035})
        df = pd.DataFrame({'close': [10.0, 9.5], 'date': ['2026-01-01', '2026-01-02']})
        position = {'stock_code': '600000', 'buy_price': 10.0, 'hold_days': 1}
        result = strategy.get_timing_result(df, position=position)
        self.assertTrue(result.is_sell)
        self.assertIn("止损", result.message)

if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 实现 `trading/short_term_auction_timing.py`**
- [ ] **Step 3: 修改 `trading/timing_strategies.py` 工厂方法**
- [ ] **Step 4: 运行单元测试通过**

Run: `python3 -m unittest tests/test_short_term_auction_timing.py`

- [ ] **Step 5: Commit**

```bash
git add trading/short_term_auction_timing.py trading/timing_strategies.py tests/test_short_term_auction_timing.py
git commit -m "feat: add ShortTermAuctionTimingStrategy for ultra-short T+1 auction trading"
```
