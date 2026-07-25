"""
utils/technical.py 向量化重构单元测试
"""
import unittest
import pandas as pd
import numpy as np
from utils.technical import SMA, KDJ


def unvectorized_sma(X, n, m):
    """基准标尺：循环实现的 SMA"""
    result = pd.Series(index=X.index, dtype=float)
    result.iloc[0] = X.iloc[0]
    for i in range(1, len(X)):
        result.iloc[i] = (X.iloc[i] * m + result.iloc[i - 1] * (n - m)) / n
    return result


def unvectorized_kdj(df, n=9, m1=3, m2=3):
    """基准标尺：循环实现的 KDJ"""
    if df is None or df.empty:
        return pd.DataFrame({'K': [], 'D': [], 'J': []}, index=df.index if df is not None else [])

    try:
        is_descending = df['date'].iloc[0] > df['date'].iloc[-1]
    except (IndexError, KeyError):
        is_descending = False

    if is_descending:
        df_calc = df.iloc[::-1].copy().reset_index(drop=True)
    else:
        df_calc = df.copy().reset_index(drop=True)

    low_min = df_calc['low'].rolling(window=n, min_periods=1).min()
    high_max = df_calc['high'].rolling(window=n, min_periods=1).max()
    range_val = high_max - low_min
    rsv = pd.Series(index=df_calc.index, dtype=float)

    for i in range(len(df_calc)):
        if i < n - 1 or range_val.iloc[i] == 0:
            rsv.iloc[i] = 50.0
        else:
            rsv.iloc[i] = (df_calc['close'].iloc[i] - low_min.iloc[i]) / range_val.iloc[i] * 100

    k = pd.Series(index=df_calc.index, dtype=float)
    d = pd.Series(index=df_calc.index, dtype=float)

    k.iloc[0] = 50.0
    d.iloc[0] = 50.0

    for i in range(1, len(df_calc)):
        k.iloc[i] = (rsv.iloc[i] * 1 + k.iloc[i - 1] * (m1 - 1)) / m1
        d.iloc[i] = (k.iloc[i] * 1 + d.iloc[i - 1] * (m2 - 1)) / m2

    j = 3 * k - 2 * d

    result = pd.DataFrame({'K': k, 'D': d, 'J': j})
    if is_descending:
        result = result.iloc[::-1].reset_index(drop=True)

    result.index = df.index
    return result


class TestTechnicalVectorized(unittest.TestCase):
    def test_sma_vectorized(self):
        data = pd.Series([10.0, 12.0, 15.0, 14.0, 16.0, 18.0, 20.0])
        expected = unvectorized_sma(data, 3, 1)
        actual = SMA(data, 3, 1)
        
        self.assertEqual(len(actual), len(data))
        pd.testing.assert_series_equal(actual, expected, check_exact=False, rtol=1e-10)

    def test_sma_various_params(self):
        data = pd.Series([5.0, 8.0, 12.0, 10.0, 15.0, 20.0, 18.0, 22.0, 25.0])
        for n, m in [(3, 1), (5, 2), (10, 1), (14, 1)]:
            expected = unvectorized_sma(data, n, m)
            actual = SMA(data, n, m)
            pd.testing.assert_series_equal(actual, expected, check_exact=False, rtol=1e-10)

    def test_kdj_vectorized_ascending(self):
        dates = pd.date_range('2026-01-01', periods=15).strftime('%Y-%m-%d').tolist()
        df = pd.DataFrame({
            'date': dates,
            'high': [10, 11, 12, 11, 13, 14, 15, 14, 16, 17, 18, 17.5, 19, 20, 21],
            'low': [9, 9.5, 10, 10.5, 11, 12, 13, 12.5, 14, 15, 15.5, 16, 17, 18, 19],
            'close': [9.5, 10.5, 11, 10.8, 12.5, 13.5, 14.2, 13, 15.5, 16.5, 17, 16.8, 18.5, 19.2, 20.1]
        })

        expected = unvectorized_kdj(df)
        actual = KDJ(df)

        self.assertEqual(set(actual.columns), {'K', 'D', 'J'})
        self.assertEqual(len(actual), len(df))
        pd.testing.assert_frame_equal(actual, expected, check_exact=False, rtol=1e-10)

    def test_kdj_vectorized_descending(self):
        dates = pd.date_range('2026-01-01', periods=15).strftime('%Y-%m-%d').tolist()[::-1]
        df = pd.DataFrame({
            'date': dates,
            'high': [21, 20, 19, 17.5, 18, 17, 16, 14, 15, 14, 13, 11, 12, 11, 10],
            'low': [19, 18, 17, 16, 15.5, 15, 14, 12.5, 13, 12, 11, 10.5, 10, 9.5, 9],
            'close': [20.1, 19.2, 18.5, 16.8, 17, 16.5, 15.5, 13, 14.2, 13.5, 12.5, 10.8, 11, 10.5, 9.5]
        })

        expected = unvectorized_kdj(df)
        actual = KDJ(df)

        self.assertEqual(len(actual), len(df))
        pd.testing.assert_frame_equal(actual, expected, check_exact=False, rtol=1e-10)

    def test_kdj_empty_and_flat(self):
        # 测试空 DataFrame
        empty_df = pd.DataFrame()
        res_empty = KDJ(empty_df)
        self.assertTrue(res_empty.empty)
        self.assertEqual(list(res_empty.columns), ['K', 'D', 'J'])

        # 测试平盘数据（high == low）
        dates = pd.date_range('2026-01-01', periods=10).strftime('%Y-%m-%d').tolist()
        flat_df = pd.DataFrame({
            'date': dates,
            'high': [10.0] * 10,
            'low': [10.0] * 10,
            'close': [10.0] * 10
        })

        expected_flat = unvectorized_kdj(flat_df)
        actual_flat = KDJ(flat_df)
        pd.testing.assert_frame_equal(actual_flat, expected_flat, check_exact=False, rtol=1e-10)


if __name__ == '__main__':
    unittest.main()

