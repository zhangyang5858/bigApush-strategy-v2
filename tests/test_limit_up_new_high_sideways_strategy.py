"""
涨停新高横盘选股策略单元测试 (LimitUpNewHighSidewaysStrategy Tests)
"""
import unittest
import pandas as pd
from strategy.limit_up_new_high_sideways_strategy import LimitUpNewHighSidewaysStrategy


class TestLimitUpNewHighSidewaysStrategy(unittest.TestCase):
    """测试 LimitUpNewHighSidewaysStrategy"""

    def setUp(self):
        self.strategy = LimitUpNewHighSidewaysStrategy()

    def test_quick_filter_and_selection(self):
        """模拟近 250 天走势：底位震荡 -> 连板放量 -> 4天极度缩量横盘 -> 今天大阳线突破创历史新高"""
        dates = pd.date_range(end='2026-07-24', periods=260, freq='B')
        
        data = []
        # 前 250 天：价格在 15~22 附近缓慢震荡
        for i, d in enumerate(dates[:250]):
            data.append({
                'date': d.strftime('%Y-%m-%d'),
                'open': 20.0,
                'high': 22.0,
                'low': 19.0,
                'close': 21.0,
                'volume': 50000
            })
            
        # 第 251 天 (2026-07-17)：首板涨停 突破 22 元历史高点到 23.1 元
        data.append({
            'date': dates[251].strftime('%Y-%m-%d'),
            'open': 21.0,
            'high': 23.1,
            'low': 21.0,
            'close': 23.1, # +10% 涨停
            'volume': 200000 # 爆量
        })

        # 第 252~255 天 (2026-07-20~07-23)：4天极度缩量横盘整理（不破 23.1 支撑，成交量缩至 70000）
        for i in range(252, 256):
            data.append({
                'date': dates[i].strftime('%Y-%m-%d'),
                'open': 23.2,
                'high': 24.0,
                'low': 22.9, # 守住 23.1 - 2% 支撑
                'close': 23.5,
                'volume': 70000 # 极度缩量
            })

        # 第 256 天 (2026-07-24)：放量大阳线突破平台，收盘 25.5 创历史新高
        data.append({
            'date': dates[256].strftime('%Y-%m-%d'),
            'open': 23.6,
            'high': 25.8,
            'low': 23.5,
            'close': 25.5, # 放量上涨突破新高
            'volume': 160000
        })

        df = pd.DataFrame(data)

        # 执行选股测试 (df 为升序，选股内部自动处理)
        results = self.strategy.select_stocks(df)
        
        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res['date'], '2026-07-21')
        self.assertEqual(res['close'], 25.5)
        self.assertIn('历史新高', res['reasons'][1])
        self.assertGreaterEqual(res['quality_score'], 70)


if __name__ == '__main__':
    unittest.main()
