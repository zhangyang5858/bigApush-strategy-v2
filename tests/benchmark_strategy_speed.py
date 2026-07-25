"""
性能基准测试脚本: 对比向量化计算 SMA/KDJ 与传统 Python 循环计算的耗时占比
"""
import os
import sys
import time
import unittest
import numpy as np
import pandas as pd

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

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
        return pd.DataFrame({"K": [], "D": [], "J": []}, index=df.index if df is not None else [])

    try:
        is_descending = df["date"].iloc[0] > df["date"].iloc[-1]
    except (IndexError, KeyError):
        is_descending = False

    if is_descending:
        df_calc = df.iloc[::-1].copy().reset_index(drop=True)
    else:
        df_calc = df.copy().reset_index(drop=True)

    low_min = df_calc["low"].rolling(window=n, min_periods=1).min()
    high_max = df_calc["high"].rolling(window=n, min_periods=1).max()
    range_val = high_max - low_min
    rsv = pd.Series(index=df_calc.index, dtype=float)

    for i in range(len(df_calc)):
        if i < n - 1 or range_val.iloc[i] == 0:
            rsv.iloc[i] = 50.0
        else:
            rsv.iloc[i] = (df_calc["close"].iloc[i] - low_min.iloc[i]) / range_val.iloc[i] * 100

    k = pd.Series(index=df_calc.index, dtype=float)
    d = pd.Series(index=df_calc.index, dtype=float)

    k.iloc[0] = 50.0
    d.iloc[0] = 50.0

    for i in range(1, len(df_calc)):
        k.iloc[i] = (rsv.iloc[i] * 1 + k.iloc[i - 1] * (m1 - 1)) / m1
        d.iloc[i] = (k.iloc[i] * 1 + d.iloc[i - 1] * (m2 - 1)) / m2

    j = 3 * k - 2 * d

    result = pd.DataFrame({"K": k, "D": d, "J": j})
    if is_descending:
        result = result.iloc[::-1].reset_index(drop=True)

    result.index = df.index
    return result


def generate_mock_stock_data(num_stocks=100, rows_per_stock=200):
    """构造大批量 K 线数据 (100只股票，每只200行)"""
    stocks = {}
    np.random.seed(42)
    dates = pd.date_range(end="2026-07-25", periods=rows_per_stock, freq="D").strftime("%Y-%m-%d").tolist()

    for s_idx in range(num_stocks):
        code = f"{s_idx:06d}"
        init_price = np.random.uniform(10, 100)
        returns = np.random.normal(0.0005, 0.02, rows_per_stock)
        price_paths = init_price * np.cumprod(1 + returns)

        high = price_paths * (1 + np.abs(np.random.normal(0, 0.01, rows_per_stock)))
        low = price_paths * (1 - np.abs(np.random.normal(0, 0.01, rows_per_stock)))
        open_p = low + (high - low) * np.random.uniform(0.1, 0.9, rows_per_stock)
        close_p = low + (high - low) * np.random.uniform(0.1, 0.9, rows_per_stock)
        volume = np.random.randint(10000, 1000000, rows_per_stock)

        df = pd.DataFrame(
            {
                "date": dates,
                "open": open_p,
                "high": high,
                "low": low,
                "close": close_p,
                "volume": volume,
            }
        )
        stocks[code] = df
    return stocks


def run_benchmark(num_stocks=100, rows_per_stock=200):
    """运行对比基准测试"""
    stocks_data = generate_mock_stock_data(num_stocks, rows_per_stock)

    # 1. 传统 Python 循环计算耗时
    start_loop = time.perf_counter()
    for code, df in stocks_data.items():
        _ = unvectorized_sma(df["close"], 20, 1)
        _ = unvectorized_kdj(df)
    end_loop = time.perf_counter()
    loop_time = end_loop - start_loop

    # 2. 向量化计算耗时
    start_vec = time.perf_counter()
    for code, df in stocks_data.items():
        _ = SMA(df["close"], 20, 1)
        _ = KDJ(df)
    end_vec = time.perf_counter()
    vec_time = end_vec - start_vec

    speedup = loop_time / vec_time if vec_time > 0 else float("inf")

    print("\n" + "=" * 60)
    print(f" 技术指标计算性能基准测试 (数据规模: {num_stocks} 只股票 x {rows_per_stock} 行)")
    print("=" * 60)
    print(f" 传统 Python 循环计算耗时: {loop_time:.4f} 秒")
    print(f" 向量化 (Pandas/eWM) 耗时 : {vec_time:.4f} 秒")
    print(f" 向量化/循环耗时占比      : {(vec_time / loop_time) * 100:.2f}%")
    print(f" 性能提升倍数              : {speedup:.2f}x")
    print("=" * 60 + "\n")

    return {
        "loop_time": loop_time,
        "vec_time": vec_time,
        "speedup": speedup,
    }


class TestBenchmarkStrategySpeed(unittest.TestCase):
    def test_benchmark_speedup(self):
        res = run_benchmark(num_stocks=100, rows_per_stock=200)
        self.assertGreater(res["speedup"], 1.0, "向量化计算速度应显著快于循环计算")


if __name__ == "__main__":
    run_benchmark(100, 200)
