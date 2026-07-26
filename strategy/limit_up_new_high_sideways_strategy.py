import pandas as pd
import numpy as np
from datetime import datetime
from strategy.base_strategy import BaseStrategy


class LimitUpNewHighSidewaysStrategy(BaseStrategy):
    """
    涨停新高横盘选股策略 (LimitUpNewHighSidewaysStrategy)

    核心交易逻辑：
    1. 【连板/涨停启动】：近 N 个交易日内出现过涨停（主板≥9.5%），支持单板爆量或连板（如星网锐捷形态）。
    2. 【突破创历史/阶段新高】：涨停或横盘突破点创下过去 M 天（默认 250 天，即近一年）历史新高，左侧无解套盘压力。
    3. 【平台整理与缩量蓄势】：
       - 涨停/连板后进行箱体平台震荡（整理天数 2~12 天）。
       - 平台箱体价格守住关键支撑位（不跌破涨停日收盘价或前低支撑）。
       - 整理期间出现明显筹码锁定与沉淀（至少 1 天成交量萎缩至涨停日或近期峰值的 60% 以下）。
    4. 【平台突破确认】：
       - 当日放量上涨（成交量较前一日放大 1.3 倍以上）突破横盘箱体最高价。
    """

    def __init__(self, params=None):
        default_params = {
            # 涨停与新高条件
            'limit_up_lookback': 15,            # 涨停板回溯天数
            'limit_up_threshold': 0.095,        # 涨停阈值（主板9.5%）
            'new_high_lookback': 90,            # 突破新高回溯天数（90天季线/半年箱体新高，扩大选股基数）
            
            # 平台整理条件
            'sideways_days_min': 2,             # 最小平台整理天数
            'sideways_days_max': 12,            # 最大平台整理天数
            'support_drop_limit': -0.02,        # 回踩支撑下限（相对涨停日收盘价 -2%）
            'box_high_limit': 0.12,             # 平台箱体上沿限制（不超过涨停价的 +12%）
            'volume_shrink_ratio': 0.75,        # 地量缩量比例（放宽至 ≤ 涨停日/峰值成交量的 75%）
            
            # 突破买入确认
            'breakout_vol_ratio': 1.25,         # 突破日成交量放大幅度（较前一日 1.25 倍）
            'breakout_price_pct': 0.015,        # 突破日涨幅下限（≥ 1.5%）
            
            'max_top_n': 5,                     # 选股最多保留 Top 5
            'strategy_weight': 70,              # 技术面评分权重
        }

        if params:
            default_params.update(params)

        super().__init__("涨停新高横盘选股", default_params)

    def calculate_indicators(self, df):
        """计算策略所需基础指标"""
        result = df.copy()
        result['volume_ma5'] = result['volume'].rolling(window=5, min_periods=1).mean()
        return result

    def quick_filter(self, df):
        """
        快速过滤：要求必须有涨停板，且最新价格处于近 250 天高位附近
        :param df: DataFrame（降序，最新在 index 0）
        """
        lookback = self.params['limit_up_lookback']
        if len(df) < lookback + 1:
            return False

        check_df = df[['close']].head(lookback + 1)
        pct_change = check_df['close'].pct_change(-1)
        has_limit_up = (pct_change >= self.params['limit_up_threshold']).any()

        if not has_limit_up:
            return False

        # 检查是否接近新高区域
        recent_close = df.iloc[0]['close']
        max_high = df['high'].head(min(len(df), self.params['new_high_lookback'])).max()
        if recent_close < max_high * 0.90:  # 必须在近一年最高价的 90% 以上
            return False

        return True

    def select_stocks(self, data, stock_name="", skip_data_check=False):
        """选股逻辑"""
        if isinstance(data, dict):
            df = data.get('df')
            if df is None:
                return []
        else:
            df = data

        if not skip_data_check:
            if len(df) < 60:
                return []
            if pd.isna(df.iloc[0]['close']) or pd.isna(df.iloc[0]['volume']):
                return []

        # 统一转为倒序 (index 0 为最新)
        is_ascending = len(df) > 1 and df['date'].iloc[0] < df['date'].iloc[-1]
        if is_ascending:
            df_desc = df.iloc[::-1].reset_index(drop=True)
        else:
            df_desc = df.copy().reset_index(drop=True)

        if not self.quick_filter(df_desc):
            return []

        # 1. 寻找涨停板/连板位置
        limit_up_info = self._find_limit_up_or_continuous(df_desc)
        if not limit_up_info:
            return []

        # 2. 检查平台震荡整理
        sideways_info = self._check_platform_sideways(df_desc, limit_up_info)
        if not sideways_info:
            return []

        # 3. 检查突破新高与放量信号
        breakout_info = self._check_new_high_breakout(df_desc, limit_up_info, sideways_info)
        if not breakout_info:
            return []

        # 4. 计算综合打分质量
        quality_score = self._calculate_quality_score(df_desc, limit_up_info, sideways_info, breakout_info)

        today_date = df_desc.iloc[0]['date']
        today_date_str = today_date.strftime('%Y-%m-%d') if hasattr(today_date, 'strftime') else str(today_date)[:10]
        key_date_str = str(limit_up_info['date'])[:10]

        reasons = [
            f"近{limit_up_info['lookback']}日出现强涨停/连板突破（涨停日：{key_date_str}）",
            f"股价突破近 {self.params['new_high_lookback']} 日历史新高，左侧零套牢盘",
            f"涨停后形成平台箱体震荡整理 {sideways_info['days']} 个交易日，守住支撑位 {sideways_info['support_price']:.2f}",
            f"整理期间出现极致地量缩盘（成交量缩至峰值 {sideways_info['min_vol_ratio']*100:.1f}%）",
            f"今日放量突破横盘箱体上沿（放量 {breakout_info['vol_ratio']:.2f} 倍）"
        ]

        result = {
            'date': today_date_str,
            'close': round(float(df_desc.iloc[0]['close']), 2),
            'volume_ratio': round(float(breakout_info['vol_ratio']), 2),
            'reasons': reasons,
            'key_date': key_date_str,
            'key_date_type': '涨停连板突破日',
            'quality_score': quality_score,
            'pattern_details': {
                'limit_up_count': limit_up_info['limit_up_count'],
                'sideways_days': sideways_info['days'],
                'box_high': round(float(sideways_info['box_high']), 2),
                'box_low': round(float(sideways_info['box_low']), 2),
                'support_price': round(float(sideways_info['support_price']), 2),
            },
            'confirmation_details': {
                'confirmed': True,
                'confirmed_date': today_date_str,
                'support_level': round(float(sideways_info['support_price']), 2),
            },
            'strategy_weight': self.params['strategy_weight'],
        }

        return [result]

    def _find_limit_up_or_continuous(self, df):
        """寻找近期的涨停板或连板事件"""
        lookback = self.params['limit_up_lookback']
        check_df = df.head(lookback + 5).copy()
        
        # 计算涨跌幅
        closes = check_df['close'].values
        pcts = []
        for i in range(len(closes) - 1):
            pcts.append((closes[i] - closes[i+1]) / closes[i+1])
        pcts.append(0.0)
        check_df['pct'] = pcts

        # 标记涨停
        is_lu = check_df['pct'] >= self.params['limit_up_threshold']
        
        # 从今天倒查第 1~lookback 天是否有涨停
        # 寻找离今天最近的一次涨停/连板（且在今天之前，即 index >= 1）
        lu_indices = np.where(is_lu.values[1:lookback+1])[0] + 1
        if len(lu_indices) == 0:
            return None

        # 取横盘前最先涨停的位置（倒序中较大的 index 对应的连板第一天，或最靠近平台的涨停板）
        # 排除 index 0（今天突破日如果是涨停板不作为之前的横盘起点）
        idx = lu_indices[-1]  # 连板/涨停的第一天起点
        
        # 计算连板数量
        lu_count = 0
        curr_idx = idx
        while curr_idx < len(check_df) and check_df.iloc[curr_idx]['pct'] >= self.params['limit_up_threshold']:
            lu_count += 1
            curr_idx += 1

        return {
            'index': idx,
            'date': check_df.iloc[idx]['date'],
            'close': check_df.iloc[idx]['close'],
            'open': check_df.iloc[idx]['open'],
            'volume': check_df.iloc[idx]['volume'],
            'limit_up_count': max(1, lu_count),
            'lookback': idx
        }

    def _check_platform_sideways(self, df, limit_up_info):
        """检查涨停/连板后的平台箱体震荡整理"""
        idx = limit_up_info['index']
        if idx < 1:  # 如果涨停就在今天，还没发生横盘
            return None

        days = idx - 1  # 涨停日与今天之间的横盘天数
        if days < self.params['sideways_days_min'] or days > self.params['sideways_days_max']:
            return None

        # 提取横盘整理段（倒序 index 1 到 idx-1）
        sideways_df = df.iloc[1:idx]
        lu_close = limit_up_info['close']

        # 箱体最高价与最低价
        box_high = sideways_df['high'].max()
        box_low = sideways_df['low'].min()

        # 支撑价位：涨停日收盘价附近
        support_price = lu_close * (1 + self.params['support_drop_limit'])

        # 1. 支撑位防守检查：箱体最低价不深跌跌破支撑位
        if box_low < support_price:
            return None

        # 2. 箱体上沿检查：不大涨拉飞（不超过涨停价 +12%）
        if box_high > lu_close * (1 + self.params['box_high_limit']):
            return None

        # 3. 缩量沉淀检查：期间至少有一天成交量缩至涨停日或整理峰值的指定比例以下
        shrink_limit = limit_up_info['volume'] * self.params['volume_shrink_ratio']
        min_volume = sideways_df['volume'].min()
        if min_volume > shrink_limit:
            return None

        return {
            'days': days,
            'box_high': box_high,
            'box_low': box_low,
            'support_price': support_price,
            'min_vol_ratio': min_volume / max(1, limit_up_info['volume']),
            'sideways_df': sideways_df
        }

    def _check_new_high_breakout(self, df, limit_up_info, sideways_info):
        """检查突破平台最高价且创阶段/历史新高"""
        today_bar = df.iloc[0]
        prev_bar = df.iloc[1]

        # 1. 当日收盘价须突破横盘箱体最高价（或逼近最高价）
        if today_bar['close'] < sideways_info['box_high'] * 0.995:
            return None

        # 2. 涨幅要求
        price_change = (today_bar['close'] - prev_bar['close']) / prev_bar['close']
        if price_change < self.params['breakout_price_pct']:
            return None

        # 3. 成交量放大要求
        vol_ratio = today_bar['volume'] / max(1, prev_bar['volume'])
        if vol_ratio < self.params['breakout_vol_ratio']:
            return None

        # 4. 创历史/阶段新高检查（过去 N 天最高价，除今天外）
        lookback_N = min(len(df) - 1, self.params['new_high_lookback'])
        past_high = df['high'].iloc[1:lookback_N+1].max()

        # 今天收盘价或最高价刷新了近 N 天的新高
        if today_bar['high'] < past_high:
            return None

        return {
            'price_change': price_change,
            'vol_ratio': vol_ratio,
            'past_high': past_high,
        }

    def _calculate_quality_score(self, df, limit_up_info, sideways_info, breakout_info):
        """综合多因子质量评分"""
        score = 60.0

        # 连板加分 (2连板及以上加 15 分)
        if limit_up_info['limit_up_count'] >= 2:
            score += 15.0

        # 极度缩量沉淀加分
        if sideways_info['min_vol_ratio'] <= 0.45:
            score += 10.0

        # 强力放量突破加分
        if breakout_info['vol_ratio'] >= 1.8:
            score += 10.0

        # 涨幅强度加分
        if breakout_info['price_change'] >= 0.05:
            score += 5.0

        return min(100.0, score)
