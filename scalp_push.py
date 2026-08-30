"""
短线决策台定时推送入口脚本 (Scalp Push Entrypoint)
用法:
  python scalp_push.py --stage auction  # 09:26 竞价初筛
  python scalp_push.py --stage confirm  # 09:35 开盘确认
  python scalp_push.py --stage auction --demo  # 测试演示推送
"""
import os
import sys
import argparse
from datetime import datetime
from utils.feishu_notifier import FeishuNotifier
from scalp_decision_engine import analyze_scalp_market, build_scalp_feishu_card
from utils.trade_date_utils import is_trading_day

DEFAULT_WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/ef0d8206-3c26-4fa0-9401-138f997db920"


def get_feishu_webhook():
    """获取飞书 Webhook 地址"""
    webhook = os.environ.get("FEISHU_WEBHOOK")
    if webhook:
        return webhook

    # 尝试从本地配置文件读取
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
    执行短线决策台推送
    stage: 'auction' | 'confirm'
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    print(f"🚀 开始执行短线决策台推送 [{stage}] - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 交易日校验 (演示模式或强制模式跳过)
    if not is_demo and not force:
        if not is_trading_day(today_str):
            print(f"☕ 今天 {today_str} 不是交易日，短线决策台跳过推送。")
            return True

    webhook_url = get_feishu_webhook()
    notifier = FeishuNotifier(webhook_url)

    is_confirm = (stage == "confirm")
    print(f"  📊 正在拉取全市场行情并执行打分计算 (阶段: {stage})...")
    res = analyze_scalp_market(is_confirm_stage=is_confirm, is_demo=is_demo)

    qualified_cnt = res.get("summary", {}).get("qualified_count", 0)
    total_cnt = res.get("summary", {}).get("total_count", 0)
    print(f"  ✓ 分析完成: 全市场扫描 {total_cnt} 只，合格优选 {qualified_cnt} 只，市场处于【{res.get('regime')}】模式")

    # 构建飞书交互式卡片
    card_json = build_scalp_feishu_card(res, stage=stage)

    # 发送推送
    print("  📤 正在向飞书推送卡片...")
    success = notifier.send_card(card_json)
    if success:
        print("  🎉 飞书卡片推送成功！")
        return True
    else:
        print("  ⚠️ 卡片推送失败，尝试降级文本推送...")
        text_lines = [
            f"⚡ 短线决策台 {'开盘确认' if is_confirm else '竞价初筛'} ({today_str})",
            f"市场状态: {res.get('regime')}模式 | 合格标的: {qualified_cnt}只",
            ""
        ]
        for s in res.get("stocks", [])[:5]:
            text_lines.append(f"🟢 {s['code']} {s['name']} (￥{s['price']:.2f} {s['change']:+.2f}%) - {s['grade']}级 {s['score']}分")
            if is_confirm:
                text_lines.append(f"   买入区间: {s['open_price']:.2f}~{s['price']:.2f} | 止损: {s['stop_loss']:.2f}")
            else:
                text_lines.append(f"   竞价开盘: {s['open_price']:.2f} | 成交: {s['amount']}")
        return notifier.send_text("\n".join(text_lines))


def main():
    parser = argparse.ArgumentParser(description="短线决策台飞书自动推送脚本")
    parser.add_argument("--stage", choices=["auction", "confirm"], default="auction",
                        help="推送阶段: auction(09:26 竞价初筛), confirm(09:35 开盘确认)")
    parser.add_argument("--demo", action="store_true", help="使用演示模拟数据运行（非交易日测试）")
    parser.add_argument("--force", action="store_true", help="忽略交易日判断强制执行")

    args = parser.parse_args()
    success = run_scalp_push(stage=args.stage, is_demo=args.demo, force=args.force)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
