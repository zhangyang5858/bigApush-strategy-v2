"""
强势涨停横盘一步到位建仓与大盈亏比择时策略 (StrongLimitUpSidewaysTimingStrategy)

核心改进逻辑：
1. 试探/一步到位建仓（满仓/80%~100%）：
   - 不再追高加仓拉高成本！
   - 当选股策略命中后，只要股价在 10 日线附近（低点 <= MA10*1.03 且收盘 >= MA10*0.97）或出现缩量，在底部区域直接一步到位完成建仓（100% 拟投资金）。

2. 阶梯止盈与大盈亏比锁利：
   - 第一阶梯（+15% 目标位）：当获利达到 15% 时，平仓 1/2（平仓一半锁定绝对收益）。
   - 第二阶梯（大主升浪跟踪）：剩余 1/2 仓位开启移动止盈（自最高点回撤 3.5%）或跌破 10日线清仓，让主升浪利润充分飞翔。

3. 资金效率离场（3天不突破则微亏/平价离场）：
   - 建仓后若 3 个交易日内未向上爆发突破（最高涨幅 < 2%），第 4 天自动平仓，释放资金效率。
"""
import pandas as pd
import numpy as np
import datetime
import logging
from typing import Dict, Optional
from trading.timing_strategies import TimingStrategy, TimingResult

logger = logging.getLogger(__name__)


