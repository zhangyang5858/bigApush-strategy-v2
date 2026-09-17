"""
端到端全链路闭环集成测试：
验证从 09:26 竞价、09:31 秒板、09:38 确认、10:00 定势、14:30 尾盘、到 15:30 收盘复盘与 Excel 战报导出的全流程。
"""
import os
import pytest
from scalp_push import run_scalp_push
from scalp_review_push import run_daily_review_push
from scalp_trade_db import (
    get_db_connection,
    get_four_pillars_attribution_df,
    get_observation_pool_df,
    export_trades_to_excel,
    EXCEL_REPORT_PATH
)
from strategy_four_pillars import load_observation_pools


def test_e2e_full_day_four_strategies_pipeline():
    """测试完整交易日5时段推送 + 收盘复盘全流程"""
    stages = ["auction", "instant", "confirm", "settle", "afternoon"]

    # 1. 模拟全天5时段推送
    for stg in stages:
        success = run_scalp_push(stage=stg, is_demo=True, force=True)
        assert success is True, f"时段 {stg} 执行失败"

    # 2. 模拟 15:30 收盘复盘
    review_success = run_daily_review_push(is_demo=True, force=True)
    assert review_success is True, "收盘复盘执行失败"

    # 3. 验证次日观察池文件已生成
    assert os.path.exists("data/observation_pools.json")
    pools = load_observation_pools("data/observation_pools.json")
    assert "s3_pullback_pool" in pools
    assert "s4_breakout_pool" in pools
    assert len(pools["s3_pullback_pool"]) > 0
    assert len(pools["s4_breakout_pool"]) > 0

    # 4. 验证数据库中推送信号包含 strategy_id
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT strategy_id FROM push_signals;")
        sig_ids = [r[0] for r in cursor.fetchall() if r[0]]
        # 至少有部分 S1/S2/S3/S4
        assert len(sig_ids) > 0

        # 验证观察池数据库表中有记录
        cursor.execute("SELECT count(*) as cnt FROM strategy_observation_pool;")
        assert cursor.fetchone()["cnt"] > 0

    # 5. 验证战法归因 DataFrame
    df_attr = get_four_pillars_attribution_df()
    assert len(df_attr) == 4
    strategy_ids = set(df_attr["战法编号"].tolist())
    assert strategy_ids == {"S1", "S2", "S3", "S4"}

    # 6. 验证 Excel 报表导出正常
    assert os.path.exists(EXCEL_REPORT_PATH)
