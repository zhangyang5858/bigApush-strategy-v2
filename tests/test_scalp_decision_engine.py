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
    # 验证卡片中包含 S1/S2/S3/S4 等策略标识或风控失效线
    assert any(tag in card_str for tag in ["S1", "S2", "S3", "S4", "风控失效线"])


def test_all_stages_feishu_card_headers_and_tips():
    """测试 4 阶段早盘超短 + 尾盘观察卡片标题与纪律提示符合设计"""
    stages_expected = {
        "auction": ("早盘竞价爆量首板榜 (09:25:30)", "竞价操作提醒"),
        "instant": ("开盘极速秒板突击榜 (09:31)", "极速秒板提醒"),
        "confirm": ("弱转强反包冲板榜 (09:40)", "弱转强反包提醒"),
        "settle": ("换手大龙回封决胜榜 (09:50)", "换手大龙回封提醒"),
        "afternoon": ("尾盘备用观察榜", "尾盘打板提醒"),
    }
    for stg, (title_sub, tip_sub) in stages_expected.items():
        res = analyze_scalp_market_v2(stage=stg, is_demo=True)
        pushed = get_stage_pushed_stocks(res, stage=stg)
        card = build_scalp_feishu_card_v2(res, stage=stg, pushed_stocks=pushed)
        card_title = card["header"]["title"]["content"]
        assert title_sub in card_title, f"Stage {stg} card title mismatch: {card_title}"
        card_str = str(card)
        assert tip_sub in card_str, f"Stage {stg} card tip mismatch: {card_str}"


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


def test_auction_m_score_camel_hump_penalty():
    """测试龙头平台 M 值模型与驼峰曲线：黄金起爆(0~2%) vs 高开出货陷阱(>5.5%)"""
    from strategy_four_pillars import calc_auction_m_score

    # 1. 黄金起爆点：高开+1.5%，成交活跃，板块前排
    gold_stock = {
        "code": "600001",
        "open_price": 10.15,
        "pre_close": 10.00,
        "auction_amount": 18_000_000,
        "vr": 3.2,
        "float_cap": 45.0,
    }
    sec_info = {"flow_rank": 1, "breadth": 0.75, "avg_pct": 2.8}
    m_gold = calc_auction_m_score(gold_stock, sector_info=sec_info)
    assert m_gold["M"] >= 0.60
    assert m_gold["grade"] in ["dragon", "watch"]
    assert m_gold["gap_over"] is False

    # 2. 高开诱多出货陷阱：高开+6.8%，成交额平平
    trap_stock = {
        "code": "600002",
        "open_price": 10.68,
        "pre_close": 10.00,
        "auction_amount": 8_000_000,
        "vr": 1.5,
        "float_cap": 40.0,
    }
    m_trap = calc_auction_m_score(trap_stock, sector_info={"flow_rank": 6})
    assert m_trap["gap_over"] is True
    assert m_trap["grade"] == "out"  # 驼峰惩罚直接淘汰


def test_intraday_q_score_and_e5_abandonment():
    """测试盘中 Q 值评估与 E5 走弱弃龙"""
    from strategy_four_pillars import calc_intraday_q_score

    # 1. 触发追龙：开盘拉升 +2.5%，量比 2.8，均线之上
    strong_stock = {
        "code": "000001",
        "price": 10.45,
        "open_price": 10.20,
        "pre_close": 10.00,
        "change": 4.5,
        "vr": 2.8,
        "vwap_diff": 1.2,
        "high": 10.50,
    }
    q_strong = calc_intraday_q_score(strong_stock)
    assert q_strong["Q"] >= 0.40
    assert q_strong["action"] == "追龙"
    assert "E1 拉升" in q_strong["events"]

    # 2. 触发弃龙：现价砸穿分时均线且较开盘价下跌 -3.5%
    weak_stock = {
        "code": "000002",
        "price": 9.80,
        "open_price": 10.15,
        "pre_close": 10.00,
        "change": -2.0,
        "vr": 1.8,
        "vwap_diff": -1.5,
        "high": 10.25,
    }
    q_weak = calc_intraday_q_score(weak_stock)
    assert q_weak["is_e5"] is True
    assert q_weak["action"] == "弃龙"
    assert "E5 走弱" in q_weak["events"]


