"""
BaseStrategy 防未来函数与历史选股日数据截断单元测试
"""
import unittest
import pandas as pd
from strategy.base_strategy import BaseStrategy


class DummyTestStrategy(BaseStrategy):
    """用于测试数据截断逻辑的虚构策略类"""

    def __init__(self):
        super().__init__("DummyTestStrategy")
        self.received_df_in_calc = None
        self.received_df_in_select = None

    def calculate_indicators(self, df) -> pd.DataFrame:
        self.received_df_in_calc = df.copy()
        df = df.copy()
        # 计算最高价滚动最大值，检验是否泄露未来价格
        df['max_high_20d'] = df['high'].rolling(20, min_periods=1).max()
        return df

    def select_stocks(self, df, stock_name='') -> list:
        self.received_df_in_select = df.copy()
        if df.empty:
            return []
        
        latest_row = df.iloc[-1] if df.iloc[0]['date'] < df.iloc[-1]['date'] else df.iloc[0]
        return [{
            'date': str(latest_row['date']).split()[0],
            'max_high': float(latest_row['max_high_20d']),
            'count': len(df)
        }]


class TestBaseStrategyFutureBias(unittest.TestCase):
    """BaseStrategy 防未来函数测试套件"""

    def setUp(self):
        # 构造40天基础价格序列 (2026-01-01 至 2026-02-09)
        dates = pd.date_range('2026-01-01', periods=40).strftime('%Y-%m-%d').tolist()
        # 前25天价格在 10-35 之间，第26-40天（2026-01-26 起）价格暴涨到 500
        highs = [10.0 + i for i in range(25)] + [500.0] * 15
        lows = [8.0 + i for i in range(25)] + [490.0] * 15
        closes = [9.0 + i for i in range(25)] + [495.0] * 15
        opens = [9.5 + i for i in range(25)] + [492.0] * 15
        volumes = [1000] * 40

        self.df_asc = pd.DataFrame({
            'date': dates,
            'open': opens,
            'high': highs,
            'low': lows,
            'close': closes,
            'volume': volumes
        })

        self.df_desc = self.df_asc.iloc[::-1].copy().reset_index(drop=True)

    def test_execute_selection_future_data_truncated_ascending(self):
        """测试正序 DataFrame 传入 selection_date 时未来数据被彻底拦截"""
        strategy = DummyTestStrategy()
        selection_date = '2026-01-25'
        
        signals = strategy.execute_selection(
            self.df_asc,
            stock_code='000001',
            stock_name='测试股票',
            selection_date=selection_date
        )

        self.assertEqual(len(signals), 1)
        # 验证返回信号中的日期不超过 selection_date
        self.assertEqual(signals[0]['date'], selection_date)
        # 验证 2026-01-26 之后暴涨到 500 的价格没有被包含在 max_high 指标中
        self.assertLess(signals[0]['max_high'], 100.0)

        # 验证传递给 calculate_indicators 和 select_stocks 的 df 不含未来日期
        df_calc_dates = list(strategy.received_df_in_calc['date'].astype(str).str.split().str[0])
        self.assertNotIn('2026-01-26', df_calc_dates)
        self.assertTrue(all(d <= selection_date for d in df_calc_dates))

    def test_execute_selection_future_data_truncated_descending(self):
        """测试倒序 DataFrame 传入 selection_date 时未来数据被彻底拦截"""
        strategy = DummyTestStrategy()
        selection_date = '2026-01-25'

        signals = strategy.execute_selection(
            self.df_desc,
            stock_code='000001',
            stock_name='测试股票',
            selection_date=selection_date
        )

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0]['date'], selection_date)
        self.assertLess(signals[0]['max_high'], 100.0)

        df_calc_dates = list(strategy.received_df_in_calc['date'].astype(str).str.split().str[0])
        self.assertNotIn('2026-01-26', df_calc_dates)
        self.assertTrue(all(d <= selection_date for d in df_calc_dates))

    def test_slice_by_date_direct(self):
        """测试 _slice_by_date 方法各种边界情况"""
        strategy = DummyTestStrategy()

        # selection_date 为 None 时不截断
        df_none = strategy._slice_by_date(self.df_asc, None)
        self.assertEqual(len(df_none), len(self.df_asc))

        # selection_date 为空字符串时不截断
        df_empty_str = strategy._slice_by_date(self.df_asc, '')
        self.assertEqual(len(df_empty_str), len(self.df_asc))

        # selection_date 带时间后缀
        df_with_time = strategy._slice_by_date(self.df_asc, '2026-01-10 00:00:00')
        max_date_with_time = df_with_time['date'].astype(str).str.split().str[0].max()
        self.assertEqual(max_date_with_time, '2026-01-10')

        # None 或 empty DataFrame
        self.assertIsNone(strategy._slice_by_date(None, '2026-01-10'))
        self.assertTrue(strategy._slice_by_date(pd.DataFrame(), '2026-01-10').empty)


if __name__ == '__main__':
    unittest.main()
