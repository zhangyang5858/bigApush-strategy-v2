"""
推送脚本时段调度与模拟账户买入测试
"""
import pytest
from datetime import datetime
from scalp_push import run_scalp_push
from scalp_account_manager import execute_stage_buys, load_account


def test_scalp_push_afternoon_demo(tmp_path, monkeypatch):
    """测试下午 14:30 尾盘阶段在 demo 模式下能够顺利执行（使用临时目录隔离数据）"""
    import scalp_account_manager
    import scalp_daily_review
    import scalp_trade_db
    from utils.feishu_notifier import FeishuNotifier

    monkeypatch.setattr(scalp_account_manager, "ACCOUNT_FILE", str(tmp_path / "scalp_account.json"))
    monkeypatch.setattr(scalp_daily_review, "REVIEW_CACHE_DIR", str(tmp_path / "scalp_records"))
    monkeypatch.setattr(scalp_trade_db, "DB_PATH", str(tmp_path / "scalp_trading.db"))
    monkeypatch.setattr(FeishuNotifier, "send_card", lambda self, card: True)

    from scalp_push import STAGE_TIME_WINDOWS, STAGE_NAME_MAP
    assert "afternoon" in STAGE_NAME_MAP
    assert "afternoon" in STAGE_TIME_WINDOWS
    assert STAGE_TIME_WINDOWS["afternoon"] == ("14:15", "14:55")

    success = run_scalp_push(stage="afternoon", is_demo=True, force=True)
    assert success is True


def test_scalp_account_manager_afternoon_allocation():
    """测试 14:30 尾盘模拟账户买入配额与选股"""
    account = {
        "total_assets": 100000.0,
        "cash": 100000.0,
        "positions": [],
        "closed_trades": []
    }
    pushed_stocks = [
        {
            "code": "000001",
            "name": "平安银行",
            "price": 10.50,
            "open_price": 10.30,
            "change": 1.9,
            "score": 85.0,
            "strategy_id": "S3",
            "strategy_tag": "🛡️ S3 涨停回调 (低吸到位)",
            "support_price": 10.00,
            "stop_loss": 9.80,
            "is_zt": False
        },
        {
            "code": "000002",
            "name": "万科A",
            "price": 8.50,
            "open_price": 8.40,
            "change": 1.2,
            "score": 82.0,
            "strategy_id": "S4",
            "strategy_tag": "⚡ S4 量价突破 (回踩确认)",
            "support_price": 8.30,
            "stop_loss": 8.10,
            "is_zt": False
        }
    ]

    buys = execute_stage_buys(
        account=account,
        pushed_stocks=pushed_stocks,
        stage="afternoon",
        today_str="2026-09-17",
        regime="中性"
    )
    assert len(buys) == 2
    assert account["cash"] < 100000.0
    assert len(account["positions"]) == 2
    assert buys[0]["code"] == "000001"
    assert buys[1]["code"] == "000002"


