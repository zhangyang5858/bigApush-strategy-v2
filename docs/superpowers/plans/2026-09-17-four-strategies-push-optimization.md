# 短线决策台四策略 (S1~S4) 推送优化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在短线决策台全天推送体系中，深度落地 S1 竞价首板、S2 主线龙头主升、S3 涨停后回调低吸、S4 量价突破回踩四套独立战法，实现“独立规则判定 + Line 67 评分排序 + 全天时钟闭环 + 飞书分栏卡片 + 模拟账户策略分仓”。

**Architecture:** 构建独立的四策略判定与观察池模块 `strategy_four_pillars.py`，输出 WATCHING / CONFIRMED / INVALIDATED 规范两级信号；在 `scalp_decision_engine.py` 中将 Line 67 打分模型严格作为排序字段，改造推送筛选与飞书分栏卡片；扩展 `scalp_push.py` 支持 14:30 尾盘决胜阶段，并在 `scalp_account_manager.py` 和 `scalp_trade_db.py` 中实现策略分仓与胜率归因。

**Tech Stack:** Python 3.10+, Requests, PyYAML, SQLite3 (WAL mode), OpenPyXL, GitHub Actions.

## Global Constraints

- S1、S2、S3、S4 各自保留独立信号条件，绝不可用综合评分替代策略定义；
- S1 今日最终是否首板只作收盘结果标签，不作为盘中入选前置；
- S2 盘前/早盘先固定主线板块与龙头候选，盘中 09:40/10:00 检查承接，避免收盘倒推龙头；
- S3 记录首板低点、实体中点与调整量能，区分“回调到位”与“确认转强”；
- S4 平台边界（前高 Ceiling）必须仅用突破前 20 日数据计算，严禁未来数据，区分“直接突破”与“回踩确认”；
- 综合评分仅作为同策略内部排序字段；
- 实盘级模拟账户绝不买入已封死涨停的不可成交票（主板 $\ge 9.7\%$，双创 $\ge 19.5\%$）。

---

### Task 1: 核心四策略独立规则与观察池构建模块

**Files:**
- Create: `strategy_four_pillars.py`
- Test: `tests/test_four_strategies.py`

**Interfaces:**
- Consumes: 股票行情字典、板块字典、历史日线数据字典
- Produces: 
  - `detect_s1_auction_first_board(stock, confirm_stock=None, yesterday=None, sector_info=None) -> dict | None`
  - `detect_s2_mainline_leader(stock, sector_rank_info, stage="auction") -> dict | None`
  - `detect_s3_limitup_pullback(stock, s3_item, stage="confirm") -> dict | None`
  - `detect_s4_breakout_retest(stock, s4_item, stage="confirm") -> dict | None`
  - `build_observation_pools(daily_bars_map, target_date_str) -> dict`

- [ ] **Step 1: 编写四策略独立判定的失败测试用例**

在 `tests/test_four_strategies.py` 中编写针对 S1、S2、S3、S4 的单元测试：
```python
import pytest
from strategy_four_pillars import (
    detect_s1_auction_first_board,
    detect_s2_mainline_leader,
    detect_s3_limitup_pullback,
    detect_s4_breakout_retest,
    build_observation_pools,
)

def test_s1_auction_first_board_watching_and_confirmed():
    # 竞价合格：金额>=500万，高开3%，昨天未涨停，板块走强
    s_early = {
        "code": "000001", "name": "测试股", "price": 10.30, "open_price": 10.30,
        "pre_close": 10.00, "auction_change": 3.0, "amount": 6_000_000,
        "vr": 1.8, "float_cap": 50.0
    }
    yesterday = {"is_limit_up": False}
    sec_info = {"name": "银行", "score": 85, "avg_pct": 2.5, "breadth": 0.65, "flow_rank": 2}
    
    # 09:25 竞价入选 (WATCHING)
    res_watching = detect_s1_auction_first_board(s_early, confirm_stock=None, yesterday=yesterday, sector_info=sec_info)
    assert res_watching is not None
    assert res_watching["status"] == "WATCHING"
    assert res_watching["strategy_id"] == "S1"

    # 09:32 开盘确认：价格守住竞价价，放量
    s_confirm = dict(s_early, price=10.35, amount=12_000_000)
    res_confirmed = detect_s1_auction_first_board(s_early, confirm_stock=s_confirm, yesterday=yesterday, sector_info=sec_info)
    assert res_confirmed is not None
    assert res_confirmed["status"] == "CONFIRMED"

def test_s1_auction_invalidated_when_broken():
    s_early = {"code": "000001", "name": "测试股", "price": 10.30, "open_price": 10.30, "pre_close": 10.00, "auction_change": 3.0, "amount": 6_000_000, "vr": 1.8, "float_cap": 50.0}
    # 跌破竞价价超过2%
    s_confirm = dict(s_early, price=10.05, amount=10_000_000)
    res = detect_s1_auction_first_board(s_early, confirm_stock=s_confirm, yesterday={"is_limit_up": False}, sector_info={"avg_pct": 2.0, "breadth": 0.6})
    assert res is not None
    assert res["status"] == "INVALIDATED"
    assert "跌破" in res["invalid_reason"]
```