def test_break_open_price_strict_stop_loss():
    """测试日内跌破开盘价-5%坚决弃龙清仓"""
    from scalp_account_manager import check_and_execute_sells

    account = {
        "cash": 10000.0,
        "positions": [
            {
                "code": "600001",
                "name": "高开走弱龙",
                "buy_date": "2026-10-18",
                "buy_price": 10.0,
                "shares": 1000,
                "cost_amount": 10000.0,
                "stop_loss": 9.20,
                "open_price": 10.50
            }
        ],
        "closed_trades": []
    }
    # 现价 9.90，较今开 10.50 跌幅达 -5.71%
    live_map = {
        "600001": {"f2": 9.90, "f3": -1.0, "f15": 10.50, "f16": 9.85, "f17": 10.50}
    }
    sells = check_and_execute_sells(account, live_map, zt_set=set(), stage="confirm", today_str="2026-10-19")
    assert len(sells) == 1
    assert sells[0]["is_executed"] is True
    assert "破今开-5%" in sells[0]["action"] or "弃龙" in sells[0]["action"]
    assert len(account["positions"]) == 0


def test_ebb_tide_brake_prevents_new_buys():
    """测试退潮防守期系统强制空仓刹车，禁止开新仓"""
    from scalp_account_manager import execute_stage_buys

    account = {
        "cash": 100000.0,
        "positions": [],
        "closed_trades": []
    }
    mock_pushed = [
        {"code": "600001", "name": "龙头股", "price": 10.0, "push_price": 10.0, "score": 85, "strategy_id": "S1"}
    ]
    buys = execute_stage_buys(account, mock_pushed, stage="instant", regime="退潮防守", today_str="2026-10-20")
    assert len(buys) == 0
    assert len(account["positions"]) == 0




def test_instant_nbdl_snapshot_stays_on_watch_even_with_strong_flow():
    from scalp_account_manager import execute_stage_buys

    stock = {
        "code": "002164", "name": "宁波东力", "price": 22.29, "open_price": 22.16,
        "change": 2.72, "score": 94.7, "qualified": True, "vol_ratio": 2.0,
        "net_flow": 20_000_000, "s1_signal": {"status": "WATCHING"},
    }
    # Even favorable hypothetical flow/volume cannot offset the recorded +0.59% move from the open.
    pushed = get_stage_pushed_stocks({"regime": "进攻", "stocks": [stock]}, "instant")
    assert len(pushed) == 1
    assert pushed[0]["watch_only"] is True
    assert pushed[0]["entry_block_reason"] == "较开盘价涨幅不足1%"
    account = {"cash": 100000, "total_assets": 100000, "positions": [], "closed_trades": []}
    assert not execute_stage_buys(account, pushed, "instant", today_str="2026-11-26", regime="进攻")


def test_confirm_prefers_funded_above_vwap_and_fills_watch_slots_without_vetoes():
    from scalp_account_manager import execute_stage_buys

    template = {"price": 10.18, "open_price": 10, "traded_vwap": 10.12, "vol_ratio": 1.5,
                "net_flow": 5_000_000, "score": 78, "qualified": True, "change": 2.0,
                "s1_signal": {"status": "CONFIRMED"}}
    leader = dict(template, code="600001", sector="贵金属", s2_signal={"status": "CONFIRMED"})
    below_vwap = dict(template, code="600002", sector="油气", traded_vwap=10.19, score=98)
    observed = dict(template, code="600003", sector="能源", s1_signal=None, score=92)
    vetoed = dict(template, code="600004", sector="机器人", hard_veto=True, score=100)
    extra = dict(template, code="600005", sector="软件", net_flow=-1000, score=70)
    pushed = get_stage_pushed_stocks({"regime": "防守", "stocks": [below_vwap, vetoed, observed, leader, extra]}, "confirm")
    assert [s["code"] for s in pushed] == ["600001", "600002", "600003"]
    assert [s["watch_only"] for s in pushed] == [False, True, True]
    account = {"cash": 100000, "total_assets": 100000, "positions": [], "closed_trades": []}
    assert not execute_stage_buys(account, pushed[1:], "confirm", today_str="2026-11-26", regime="防守")
    assert execute_stage_buys(account, pushed, "confirm", today_str="2026-11-26", regime="防守")[0]["code"] == "600001"