def test_oct9_replay_selects_winner_and_blocks_pullback_loser():
    """
    复盘 2026-10-09 真实场景测试：
    1. 09:26 竞价阶段：即便旧仓有 2 只标记了 pre_market_stop=True，也应预释放名额买入排名第1的 002805 丰元股份
    2. 09:31:30 秒板阶段：防守模式下 72.7 分且强势拉升的 002805 丰元股份不应被 86 分虚高门槛拦截
    3. 09:38 承接阶段：冲高至 22.80 后回落到 22.25 (回撤 > 1.8%) 的 603906 龙蟠科技应被冲高回落过滤器拦截
    """
    # 场景 A: 09:26 竞价阶段，2只旧仓均已标记 pre_market_stop=True，现金充足
    account_auction = {
        "total_assets": 90346.06,
        "cash": 43961.06,
        "positions": [
            {"code": "002361", "name": "神剑股份", "buy_date": "2026-10-08", "buy_price": 9.95, "shares": 2300, "pre_market_stop": True},
            {"code": "601091", "name": "沈鼓集团", "buy_date": "2026-10-08", "buy_price": 24.34, "shares": 1000, "pre_market_stop": True},
        ],
        "closed_trades": []
    }
    auction_pushed = [
        {"code": "002805", "name": "丰元股份", "push_price": 18.56, "open_price": 18.56, "pre_close": 17.67, "score": 64.5, "strategy_tag": "S1 竞价首板 (竞价入选)", "is_zt": False},
        {"code": "603906", "name": "龙蟠科技", "push_price": 21.60, "open_price": 21.60, "pre_close": 20.94, "score": 61.3, "strategy_tag": "S1 竞价首板 (竞价入选)", "is_zt": False},
    ]
    buys_auction = execute_stage_buys(
        account=account_auction,
        pushed_stocks=auction_pushed,
        stage="auction",
        today_str="2026-10-09",
        regime="防守"
    )
    assert len(buys_auction) == 1
    assert buys_auction[0]["code"] == "002805"

    # 场景 B: 09:31:30 秒板阶段，旧仓已清仓，防守模式下买入 72.7 分强势拉升的 002805 丰元股份
    account_instant = {
        "total_assets": 90499.66,
        "cash": 90499.66,
        "positions": [],
        "closed_trades": []
    }
    instant_pushed = [
        {"code": "002805", "name": "丰元股份", "push_price": 19.23, "open_price": 18.56, "pre_close": 17.67, "high": 19.30, "score": 72.7, "strategy_tag": "S1 竞价首板 (竞价入选)", "is_zt": False},
        {"code": "603906", "name": "龙蟠科技", "push_price": 22.34, "open_price": 21.60, "pre_close": 20.94, "high": 22.80, "score": 70.1, "strategy_tag": "S1 竞价首板 (竞价入选)", "is_zt": False},
    ]
    buys_instant = execute_stage_buys(
        account=account_instant,
        pushed_stocks=instant_pushed,
        stage="instant",
        today_str="2026-10-09",
        regime="防守"
    )
    assert len(buys_instant) == 1
    assert buys_instant[0]["code"] == "002805"

    # 场景 C: 09:38 承接阶段，603906 龙蟠科技从高点 22.80 回落至 22.25 (回撤 2.41% > 1.8%)，应被拦截不买
    account_confirm = {
        "total_assets": 90499.66,
        "cash": 65000.0,
        "positions": [],
        "closed_trades": []
    }
    confirm_pushed = [
        {"code": "603906", "name": "龙蟠科技", "push_price": 22.25, "open_price": 21.60, "pre_close": 20.94, "high": 22.80, "score": 72.0, "strategy_tag": "S1 竞价首板 (开盘确认)", "is_zt": False}
    ]
    buys_confirm = execute_stage_buys(
        account=account_confirm,
        pushed_stocks=confirm_pushed,
        stage="confirm",
        today_str="2026-10-09",
        regime="防守"
    )
    assert len(buys_confirm) == 0


def test_same_day_sold_stock_cooldown_and_holiday_check():
    """验证同日卖出标的禁止回买，以及国庆节假日非交易日识别"""
    from utils.trade_date_utils import is_trading_day

    # 1. 同日已卖出的股票 (如 300585 奥联电子) 禁止当天再次买回
    account = {
        "total_assets": 95000.0,
        "cash": 95000.0,
        "positions": [],
        "closed_trades": [
            {"code": "300585", "name": "奥联电子", "buy_date": "2026-09-24", "sell_date": "2026-09-25", "realized_profit": -315.59}
        ]
    }
    pushed = [
        {"code": "300585", "name": "奥联电子", "push_price": 16.86, "open_price": 16.50, "high": 16.90, "score": 78.0, "is_zt": False}
    ]
    buys = execute_stage_buys(account, pushed, stage="confirm", today_str="2026-09-25", regime="中性")
    assert len(buys) == 0

    # 2. 国庆法定节假日 (10-01 ~ 10-07) 应识别为非交易日
    assert is_trading_day("2026-10-01") is False
    assert is_trading_day("2026-10-05") is False
    assert is_trading_day("2026-10-07") is False
    assert is_trading_day("2026-10-08") is True
    assert is_trading_day("2026-10-09") is True