- [ ] **Step 2: 运行测试并验证其失败**

运行：`pytest tests/test_four_strategies.py -v`
预期：FAIL (ModuleNotFoundError: No module named 'strategy_four_pillars')

- [ ] **Step 3: 实现 `strategy_four_pillars.py`**

编写包含 S1~S4 独立函数、两级状态机以及历史日线观察池生成函数。严格执行：
1. S1 竞价首板：09:25 竞价入选、09:32 守住竞价放量确认、ST/估算/跌破开盘2%失效；
2. S2 主线龙头：板块前3+breadth>=0.5+净流入，龙头个股板块前排+成交>=3000万，10:00 确认；
3. S3 涨停回调：首板低点、实体中点、缩量调整池，支持“回调低吸”与“洗盘再启动”两变体；
4. S4 突破回踩：突破前20日平台最高价 Ceiling 计算，放量>=1.5倍，日内回踩守稳确认。

- [ ] **Step 4: 运行测试并验证全部通过**

运行：`pytest tests/test_four_strategies.py -v`
预期：PASS

- [ ] **Step 5: 提交 Task 1 代码**

```bash
git add strategy_four_pillars.py tests/test_four_strategies.py
git commit -m "feat: implement four pillars strategy rules and observation pool generator"
```

---

### Task 2: 改造量化决策引擎 `scalp_decision_engine.py`

**Files:**
- Modify: `scalp_decision_engine.py`
- Test: `tests/test_scalp_decision_engine.py`

**Interfaces:**
- Consumes: `strategy_four_pillars.py`, Eastmoney 全景行情
- Produces: 
  - `analyze_scalp_market_v2`: 引入 Line 67 评分模型计算 `score`，并将命中的 S1~S4 独立装配进股票对象；
  - `get_stage_pushed_stocks`: 输出按策略分栏的候选清单（`strategy_groups` 与 `pushed_stocks`）；
  - `build_scalp_feishu_card_v2`: 渲染飞书交互式卡片，展示各策略分栏与失效观察线。

- [ ] **Step 1: 编写决策引擎策略分栏与评分排序测试**

在 `tests/test_scalp_decision_engine.py` 中测试：
1. 验证综合评分模型满足 Line 67 公式（资金强度、价格合理性、量比、板块、流通盘）；
2. 验证多标的命中同策略时，优先按 `score` 倒序排名前 2；
3. 验证卡片 JSON 结构包含 S1/S2/S3/S4 策略分栏与风控失效线。

- [ ] **Step 2: 运行测试并验证失败**

运行：`pytest tests/test_scalp_decision_engine.py -v`
预期：FAIL

- [ ] **Step 3: 改造 `scalp_decision_engine.py`**

1. 继承 Line 67 的打分函数（`score_auction_amount`, `score_auction_change`, `score_volume_ratio`, `score_market_cap`, `score_price_hold`, `score_trend`, `score_liquidity`）；
2. 调用 `strategy_four_pillars` 为标的贴上规范策略标签与状态（`strategy_id`, `signal_stage`, `strategy_variant`, `support_price`, `invalid_reason`）；
3. 改造 `get_stage_pushed_stocks`：早盘阶段重点筛选 S1 和 S2，尾盘阶段重点筛选 S3 和 S4，各策略内部按分数倒序；
4. 改造 `build_scalp_feishu_card_v2`：增加 S1~S4 策略板块卡片模块渲染。

- [ ] **Step 4: 运行测试并验证通过**

运行：`pytest tests/test_scalp_decision_engine.py -v`
预期：PASS

- [ ] **Step 5: 提交 Task 2 代码**

```bash
git add scalp_decision_engine.py tests/test_scalp_decision_engine.py
git commit -m "feat(engine): integrate Line 67 scoring and four-strategy categorized push pipeline"
```

---

### Task 3: 扩展推送入口 `scalp_push.py` 与 14:30 尾盘调度

**Files:**
- Modify: `scalp_push.py`
- Modify: `scalp_account_manager.py`
- Modify: `scalp_daily_review.py`
- Create: `.github/workflows/scalp-afternoon.yml`
- Test: `tests/test_scalp_push.py`

**Interfaces:**
- Consumes: `scalp_decision_engine.py`, `scalp_account_manager.py`
- Produces: 
  - `python scalp_push.py --stage afternoon` 尾盘 14:30 推送与模拟买入；
  - 模拟账户早盘配置 S1/S2，尾盘配置 S3/S4。

- [ ] **Step 1: 编写 14:30 尾盘推送测试**

