"""
四策略 (S1~S4) 独立规则与状态机单元测试
"""
import pytest
from strategy_four_pillars import (
    detect_s1_auction_first_board,
    detect_s2_mainline_leader,
    detect_s3_limitup_pullback,
    detect_s4_breakout_retest,
    build_observation_pools,
)


def test_s1_auction_first_board_watching():
    """测试 S1 09:25 竞价入选 (WATCHING)"""
    stock = {
        "code": "000001",
        "name": "平安银行",
        "price": 10.30,
        "open_price": 10.30,
        "pre_close": 10.00,
        "auction_change": 3.0,
        "amount": 6_000_000,
        "vr": 1.8,
        "float_cap": 50.0,
    }
    yesterday = {"is_limit_up": False}
    sec_info = {"name": "银行", "score": 85, "avg_pct": 2.5, "breadth": 0.65, "flow_rank": 2}

    res = detect_s1_auction_first_board(stock, confirm_stock=None, yesterday=yesterday, sector_info=sec_info)
    assert res is not None
    assert res["strategy_id"] == "S1"
    assert res["status"] == "WATCHING"
    assert "竞价金额600万" in " ".join(res["reasons"])
    assert res["invalid_reason"] is None


def test_s1_auction_first_board_confirmed():
    """测试 S1 09:32 开盘承接确认 (CONFIRMED)"""
    early_stock = {
        "code": "000001",
        "name": "平安银行",
        "price": 10.30,
        "open_price": 10.30,
        "pre_close": 10.00,
        "auction_change": 3.0,
        "amount": 6_000_000,
        "vr": 1.8,
        "float_cap": 50.0,
    }
    confirm_stock = dict(early_stock, price=10.38, amount=15_000_000)
    yesterday = {"is_limit_up": False}
    sec_info = {"name": "银行", "score": 85, "avg_pct": 2.5, "breadth": 0.65, "flow_rank": 2}

    res = detect_s1_auction_first_board(early_stock, confirm_stock=confirm_stock, yesterday=yesterday, sector_info=sec_info)
    assert res is not None
    assert res["strategy_id"] == "S1"
    assert res["status"] == "CONFIRMED"
    assert res["support_price"] == 10.30


def test_s1_auction_invalidated_by_hard_veto():
    """测试 S1 跌破开盘价2%或ST硬性失效 (INVALIDATED)"""
    early_stock = {
        "code": "000001",
        "name": "平安银行",
        "price": 10.30,
        "open_price": 10.30,
        "pre_close": 10.00,
        "auction_change": 3.0,
        "amount": 6_000_000,
        "vr": 1.8,
        "float_cap": 50.0,
    }
    # 现价跌破开盘价超过2% (10.05 < 10.30 * 0.98 = 10.094)
    broken_stock = dict(early_stock, price=10.05, amount=12_000_000)
    res = detect_s1_auction_first_board(early_stock, confirm_stock=broken_stock, yesterday={"is_limit_up": False}, sector_info={"breadth": 0.6, "avg_pct": 2.0})
    assert res is not None
    assert res["status"] == "INVALIDATED"
    assert "跌破" in res["invalid_reason"]


def test_s2_mainline_leader():
    """测试 S2 主线龙头主升候选与确认"""
    stock = {
        "code": "603986",
        "name": "兆易创新",
        "price": 105.0,
        "open_price": 102.0,
        "change": 5.5,
        "amount": 80_000_000,
        "vwap_diff": 1.5,
        "float_cap": 60.0,
    }
    sec_rank = {
        "name": "芯片半导体",
        "flow_rank": 1,
        "avg_pct": 3.8,
        "breadth": 0.85,
        "net_flow": 8e8,
    }

    # 早盘候选
    res_watching = detect_s2_mainline_leader(stock, sector_rank_info=sec_rank, stage="auction")
    assert res_watching is not None
    assert res_watching["strategy_id"] == "S2"
    assert res_watching["status"] == "WATCHING"

    # 定势确认
    res_confirmed = detect_s2_mainline_leader(stock, sector_rank_info=sec_rank, stage="settle")
    assert res_confirmed is not None
    assert res_confirmed["strategy_id"] == "S2"
    assert res_confirmed["status"] == "CONFIRMED"


