#!/usr/bin/env python3
"""
短线决策台日内与波段回测控制台 (Scalp Backtest CLI)
Phase 2: 专为 09:26 竞价初筛、09:31 秒板、09:38 确认、09:55 定势打造的日内仿真回测与推演工具
"""

import sys
import argparse
import logging
from datetime import datetime
from trading.scalp_backtest_engine import ScalpBacktestEngine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("ScalpCLI")


def run_replay(args):
    """运行真实快照历史重演"""
    engine = ScalpBacktestEngine()
    print("\n" + "⚡ " * 22)
    print("🚀 启动短线决策台真实早盘快照历史回测推演 (Scalp Snapshot Replay)")
    print(f"初始本金: ¥{args.capital:,.2f} | 最大持仓: {args.positions} 只 | 硬止损: {args.stop_loss}%")
    print(f"阶梯止盈: +{args.tp}% | 冲高回落动态止盈: +{args.trailing_tp}% (回撤2.5%锁定)")
    print("⚡ " * 22 + "\n")

    strat_filters = [s.strip() for s in args.strategy_filter.split(",")] if args.strategy_filter else None
    stage_filters = [s.strip() for s in args.stage_filter.split(",")] if args.stage_filter else None

    t0 = datetime.now()
    res = engine.replay_snapshots(
        start_date=args.start,
        end_date=args.end,
        initial_capital=args.capital,
        max_positions=args.positions,
        stop_loss_pct=args.stop_loss,
        staged_tp_pct=args.tp,
        trailing_tp_pct=args.trailing_tp,
        max_hold_days=args.hold_days,
        strategy_filter=strat_filters,
        stage_filter=stage_filters,
        enable_dragon_rules=getattr(args, "dragon", False)
    )

    if "error" in res:
        print(f"❌ 运行失败: {res['error']}")
        return

    duration = (datetime.now() - t0).total_seconds()

    # 1. 打印全景业绩报告
    print("\n" + "=" * 68)
    print(f"🏆 【短线决策台】历史回测全景业绩卡片")
    print("=" * 68)
    print(f"  回测区间      : {res['period']}")
    print(f"  推演耗时      : {duration:.1f} 秒")
    print(f"  初始本金      : ¥{res['initial_capital']:,.2f}")
    print(f"  最终资产      : ¥{res['final_assets']:,.2f}")
    print(f"  累计收益率    : {res['total_return']:+.2f}%")
    print(f"  最大回撤 (MDD): {res['max_drawdown']:.2f}%")
    print(f"  平仓总笔数    : {res['total_closed_trades']} 笔 (盈利 {res['win_trades_count']} 笔 / 亏损 {res['loss_trades_count']} 笔)")
    print(f"  回测胜率      : {res['win_rate']:.2f}%")
    print(f"  盈亏比 (P/L)  : {res['profit_loss_ratio']:.2f}")
    print(f"  单笔平均盈利  : +{res['avg_win']:.2f}%")
    print(f"  单笔平均亏损  : -{res['avg_loss']:.2f}%")
    print(f"  日内封板率    : {res['intraday_zt_rate']}% (当日涨停率)")
    print(f"  平均冲高空间  : +{res['avg_intraday_space']:.2f}% (买入后盘中最大涨幅)")
    print("=" * 68)

    # 2. 打印分战法表现矩阵
    strategy_stats = res.get("strategy_stats", {})
    if strategy_stats:
        print("\n📊 各战法策略实盘表现矩阵 (战法透视):")
        print(f"{'战法名称':<18} | {'交易笔数':<6} | {'胜率':<8} | {'单笔平均收益':<10} | {'平均持股天数'}")
        print("-" * 68)
        for tag, st in strategy_stats.items():
            print(f"{tag:<18} | {st['trades']:<6} | {st['win_rate']:>6.2f}% | {st['avg_return']:>+8.2f}% | {st['avg_hold_days']:>6.1f} 天")
        print("-" * 68)

    # 3. 打印最近平仓交易样本
    closed_trades = res.get("closed_trades", [])
    if closed_trades:
        print(f"\n📋 最近平仓交易记录 (共 {len(closed_trades)} 笔，展示最新 8 笔):")
        print(f"{'买入日期':<10} | {'卖出日期':<10} | {'代码':<6} | {'标的名称':<6} | {'买价':<6} | {'卖价':<6} | {'收益率':<7} | {'持股':<3} | {'平仓原因'}")
        print("-" * 88)
        for t in closed_trades[-8:]:
            b_dt = t["buy_date"]
            s_dt = t["sell_date"]
            c = t["code"]
            n = t["name"]
            bp = t["buy_price"]
            sp = t["sell_price"]
            r = t["return_rate"]
            hd = t.get("hold_days", 1)
            reason = t.get("sell_reason", "平仓")
            print(f"{b_dt:<10} | {s_dt:<10} | {c:<6} | {n:<6} | {bp:<6.2f} | {sp:<6.2f} | {r:>+6.2f}% | {hd:>2}天 | {reason}")
        print("-" * 88)

    # 4. 当前仍持有的标的
    active_pos = res.get("active_positions", [])
    if active_pos:
        print(f"\n🛡️ 回测期末仍在持仓中的标的 (共 {len(active_pos)} 只):")
        for p in active_pos:
            unrealized = ((p['current_price'] - p['buy_price']) / p['buy_price']) * 100 if p['buy_price'] > 0 else 0.0
            print(f"  • {p['code']} {p['name']} | 买入: ￥{p['buy_price']:.2f} ({p['buy_date']}) | 现价: ￥{p['current_price']:.2f} | 浮动盈亏: {unrealized:+.2f}%")
        print()


