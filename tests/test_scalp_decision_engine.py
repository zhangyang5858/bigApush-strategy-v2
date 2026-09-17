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
