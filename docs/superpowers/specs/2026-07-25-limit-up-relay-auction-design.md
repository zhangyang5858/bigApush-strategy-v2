# 首板接力竞价策略 (LimitUpRelayAuctionStrategy) 设计文档

**日期**: 2026-07-25  
**分支**: `feature/code-optimization`  

---

## 1. 背景与目标

在 A 股超短线交易中，“首板接力二板”是确定性极高的核心模式之一。通过在早盘 `09:25:30` 抓取集合竞价数据，对昨日“首板涨停”的股票进行竞价高开溢价与爆量抢筹筛选，能够精准捕捉具有大资金接力意愿的强转弱标的。

**目标**：
* 新增 `LimitUpRelayAuctionStrategy` 策略，继承自 `BaseStrategy`。
* 完美接入系统的 `StrategyRegistry`、配置文件 `config/strategy_params.yaml`、Web 服务界面与飞书推送。
* 实现完整的单元测试覆盖。

---

## 2. 核心算法逻辑

### 2.1 昨日首板特征筛选 (Yesterday First Board Filter)
1. **昨日收盘封板**：昨日涨幅 $\ge 9.8\%$（创业板/科创板可配置支持 $\ge 19.8\%$）。
2. **前日非涨停**：前日涨幅 $< 9.8\%$，保证该标的昨日属于“首板”，而非连板高位股。
3. **昨日换手率适中**：昨日换手率位于 `5% ~ 20%` 之间，排除缩量一字板（次日容易爆量砸盘）。

### 2.2 竞价抢筹特征筛选 (Auction Features)
1. **黄金高开区间**：
   $$\text{gap\_up} = \frac{\text{open} - \text{prev\_close}}{\text{prev\_close}}$$
   要求 $2.0\% \le \text{gap\_up} \le 6.0\%$。
2. **竞价成交额/爆量比**：
   - 竞价成交金额 $\ge 1500$ 万元。
   - 竞价成交量占昨日全天成交量比例：$\text{auction\_volume} / \text{prev\_volume} \ge 5.0\%$。
3. **趋势支撑**：昨日收盘价站在 5 日均线（MA5）之上，剔除 ST / 退市股票。

---

## 3. 配置文件修改 (`config/strategy_params.yaml`)

新增 `LimitUpRelayAuctionStrategy` 配置描述与参数组：
- `min_gap_up`: 0.02 (竞价高开下限)
- `max_gap_up`: 0.06 (竞价高开上限)
- `min_auction_amount`: 15000000 (竞价最低金额 1500万)
- `min_auction_volume_ratio`: 0.05 (竞价占比 5%)
- `yesterday_min_turnover`: 0.05 (昨日最低换手率 5%)
- `yesterday_max_turnover`: 0.20 (昨日最高换手率 20%)

---

## 4. 验证与测试计划

1. **策略算法逻辑单元测试**：编写 `tests/test_limit_up_relay_auction_strategy.py` 测试首板识别、竞价高开计算及各种边界。
2. **注册器自动加载验证**：验证 `StrategyRegistry` 成功识别并加载 `LimitUpRelayAuctionStrategy`。