在 `tests/test_scalp_push.py` 中测试：
1. 测试 `--stage afternoon` 时间窗口校验（14:20 ~ 14:45）；
2. 验证模拟账户在 afternoon 阶段优先买入 S3 回调低吸与 S4 突破回踩标的；
3. 验证不买入已封死涨停标的。

- [ ] **Step 2: 运行测试并验证失败**

运行：`pytest tests/test_scalp_push.py -v`
预期：FAIL

- [ ] **Step 3: 实现 `scalp_push.py` 与 `scalp_account_manager.py` 改造**

1. 在 `scalp_push.py` 中加入 `stage="afternoon"`，对应标签“尾盘低吸与突破回踩决胜 (14:30)”；
2. 调整时间窗口保护：`"afternoon": ("14:20", "14:45")`；
3. 在 `scalp_account_manager.py` 中针对 stage 做策略分仓买入匹配；
4. 在 `scalp_daily_review.py` 的收盘复盘中，自动调用 `strategy_four_pillars.build_and_save_observation_pools` 刷新次日 S3 和 S4 观察池；
5. 新增 `.github/workflows/scalp-afternoon.yml`。

- [ ] **Step 4: 运行测试并验证通过**

运行：`pytest tests/test_scalp_push.py -v`
预期：PASS

- [ ] **Step 5: 提交 Task 3 代码**

```bash
git add scalp_push.py scalp_account_manager.py scalp_daily_review.py .github/workflows/scalp-afternoon.yml tests/test_scalp_push.py
git commit -m "feat(push): add 14:30 afternoon stage and time-based strategy allocation"
```

---

### Task 4: 升级数据库存储与战法胜率归因 `scalp_trade_db.py`

**Files:**
- Modify: `scalp_trade_db.py`
- Test: `tests/test_scalp_trade_db.py`

**Interfaces:**
- Consumes: 推送信号、平仓记录
- Produces: 
  - `record_push_signals` 写入 S1~S4 字段；
  - `save_observation_pool` / `load_observation_pool`；
  - Excel 报表与战法胜率分析按 S1~S4 聚合。

- [ ] **Step 1: 编写数据库升级与归因统计测试**

在 `tests/test_scalp_trade_db.py` 中测试：
1. 验证 `push_signals` 新增字段兼容现有数据库；
2. 验证观察池写入与读取；
3. 验证 Excel 报表包含按 S1~S4 统计的胜率 Sheet。

- [ ] **Step 2: 运行测试并验证失败**

运行：`pytest tests/test_scalp_trade_db.py -v`
预期：FAIL

- [ ] **Step 3: 改造 `scalp_trade_db.py`**

1. `init_db`: 检查并执行 `ALTER TABLE push_signals ADD COLUMN ...`；
2. 新增 `CREATE TABLE IF NOT EXISTS strategy_observation_pool ...`；
3. 升级 `record_push_signals` 存储 `strategy_id`, `signal_stage`, `strategy_variant`, `support_price`；
4. 升级 `generate_excel_report`，在战法统计 Sheet 中分别展示 S1 竞价首板、S2 主线龙头、S3 涨停回调、S4 量价突破的交易次数、胜率、平均盈亏。

- [ ] **Step 4: 运行测试并验证通过**

运行：`pytest tests/test_scalp_trade_db.py -v`
预期：PASS

- [ ] **Step 5: 提交 Task 4 代码**

```bash
git add scalp_trade_db.py tests/test_scalp_trade_db.py
git commit -m "feat(db): upgrade scalp trade db with four-strategy attribution and observation pool"
```

---

### Task 5: 整体集成与端到端真实/演示测试

**Files:**
- Create: `tests/test_integration_four_strategies.py`

- [ ] **Step 1: 编写全天时序回放集成测试**

模拟 09:26 ➔ 09:38 ➔ 10:00 ➔ 14:30 ➔ 15:30 完整流程：
- 09:26: 生成 S1 WATCHING 信号
- 09:38: 确认 S1 CONFIRMED，模拟账户买入
- 10:00: 生成 S2 CONFIRMED，模拟账户买入
- 14:30: 比对观察池，确认 S3/S4，模拟账户买入
- 15:30: 每日复盘与资产重估，校验所有卡片与数据记录正确性

- [ ] **Step 2: 执行全量测试套件**

运行：`pytest tests/ -v`
预期：所有测试 100% PASS

- [ ] **Step 3: 使用 demo 模式运行命令行验证**

运行：
`python scalp_push.py --stage auction --demo`
`python scalp_push.py --stage confirm --demo`
`python scalp_push.py --stage settle --demo`
`python scalp_push.py --stage afternoon --demo`
验证控制台日志输出与卡片数据结构完全符合预期。

- [ ] **Step 4: 提交集成测试与最终记录**

```bash
git add tests/test_integration_four_strategies.py
git commit -m "test: add end-to-end integration tests for four strategies push system"
```