class StrongLimitUpSidewaysTimingStrategy(TimingStrategy):
    """强势涨停横盘一步到位建仓与大盈亏比择时策略"""

    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)

        # 核心控制参数
        self.stop_loss_ratio = float(self.config.get('stop_loss_ratio', 0.04))          # 4% 硬止损
        self.first_target_profit = float(self.config.get('first_target_profit', 0.15))   # 15% 达成第1阶梯止盈（平半仓）
        self.trailing_stop_pullback = float(self.config.get('trailing_stop_pullback', 0.035)) # 最高点回撤 3.5% 止盈
        self.no_breakout_days = int(self.config.get('no_breakout_days', 3))             # 3天不突破离场
        self.max_hold_days = int(self.config.get('max_hold_days', 15))                  # 最长持股 15 天
        self.base_position_amount = float(self.config.get('base_position_amount', 100000.0))

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        result = df.copy()
        if len(result) > 1 and 'date' in result.columns and result['date'].iloc[0] > result['date'].iloc[1]:
            result = result.iloc[::-1].reset_index(drop=True)
            
        result['ma5'] = result['close'].rolling(window=5, min_periods=1).mean()
        result['ma10'] = result['close'].rolling(window=10, min_periods=1).mean()
        return result

    def get_timing_result(
        self,
        df: pd.DataFrame,
        position: Optional[Dict] = None,
        cash: Optional[float] = None,
        use_prev_day_signal: bool = True
    ) -> TimingResult:
        result = TimingResult()

        if df is None or len(df) == 0:
            return result

        df_sorted = self.calculate_indicators(df)
        latest_bar = df_sorted.iloc[-1]
        prev_bar = df_sorted.iloc[-2] if len(df_sorted) >= 2 else latest_bar
        current_price = float(latest_bar['close'])
        trade_price = float(latest_bar.get('open', current_price))
        if trade_price <= 0:
            trade_price = current_price

        total_cash = cash if (cash is not None and cash > 0) else self.base_position_amount

        # ==========================================
        # 1. 无持仓：10日线支撑区一步到位满仓建仓
        # ==========================================
        if not position or position.get('quantity', 0) <= 0:
            ma10_val = float(latest_bar.get('ma10', 0.0))
            
            # 缩量回踩 10 日线支撑判断
            is_near_ma10 = (ma10_val > 0) and (latest_bar['low'] <= ma10_val * 1.03) and (latest_bar['close'] >= ma10_val * 0.97)
            is_shrink_vol = (latest_bar['volume'] <= prev_bar['volume'] * 1.15)

            if is_near_ma10 or is_shrink_vol:
                result.is_buy = True
                result.trade_type = 'buy'
                result.add_count = 0
                result.signal_strength = 0.95
                result.message = f"10 日线支撑区 (MA10={ma10_val:.2f}) 企稳，一步到位满仓建立底仓"

                if trade_price > 0:
                    result.buy_quantity = int(total_cash / trade_price) // 100 * 100
                    if result.buy_quantity < 100 and total_cash >= trade_price * 100:
                        result.buy_quantity = 100
                else:
                    result.buy_quantity = 0

                return result
            else:
                return result

        # ==========================================
        # 2. 已持仓：风控离场、阶梯止盈与资金效率控制
        # ==========================================
        buy_price = float(position.get('buy_price', 0.0))
        quantity = position.get('quantity', 0)
        reduced_count = position.get('reduce_count', 0)

        # 计算持股天数
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

        if buy_price > 0:
            price_change_ratio = (current_price - buy_price) / buy_price

            # A) 硬止损 (-4%)
            low_price = float(latest_bar.get('low', current_price))
            max_drop_ratio = (buy_price - min(current_price, low_price)) / buy_price
            if max_drop_ratio >= self.stop_loss_ratio or price_change_ratio <= -self.stop_loss_ratio:
                result.is_sell = True
                result.trade_type = 'sell'
                result.signal_strength = 1.0
                result.sell_quantity = quantity
                result.message = f"跌破 4% 止损下限，全仓止损离场"
                return result

            # B) 阶梯止盈一：达 +15% 锁定 1/2 收益
            high_price = float(latest_bar.get('high', current_price))
            max_gain_today = (max(current_price, high_price) - buy_price) / buy_price

            if (price_change_ratio >= self.first_target_profit or max_gain_today >= self.first_target_profit) and reduced_count == 0 and quantity >= 200:
                result.is_sell = True
                result.trade_type = 'reduce'
                result.signal_strength = 0.9
                reduce_qty = (quantity // 2) // 100 * 100
                result.sell_quantity = reduce_qty if reduce_qty > 0 else quantity
                result.message = f"涨幅达到 +15% 目标位，平仓 1/2 锁住丰厚利润"
                return result

            # C) 主升浪高位移动止盈（自最高点回撤 3.5% 止盈）
            buy_date_val = position.get('buy_date')
            if buy_date_val and 'date' in df_sorted.columns:
                buy_date_str = str(buy_date_val).split()[0] if not isinstance(buy_date_val, str) else buy_date_val.split()[0]
                holding_df = df_sorted[df_sorted['date'].astype(str) >= buy_date_str]
                if holding_df.empty:
                    holding_df = df_sorted
            else:
                holding_df = df_sorted

            max_price = float(max(holding_df['high'].max() if 'high' in holding_df.columns else holding_df['close'].max(), position.get('highest_price', 0.0)))
            max_price = max(max_price, buy_price)
            max_gain_from_buy = (max_price - buy_price) / buy_price

            if max_gain_from_buy >= 0.08:  # 浮盈 > 8% 激活移动止盈
                pullback_ratio = (max_price - current_price) / max_price if max_price > 0 else 0.0
                if pullback_ratio >= self.trailing_stop_pullback:
                    result.is_sell = True
                    result.trade_type = 'sell'
                    result.signal_strength = 1.0
                    result.sell_quantity = quantity
                    result.message = f"高点 {max_price:.2f} (最高浮盈 {max_gain_from_buy*100:.1f}%) 回撤 {pullback_ratio*100:.1f}%，触发移动止盈清仓"
                    return result

            # D) 跌破 10日均线 (MA10) 波段离场
            ma10_val = float(latest_bar.get('ma10', 0.0))
            if ma10_val > 0 and current_price < ma10_val:
                result.is_sell = True
                result.trade_type = 'sell'
                result.signal_strength = 1.0
                result.sell_quantity = quantity
                result.message = f"跌破 10 日均线 ({current_price:.2f} < MA10 {ma10_val:.2f})，波段趋势结束清仓"
                return result

            # E) 资金效率：建仓后 3 天内未能向上突破（最大浮盈 < 2%），自动平仓换股
            if hold_days >= self.no_breakout_days and max_gain_from_buy < 0.02:
                result.is_sell = True
                result.trade_type = 'sell'
                result.signal_strength = 0.8
                result.sell_quantity = quantity
                result.message = f"建仓{hold_days}天仍未向上爆发突破，微亏/平价平仓释放资金"
                return result

        # 持股超时
        if hold_days >= self.max_hold_days:
            result.is_sell = True
            result.trade_type = 'sell'
            result.signal_strength = 0.8
            result.sell_quantity = quantity
            result.message = f"持股达到上限（{hold_days}天 >= {self.max_hold_days}天），强制清仓"
            return result

        return result
