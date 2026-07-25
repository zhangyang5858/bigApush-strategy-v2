"""
首板接力竞价策略 - 筛选昨日首板涨停且今日竞价高开放量抢筹的二板潜在龙头标的
"""
import pandas as pd
import numpy as np
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from strategy.base_strategy import BaseStrategy


class LimitUpRelayAuctionStrategy(BaseStrategy):
    """
    首板接力竞价策略

    过滤及判断条件：
    a) 昨日收盘涨停（主板涨幅 >= 9.8%）。
    b) 前日非涨停（涨幅 < 9.8%），确保为首板。
    c) 昨日换手率在 5%~20% 之间。
    d) 今日竞价高开比例在 2%~6% 之间（open/prev_close - 1）。
    e) 今日竞价金额 >= 1500 万元，或竞价成交量/昨日成交量 >= 5%。
    f) 过滤 ST/退市股票，要求站在 5 日均线之上。
    """

    def __init__(self, params=None):
        default_params = {
            'limit_up_threshold': 0.098,        # 涨停阈值（主板涨幅 >= 9.8%）
            'turnover_min': 5.0,                # 昨日换手率最小值 (%)
            'turnover_max': 20.0,               # 昨日换手率最大值 (%)
            'open_ratio_min': 0.02,             # 今日竞价高开比例最小值 (2%)
            'open_ratio_max': 0.06,             # 今日竞价高开比例最大值 (6%)
            'auction_amount_min': 15000000.0,   # 今日竞价金额最小值 (1500 万元)
            'auction_vol_ratio_min': 0.05,      # 竞价成交量/昨日成交量最小值 (5%)
            'ma_period': 5,                     # 均线周期 (5日均线)
        }
        if params:
            default_params.update(params)
        super().__init__("首板接力竞价", default_params)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        计算 5 日均线等技术指标
        统一使用升序 DataFrame 计算
        """
        if df is None or df.empty:
            return df

        # 检测数据顺序，统一转换为升序（从旧到新）
        is_descending = len(df) > 1 and str(df['date'].iloc[0]) > str(df['date'].iloc[-1])
        if is_descending:
            df_calc = df.iloc[::-1].copy().reset_index(drop=True)
        else:
            df_calc = df.copy().reset_index(drop=True)

        ma_period = self.params.get('ma_period', 5)
        df_calc['ma5'] = df_calc['close'].rolling(window=ma_period, min_periods=1).mean()

        # 如果原始输入是倒序，计算完毕后恢复为倒序
        if is_descending:
            result = df_calc.iloc[::-1].reset_index(drop=True)
        else:
            result = df_calc

        return result

    def quick_filter(self, df: pd.DataFrame) -> bool:
        """
        快速过滤：检查数据长度并初步判断昨日是否接近涨停
        """
        if df is None or len(df) < 3:
            return False

        # 转换为升序判断
        if str(df['date'].iloc[0]) > str(df['date'].iloc[-1]):
            df_asc = df.iloc[::-1].reset_index(drop=True)
        else:
            df_asc = df

        yesterday_close = float(df_asc.iloc[-2]['close'])
        day_before_close = float(df_asc.iloc[-3]['close'])
        if day_before_close <= 0:
            return False

        yesterday_pct = (yesterday_close - day_before_close) / day_before_close
        limit_up_threshold = float(self.params.get('limit_up_threshold', 0.098))

        return yesterday_pct >= limit_up_threshold

    def get_selection_criteria(self) -> list:
        """获取选股条件描述"""
        return [
            "1. 昨日收盘涨停（主板涨幅 >= 9.8%）",
            "2. 前日非涨停（涨幅 < 9.8%），确保为首板",
            "3. 昨日换手率在 5%~20% 之间",
            "4. 今日竞价高开比例在 2%~6% 之间",
            "5. 今日竞价金额 >= 1500 万元，或竞价成交量/昨日成交量 >= 5%",
            "6. 过滤 ST/退市股票，要求站在 5 日均线之上"
        ]

    def select_stocks(self, df: pd.DataFrame, stock_name: str = '', stock_code: str = '') -> list:
        """
        选股逻辑
        :param df: 股票数据 DataFrame（支持升序或降序）
        :param stock_name: 股票名称
        :param stock_code: 股票代码
        :return: 选股信号列表
        """
        if df is None or len(df) < 3:
            return []

        # f) 过滤 ST/退市股票
        if stock_name and not self._validate_stock_name(stock_name):
            return []

        # 确保数据为升序排列（从旧到新），防范未来函数与数据方向混乱
        if str(df['date'].iloc[0]) > str(df['date'].iloc[-1]):
            df_asc = df.iloc[::-1].reset_index(drop=True)
        else:
            df_asc = df.copy().reset_index(drop=True)

        # 确保 MA5 指标存在
        if 'ma5' not in df_asc.columns:
            df_asc = self.calculate_indicators(df_asc)

        # 获取各阶段数据行
        today = df_asc.iloc[-1]
        yesterday = df_asc.iloc[-2]
        day_before = df_asc.iloc[-3]

        # 获取参数
        limit_up_threshold = float(self.params.get('limit_up_threshold', 0.098))
        turnover_min = float(self.params.get('turnover_min', 5.0))
        turnover_max = float(self.params.get('turnover_max', 20.0))
        open_ratio_min = float(self.params.get('open_ratio_min', 0.02))
        open_ratio_max = float(self.params.get('open_ratio_max', 0.06))
        auction_amount_min = float(self.params.get('auction_amount_min', 15000000.0))
        auction_vol_ratio_min = float(self.params.get('auction_vol_ratio_min', 0.05))

        # a) 昨日收盘涨停（主板涨幅 >= 9.8%）
        day_before_close = float(day_before['close'])
        yesterday_close = float(yesterday['close'])
        if day_before_close <= 0:
            return []
        yesterday_pct = (yesterday_close - day_before_close) / day_before_close
        if yesterday_pct < limit_up_threshold:
            return []

        # b) 前日非涨停（涨幅 < 9.8%），确保为首板
        if len(df_asc) >= 4:
            prior_close = float(df_asc.iloc[-4]['close'])
            day_before_pct = (day_before_close - prior_close) / prior_close if prior_close > 0 else 0.0
        else:
            day_before_open = float(day_before['open'])
            day_before_pct = (day_before_close - day_before_open) / day_before_open if day_before_open > 0 else 0.0

        if day_before_pct >= limit_up_threshold:
            return []

        # c) 昨日换手率在 5%~20% 之间
        turnover_val = yesterday.get('turnover_rate', None)
        if turnover_val is not None and not pd.isna(turnover_val):
            turnover_float = float(turnover_val)
            if turnover_float <= 1.0:
                turnover_float *= 100.0
            if not (turnover_min <= turnover_float <= turnover_max):
                return []
            yesterday_turnover_pct = turnover_float
        else:
            yesterday_turnover_pct = 0.0

        # d) 今日竞价高开比例在 2%~6% 之间 (open/prev_close - 1)
        today_open = float(today['open'])
        open_ratio = (today_open / yesterday_close) - 1.0
        if not (open_ratio_min <= open_ratio <= open_ratio_max):
            return []

        # e) 今日竞价金额 >= 1500 万元，或竞价成交量/昨日成交量 >= 5%
        today_amount = float(today.get('amount', 0))
        today_volume = float(today.get('volume', 0))
        yesterday_volume = float(yesterday.get('volume', 0))
        vol_ratio = (today_volume / yesterday_volume) if yesterday_volume > 0 else 0.0

        auction_ok = (today_amount >= auction_amount_min) or (vol_ratio >= auction_vol_ratio_min)
        if not auction_ok:
            return []

        # f) 站在 5 日均线之上 (今日开盘价/收盘价 >= ma5)
        ma5_val = float(today.get('ma5', 0))
        if ma5_val > 0:
            if today_open < ma5_val and float(today['close']) < ma5_val:
                return []

        # 满足所有条件，构建选股信号
        key_date_str = str(today['date']).split()[0]
        return [{
            'code': stock_code,
            'name': stock_name,
            'signal': 'buy',
            'key_date': key_date_str,
            'key_date_type': '首板接力竞价',
            'price': today_open,
            'open_ratio': open_ratio,
            'auction_amount': today_amount,
            'auction_vol_ratio': vol_ratio,
            'yesterday_turnover': yesterday_turnover_pct,
            'reasons': ["首板涨停次日竞价高开抢筹"],
        }]
