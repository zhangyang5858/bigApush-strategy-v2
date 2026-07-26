import unittest
import pandas as pd
from strategy.limit_up_relay_auction_strategy import LimitUpRelayAuctionStrategy
from strategy.strategy_registry import StrategyRegistry


class TestLimitUpRelayAuctionStrategy(unittest.TestCase):
    """首板接力竞价策略单元测试"""

    def setUp(self):
        self.strategy = LimitUpRelayAuctionStrategy()

    def test_relay_auction_selection(self):
        """测试符合所有条件的标准选股场景"""
        # 构造 3 天数据：Day 1 (普通), Day 2 (首板涨停), Day 3 (竞价高开抢筹)
        df = pd.DataFrame({
            'date': ['2026-01-01', '2026-01-02', '2026-01-05'],
            'open': [10.0, 10.2, 11.4],     # Day 3 高开 3.6% (11.4/11.0 - 1 = 0.0363)
            'high': [10.2, 11.0, 11.8],
            'low': [9.8, 10.1, 11.2],
            'close': [10.0, 11.0, 11.5],    # Day 2 涨停 (+10%)
            'volume': [10000, 50000, 4000], # Day 3 竞价成交量 4000 (占比 4000/50000 = 8%)
            'amount': [100000, 550000, 45600000], # Day 3 竞价金额 4560万 (>1500万)
            'turnover_rate': [2.0, 8.0, 1.0]      # Day 2 换手率 8.0%
        })

        signals = self.strategy.select_stocks(df, stock_name="测试股票", stock_code="600000")
        self.assertGreater(len(signals), 0)
        self.assertEqual(signals[0]['reasons'][0], "首板涨停次日竞价高开抢筹")
        self.assertEqual(signals[0]['code'], "600000")
        self.assertEqual(signals[0]['key_date_type'], "首板接力竞价")

    def test_not_first_board(self):
        """测试连板（前日也是涨停）被过滤的情况"""
        # 4天数据，Day 1->Day 2 涨停，Day 2->Day 3 也是涨停，确保 Day 3 前一日是二板而非首板
        df = pd.DataFrame({
            'date': ['2025-12-31', '2026-01-01', '2026-01-02', '2026-01-05'],
            'open': [10.0, 10.0, 11.0, 12.5],
            'high': [10.0, 11.0, 12.1, 12.8],
            'low': [9.8, 10.0, 11.0, 12.2],
            'close': [10.0, 11.0, 12.1, 12.6],    # Day 2 (+10%), Day 3 (+10%)
            'volume': [10000, 50000, 50000, 4000],
            'amount': [100000, 550000, 600000, 45600000],
            'turnover_rate': [2.0, 8.0, 8.0, 1.0]
        })
        signals = self.strategy.select_stocks(df, stock_name="连板股票")
        self.assertEqual(len(signals), 0)

    def test_yesterday_not_limit_up(self):
        """测试昨日未涨停的情况"""
        df = pd.DataFrame({
            'date': ['2026-01-01', '2026-01-02', '2026-01-05'],
            'open': [10.0, 10.0, 11.0],
            'high': [10.2, 10.5, 11.4],
            'low': [9.8, 9.9, 10.8],
            'close': [10.0, 10.4, 11.0],    # Day 2 仅涨 4%
            'volume': [10000, 50000, 4000],
            'amount': [100000, 550000, 45600000],
            'turnover_rate': [2.0, 8.0, 1.0]
        })
        signals = self.strategy.select_stocks(df, stock_name="未涨停股票")
        self.assertEqual(len(signals), 0)

    def test_turnover_out_of_bounds(self):
        """测试换手率低于 5% 或高于 20% 被过滤"""
        # 换手率 3% (< 5%)
        df_low_turnover = pd.DataFrame({
            'date': ['2026-01-01', '2026-01-02', '2026-01-05'],
            'open': [10.0, 10.2, 11.4],
            'high': [10.2, 11.0, 11.8],
            'low': [9.8, 10.1, 11.2],
            'close': [10.0, 11.0, 11.5],
            'volume': [10000, 50000, 4000],
            'amount': [100000, 550000, 45600000],
            'turnover_rate': [2.0, 3.0, 1.0]
        })
        self.assertEqual(len(self.strategy.select_stocks(df_low_turnover)), 0)

        # 换手率 25% (> 20%)
        df_high_turnover = df_low_turnover.copy()
        df_high_turnover['turnover_rate'] = [2.0, 25.0, 1.0]
        self.assertEqual(len(self.strategy.select_stocks(df_high_turnover)), 0)

    def test_open_ratio_out_of_bounds(self):
        """测试高开比例不在 2%~6% 之间被过滤"""
        # 高开仅 1% (11.11 / 11.0 - 1 = 0.01)
        df_low_open = pd.DataFrame({
            'date': ['2026-01-01', '2026-01-02', '2026-01-05'],
            'open': [10.0, 10.2, 11.11],
            'high': [10.2, 11.0, 11.8],
            'low': [9.8, 10.1, 11.0],
            'close': [10.0, 11.0, 11.5],
            'volume': [10000, 50000, 4000],
            'amount': [100000, 550000, 45600000],
            'turnover_rate': [2.0, 8.0, 1.0]
        })
        self.assertEqual(len(self.strategy.select_stocks(df_low_open)), 0)

        # 高开 8% (11.88 / 11.0 - 1 = 0.08)
        df_high_open = df_low_open.copy()
        df_high_open['open'] = [10.0, 10.2, 11.88]
        self.assertEqual(len(self.strategy.select_stocks(df_high_open)), 0)

    def test_insufficient_auction_amount_and_volume(self):
        """测试竞价金额 < 1500万 且 竞价量占比 < 5% 被过滤"""
        df = pd.DataFrame({
            'date': ['2026-01-01', '2026-01-02', '2026-01-05'],
            'open': [10.0, 10.2, 11.4],
            'high': [10.2, 11.0, 11.8],
            'low': [9.8, 10.1, 11.2],
            'close': [10.0, 11.0, 11.5],
            'volume': [10000, 50000, 1000],     # 竞价量占比 1000/50000 = 2% (< 5%)
            'amount': [100000, 550000, 500000], # 竞价金额 50万 (< 1500万)
            'turnover_rate': [2.0, 8.0, 1.0]
        })
        signals = self.strategy.select_stocks(df, stock_name="弱竞价股票")
        self.assertEqual(len(signals), 0)

    def test_st_and_delisted_stocks(self):
        """测试 ST 或退市股票被过滤"""
        df = pd.DataFrame({
            'date': ['2026-01-01', '2026-01-02', '2026-01-05'],
            'open': [10.0, 10.2, 11.4],
            'high': [10.2, 11.0, 11.8],
            'low': [9.8, 10.1, 11.2],
            'close': [10.0, 11.0, 11.5],
            'volume': [10000, 50000, 4000],
            'amount': [100000, 550000, 45600000],
            'turnover_rate': [2.0, 8.0, 1.0]
        })
        self.assertEqual(len(self.strategy.select_stocks(df, stock_name="ST股票")), 0)
        self.assertEqual(len(self.strategy.select_stocks(df, stock_name="*ST某某")), 0)
        self.assertEqual(len(self.strategy.select_stocks(df, stock_name="退市某某")), 0)

    def test_descending_dataframe_support(self):
        """测试倒序 DataFrame 输入时的选股兼容性"""
        df_desc = pd.DataFrame({
            'date': ['2026-01-05', '2026-01-02', '2026-01-01'],
            'open': [11.4, 10.2, 10.0],
            'high': [11.8, 11.0, 10.2],
            'low': [11.2, 10.1, 9.8],
            'close': [11.5, 11.0, 10.0],
            'volume': [4000, 50000, 10000],
            'amount': [45600000, 550000, 100000],
            'turnover_rate': [1.0, 8.0, 2.0]
        })
        signals = self.strategy.select_stocks(df_desc, stock_name="倒序测试股票")
        self.assertGreater(len(signals), 0)
        self.assertEqual(signals[0]['reasons'][0], "首板涨停次日竞价高开抢筹")

    def test_strategy_registry(self):
        """测试 StrategyRegistry 成功注册和加载策略"""
        registry = StrategyRegistry()
        strategy_instance = registry.register(LimitUpRelayAuctionStrategy)
        self.assertIsNotNone(strategy_instance)
        self.assertEqual(strategy_instance.name, "首板接力竞价")
        self.assertEqual(strategy_instance.metadata.get('display_name'), "首板接力竞价")

    def test_quality_score_calculation(self):
        """测试多因子质量打分模型计算逻辑"""
        # 黄金高开 4.0% (40分), 爆量比 15% (40分), 黄金换手 10.0% (20分) -> 100 分
        score_full = self.strategy.calculate_quality_score(0.04, 0.15, 10.0)
        self.assertEqual(score_full, 100.0)

        # 衰减区间测试: 高开 2.75% (20分), 爆量比 7.5% (20分), 换手率 6.75% (10分) -> 50分
        score_half = self.strategy.calculate_quality_score(0.0275, 0.075, 6.75)
        self.assertEqual(score_half, 50.0)

    def test_top_n_truncation_and_quality_score_ranking(self):
        """测试包含多只候选股票时的 Top 5 截断与 Quality Score 排序断言"""
        # 构造 7 只不同的候选股票结果字典
        candidates = []
        scores_expected = [100.0, 95.0, 85.0, 70.0, 60.0, 45.0, 30.0]
        for i, score in enumerate(scores_expected):
            candidates.append({
                'code': f'60000{i}',
                'name': f'测试股票{i}',
                'quality_score': score,
                'signals': [{'code': f'60000{i}', 'quality_score': score}]
            })

        # 逆序输入（故意将打分较低的排在前面）
        input_candidates = list(reversed(candidates))

        # 执行 post_process_selection
        selected = self.strategy.post_process_selection(input_candidates)

        # 断言结果数量被截截在 max_top_n (5只)
        self.assertEqual(len(selected), 5)

        # 断言结果按 quality_score 降序排列
        scores_returned = [item['quality_score'] for item in selected]
        self.assertEqual(scores_returned, [100.0, 95.0, 85.0, 70.0, 60.0])

        # 测试自定义 max_top_n = 3
        self.strategy.params['max_top_n'] = 3
        selected_3 = self.strategy.post_process_selection(input_candidates)
        self.assertEqual(len(selected_3), 3)
        self.assertEqual([item['quality_score'] for item in selected_3], [100.0, 95.0, 85.0])

    def test_web_server_format_truncation(self):
        """测试 Web Server 返回结构 (含 strategy_display_name 包装) 下的 Top 5 截断"""
        web_candidates = []
        for i in range(10):
            score = float(100 - i * 5)
            web_candidates.append({
                'code': f'6000{i:02d}',
                'name': f'测试股票{i}',
                'signals': [{'code': f'6000{i:02d}', 'quality_score': score}],
                'strategy_display_name': '首板接力竞价'
            })
        self.strategy.params['max_top_n'] = 5
        selected = self.strategy.post_process_selection(web_candidates)
        self.assertEqual(len(selected), 5)
        top_scores = [item['signals'][0]['quality_score'] for item in selected]
        self.assertEqual(top_scores, [100.0, 95.0, 90.0, 85.0, 80.0])


if __name__ == '__main__':
    unittest.main()