def run_minute_trace(args):
    """通达信 1 分钟线分时切片复盘"""
    code = args.code.strip()
    date_str = args.date.strip() if args.date else datetime.now().strftime("%Y-%m-%d")

    print(f"\n⚡ 正在调取通达信 1 分钟线重构 【{code}】 于 {date_str} 的日内分时波形...")
    engine = ScalpBacktestEngine()
    data = engine.trace_minute_execution(code, date_str)

    if "error" in data:
        print(f"❌ {data['error']}")
        return

    print("\n" + "=" * 65)
    print(f"📈 【{data['code']}】日内分时分秒量化切片复盘报告 ({data['date']})")
    print("=" * 65)
    print(f"  开盘价: ￥{data['open']:.2f} | 收盘价: ￥{data['close']:.2f} | 日内涨跌: {data['day_return']:+.2f}%")
    print(f"  最高价: ￥{data['high']:.2f} | 最低价: ￥{data['low']:.2f} | 最大拉升空间: +{data['max_pump']:.2f}%")
    print(f"  总 1 分钟 K 线根数: {data['total_1min_bars']} 根")
    print("=" * 65)

    print("\n⏰ 关键交易时点分时量价快照 (VWAP 均线对照):")
    print(f"{'时点':<6} | {'现价':<7} | {'VWAP分时均价':<12} | {'分时位置':<10} | {'1分钟量'}")
    print("-" * 55)
    for m in data.get("milestones", []):
        p = m["price"]
        v = m["vwap"]
        pos_str = "高于分时线" if p >= v else "低于分时线"
        print(f"{m['time']:<6} | {p:<7.2f} | {v:<12.2f} | {pos_str:<10} | {m['volume']:,.0f}")
    print("-" * 55 + "\n")


def main():
    parser = argparse.ArgumentParser(description="短线决策台日内与波段回测控制台 (Scalp Backtest CLI)")
    subparsers = parser.add_subparsers(dest="subcommand", help="子命令")

    # 1. 运行快照回测
    replay_parser = subparsers.add_parser("replay", help="重放真实早盘推送快照并执行实盘仿真回测")
    replay_parser.add_argument("--capital", "-c", type=float, default=100000.0, help="初始本金 (默认: 100,000)")
    replay_parser.add_argument("--positions", "-p", type=int, default=4, help="最大持仓股票数 (默认: 4)")
    replay_parser.add_argument("--stop-loss", type=float, default=-4.0, help="硬止损百分比 (默认: -4.0)")
    replay_parser.add_argument("--tp", type=float, default=10.0, help="阶梯止盈百分比 (默认: 10.0)")
    replay_parser.add_argument("--trailing-tp", type=float, default=8.0, help="冲高回落动态止盈线 (默认: 8.0)")
    replay_parser.add_argument("--hold-days", type=int, default=5, help="最大持股天数 (默认: 5)")
    replay_parser.add_argument("--start", type=str, default=None, help="开始日期 (YYYY-MM-DD)")
    replay_parser.add_argument("--end", type=str, default=None, help="结束日期 (YYYY-MM-DD)")
    replay_parser.add_argument("--strategy-filter", type=str, default=None, help="仅回测指定战法(逗号分隔，如 '二波,弱转强')")
    replay_parser.add_argument("--stage-filter", type=str, default=None, help="仅回测指定时段(逗号分隔，如 'settle,confirm')")
    replay_parser.add_argument("--dragon", action="store_true", default=False, help="启用龙头平台新规则(驼峰曲线、破今开-5%弃龙斩仓、退潮刹车)")

    # 2. 分时分钟级追踪
    trace_parser = subparsers.add_parser("trace", help="使用通达信1分钟K线对指定标的进行日内分时波形复盘")
    trace_parser.add_argument("--code", required=True, type=str, help="股票代码 (如 002437)")
    trace_parser.add_argument("--date", type=str, default=None, help="复盘日期 (默认今天)")

    args = parser.parse_args()

    if args.subcommand == "replay":
        run_replay(args)
    elif args.subcommand == "trace":
        run_minute_trace(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
