"""
短线决策台日内与波段回测仿真引擎 (Scalp Intraday & Swing Backtest Engine)
Phase 2 核心量化引擎：
1. 真实早盘快照历史重演 (Snapshot Replay):
   读取 data/scalp_records/ 沉淀的 09:26/09:31/09:38/09:55 真实推送记录，
   基于通达信真实行情与 A 股 T+1 交易规则进行全景推演。
2. 多维度表现透视:
   按时段(竞价/秒板/确认/定势)及战法(弱转强/VWAP低吸/二波蓄势/大单抢筹)拆解胜率与盈亏比。
3. 通达信 1 分钟级别分时轨迹重现 (Minute Trace):
   利用 pytdx 毫秒级 1 分钟 K 线重构日内分时成交、VWAP 均线与成交量异动。
"""

import os
import glob
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np

from utils.tdx_fetcher import TDXFetcher

logger = logging.getLogger("ScalpBacktest")


class ScalpBacktestEngine:
    """短线决策台量化回测与仿真推演引擎"""

    def __init__(self, record_dir: str = "data/scalp_records"):
        self.record_dir = record_dir
        self.price_cache: Dict[str, pd.DataFrame] = {}  # {code: df_daily}
        self.minute_cache: Dict[str, pd.DataFrame] = {} # {f"{code}_{date}": df_minute}

    def load_all_snapshot_files(self) -> Dict[str, Dict[str, Dict]]:
        """
        加载所有本地已保存的推送快照
        返回格式: {date_str: {stage: payload}}
        """
        all_dates = {}
        files = sorted(glob.glob(os.path.join(self.record_dir, "push_*.json")))
        for f in files:
            base = os.path.basename(f)
            # 文件名格式: push_YYYY-MM-DD_stage.json
            parts = base.replace(".json", "").split("_")
            if len(parts) >= 3:
                date_str = parts[1]
                stage = parts[2]
                try:
                    with open(f, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                    if date_str not in all_dates:
                        all_dates[date_str] = {}
                    all_dates[date_str][stage] = data
                except Exception as e:
                    logger.warning(f"读取快照文件 {f} 失败: {e}")
        return all_dates

    def preload_stocks_market_data(self, codes: List[str], count: int = 60) -> int:
        """通过通达信批量预加载行情基准数据，若通达信离线自动切换东财24/7高速接口"""
        unique_codes = list(set([c for c in codes if c and c not in self.price_cache]))
        if not unique_codes:
            return len(self.price_cache)

        logger.info(f"⚡ 正在加载 {len(unique_codes)} 只标的行情基准数据...")
        # 1. 尝试通达信直连
        try:
            with TDXFetcher() as fetcher:
                if fetcher.is_connected:
                    for c in unique_codes:
                        try:
                            df = fetcher.get_daily_bars(c, count=count)
                            if not df.empty:
                                df["date"] = df["date"].astype(str)
                                self.price_cache[c] = df
                        except Exception:
                            pass
        except Exception:
            pass

        # 2. 对未获取到的标的，使用东财 24/7 高速接口多线程补齐
        missing_codes = [c for c in unique_codes if c not in self.price_cache]
        if missing_codes:
            import urllib.request
            from concurrent.futures import ThreadPoolExecutor

            def fetch_single_em(code):
                try:
                    secid = f"0.{code}" if code.startswith(("0", "3")) else f"1.{code}"
                    url = f"http://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=1&end=20500101&lmt={count}"
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    resp = urllib.request.urlopen(req, timeout=4)
                    data = json.loads(resp.read().decode())
                    klines = data.get("data", {}).get("klines", [])
                    if not klines:
                        return code, None
                    rows = []
                    for k in klines:
                        p = k.split(",")
                        rows.append({
                            "date": p[0],
                            "open": float(p[1]),
                            "close": float(p[2]),
                            "high": float(p[3]),
                            "low": float(p[4]),
                            "vol": float(p[5]),
                            "amount": float(p[6])
                        })
                    return code, pd.DataFrame(rows)
                except Exception:
                    return code, None

            with ThreadPoolExecutor(max_workers=16) as pool:
                results = pool.map(fetch_single_em, missing_codes)
                for code, df in results:
                    if df is not None and not df.empty:
                        self.price_cache[code] = df

        logger.info(f"✓ 成功缓存 {len(self.price_cache)} 只股票基准行情数据")
        return len(self.price_cache)

    def replay_snapshots(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        initial_capital: float = 100000.0,
        max_positions: int = 4,
        stop_loss_pct: float = -4.0,
        staged_tp_pct: float = 10.0,
        trailing_tp_pct: float = 8.0,
        max_hold_days: int = 5,
        strategy_filter: Optional[List[str]] = None,
        stage_filter: Optional[List[str]] = None,
        enable_dragon_rules: bool = False
    ) -> Dict:
        """
        历史推送快照全景回测回放 (实盘级 T+1 模拟账户推演)
        """
        all_snapshots = self.load_all_snapshot_files()
        sorted_dates = sorted(all_snapshots.keys())
        if start_date:
            sorted_dates = [d for d in sorted_dates if d >= start_date]
        if end_date:
            sorted_dates = [d for d in sorted_dates if d <= end_date]

        if not sorted_dates:
            return {"error": "未找到符合日期范围的历史快照记录"}

        # 收集所有推荐股票代码并预加载行情
        all_rec_codes = set()
        for d in sorted_dates:
            for stage, snap in all_snapshots[d].items():
                for s in snap.get("stocks", []):
                    code = str(s.get("code") or "").zfill(6)
                    if code:
                        all_rec_codes.add(code)

        self.preload_stocks_market_data(list(all_rec_codes), count=60)

        # 初始化仿真账户
        account = {
            "initial_capital": initial_capital,
            "total_assets": initial_capital,
            "cash": initial_capital,
            "positions": [],         # 正在持仓
            "closed_trades": [],     # 已平仓交易
            "equity_curve": []       # 每日资产曲线
        }

        # 统计明细
        all_eval_items = []

        # 逐日推演
        for d_idx, current_date in enumerate(sorted_dates):
            day_snaps = all_snapshots[current_date]

            # ── 1. 早盘处置昨日持仓 (T+1 卖出/止盈止损) ──
            remaining_positions = []
            for pos in account["positions"]:
                code = pos["code"]
                buy_date = pos["buy_date"]
                buy_price = pos["buy_price"]
                shares = pos["shares"]
                hold_days = pos.get("hold_days", 1) + 1
                pos["hold_days"] = hold_days

                # 获取股票当日行情
                df = self.price_cache.get(code)
                cur_bar = None
                if df is not None and not df.empty:
                    match_row = df[df["date"] == current_date]
                    if not match_row.empty:
                        cur_bar = match_row.iloc[0]

                if cur_bar is None:
                    # 无行情保持现状
                    remaining_positions.append(pos)
                    continue

                open_p = float(cur_bar["open"])
                high_p = float(cur_bar["high"])
                low_p = float(cur_bar["low"])
                close_p = float(cur_bar["close"])

                # 动态追踪历史最高价与最大浮盈
                highest_price = max(pos.get("highest_price", buy_price), high_p)
                pos["highest_price"] = highest_price
                max_profit_pct = ((highest_price - buy_price) / buy_price) * 100
                pos["max_profit_pct"] = max_profit_pct

                # 判断止损/止盈条件
                # 规则 0: 龙头平台风控铁律：破今开 -5% 坚决弃龙止损
                is_break_open_stop = enable_dragon_rules and (((low_p - open_p) / open_p * 100) <= -5.0)

                # 规则 1: 保本锁 (曾浮盈 >= +3.5%，回落跌破成本)
                is_breakeven_hit = (max_profit_pct >= 3.5 and low_p <= buy_price * 1.003)

                # 规则 2: 竞价大幅低开抢跑
                is_auction_gap_down = ((open_p - buy_price) / buy_price * 100 <= -4.0)

                # 规则 3: 硬止损
                is_hard_stop = ((low_p - buy_price) / buy_price * 100 <= stop_loss_pct)

                # 规则 4: 冲高回落动态止盈 (浮盈曾经达标 trailing_tp_pct，且从高点回撤 >= 2.5%)
                is_trailing_tp = (max_profit_pct >= trailing_tp_pct and close_p <= highest_price * 0.975)

                # 规则 5: 持股达上限 5 天退出
                is_time_stop = (hold_days >= max_hold_days)

                should_sell = False
                sell_price = close_p
                sell_reason = ""

                if is_break_open_stop:
                    should_sell = True
                    sell_price = round(open_p * 0.95, 2)
                    sell_reason = "🪓 破今开-5%坚决弃龙止损"
                elif is_auction_gap_down:
                    if enable_dragon_rules and max_profit_pct >= 5.0 and open_p >= buy_price * 0.94:
                        if close_p > open_p:
                            sell_price = close_p
                            sell_reason = "⚠️ 龙头低开反抽减仓"
                        else:
                            sell_price = open_p
                            sell_reason = "🚨 竞价大幅低开抢跑止损"
                    else:
                        sell_price = open_p
                        sell_reason = "🚨 竞价大幅低开抢跑止损"
                    should_sell = True
                elif is_breakeven_hit:
                    should_sell = True
                    sell_price = buy_price * 1.003
                    sell_reason = "🛡️ 触发移动保本锁盈"
                elif is_hard_stop:
                    should_sell = True
                    sell_price = max(low_p, buy_price * (1 + stop_loss_pct / 100))
                    sell_reason = f"🚨 触发波段硬止损 ({stop_loss_pct}%)"
                elif is_trailing_tp:
                    should_sell = True
                    sell_price = close_p
                    sell_reason = "🎯 冲高回落锁定利润止盈"
                elif is_time_stop:
                    should_sell = True
                    sell_price = close_p
                    sell_reason = f"⏰ 达到最大持股天数({max_hold_days}天)到期平仓"

                if should_sell:
                    gross_amount = sell_price * shares
                    # 手续费计算 (佣金0.015% + 印花税0.05% + 过户费0.001%)
                    fee = max(gross_amount * 0.00015, 5.0) + (gross_amount * 0.0005) + (gross_amount * 0.00001)
                    net_amount = gross_amount - fee
                    profit_amount = net_amount - pos["cost_amount"]
                    return_rate = (profit_amount / pos["cost_amount"]) * 100

                    account["cash"] += net_amount
                    account["closed_trades"].append({
                        "code": code,
                        "name": pos["name"],
                        "strategy_tag": pos.get("strategy_tag", "短线决策"),
                        "buy_date": buy_date,
                        "sell_date": current_date,
                        "buy_price": buy_price,
                        "sell_price": round(sell_price, 2),
                        "shares": shares,
                        "cost_amount": pos["cost_amount"],
                        "net_amount": round(net_amount, 2),
                        "profit_amount": round(profit_amount, 2),
                        "return_rate": round(return_rate, 2),
                        "hold_days": hold_days,
                        "sell_reason": sell_reason
                    })
                else:
                    pos["current_price"] = close_p
                    remaining_positions.append(pos)

            account["positions"] = remaining_positions

            # ── 2. 处理当日各时段推送买入 ──
            stage_order = ["auction", "instant", "confirm", "settle"]
            for stg in stage_order:
                if stage_filter and stg not in stage_filter:
                    continue
                snap = day_snaps.get(stg)
                if not snap:
                    continue

                regime = snap.get("regime", "中性")
                if enable_dragon_rules:
                    if regime == "退潮防守":
                        continue
                    if regime == "防守" and stg in ["confirm", "settle", "afternoon"]:
                        continue

                stocks = snap.get("stocks", [])
                for s in stocks:
                    code = str(s.get("code") or "").zfill(6)
                    name = s.get("name") or ""
                    tag = s.get("strategy_tag") or "🎯 综合短线"
                    if strategy_filter and not any(sf in tag for sf in strategy_filter):
                        continue

                    # 龙头规则 1: 防核按钮，全面剔除 300/301/688 20cm 标的
                    if enable_dragon_rules and code.startswith(("300", "301", "688", "8", "4")):
                        continue

                    push_p = float(s.get("push_price") or s.get("open_price") or 0.0)
                    open_p = float(s.get("open_price") or push_p)
                    pre_c = float(s.get("pre_close") or open_p)

                    # 龙头规则 2: 竞价驼峰过滤与日内追高拦截
                    if enable_dragon_rules and not s.get("is_zt"):
                        auc_chg = ((open_p - pre_c) / pre_c * 100) if pre_c > 0 else 0.0
                        if auc_chg > 4.5:
                            continue  # 高开过度诱多出货惩罚
                        if push_p > open_p * 1.05:
                            continue  # 盘中追高超5%拦截

                    # 记录单日全景跟踪
                    df = self.price_cache.get(code)
                    if df is not None and not df.empty:
                        m_row = df[df["date"] == current_date]
                        if not m_row.empty:
                            c_bar = m_row.iloc[0]
                            c_close = float(c_bar["close"])
                            c_high = float(c_bar["high"])
                            c_low = float(c_bar["low"])
                            c_pre = float(c_bar.get("open", push_p)) # 参考
                            
                            intraday_ret = ((c_close - push_p) / push_p * 100) if push_p > 0 else 0.0
                            intraday_max = ((c_high - push_p) / push_p * 100) if push_p > 0 else 0.0
                            is_zt = (c_close == c_high and intraday_ret >= 9.8)

                            all_eval_items.append({
                                "date": current_date,
                                "stage": stg,
                                "code": code,
                                "name": name,
                                "strategy_tag": tag,
                                "push_price": push_p,
                                "close_price": c_close,
                                "high_price": c_high,
                                "intraday_return": round(intraday_ret, 2),
                                "max_intraday_space": round(intraday_max, 2),
                                "is_zt": is_zt
                            })

                    # 检查账户是否开仓买入
                    already_held = any(p["code"] == code for p in account["positions"])
                    if not already_held and len(account["positions"]) < max_positions and push_p > 0:
                        pos_budget = account["total_assets"] / max_positions
                        pos_budget = min(pos_budget, account["cash"])
                        shares = int((pos_budget / push_p) // 100) * 100
                        if shares >= 100:
                            gross = shares * push_p
                            buy_fee = max(gross * 0.00015, 5.0) + (gross * 0.00001)
                            total_cost = gross + buy_fee
                            if account["cash"] >= total_cost:
                                account["cash"] -= total_cost
                                account["positions"].append({
                                    "code": code,
                                    "name": name,
                                    "strategy_tag": tag,
                                    "buy_date": current_date,
                                    "buy_stage": stg,
                                    "buy_price": push_p,
                                    "current_price": push_p,
                                    "highest_price": push_p,
                                    "shares": shares,
                                    "cost_amount": total_cost,
                                    "hold_days": 0
                                })

            # 结算当日收盘总资产
            pos_val = 0.0
            for p in account["positions"]:
                df = self.price_cache.get(p["code"])
                if df is not None and not df.empty:
                    m_row = df[df["date"] == current_date]
                    if not m_row.empty:
                        p["current_price"] = float(m_row.iloc[0]["close"])
                pos_val += p["shares"] * p["current_price"]

            account["total_assets"] = account["cash"] + pos_val
            account["equity_curve"].append({
                "date": current_date,
                "cash": round(account["cash"], 2),
                "pos_value": round(pos_val, 2),
                "total_assets": round(account["total_assets"], 2),
                "positions_count": len(account["positions"])
            })

        # ── 3. 统计计算核心表现指标 ──
        closed = account["closed_trades"]
        win_trades = [t for t in closed if t["return_rate"] > 0]
        loss_trades = [t for t in closed if t["return_rate"] <= 0]
        total_closed = len(closed)
        win_rate = (len(win_trades) / total_closed * 100) if total_closed > 0 else 0.0

        avg_win = sum(t["return_rate"] for t in win_trades) / len(win_trades) if win_trades else 0.0
        avg_loss = abs(sum(t["return_rate"] for t in loss_trades) / len(loss_trades)) if loss_trades else 0.0
        profit_loss_ratio = (avg_win / avg_loss) if avg_loss > 0 else (avg_win if avg_win > 0 else 1.0)

        total_ret = ((account["total_assets"] - initial_capital) / initial_capital) * 100

        # 计算最大回撤
        peak = initial_capital
        max_drawdown = 0.0
        for eq in account["equity_curve"]:
            val = eq["total_assets"]
            if val > peak:
                peak = val
            dd = (peak - val) / peak * 100 if peak > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd

        # 战法分类透视
        by_strategy_stats = {}
        for t in closed:
            tag = t["strategy_tag"]
            if tag not in by_strategy_stats:
                by_strategy_stats[tag] = {"trades": 0, "win_trades": 0, "profit_sum": 0.0, "hold_days_sum": 0}
            st = by_strategy_stats[tag]
            st["trades"] += 1
            if t["return_rate"] > 0:
                st["win_trades"] += 1
            st["profit_sum"] += t["return_rate"]
            st["hold_days_sum"] += t.get("hold_days", 1)

        for tag, st in by_strategy_stats.items():
            cnt = st["trades"]
            st["win_rate"] = round((st["win_trades"] / cnt * 100), 2) if cnt > 0 else 0.0
            st["avg_return"] = round(st["profit_sum"] / cnt, 2) if cnt > 0 else 0.0
            st["avg_hold_days"] = round(st["hold_days_sum"] / cnt, 1) if cnt > 0 else 0.0

        # 日内选股质量 (推荐当日封板率与冲高空间)
        eval_df = pd.DataFrame(all_eval_items) if all_eval_items else pd.DataFrame()
        intraday_zt_rate = 0.0
        avg_intraday_space = 0.0
        if not eval_df.empty:
            intraday_zt_rate = round(eval_df["is_zt"].sum() / len(eval_df) * 100, 2)
            avg_intraday_space = round(eval_df["max_intraday_space"].mean(), 2)

        return {
            "period": f"{sorted_dates[0]} 至 {sorted_dates[-1]} ({len(sorted_dates)} 个交易日)",
            "initial_capital": initial_capital,
            "final_assets": round(account["total_assets"], 2),
            "total_return": round(total_ret, 2),
            "max_drawdown": round(max_drawdown, 2),
            "total_closed_trades": total_closed,
            "win_trades_count": len(win_trades),
            "loss_trades_count": len(loss_trades),
            "win_rate": round(win_rate, 2),
            "profit_loss_ratio": round(profit_loss_ratio, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "intraday_zt_rate": intraday_zt_rate,
            "avg_intraday_space": avg_intraday_space,
            "active_positions": account["positions"],
            "strategy_stats": by_strategy_stats,
            "closed_trades": closed,
            "equity_curve": account["equity_curve"]
        }

    def trace_minute_execution(self, code: str, date_str: str) -> Dict:
        """
        利用通达信 1 分钟线对某只标的在指定日期的真实日内走势进行毫秒级切片复盘
        重构 VWAP 分时均价、拉升波形与量比
        """
        code_clean = str(code).zfill(6)
        with TDXFetcher() as fetcher:
            df = fetcher.get_minute_bars(code_clean, category=8, count=240)

        if df.empty:
            return {"error": f"未能拉取股票 {code_clean} 的通达信 1 分钟分时数据"}

        # 过滤指定日期 (或取当天最后240根)
        df["date_only"] = df["datetime"].apply(lambda x: str(x)[:10])
        day_df = df[df["date_only"] == date_str]
        if day_df.empty:
            day_df = df  # 若日期跨越，展示最近一组日内走势

        # 计算日内累计 VWAP (成交额 / 成交量)
        # pytdx 中 volume 为成交量，amount 为成交额
        day_df = day_df.copy().reset_index(drop=True)
        day_df["cum_vol"] = day_df["volume"].cumsum()
        day_df["cum_amt"] = day_df["amount"].cumsum()
        day_df["vwap"] = (day_df["cum_amt"] / day_df["cum_vol"]).round(2)

        # 提取关键时点快照 (09:31, 09:35, 09:38, 09:55, 11:30, 14:30, 15:00)
        key_times = ["09:31", "09:35", "09:38", "09:55", "11:30", "14:30", "15:00"]
        milestones = []
        for kt in key_times:
            matched = day_df[day_df["datetime"].str.contains(kt)]
            if not matched.empty:
                r = matched.iloc[0]
                milestones.append({
                    "time": kt,
                    "price": float(r["close"]),
                    "vwap": float(r["vwap"]) if pd.notnull(r["vwap"]) else float(r["close"]),
                    "volume": float(r["volume"]),
                    "high": float(r["high"]),
                    "low": float(r["low"])
                })

        day_open = float(day_df.iloc[0]["open"])
        day_close = float(day_df.iloc[-1]["close"])
        day_high = float(day_df["high"].max())
        day_low = float(day_df["low"].min())
        day_ret = round(((day_close - day_open) / day_open) * 100, 2)
        max_pump = round(((day_high - day_open) / day_open) * 100, 2)

        return {
            "code": code_clean,
            "date": date_str,
            "open": day_open,
            "close": day_close,
            "high": day_high,
            "low": day_low,
            "day_return": day_ret,
            "max_pump": max_pump,
            "milestones": milestones,
            "total_1min_bars": len(day_df)
        }
