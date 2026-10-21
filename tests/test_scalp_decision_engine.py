"""
决策引擎四策略整合与 Line 67 打分测试
"""
import pytest
from scalp_decision_engine import (
    analyze_scalp_market_v2,
    get_stage_pushed_stocks,
    build_scalp_feishu_card_v2,
    calc_line67_auction_score,
    calc_line67_confirm_score,
)


def test_line67_scoring_formulas():
    """验证 Line 67 打分公式在边界和典型场景下的取值"""
    # 竞价：金额1000万，高开3.5%(落在黄金区间)，量比2.0，板块中等，市值50亿，进攻模式
    s_amt = calc_line67_auction_score(
        amount=10_000_000,
        auction_change=3.5,
        vol_ratio=2.0,
        sector_score=80,
        sector_breadth=0.6,
        float_cap=50.0,
        regime="进攻"
    )
    assert 60 <= s_amt <= 100

    # 承接：守住开盘价，冲拔+1.5%，成交额6000万，进攻模式
    s_conf = calc_line67_confirm_score(
        hold_diff=0.01,
        trend_diff=1.5,
        amount=60_000_000,
        sector_score=80,
        regime="进攻"
    )
    assert 70 <= s_conf <= 100


def test_analyze_scalp_market_v2_with_four_strategies():
    """测试 analyze_scalp_market_v2 输出包含四策略标签与 Line 67 得分"""
    res = analyze_scalp_market_v2(stage="auction", is_demo=True)
    assert "stocks" in res
    assert len(res["stocks"]) > 0

    # 验证至少有标的输出 score，且包含 strategy_id 属性
    for s in res["stocks"][:5]:
        assert "score" in s
        assert "grade" in s
        assert "strategy_id" in s
        assert "support_price" in s


def test_get_stage_pushed_stocks_categorized():
    """测试 get_stage_pushed_stocks 按策略分栏与下午阶段"""
    res = analyze_scalp_market_v2(stage="auction", is_demo=True)
    pushed = get_stage_pushed_stocks(res, stage="auction")
    assert len(pushed) > 0

    # 验证 afternoon 阶段提取
    res_pm = analyze_scalp_market_v2(stage="afternoon", is_demo=True)
    pushed_pm = get_stage_pushed_stocks(res_pm, stage="afternoon")
    assert len(pushed_pm) > 0


def test_build_scalp_feishu_card_v2_sections():
    """测试飞书卡片渲染包含策略分栏与风控失效线"""
    res = analyze_scalp_market_v2(stage="confirm", is_demo=True)
    pushed = get_stage_pushed_stocks(res, stage="confirm")
    card = build_scalp_feishu_card_v2(res, stage="confirm", pushed_stocks=pushed)

    assert "header" in card
    assert "elements" in card
    card_str = str(card)
    # 验证卡片中包含 S1 或 S2 等策略标识
    assert "S1" in card_str or "S2" in card_str or "短线" in card_str


def test_weak_to_strong_auction_factor():
    """测试竞价爆量弱转强判定"""
    from strategy_four_pillars import detect_s1_auction_first_board

    stock = {
        "code": "000001",
        "name": "测试龙头",
        "open_price": 10.40,
        "pre_close": 10.00,
        "auction_amount": 25_000_000,
        "vr": 2.5,
        "float_cap": 30.0
    }
    sec = {"name": "算力", "breadth": 0.6, "avg_pct": 1.2}
    yesterday = {"is_limit_up": False, "amount": 200_000_000}

    sig = detect_s1_auction_first_board(stock=stock, yesterday=yesterday, sector_info=sec)
    assert sig is not None
    assert sig["is_weak_to_strong"] is True
    assert "弱转强" in sig["strategy_variant"]


def test_sector_exclusivity():
    """测试同板块先锋身位排他，屏蔽后排跟风标的"""
    fake_res = {
        "stocks": [
            {"code": "600001", "name": "龙头A", "sector": "半导体", "score": 92, "qualified": True, "is_zt": False, "change": 3.5, "s1_signal": {"status": "CONFIRMED"}},
            {"code": "600002", "name": "跟风B", "sector": "半导体", "score": 85, "qualified": True, "is_zt": False, "change": 2.5, "s1_signal": {"status": "CONFIRMED"}},
            {"code": "000003", "name": "龙头C", "sector": "低空经济", "score": 88, "qualified": True, "is_zt": False, "change": 4.0, "s2_signal": {"status": "CONFIRMED"}},
        ]
    }
    pushed = get_stage_pushed_stocks(fake_res, stage="confirm")
    codes = [s["code"] for s in pushed]
    assert "600001" in codes
    assert "600002" not in codes  # 跟风B同板块被排他剔除
    assert "000003" in codes


def test_morning_limit_up_lock_in_account_manager():
    """测试次日一字或秒板锁仓，严禁在早盘过早卖出"""
    from scalp_account_manager import check_and_execute_sells

    account = {
        "cash": 20000.0,
        "positions": [
            {
                "code": "600001",
                "name": "连板龙",
                "buy_date": "2026-10-19",
                "buy_price": 10.0,
                "shares": 1000,
                "cost_amount": 10000.0,
                "stop_loss": 9.75
            }
        ],
        "closed_trades": []
    }
    # 模拟 09:31 开盘秒板至 +9.2%（未正式上报zt_set或封板瞬间）
    live_map = {
        "600001": {"f2": 10.92, "f3": 9.2, "f15": 10.92, "f16": 10.5, "f17": 10.5}
    }
    sells = check_and_execute_sells(account, live_map, zt_set=set(), stage="instant", today_str="2026-10-20")

    # 验证未被卖出，而是锁仓
    assert len(sells) == 1
    assert sells[0]["is_executed"] is False
    assert "锁仓" in sells[0]["action"]
    assert len(account["positions"]) == 1

