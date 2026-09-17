"""
每日收盘短线复盘飞书推送脚本 (Daily Review Push Entrypoint)
用法:
  python scalp_review_push.py         # 15:30 自动收盘复盘推送
  python scalp_review_push.py --demo  # 测试复盘推送
"""
import os
import sys
import argparse
from datetime import datetime
from utils.feishu_notifier import FeishuNotifier
from scalp_daily_review import evaluate_daily_scalp, build_daily_review_card
from utils.trade_date_utils import is_trading_day

DEFAULT_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/186dde11-c61e-47bf-aa54-18514c9dbecb"


def get_feishu_webhook():
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


def run_daily_review_push(is_demo=False, force=False):
    today_str = datetime.now().strftime("%Y-%m-%d")
    print(f"🚀 开始执行短线决策每日收盘复盘推送 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if not is_demo and not force:
        if not is_trading_day(today_str):
            print(f"☕ 今天 {today_str} 不是交易日，跳过收盘复盘。")
            return True
        cur_hm = datetime.now().strftime("%H:%M")
        if cur_hm < "15:00":
            print(f"⏰ [时间窗口拦截] 当前时间 {cur_hm} 尚未收盘 (15:00后)，跳过收盘复盘以防获取未收盘行情。")
            return True

    print("  📊 正在拉取全天推送记录与收盘数据执行胜率评估...")
    review_data = evaluate_daily_scalp(date_str=today_str, is_demo=is_demo)
    if not review_data:
        print("  ⚠️ 今日无短线推送记录，跳过复盘。")
        return True

    card_json = build_daily_review_card(review_data)

    webhook_url = get_feishu_webhook()
    notifier = FeishuNotifier(webhook_url)

    print("  📤 正在向飞书推送每日复盘卡片...")
    success = notifier.send_card(card_json)

    # 同步日结数据到 SQLite 数据库并导出多 Sheet Excel 报表
    try:
        from scalp_trade_db import record_daily_settlement, export_trades_to_excel
        if review_data.get("settle_info"):
            record_daily_settlement(review_data["settle_info"])
        excel_file = export_trades_to_excel()
        print(f"  📊 收盘战报 Excel 报表已生成: {excel_file}")
    except Exception as e:
        print(f"  ⚠️ 同步数据库与导出 Excel 异常: {e}")

    if success:
        print("  🎉 每日收盘复盘卡片推送成功！")
        return True
    else:
        print("  ⚠️ 卡片发送失败，尝试发送降级文本...")
        m = review_data["metrics"]
        text = f"📊 短线决策收盘复盘 ({today_str})\n胜率: {m['win_rate']} | 封板率: {m['zt_rate']} ({m['zt_count']}只涨停) | 日内浮盈: {m['avg_intraday_profit']}"
        return notifier.send_text(text)


def main():
    parser = argparse.ArgumentParser(description="短线决策每日收盘复盘推送脚本")
    parser.add_argument("--demo", action="store_true", help="使用演示模拟数据运行（非交易日测试）")
    parser.add_argument("--force", action="store_true", help="忽略交易日判断强制执行")

    args = parser.parse_args()
    success = run_daily_review_push(is_demo=args.demo, force=args.force)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
