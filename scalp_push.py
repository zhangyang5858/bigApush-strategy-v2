"""
短线决策台定时推送入口脚本 (Scalp Push Entrypoint)
融合 10 万元实盘级模拟账户与 T+1 交易决策：
- 09:26 竞价初筛 (`stage="auction"`): 竞价抢筹选股 + 昨日持仓竞价预警
- 09:35 开盘确认 (`stage="confirm"`): 强攻/低吸选股 + 持仓止盈止损执行与资金释放 + 模拟分仓买入
- 09:55 早盘定势 (`stage="settle"`): 主线封板/二波选股 + 调仓处置 + 模拟分仓买入
"""
import os
import sys
import argparse
from datetime import datetime
from utils.feishu_notifier import FeishuNotifier
from scalp_decision_engine import (
    analyze_scalp_market_v2, build_scalp_feishu_card_v2, get_stage_pushed_stocks
)
from scalp_account_manager import (
    load_account, save_account, check_and_execute_sells, execute_stage_buys
)
from utils.trade_date_utils import is_trading_day

DEFAULT_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/ef0d8206-3c26-4fa0-9401-138f997db920"


def get_feishu_webhook():
    """获取飞书 Webhook 地址"""
    webhook = os.environ.get("FEISHU_WEBHOOK")
    if webhook:
        return webhook

    try:
        import yaml
        config_path = "config/config.yaml"
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            webhook = cfg.get("feishu", {}).get("webhook_url")
            if webhook:
                return webhook
    except Exception:
        pass

    return DEFAULT_WEBHOOK


def run_scalp_push(stage="auction", is_demo=False, force=False):
    """
    执行短线决策台 V2 推送与 10万模拟账户联动
    stage: 'auction' (09:26) | 'confirm' (09:35) | 'settle' (09:55)
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    stage_name_map = {
        "auction": "早盘竞价初筛 (09:26)",
        "confirm": "开盘承接确认 (09:35)",
        "settle": "早盘定势封板与二波 (09:55)"
    }
    stage_label = stage_name_map.get(stage, stage)
    print(f"🚀 开始执行短线决策台 V2 推送 [{stage_label}] - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 交易日校验 (演示模式或强制模式跳过)
    if not is_demo and not force:
        if not is_trading_day(today_str):
            print(f"☕ 今天 {today_str} 不是交易日，短线决策台跳过推送。")
            return True

    webhook_url = get_feishu_webhook()
    notifier = FeishuNotifier(webhook_url)

    print(f"  📊 正在运行 V2 量化多因子与多战法计算引擎 (阶段: {stage})...")
    res = analyze_scalp_market_v2(stage=stage, is_demo=is_demo)

    qualified_cnt = res.get("summary", {}).get("qualified_count", 0)
    total_cnt = res.get("summary", {}).get("total_count", 0)
    print(f"  ✓ 分析完成: 全市场扫描 {total_cnt} 只，合格优选 {qualified_cnt} 只，市场处于【{res.get('regime')}】模式")

    # 提取真正上榜推荐的标的
    pushed_stocks = get_stage_pushed_stocks(res, stage=stage)

    # ── 1. 模拟账户操作：处理昨日持仓处置 (T+1 卖出/预警) ──
    account = load_account()
    live_price_map = {str(s["code"]): s for s in res.get("stocks", [])}
    zt_set = {str(s["code"]) for s in res.get("stocks", []) if s.get("is_zt", False)}

    sell_actions = check_and_execute_sells(account, live_price_map, zt_set, stage=stage, today_str=today_str)

    # ── 2. 模拟账户操作：今日推荐新标的模拟分仓买入 ──
    buy_records = execute_stage_buys(account, pushed_stocks, stage=stage, today_str=today_str)

    # 保存账户最新状态
    save_account(account)

    # 保存阶段推送记录以供收盘 15:30 自动复盘
    try:
        from scalp_daily_review import save_stage_push_record
        save_stage_push_record(stage, pushed_stocks, res=res, date_str=today_str)
    except Exception as e:
        print(f"  ⚠️ 保存推送记录异常: {e}")

    # ── 3. 构建飞书交互式卡片 ──
    card_json = build_scalp_feishu_card_v2(
        res,
        stage=stage,
        pushed_stocks=pushed_stocks,
        sell_actions=sell_actions,
        buy_records=buy_records,
        account_data=account
    )

    # 发送推送
    print("  📤 正在向飞书推送卡片...")
    success = notifier.send_card(card_json)
    if success:
        print("  🎉 飞书卡片推送成功！")
        return True
    else:
        print("  ⚠️ 卡片推送失败，尝试降级文本推送...")
        text_lines = [
            f"⚡ 短线决策台 {stage_label} ({today_str})",
            f"市场状态: {res.get('regime')}模式 | 优选标的: {len(pushed_stocks)}只",
            f"模拟账户: 总资产 ￥{account.get('total_assets', 100000.0):,.2f} | 现金 ￥{account.get('cash', 100000.0):,.2f}",
            ""
        ]
        if sell_actions:
            text_lines.append("📦 【持仓处置指引】")
            for sa in sell_actions:
                text_lines.append(f"• {sa['code']} {sa['name']}: {sa['action']} - {sa['reason']}")
            text_lines.append("")

        text_lines.append("🎯 【今日选股推荐】")
        for s in pushed_stocks:
            text_lines.append(f"🟢 {s['code']} {s['name']} (￥{s['price']:.2f} {s['change']:+.2f}%) - {s['grade']}级 {s['score']}分")
            text_lines.append(f"   战法: {s['strategy_tag']} | 买入参考: ￥{s['push_price']:.2f} | 止损: ￥{s['stop_loss']:.2f}")

        return notifier.send_text("\n".join(text_lines))


def main():
    parser = argparse.ArgumentParser(description="短线决策台飞书自动推送脚本")
    parser.add_argument("--stage", choices=["auction", "confirm", "settle"], default="auction",
                        help="推送阶段: auction(09:26 竞价初筛), confirm(09:35 开盘确认), settle(09:55 早盘定势与二波)")
    parser.add_argument("--demo", action="store_true", help="使用演示模拟数据运行（非交易日测试）")
    parser.add_argument("--force", action="store_true", help="忽略交易日判断强制执行")

    args = parser.parse_args()
    success = run_scalp_push(stage=args.stage, is_demo=args.demo, force=args.force)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
