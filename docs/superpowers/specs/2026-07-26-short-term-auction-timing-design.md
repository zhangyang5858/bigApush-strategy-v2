# 超短线竞价择时策略 (ShortTermAuctionTimingStrategy) 设计文档

**日期**: 2026-07-26  
**分支**: `feature/code-optimization`  

---

## 1. 背景与目标

针对“首板接力竞价”等超短线打板与接力模式，传统中长线择时策略（持股 10~20 天）无法适应其快进快出（T+1 ~ T+2）的交易特征。
本项目旨在实现专用的超短线竞价择时策略 `ShortTermAuctionTimingStrategy`，完美接入现有的 `TimingStrategyFactory` 与 `BacktestEngine` 回测引擎。

---

## 2. 核心算法逻辑

### 2.1 买入与建仓 (Buy Signal)
* 配合选股策略发出的选股信号（或在回测中前一日满足竞价高开与爆量条件），买入建立基础仓位（默认 100% 仓位）。

### 2.2 卖出与风控出场 (Sell Signals)
1. **固定百分比硬止损 (Hard Stop Loss)**:
   - 当价格相对于持仓成本下跌达到 `stop_loss_ratio`（默认 `-3.5%`）或低开破位时，触发硬止损强平。
2. **冲高动态止盈 / 移动保盈 (Take Profit & Trailing Stop)**:
   - 目标止盈：持仓价格相比买入价上涨达到 `take_profit_ratio`（默认 `+6.0%`）以上触发分批/全量止盈。
   - 移动保盈：若日内最高冲高幅度超过 `+4.0%` 后大幅回落超 `2.0%`，触发锁定利润离场。
3. **最长持股天数强制出清 (Max Holding Limit)**:
   - 持股天数达到 `max_hold_days`（默认 `2` 个交易日）且次日未封涨停，强制平仓，绝不将超短线拖成中线套牢。

---

## 3. 工厂注册 (`trading/timing_strategies.py`)

在 `TimingStrategyFactory.create_strategy` 中增加 `"short_term_auction"` 识别分支，实例化 `ShortTermAuctionTimingStrategy`。

---

## 4. 验证与测试计划

1. **单元测试**: 创建 `tests/test_short_term_auction_timing.py`，模拟多天 K 线，测试买点判断、硬止损、止盈与持股天数超期清仓。
2. **工厂接入验证**: 验证 `TimingStrategyFactory.create_strategy('short_term_auction', config)` 正常创建策略对象。