def test_s3_limitup_pullback_variants():
    """测试 S3 涨停回调两变体：回调低吸 vs 洗盘再启动"""
    s3_item = {
        "code": "002230",
        "name": "科大讯飞",
        "first_board_date": "2026-09-10",
        "support_low": 40.00,
        "midpoint": 42.00,
        "first_vol": 100_000,
        "adjust_days": 3,
    }

    # 变体 A: 回调到实体中点~支撑低点止跌
    stock_dip = {
        "code": "002230",
        "name": "科大讯飞",
        "price": 41.50,
        "open_price": 41.20,
        "low": 40.80,
        "change": 0.8,
        "float_cap": 80.0,
    }
    res_a = detect_s3_limitup_pullback(stock_dip, s3_item, stage="afternoon")
    assert res_a is not None
    assert res_a["strategy_id"] == "S3"
    assert res_a["status"] == "CONFIRMED"
    assert res_a["strategy_variant"] == "回调低吸"
    assert res_a["support_price"] == 40.00

    # 变体 B: 调整后放量再启动突破昨日高点
    stock_launch = {
        "code": "002230",
        "name": "科大讯飞",
        "price": 44.50,
        "open_price": 42.50,
        "change": 4.8,
        "float_cap": 80.0,
    }
    res_b = detect_s3_limitup_pullback(stock_launch, s3_item, stage="confirm")
    assert res_b is not None
    assert res_b["strategy_id"] == "S3"
    assert res_b["status"] == "CONFIRMED"
    assert res_b["strategy_variant"] == "洗盘再启动"

    # 失效测试：跌破首板低点
    stock_broken = dict(stock_dip, price=39.50)
    res_broken = detect_s3_limitup_pullback(stock_broken, s3_item, stage="afternoon")
    assert res_broken is not None
    assert res_broken["status"] == "INVALIDATED"


def test_s4_breakout_retest():
    """测试 S4 量价突破回踩与直接突破"""
    s4_item = {
        "code": "300750",
        "name": "宁德时代",
        "breakout_date": "2026-09-15",
        "ceiling": 200.00,
        "avg_vol": 50_000,
        "breakout_vol": 90_000,
    }

    # 回踩确认：日内曾触及平台顶 200 附近，现价守在 201 站稳
    stock_retest = {
        "code": "300750",
        "name": "宁德时代",
        "price": 202.50,
        "open_price": 201.00,
        "low": 200.20,
        "change": 1.2,
        "float_cap": 120.0,
    }
    res_retest = detect_s4_breakout_retest(stock_retest, s4_item, stage="afternoon")
    assert res_retest is not None
    assert res_retest["strategy_id"] == "S4"
    assert res_retest["status"] == "CONFIRMED"
    assert res_retest["strategy_variant"] == "回踩确认"
    assert res_retest["support_price"] == 200.00

    # 失效测试：跌回平台深处
    stock_broken = dict(stock_retest, price=195.00)
    res_broken = detect_s4_breakout_retest(stock_broken, s4_item, stage="afternoon")
    assert res_broken is not None
    assert res_broken["status"] == "INVALIDATED"


def test_build_observation_pools():
    """测试基于日线生成 S3 和 S4 观察池"""
    daily_bars_map = {
        "000001": [
            {"date": "2026-09-10", "open": 10.0, "high": 11.0, "low": 9.9, "close": 11.0, "volume": 100_000, "is_limit_up": True},
            {"date": "2026-09-11", "open": 11.0, "high": 11.2, "low": 10.5, "close": 10.7, "volume": 60_000, "is_limit_up": False},
            {"date": "2026-09-12", "open": 10.7, "high": 10.8, "low": 10.2, "close": 10.4, "volume": 50_000, "is_limit_up": False},
            {"date": "2026-09-13", "open": 10.4, "high": 10.6, "low": 10.1, "close": 10.3, "volume": 45_000, "is_limit_up": False},
        ]
    }
    pools = build_observation_pools(daily_bars_map, target_date_str="2026-09-14")
    assert "s3_pullback_pool" in pools
    assert "s4_breakout_pool" in pools
    assert len(pools["s3_pullback_pool"]) == 1
    item = pools["s3_pullback_pool"][0]
    assert item["code"] == "000001"
    assert item["support_low"] == 9.9
    assert item["midpoint"] == 10.5
