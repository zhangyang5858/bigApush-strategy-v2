"""
短线决策台 10 万元模拟交易账户与 T+1 生命周期管理器
(Scalp Account Manager with T+1 Execution Engine)

核心规则：
1. 初始本金：100,000.00 元
2. 仓位管理：单只标的分配 20%~25% 仓位（约 20,000~25,000 元），每只买入股数严格为 100 股（1手）的整数倍
3. T+1 交易制度：
   - 当天（T日）买入不可卖出，记录 buy_date
   - 次日（T+1日）在 09:26、09:35、09:55 监测行情：
     * 09:26 竞价预警：若大幅低开 <= -2.5%，提示竞价抢跑止损；若大幅高开，提示冲高观察
     * 09:35/09:55 实盘处置：
       - 涨停封死 ➔ 🏆 连板持有
       - 冲高盈利 >= +3.5% 且未板 ➔ 🎯 冲高止盈卖出（回收现金）
       - 跌破成本 -2.5% 或跌破昨开防守线 ➔ 🚨 破位止损卖出（回收现金）
       - 持股满期/走弱 ➔ ⏱️ 调仓清仓
4. 交易费用全真扣除：
   - 买入：佣金万2.5（最低5元）+ 过户费十万分之1
   - 卖出：佣金万2.5（最低5元）+ 印花税千分之0.5 + 过户费十万分之1
5. 资金复用与资产曲线：卖出资金即时释放回可用现金，可用于买入当天新标的
"""
import os
import json
from datetime import datetime
from scalp_decision_engine import n, clamp

ACCOUNT_FILE = "data/scalp_account.json"
INITIAL_CAPITAL = 100000.00
COMMISSION_RATE = 0.00025    # 佣金万2.5
MIN_COMMISSION = 5.00        # 最低佣金5元
STAMP_DUTY_RATE = 0.0005     # 卖出印花税千0.5
TRANSFER_FEE_RATE = 0.00001  # 过户费十万分之1


