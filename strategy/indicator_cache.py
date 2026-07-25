"""
IndicatorCache 内存指标复用池
"""
import threading
from typing import Callable, Any, Dict, Tuple
import pandas as pd


class IndicatorCache:
    """股票级指标缓存池"""

    def __init__(self):
        self._cache: Dict[Tuple[str, str], Any] = {}
        self._lock = threading.Lock()

    def get_or_calculate(
        self,
        stock_code: str,
        indicator_key: str,
        df: pd.DataFrame,
        calc_fn: Callable[[pd.DataFrame], Any],
    ) -> Any:
        """
        获取或计算股票指标

        :param stock_code: 股票代码
        :param indicator_key: 指标唯一标识 (例如 'MACD_12_26_9' 或 'MA_5')
        :param df: K线数据 DataFrame
        :param calc_fn: 计算函数，接收 df 参数并返回计算结果
        :return: 计算后的指标结果 (如 pd.Series 或 pd.DataFrame)
        """
        key = (stock_code, indicator_key)
        with self._lock:
            if key in self._cache:
                return self._cache[key]

            result = calc_fn(df)
            self._cache[key] = result
            return result

    def clear(self):
        """清空缓存"""
        with self._lock:
            self._cache.clear()


# 全局单例
global_indicator_cache = IndicatorCache()
