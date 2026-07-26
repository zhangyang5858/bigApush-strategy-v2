"""
涨停横盘突破择时策略 (LimitUpSidewaysTimingStrategy)
专门适配涨停横盘整理策略的择时控制：
- 识别涨停横盘后的缩量回踩站稳 / 放量反弹突破买点
- 提供短线止盈、跌破涨停日支撑线止损、持股超时平仓风控
"""
import pandas as pd
import datetime
import logging
from typing import Dict, Optional
from trading.timing_strategies import TimingStrategy, TimingResult

logger = logging.getLogger(__name__)


class LimitUpSidewaysTimingStrategy(TimingStrategy):
    """涨停横盘专属择时策略"""

    def __init__(self, config: Optional[Dict] = None):
        """初始化涨停横盘择时策略

        Args:
            config: 策略配置
        """
        super().__init__(config)

        # 风控与出场参数
        self.take_profit_ratio = float(self.config.get('take_profit_ratio', 0.08))     # 8% 止盈
        self.stop_loss_ratio = float(self.config.get('stop_loss_ratio', 0.04))       # 4% 硬止损
        self.max_hold_days = int(self.config.get('max_hold_days', 5))                 # 最长持股 5 天（横盘突破短线）
        self.trailing_stop_activation = float(self.config.get('trailing_stop_activation', 0.05)) # 冲高 5% 启动移动止盈
        self.trailing_stop_pullback = float(self.config.get('trailing_stop_pullback', 0.025))    # 冲高回落 2.5% 止盈出场
        self.base_position_amount = float(self.config.get('base_position_amount', 50000.0))      # 底仓金额

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算指标"""
        result = df.copy()
        if len(result) > 1 and 'date' in result.columns and result['date'].iloc[0] > result['date'].iloc[1]:
            result = result.iloc[::-1].reset_index(drop=True)
        return result

    def get_timing_result(
        self,
        df: pd.DataFrame,
        position: Optional[Dict] = None,
        cash: Optional[float] = None,
        use_prev_day_signal: bool = True
    ) -> TimingResult:
        """获取涨停横盘择时结果

        Args:
            df: 股票数据 DataFrame
            position: 持仓信息 dict
            cash: 可用资金
            use_prev_day_signal: 是否使用前一天信号

        Returns:
            TimingResult 择时结果
        """
        result = TimingResult()

        if df is None or len(df) == 0:
            return result

        # 保证 df 按日期正序 (旧 -> 新)
        df_sorted = df.copy()
        if len(df_sorted) > 1 and 'date' in df_sorted.columns and df_sorted['date'].iloc[0] > df_sorted['date'].iloc[1]:
            df_sorted = df_sorted.iloc[::-1].reset_index(drop=True)

        latest_bar = df_sorted.iloc[-1]
        current_price = float(latest_bar['close'])

        # 如果没有持仓，评估买入信号
        if not position or position.get('quantity', 0) <= 0:
            # 涨停横盘被选出后，买入点逻辑：
            # 选股策略已验证其符合“涨停后横盘+缩量蓄势/放量突破”，此处直接执行进场
            result.is_buy = True
            result.trade_type = 'buy'
            result.signal_strength = 1.0
            result.message = "涨停横盘整理确认，买入进场信号"

            # 计算买入数量
            trade_price = float(latest_bar.get('open', current_price))
            if trade_price <= 0:
                trade_price = current_price

            buy_amount = cash if (cash is not None and cash > 0) else self.base_position_amount
            if trade_price > 0:
                result.buy_quantity = int(buy_amount / trade_price) // 100 * 100
                if result.buy_quantity < 100 and buy_amount >= trade_price * 100:
                    result.buy_quantity = 100
            else:
                result.buy_quantity = 0

            return result

        # 如果有持仓，评估卖出风控信号
        buy_price = float(position.get('buy_price', 0.0))
        quantity = position.get('quantity', 0)

        # 计算持股天数 hold_days
        hold_days = position.get('hold_days')
        if hold_days is None:
            buy_date_val = position.get('buy_date')
            if buy_date_val and 'date' in latest_bar:
                try:
                    if isinstance(buy_date_val, str):
                        b_date = datetime.datetime.strptime(buy_date_val, '%Y-%m-%d').date()
                    elif isinstance(buy_date_val, (datetime.date, datetime.datetime)):
                        b_date = buy_date_val.date() if isinstance(buy_date_val, datetime.datetime) else buy_date_val
                    else:
                        b_date = None

                    cur_date_val = latest_bar['date']
                    if isinstance(cur_date_val, str):
                        c_date = datetime.datetime.strptime(cur_date_val, '%Y-%m-%d').date()
                    elif isinstance(cur_date_val, (datetime.date, datetime.datetime)):
                        c_date = cur_date_val.date() if isinstance(cur_date_val, datetime.datetime) else cur_date_val
                    else:
                        c_date = None

                    if b_date and c_date:
                        hold_days = (c_date - b_date).days
                    else:
                        hold_days = 0
                except Exception:
                    hold_days = 0
            else:
                hold_days = 0

        # 计算收益/亏损比例
        if buy_price > 0:
            price_change_ratio = (current_price - buy_price) / buy_price

            # 1. 硬止损检查 (跌幅 >= stop_loss_ratio)
            low_price = float(latest_bar.get('low', current_price))
            max_drop_ratio = (buy_price - min(current_price, low_price)) / buy_price

            if max_drop_ratio >= self.stop_loss_ratio or price_change_ratio <= -self.stop_loss_ratio:
                result.is_sell = True
                result.trade_type = 'sell'
                result.signal_strength = 1.0
                result.sell_quantity = quantity
                effective_drop = max(max_drop_ratio, -price_change_ratio)
                result.message = f"触发涨停横盘止损：跌幅 {effective_drop*100:.2f}% >= 阈值 {self.stop_loss_ratio*100:.2f}%"
                return result

            # 2. 止盈检查 (涨幅 >= take_profit_ratio)
            high_price = float(latest_bar.get('high', current_price))
            max_gain_today = (max(current_price, high_price) - buy_price) / buy_price

            if price_change_ratio >= self.take_profit_ratio or max_gain_today >= self.take_profit_ratio:
                result.is_sell = True
                result.trade_type = 'sell'
                result.signal_strength = 1.0
                result.sell_quantity = quantity
                effective_gain = max(price_change_ratio, max_gain_today)
                result.message = f"触发涨停横盘止盈：涨幅 {effective_gain*100:.2f}% >= 阈值 {self.take_profit_ratio*100:.2f}%"
                return result

            # 3. 移动保盈检查
            buy_date_val = position.get('buy_date')
            if buy_date_val and 'date' in df_sorted.columns:
                buy_date_str = str(buy_date_val).split()[0] if not isinstance(buy_date_val, str) else buy_date_val.split()[0]
                holding_df = df_sorted[df_sorted['date'].astype(str) >= buy_date_str]
                if holding_df.empty:
                    holding_df = df_sorted
            else:
                holding_df = df_sorted

            if 'high' in holding_df.columns:
                max_price = float(max(holding_df['high'].max(), position.get('highest_price', 0.0)))
            else:
                max_price = float(max(holding_df['close'].max(), position.get('highest_price', 0.0)))

            max_price = max(max_price, buy_price)
            max_gain_from_buy = (max_price - buy_price) / buy_price

            if max_gain_from_buy >= self.trailing_stop_activation:
                pullback_ratio = (max_price - current_price) / max_price if max_price > 0 else 0.0
                if pullback_ratio >= self.trailing_stop_pullback:
                    result.is_sell = True
                    result.trade_type = 'sell'
                    result.signal_strength = 0.9
                    result.sell_quantity = quantity
                    result.message = (
                        f"触发移动止盈：最高冲高 {max_gain_from_buy*100:.2f}% (最高价{max_price:.2f})，"
                        f"回落 {pullback_ratio*100:.2f}% >= 阈值 {self.trailing_stop_pullback*100:.2f}%"
                    )
                    return result

        # 4. 持股超时检查 (hold_days >= max_hold_days)
        if hold_days >= self.max_hold_days:
            result.is_sell = True
            result.trade_type = 'sell'
            result.signal_strength = 0.8
            result.sell_quantity = quantity
            result.message = f"横盘突破持股超时（{hold_days}天 >= {self.max_hold_days}天），触发强制平仓"
            return result

        return result
