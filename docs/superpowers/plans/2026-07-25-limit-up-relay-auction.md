# 首板接力竞价策略 Top 5 精选优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `LimitUpRelayAuctionStrategy` 实现多因子质量打分排序，并添加 `max_top_n: 5` 截断，控制最大输出股票数为 5 只。

**Architecture:** 
1. `LimitUpRelayAuctionStrategy.select_stocks` 按照量化得分打分、降序排列并截取前 `max_top_n` 项。
2. 更新 `config/strategy_params.yaml` 添加 `max_top_n` 参数。
3. 单元测试 `tests/test_limit_up_relay_auction_strategy.py` 验证打分与 Top 5 截断功能。

**Tech Stack:** Python 3, Pandas, NumPy, unittest

## Global Constraints

- 不改变现有策略框架规范，确保 `max_top_n` 可在 UI 中自由调节。

---

### Task 1: 策略打分模型实现、Top 5 截断与单元测试

**Files:**
- Modify: `strategy/limit_up_relay_auction_strategy.py`
- Modify: `config/strategy_params.yaml`
- Modify: `tests/test_limit_up_relay_auction_strategy.py`

- [ ] **Step 1: 更新单元测试验证 Top 5 限制与打分排序**
- [ ] **Step 2: 在 `limit_up_relay_auction_strategy.py` 实现 `quality_score` 计算与 `max_top_n` 截断**
- [ ] **Step 3: 更新 `config/strategy_params.yaml`**
- [ ] **Step 4: 运行单元测试验证 100% 通过**
- [ ] **Step 5: Commit**

```bash
git add strategy/limit_up_relay_auction_strategy.py config/strategy_params.yaml tests/test_limit_up_relay_auction_strategy.py
git commit -m "feat: restrict LimitUpRelayAuctionStrategy output to top 5 stocks via quality score ranking"
```
