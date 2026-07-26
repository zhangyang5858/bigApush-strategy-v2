"""
强势涨停横盘一步到位建仓与大盈亏比择时策略单元测试 (StrongLimitUpSidewaysTimingStrategy Tests)
"""
import unittest
import pandas as pd
from trading.timing_strategies import TimingStrategyFactory
from trading.strong_limit_up_sideways_timing import StrongLimitUpSidewaysTimingStrategy


class TestStrongLimitUpSidewaysTimingStrategy(unittest.TestCase):
    """测试 StrongLimitUpSidewaysTimingStrategy"""

    def setUp(self):
        self.strategy = StrongLimitUpSidewaysTimingStrategy({
            'stop_loss_ratio': 0.04,
            'first_target_profit': 0.15,
            'base_position_amount': 100000.0,
        })

    def test_factory_creation(self):
        """测试工厂创建该策略"""
        strat = TimingStrategyFactory.create_strategy('strong_limit_up_sideways', {})
        self.assertIsInstance(strat, StrongLimitUpSidewaysTimingStrategy)

    def test_full_tranche_buy(self):
        """测试 10 日线支撑区一步到位建立满仓"""
        df = pd.DataFrame([
            {'date': '2026-07-20', 'open': 10.0, 'high': 10.5, 'low': 9.8, 'close': 10.0, 'volume': 10000},
        ])
        result = self.strategy.get_timing_result(df, position=None, cash=100000)
        self.assertTrue(result.is_buy)
        self.assertEqual(result.trade_type, 'buy')
        # 资金100000，开盘价格10.0元，直接买入 10000 股（一步到位满仓）
        self.assertEqual(result.buy_quantity, 10000)

    def test_step_take_profit_15_percent(self):
        """测试涨幅达到 15% 减仓 1/2 锁定利润"""
        df = pd.DataFrame([
            {'date': '2026-07-20', 'open': 10.0, 'high': 10.0, 'low': 10.0, 'close': 10.0, 'volume': 10000},
            {'date': '2026-07-21', 'open': 11.6, 'high': 11.6, 'low': 11.0, 'close': 11.6, 'volume': 10000}, # +16%
        ])
        position = {
            'stock_code': '000001',
            'buy_price': 10.0,
            'quantity': 10000,
            'reduce_count': 0,
            'buy_date': '2026-07-20',
            'hold_days': 1
        }
        result = self.strategy.get_timing_result(df, position=position)
        self.assertTrue(result.is_sell)
        self.assertEqual(result.trade_type, 'reduce')
        self.assertEqual(result.sell_quantity, 5000) # 减仓 1/2 锁利
        self.assertIn('锁住丰厚利润', result.message)

    def test_no_breakout_release_cash(self):
        """测试建仓 3 天未爆发平仓释放资金"""
        data = []
        for i in range(5):
            data.append({
                'date': f'2026-07-{i+20:02d}',
                'open': 10.0,
                'high': 10.1,
                'low': 9.9,
                'close': 10.0,
                'volume': 10000
            })
        df = pd.DataFrame(data)

        position = {
            'stock_code': '000001',
            'buy_price': 10.0,
            'quantity': 10000,
            'buy_date': '2026-07-20',
            'hold_days': 3
        }
        result = self.strategy.get_timing_result(df, position=position)
        self.assertTrue(result.is_sell)
        self.assertEqual(result.trade_type, 'sell')
        self.assertIn('平仓释放资金', result.message)


if __name__ == '__main__':
    unittest.main()
