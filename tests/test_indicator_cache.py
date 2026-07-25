import unittest
import pandas as pd
from strategy.indicator_cache import IndicatorCache, global_indicator_cache


class TestIndicatorCache(unittest.TestCase):
    def setUp(self):
        self.cache = IndicatorCache()
        self.df = pd.DataFrame({'close': [10.0, 11.0, 12.0, 13.0, 14.0]})

    def test_cache_hit_and_miss(self):
        call_count = 0

        def mock_calc(df):
            nonlocal call_count
            call_count += 1
            return df['close'].rolling(2).mean()

        # 首次调用：应触发计算并缓存
        res1 = self.cache.get_or_calculate("000001", "ma_2", self.df, mock_calc)
        self.assertEqual(call_count, 1)

        # 第二次相同调用：应直接命中缓存，不触发 mock_calc
        res2 = self.cache.get_or_calculate("000001", "ma_2", self.df, mock_calc)
        self.assertEqual(call_count, 1)
        pd.testing.assert_series_equal(res1, res2)

        # 不同 stock_code：应触发计算
        res3 = self.cache.get_or_calculate("000002", "ma_2", self.df, mock_calc)
        self.assertEqual(call_count, 2)

        # 不同 indicator_key：应触发计算
        res4 = self.cache.get_or_calculate("000001", "ma_5", self.df, mock_calc)
        self.assertEqual(call_count, 3)

    def test_clear_cache(self):
        call_count = 0

        def mock_calc(df):
            nonlocal call_count
            call_count += 1
            return df['close'] * 2

        self.cache.get_or_calculate("000001", "double_close", self.df, mock_calc)
        self.assertEqual(call_count, 1)

        # 清空缓存
        self.cache.clear()

        # 再次调用：由于缓存已清空，应重新触发计算
        self.cache.get_or_calculate("000001", "double_close", self.df, mock_calc)
        self.assertEqual(call_count, 2)

    def test_global_singleton(self):
        global_indicator_cache.clear()
        call_count = 0

        def mock_calc(df):
            nonlocal call_count
            call_count += 1
            return df['close'] + 1

        global_indicator_cache.get_or_calculate("600000", "plus_one", self.df, mock_calc)
        self.assertEqual(call_count, 1)

        global_indicator_cache.get_or_calculate("600000", "plus_one", self.df, mock_calc)
        self.assertEqual(call_count, 1)

        global_indicator_cache.clear()


if __name__ == '__main__':
    unittest.main()
