"""
超短线竞价择时策略 (ShortTermAuctionTimingStrategy) 单元测试
"""
import unittest
import pandas as pd
from trading.timing_strategies import TimingStrategyFactory
from trading.short_term_auction_timing import ShortTermAuctionTimingStrategy


class TestShortTermAuctionTiming(unittest.TestCase):
    """测试 ShortTermAuctionTimingStrategy 策略与工厂集成"""

    def test_factory_creation(self):
        """测试 TimingStrategyFactory 正确创建 short_term_auction 实例"""
        strategy = TimingStrategyFactory.create_strategy("short_term_auction", {})
        self.assertIsInstance(strategy, ShortTermAuctionTimingStrategy)
        self.assertEqual(strategy.take_profit_ratio, 0.06)
        self.assertEqual(strategy.stop_loss_ratio, 0.035)
        self.assertEqual(strategy.max_hold_days, 2)
        self.assertEqual(strategy.trailing_stop_activation, 0.04)
        self.assertEqual(strategy.trailing_stop_pullback, 0.02)

    def test_buy_signal_trigger(self):
        """测试买点触发 (无持仓时触发买入)"""
        strategy = ShortTermAuctionTimingStrategy()
        df = pd.DataFrame({
            'date': ['2026-01-01', '2026-01-02'],
            'open': [10.0, 10.5],
            'close': [10.2, 10.6],
            'high': [10.3, 10.8],
            'low': [9.9, 10.4]
        })
        result = strategy.get_timing_result(df, position=None, cash=100000.0)
        self.assertTrue(result.is_buy)
        self.assertFalse(result.is_sell)
        self.assertEqual(result.trade_type, 'buy')
        self.assertGreater(result.buy_quantity, 0)
        self.assertEqual(result.buy_quantity % 100, 0)

    def test_hard_stop_loss_trigger(self):
        """测试硬止损触发 (跌幅 >= 3.5% 触发卖出)"""
        strategy = ShortTermAuctionTimingStrategy({'stop_loss_ratio': 0.035})
        # 买入价 10.0，跌至 9.5 (跌幅 5.0% >= 3.5%)
        df = pd.DataFrame({
            'date': ['2026-01-01', '2026-01-02'],
            'open': [10.0, 9.6],
            'close': [10.0, 9.5],
            'high': [10.1, 9.7],
            'low': [9.9, 9.4]
        })
        position = {'stock_code': '600000', 'buy_price': 10.0, 'hold_days': 1, 'quantity': 1000}
        result = strategy.get_timing_result(df, position=position)
        self.assertTrue(result.is_sell)
        self.assertEqual(result.trade_type, 'sell')
        self.assertEqual(result.sell_quantity, 1000)
        self.assertIn("止损", result.message)

    def test_take_profit_trigger(self):
        """测试止盈触发 (涨幅 >= 6.0% 触发卖出)"""
        strategy = ShortTermAuctionTimingStrategy({'take_profit_ratio': 0.06})
        # 买入价 10.0，涨至 10.7 (涨幅 7.0% >= 6.0%)
        df = pd.DataFrame({
            'date': ['2026-01-01', '2026-01-02'],
            'open': [10.0, 10.3],
            'close': [10.0, 10.7],
            'high': [10.1, 10.8],
            'low': [9.9, 10.2]
        })
        position = {'stock_code': '600000', 'buy_price': 10.0, 'hold_days': 1, 'quantity': 1000}
        result = strategy.get_timing_result(df, position=position)
        self.assertTrue(result.is_sell)
        self.assertEqual(result.trade_type, 'sell')
        self.assertEqual(result.sell_quantity, 1000)
        self.assertIn("止盈", result.message)

    def test_hold_timeout_trigger(self):
        """测试持股超时 (持股天数 >= 2 天触发强制卖出清仓)"""
        strategy = ShortTermAuctionTimingStrategy({'max_hold_days': 2})
        # 价格无大涨大跌 (10.0 -> 10.1)，但 hold_days = 2
        df = pd.DataFrame({
            'date': ['2026-01-01', '2026-01-03'],
            'open': [10.0, 10.0],
            'close': [10.0, 10.1],
            'high': [10.1, 10.2],
            'low': [9.9, 10.0]
        })
        position = {'stock_code': '600000', 'buy_price': 10.0, 'hold_days': 2, 'quantity': 1000}
        result = strategy.get_timing_result(df, position=position)
        self.assertTrue(result.is_sell)
        self.assertEqual(result.trade_type, 'sell')
        self.assertEqual(result.sell_quantity, 1000)
        self.assertIn("超时", result.message)

    def test_trailing_stop_trigger(self):
        """测试移动保盈触发 (冲高 >= 4% 后回落 >= 2% 离场)"""
        strategy = ShortTermAuctionTimingStrategy({
            'trailing_stop_activation': 0.04,
            'trailing_stop_pullback': 0.02
        })
        # 买入价 10.0，日内/持仓期最高到达 10.5 (冲高 5.0% >= 4.0%)，收盘回落至 10.25 (从最高点 10.5 回落 2.38% >= 2.0%)
        df = pd.DataFrame({
            'date': ['2026-01-01', '2026-01-02'],
            'open': [10.0, 10.4],
            'close': [10.0, 10.25],
            'high': [10.1, 10.5],
            'low': [9.9, 10.2]
        })
        position = {'stock_code': '600000', 'buy_price': 10.0, 'hold_days': 1, 'quantity': 1000, 'buy_date': '2026-01-01'}
        result = strategy.get_timing_result(df, position=position)
        self.assertTrue(result.is_sell)
        self.assertEqual(result.trade_type, 'sell')
        self.assertIn("保盈", result.message)


if __name__ == '__main__':
    unittest.main()
