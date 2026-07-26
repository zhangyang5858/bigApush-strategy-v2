"""
涨停横盘专属择时策略单元测试 (LimitUpSidewaysTimingStrategy Tests)
"""
import unittest
import pandas as pd
from datetime import datetime, timedelta
from trading.timing_strategies import TimingStrategyFactory
from trading.limit_up_sideways_timing import LimitUpSidewaysTimingStrategy


class TestLimitUpSidewaysTimingStrategy(unittest.TestCase):
    """测试 LimitUpSidewaysTimingStrategy"""

    def setUp(self):
        self.strategy = LimitUpSidewaysTimingStrategy({
            'take_profit_ratio': 0.08,
            'stop_loss_ratio': 0.04,
            'max_hold_days': 5,
            'trailing_stop_activation': 0.05,
            'trailing_stop_pullback': 0.025,
            'base_position_amount': 50000.0,
        })

    def test_factory_creation(self):
        """测试工厂方法能正确创建策略"""
        strat = TimingStrategyFactory.create_strategy('limit_up_sideways', {})
        self.assertIsInstance(strat, LimitUpSidewaysTimingStrategy)

    def test_buy_signal_no_position(self):
        """测试未持仓时生成买入信号"""
        df = pd.DataFrame([
            {'date': '2026-07-20', 'open': 10.0, 'high': 10.5, 'low': 9.8, 'close': 10.2, 'volume': 10000},
            {'date': '2026-07-21', 'open': 10.2, 'high': 10.6, 'low': 10.1, 'close': 10.5, 'volume': 12000},
        ])
        result = self.strategy.get_timing_result(df, position=None, cash=100000)
        self.assertTrue(result.is_buy)
        self.assertFalse(result.is_sell)
        self.assertEqual(result.trade_type, 'buy')
        self.assertGreater(result.buy_quantity, 0)

    def test_stop_loss_signal(self):
        """测试跌幅达到 4% 触发止损"""
        df = pd.DataFrame([
            {'date': '2026-07-20', 'open': 10.0, 'high': 10.2, 'low': 9.5, 'close': 9.5, 'volume': 10000},
        ])
        position = {
            'stock_code': '000001',
            'buy_price': 10.0,
            'quantity': 1000,
            'buy_date': '2026-07-19',
            'hold_days': 1
        }
        result = self.strategy.get_timing_result(df, position=position)
        self.assertTrue(result.is_sell)
        self.assertIn('止损', result.message)

    def test_take_profit_signal(self):
        """测试涨幅达到 8% 触发止盈"""
        df = pd.DataFrame([
            {'date': '2026-07-20', 'open': 10.0, 'high': 11.0, 'low': 10.0, 'close': 10.9, 'volume': 10000},
        ])
        position = {
            'stock_code': '000001',
            'buy_price': 10.0,
            'quantity': 1000,
            'buy_date': '2026-07-19',
            'hold_days': 1
        }
        result = self.strategy.get_timing_result(df, position=position)
        self.assertTrue(result.is_sell)
        self.assertIn('止盈', result.message)

    def test_max_hold_days_signal(self):
        """测试持股达到 5 天触发超时清仓"""
        df = pd.DataFrame([
            {'date': '2026-07-25', 'open': 10.0, 'high': 10.2, 'low': 9.9, 'close': 10.0, 'volume': 10000},
        ])
        position = {
            'stock_code': '000001',
            'buy_price': 10.0,
            'quantity': 1000,
            'buy_date': '2026-07-20',
            'hold_days': 5
        }
        result = self.strategy.get_timing_result(df, position=position)
        self.assertTrue(result.is_sell)
        self.assertIn('持股超时', result.message)


if __name__ == '__main__':
    unittest.main()
