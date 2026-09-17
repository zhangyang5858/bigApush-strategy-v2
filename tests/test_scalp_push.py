"""
推送脚本时段调度与模拟账户买入测试
"""
import pytest
from datetime import datetime
from scalp_push import run_scalp_push
from scalp_account_manager import execute_stage_buys, load_account


def test_scalp_push_afternoon_demo():
    """测试下午 14:30 尾盘阶段在 demo 模式下能够顺利执行"""
    # 强制在 demo 模式下运行 afternoon 阶段
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
