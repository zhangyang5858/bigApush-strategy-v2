"""
测试 SQLite 数据库扩展、四柱战法归因与多 Sheet Excel 报表导出
"""
import os
import sqlite3
import pytest
import pandas as pd
from scalp_trade_db import (
    init_db,
    record_push_signals,
    record_closed_trade,
    sync_observation_pools_to_db,
    get_four_pillars_attribution_df,
    get_observation_pool_df,
    export_trades_to_excel,
    get_db_connection
)


def test_init_db_and_schema_extension():
    """测试数据库初始化、四柱战法新增字段与观察池表创建"""
    init_db()
    with get_db_connection() as conn:
        cursor = conn.cursor()

        # 检查 push_signals 字段
        cursor.execute("PRAGMA table_info(push_signals);")
        ps_cols = {col["name"] for col in cursor.fetchall()}
        assert "strategy_id" in ps_cols
        assert "signal_stage" in ps_cols
        assert "strategy_variant" in ps_cols
        assert "support_price" in ps_cols
        assert "invalid_reason" in ps_cols

        # 检查 strategy_observation_pool 表
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='strategy_observation_pool';")
        assert cursor.fetchone() is not None


def test_record_push_signals_with_strategy_id():
    """测试记录各战法推送信号快照"""
    sample_stocks = [
        {
            "code": "002478",
            "name": "常宝股份",
            "price": 7.30,
            "open_price": 7.20,
            "pre_close": 7.00,
            "change": 4.29,
            "net_flow": 15000000.0,
            "flow_ratio": 12.5,
            "sector": "机械制造",
            "score": 90.0,
            "grade": "S",
            "strategy_id": "S1",
            "strategy_tag": "🔥 S1 竞价首板 (开盘确认)",
            "signal_stage": "CONFIRMED",
            "strategy_variant": "开盘秒板",
            "support_price": 7.20,
            "is_zt": True,
            "is_leader": True
        },
        {
            "code": "603967",
            "name": "中创物流",
            "price": 12.10,
            "open_price": 11.80,
            "pre_close": 11.50,
            "change": 5.22,
            "net_flow": 25000000.0,
            "flow_ratio": 15.0,
            "sector": "跨境物流",
            "score": 88.0,
            "grade": "A",
            "strategy_id": "S4",
            "strategy_tag": "⚡ S4 量价突破 (回踩确认)",
            "signal_stage": "CONFIRMED",
            "strategy_variant": "回踩确认",
            "support_price": 11.50,
            "is_zt": False,
            "is_leader": False
        }
    ]

    record_push_signals("confirm", sample_stocks, date_str="2026-09-17", force=True)

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM push_signals WHERE date = '2026-09-17' AND code = '002478';")
        row = cursor.fetchone()
        assert row is not None
        assert row["strategy_id"] == "S1"
        assert row["signal_stage"] == "CONFIRMED"
        assert row["support_price"] == 7.20


def test_sync_observation_pools_to_db():
    """测试将 S3/S4 观察池存入数据库"""
    pools = {
        "s3_pullback_pool": [
            {
                "code": "002478",
                "name": "常宝股份",
                "support_low": 6.25,
                "target_date": "2026-09-18"
            }
        ],
        "s4_breakout_pool": [
            {
                "code": "603967",
                "name": "中创物流",
                "ceiling": 10.8,
                "target_date": "2026-09-18"
            }
        ]
    }

    sync_observation_pools_to_db(pools, target_date="2026-09-18")
    df_pool = get_observation_pool_df()
    assert not df_pool.empty
    codes = df_pool["股票代码"].tolist()
    assert "002478" in codes
    assert "603967" in codes


def test_four_pillars_attribution_and_excel_export(tmp_path):
    """测试四柱战法归因分析计算与多 Sheet 格式化 Excel 导出"""
    # 模拟写入一笔闭环平仓数据
    trade = {
        "code": "002478",
        "name": "常宝股份",
        "buy_date": "2026-09-16",
        "buy_time": "09:30:00",
        "buy_stage": "confirm",
        "strategy_id": "S1",
        "strategy_tag": "🔥 S1 竞价首板",
        "buy_price": 7.00,
        "sell_date": "2026-09-17",
        "sell_time": "09:35:00",
        "sell_stage": "confirm",
        "sell_price": 7.70,
        "shares": 3000,
        "cost_amount": 21000.0,
        "gross_sell_amount": 23100.0,
        "fee": 16.5,
        "realized_profit": 2083.5,
        "realized_profit_pct": 9.92,
        "hold_days": 1,
        "action": "冲高止盈",
        "reason": "连板未能封死冲高兑现"
    }
    record_closed_trade(trade)

    df_attr = get_four_pillars_attribution_df()
    assert isinstance(df_attr, pd.DataFrame)
    assert len(df_attr) == 4  # S1, S2, S3, S4
    s1_row = df_attr[df_attr["战法编号"] == "S1"].iloc[0]
    assert s1_row["实盘交易数"] >= 1
    assert s1_row["累计净利润 (元)"] > 0

    # 测试导出 Excel
    excel_path = str(tmp_path / "test_report.xlsx")
    out_file = export_trades_to_excel(excel_path)
    assert os.path.exists(out_file)

    # 验证 Excel 内所有核心 Sheet 存在
    xl = pd.ExcelFile(out_file)
    assert "四柱战法归因分析" in xl.sheet_names
    assert "战法策略胜率透视" in xl.sheet_names
    assert "历史平仓明细流水" in xl.sheet_names
    assert "账户日结与资金曲线" in xl.sheet_names
    assert "当前持仓监控" in xl.sheet_names