def ensure_account_exists():
    """确保账户数据文件存在，若不存在则初始化 10 万元账户"""
    os.makedirs(os.path.dirname(ACCOUNT_FILE), exist_ok=True)
    if not os.path.exists(ACCOUNT_FILE):
        init_account = {
            "initial_capital": INITIAL_CAPITAL,
            "total_assets": INITIAL_CAPITAL,
            "cash": INITIAL_CAPITAL,
            "positions": [],
            "closed_trades": [],
            "daily_history": [],
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_account(init_account)
        return init_account
    try:
        with open(ACCOUNT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        init_account = {
            "initial_capital": INITIAL_CAPITAL,
            "total_assets": INITIAL_CAPITAL,
            "cash": INITIAL_CAPITAL,
            "positions": [],
            "closed_trades": [],
            "daily_history": [],
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        save_account(init_account)
        return init_account


def load_account():
    return ensure_account_exists()


def save_account(account_data):
    os.makedirs(os.path.dirname(ACCOUNT_FILE), exist_ok=True)
    account_data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(ACCOUNT_FILE, "w", encoding="utf-8") as f:
        json.dump(account_data, f, ensure_ascii=False, indent=2)

    # 自动同步至 SQLite 数据库
    try:
        from scalp_trade_db import sync_active_positions, record_closed_trade
        sync_active_positions(account_data.get("positions", []))
        for trade in account_data.get("closed_trades", []):
            record_closed_trade(trade)
    except Exception as e:
        pass



def calc_buy_fee(gross_amount):
    """计算买入手续费 (佣金 + 过户费)"""
    comm = max(gross_amount * COMMISSION_RATE, MIN_COMMISSION)
    trans = gross_amount * TRANSFER_FEE_RATE
    return round(comm + trans, 2)


def calc_sell_fee(gross_amount):
    """计算卖出手续费 (佣金 + 印花税 + 过户费)"""
    comm = max(gross_amount * COMMISSION_RATE, MIN_COMMISSION)
    stamp = gross_amount * STAMP_DUTY_RATE
    trans = gross_amount * TRANSFER_FEE_RATE
    return round(comm + stamp + trans, 2)


def check_and_execute_sells(account, live_price_map, zt_set, stage="auction", today_str=None):
    """
    检查并执行 T+1 持仓处置决策
    - 只能卖出 buy_date < today_str 的持仓 (T+1 规则)
    - 阶段判断：
      * 09:26 竞价阶段：只输出建议与预警，不实际成交扣减（9:30前不能成交）
      * 09:35/09:55 开盘后阶段：若满足止盈/止损/调仓条件，自动执行卖出成交并回收现金
    """
    if not today_str:
        today_str = datetime.now().strftime("%Y-%m-%d")

    positions = account.get("positions", [])
    remaining_positions = []
    sell_actions = []

    for pos in positions:
        code = str(pos.get("code") or "")
        name = pos.get("name") or ""
        buy_date = pos.get("buy_date", "")
        buy_price = n(pos.get("buy_price"))
        shares = int(pos.get("shares", 0))
        stop_loss = n(pos.get("stop_loss") or (buy_price * 0.975))
        cost_amount = n(pos.get("cost_amount"))

        # 判断是否为 T+1 可卖状态
        is_t_plus_1 = (buy_date < today_str)

        # 获取实时行情
        live_info = live_price_map.get(code, {})
        cur_price = n(live_info.get("f2") or buy_price)
        cur_chg = n(live_info.get("f3"))
        high_price = n(live_info.get("f15") or cur_price)
        low_price = n(live_info.get("f16") or cur_price)
        open_price = n(live_info.get("f17") or cur_price)

        is_zt = (code in zt_set) or (cur_chg >= 9.85 and cur_price >= high_price)
        unrealized_profit_pct = ((cur_price / buy_price) - 1) * 100 if buy_price > 0 else 0.0
        unrealized_profit_amount = (cur_price - buy_price) * shares

        action_desc = "🛡️ 正常持股"
        reason = "处于正常波动区间，继续持有观察"
        should_sell = False

        if not is_t_plus_1:
            # T 日持仓：当天买入，锁定不可卖出
            action_desc = "🔒 T日持仓锁定"
            reason = f"今日建仓({pos.get('buy_stage', '早盘')})，严格按T+1规则锁定，次日方可处置"
            pos["current_price"] = cur_price
            pos["unrealized_profit_pct"] = round(unrealized_profit_pct, 2)
            pos["unrealized_profit_amount"] = round(unrealized_profit_amount, 2)
            remaining_positions.append(pos)
            sell_actions.append({
                "code": code,
                "name": name,
                "is_t_plus_1": False,
                "action": action_desc,
                "reason": reason,
                "shares": shares,
                "buy_price": buy_price,
                "cur_price": cur_price,
                "profit_pct": unrealized_profit_pct,
                "profit_amount": unrealized_profit_amount,
                "is_executed": False
            })
            continue

        # ── T+1 可卖持仓处置策略 ──
        if is_zt:
            action_desc = "🏆 连板格局持股"
            reason = "早盘强势封死涨停板，继续持有享受连板溢价"
            should_sell = False

        elif stage == "auction":
            # 09:26 竞价阶段：只做预警提示
            auction_chg = ((cur_price / buy_price) - 1) * 100 if buy_price > 0 else 0
            if cur_price <= stop_loss or auction_chg <= -2.5:
                action_desc = "🚨 竞价不及预期·预警"
                reason = f"竞价大幅低开({auction_chg:+.2f}%)，建议 9:30 开盘反抽均线果断止损抢跑"
            elif auction_chg >= 3.0:
                action_desc = "🎯 竞价高开超预期"
                reason = f"竞价强势高开({auction_chg:+.2f}%)，9:30开盘观察冲高力度，若不板可在 9:35 冲高止盈"
            else:
                action_desc = "👀 竞价平开盯盘"
                reason = f"竞价平稳，开盘观察分时承接与量能"
            should_sell = False  # 竞价不直接成交，等待 09:35 确认

        else:
            # 09:35 / 09:55 实盘操作阶段
            if cur_price <= stop_loss or unrealized_profit_pct <= -2.5:
                action_desc = "🚨 触发止损卖出"
                reason = f"跌破防守线({unrealized_profit_pct:+.2f}%)，无条件止损控制风险"
                should_sell = True
            elif unrealized_profit_pct >= 3.5 and not is_zt:
                action_desc = "🎯 冲高止盈卖出"
                reason = f"早盘冲高获利({unrealized_profit_pct:+.2f}%)，未封涨停，分批落袋为安"
                should_sell = True
            elif unrealized_profit_pct < 0 and low_price <= stop_loss:
                action_desc = "🚨 盘中破位止损"
                reason = f"盘中触及止损价 ￥{stop_loss:.2f}，按纪律清仓"
                should_sell = True
            elif stage == "settle" and not is_zt:
                # 09:55 定势阶段仍未冲高且走弱，执行调仓
                action_desc = "⏱️ 超短调仓卖出"
                reason = f"早盘半小时定势未走强({unrealized_profit_pct:+.2f}%)，清仓腾出资金"
                should_sell = True
            else:
                action_desc = "🛡️ VWAP上方持股"
                reason = f"稳居买入价上方({unrealized_profit_pct:+.2f}%)，继续观察"
                should_sell = False

        if should_sell and stage in ["instant", "confirm", "settle"]:
            # 执行卖出结算
            gross_sell_amount = shares * cur_price
            sell_fee = calc_sell_fee(gross_sell_amount)
            net_sell_amount = gross_sell_amount - sell_fee
            realized_profit = net_sell_amount - cost_amount
            realized_profit_pct = (realized_profit / cost_amount * 100) if cost_amount > 0 else 0.0

            account["cash"] = round(account["cash"] + net_sell_amount, 2)
            closed_record = {
                "code": code,
                "name": name,
                "buy_date": buy_date,
                "buy_price": buy_price,
                "sell_date": today_str,
                "sell_time": datetime.now().strftime("%H:%M:%S"),
                "sell_stage": stage,
                "sell_price": cur_price,
                "shares": shares,
                "gross_sell_amount": round(gross_sell_amount, 2),
                "fee": sell_fee,
                "realized_profit": round(realized_profit, 2),
                "realized_profit_pct": round(realized_profit_pct, 2),
                "action": action_desc,
                "reason": reason
            }
            account["closed_trades"].append(closed_record)
            sell_actions.append({
                "code": code,
                "name": name,
                "is_t_plus_1": True,
                "action": action_desc,
                "reason": reason,
                "shares": shares,
                "buy_price": buy_price,
                "cur_price": cur_price,
                "profit_pct": realized_profit_pct,
                "profit_amount": realized_profit,
                "is_executed": True
            })
            print(f"  💸 [模拟卖出] {code} {name} {shares}股 @ ￥{cur_price:.2f} | 盈亏: {realized_profit:+.2f}元 ({realized_profit_pct:+.2f}%) | 释放现金: {net_sell_amount:.2f}元")
        else:
            pos["current_price"] = cur_price
            pos["unrealized_profit_pct"] = round(unrealized_profit_pct, 2)
            pos["unrealized_profit_amount"] = round(unrealized_profit_amount, 2)
            remaining_positions.append(pos)
            sell_actions.append({
                "code": code,
                "name": name,
                "is_t_plus_1": True,
                "action": action_desc,
                "reason": reason,
                "shares": shares,
                "buy_price": buy_price,
                "cur_price": cur_price,
                "profit_pct": unrealized_profit_pct,
                "profit_amount": unrealized_profit_amount,
                "is_executed": False
            })

    account["positions"] = remaining_positions
    return sell_actions


STAGE_MAX_BUYS = {
    "auction": 1,   # 09:26 竞价阶段：严格限购 1 只（探针试错，仓位上限 25%，防大额诱多）
    "instant": 1,   # 09:31:30 极速秒板：限购 1 只（专抓开盘 90 秒主力闪电封板龙头）
    "confirm": 2,   # 09:35/09:38 开盘确认：核心主战场，允许买入 1~2 只（确定性最高）
    "settle": 1     # 09:55 早盘定势：机动补仓 1 只
}


def execute_stage_buys(account, pushed_stocks, stage="auction", today_str=None, max_positions=4, target_pos_ratio=0.25):
    """
    执行早盘新推荐标的的模拟买入建仓
    - 阶段控仓配额：
      * auction (09:26): 最多买 1 只 (25%)，避免过早打光子弹
      * instant (09:31:30): 最多买 1 只 (25%)
      * confirm (09:35/09:38): 最多买 2 只 (50%)，确定性最高的主战场
      * settle (09:55): 机动买 1 只
    - target_pos_ratio: 单只标的分配总资产的 25%（约 2.5 万元）
    - 检查现金是否充足
    - 股数严格向下取整到 100 股（1手）
    """
    if not today_str:
        today_str = datetime.now().strftime("%Y-%m-%d")

    stage_limit = STAGE_MAX_BUYS.get(stage, 2)
    existing_codes = {p["code"] for p in account.get("positions", [])}
    buy_records = []

    for stock in pushed_stocks:
        if len(buy_records) >= stage_limit:
            break
        if len(account.get("positions", [])) >= max_positions:
            break

        code = str(stock.get("code") or "")
        name = stock.get("name") or ""
        push_price = n(stock.get("push_price") or stock.get("price") or stock.get("open_price"))
        open_price = n(stock.get("open_price") or push_price)
        stop_loss = n(stock.get("stop_loss") or (open_price * 0.98))
        strategy_tag = stock.get("strategy_tag", "🎯 综合短线")

        if code in existing_codes:
            continue
        if push_price <= 0:
            continue

        # 计算拟分配买入资金
        target_buy_amount = min(account.get("total_assets", INITIAL_CAPITAL) * target_pos_ratio, account["cash"])
        if target_buy_amount < 5000:  # 可用现金不足 5000 元不再建仓
            break

        # 计算买入股数 (向下取 100 股整数倍)
        raw_shares = int(target_buy_amount / (push_price * 100)) * 100
        if raw_shares < 100:
            continue

        gross_buy_amount = raw_shares * push_price
        buy_fee = calc_buy_fee(gross_buy_amount)
        total_cost = gross_buy_amount + buy_fee

        if total_cost > account["cash"]:
            raw_shares -= 100
            if raw_shares < 100:
                continue
            gross_buy_amount = raw_shares * push_price
            buy_fee = calc_buy_fee(gross_buy_amount)
            total_cost = gross_buy_amount + buy_fee

        # 扣除现金并建仓
        account["cash"] = round(account["cash"] - total_cost, 2)
        pos_entry = {
            "code": code,
            "name": name,
            "buy_date": today_str,
            "buy_time": datetime.now().strftime("%H:%M:%S"),
            "buy_stage": stage,
            "strategy_tag": strategy_tag,
            "buy_price": push_price,
            "current_price": push_price,
            "open_price": open_price,
            "stop_loss": stop_loss,
            "shares": raw_shares,
            "cost_amount": round(total_cost, 2),
            "fee": buy_fee,
            "unrealized_profit_pct": 0.0,
            "unrealized_profit_amount": 0.0
        }
        account["positions"].append(pos_entry)
        existing_codes.add(code)

        buy_records.append({
            "code": code,
            "name": name,
            "shares": raw_shares,
            "buy_price": push_price,
            "cost_amount": total_cost,
            "pos_ratio": (total_cost / account.get("total_assets", INITIAL_CAPITAL)) * 100,
            "stop_loss": stop_loss,
            "strategy_tag": strategy_tag
        })
        print(f"  🛒 [模拟买入] {code} {name} {raw_shares}股 @ ￥{push_price:.2f} | 占用现金: {total_cost:.2f}元 (仓位 {(total_cost / account.get('total_assets', INITIAL_CAPITAL))*100:.1f}%)")

    return buy_records


def settle_daily_account(account, live_price_map, zt_set, today_str=None):
    """
    15:30 每日收盘账户结算
    - 更新当前所有持仓市值
    - 计算账户总资产 = 可用现金 + 持仓总市值
    - 计算今日收益额与累计收益率
    - 记录到 daily_history
    """
    if not today_str:
        today_str = datetime.now().strftime("%Y-%m-%d")

    pos_market_value = 0.0
    for pos in account.get("positions", []):
        code = str(pos.get("code") or "")
        shares = int(pos.get("shares", 0))
        buy_price = n(pos.get("buy_price"))
        cost_amount = n(pos.get("cost_amount"))

        live_info = live_price_map.get(code, {})
        close_price = n(live_info.get("f2") or pos.get("current_price") or buy_price)
        cur_market_val = shares * close_price
        pos_market_value += cur_market_val

        pos["current_price"] = close_price
        pos["market_value"] = round(cur_market_val, 2)
        pos["unrealized_profit_amount"] = round(cur_market_val - cost_amount, 2)
        pos["unrealized_profit_pct"] = round(((close_price / buy_price) - 1) * 100, 2) if buy_price > 0 else 0.0
        pos["is_zt"] = (code in zt_set) or (n(live_info.get("f3")) >= 9.85)

    account["position_market_value"] = round(pos_market_value, 2)
    prev_assets = INITIAL_CAPITAL
    if account.get("daily_history"):
        prev_assets = account["daily_history"][-1].get("total_assets", INITIAL_CAPITAL)

    new_total_assets = round(account["cash"] + pos_market_value, 2)
    daily_profit = round(new_total_assets - prev_assets, 2)
    daily_return_pct = round((daily_profit / prev_assets) * 100, 2) if prev_assets > 0 else 0.0
    total_profit = round(new_total_assets - INITIAL_CAPITAL, 2)
    total_return_pct = round((total_profit / INITIAL_CAPITAL) * 100, 2)

    account["total_assets"] = new_total_assets

    # 更新或追加今日日结记录
    history_entry = {
        "date": today_str,
        "total_assets": new_total_assets,
        "cash": account["cash"],
        "position_market_value": round(pos_market_value, 2),
        "daily_profit": daily_profit,
        "daily_return_pct": daily_return_pct,
        "total_profit": total_profit,
        "total_return_pct": total_return_pct,
        "position_count": len(account.get("positions", []))
    }

    # 替换当天已有记录或新增
    existing_idx = next((idx for idx, h in enumerate(account.get("daily_history", [])) if h.get("date") == today_str), None)
    if existing_idx is not None:
        account["daily_history"][existing_idx] = history_entry
    else:
        account["daily_history"].append(history_entry)

    save_account(account)

    # 同步日结记录到 SQLite 并自动刷新 Excel 报表
    try:
        from scalp_trade_db import record_daily_settlement, export_trades_to_excel
        record_daily_settlement(history_entry)
        export_trades_to_excel()
    except Exception:
        pass

    return history_entry
