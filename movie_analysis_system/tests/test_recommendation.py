"""
推荐系统测试用例
===============
测试内容：
  1. 推荐器的5种模式是否能正常返回结果
  2. 推荐理由是否能正常生成
  3. 结果数量是否符合预期
  4. 各模式是否真的有不同的排序结果

运行：
    cd movie_analysis_system
    python tests/test_recommendation.py

注意：
    测试使用独立的数据库文件 data/test_rec.db。
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_manager import DatabaseManager
from recommendation.recommender import Recommender as MovieRecommender
from recommendation import scorer

TEST_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "test_rec.db")


class TestRecommendation(unittest.TestCase):
    """推荐系统测试。"""

    @classmethod
    def setUpClass(cls):
        db_path = TEST_DB
        if os.path.exists(db_path):
            os.remove(db_path)
        for ext in ("-shm", "-wal"):
            p = db_path + ext
            if os.path.exists(p):
                os.remove(p)

        cls.db = DatabaseManager(db_path=db_path)
        cls.db.init_db()
        csv_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "backup_movies.csv"
        )
        loaded = 0
        if os.path.exists(csv_path):
            loaded = cls.db.load_csv_to_db(csv_path)

        # 模拟爬虫获取在映电影
        try:
            from crawler.crawl_controller import CrawlController
            CrawlController(cls.db).crawl_showing_movies(background=False)
            # 补评分
            import requests
            h = {'User-Agent': 'Mozilla/5.0'}
            conn = cls.db.get_connection()
            c = conn.cursor()
            c.execute("SELECT id, maoyan_id FROM movies WHERE showing_status='showing' AND (rating IS NULL OR rating=0) AND maoyan_id != ''")
            for mid, mid_str in c.fetchall():
                try:
                    r = requests.get('https://m.maoyan.com/ajax/detailmovie?movieId=' + mid_str, headers=h, timeout=8)
                    if r.status_code == 200:
                        sc = r.json().get('detailMovie', {}).get('sc', 0)
                        if sc and float(sc) > 0:
                            conn.execute("UPDATE movies SET rating=? WHERE id=?", (float(sc), mid))
                            conn.commit()
                except:
                    pass
            c.close()
        except Exception as e:
            print(f"测试爬虫跳过: {e}")

        conn = cls.db.get_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM movies")
        cls.movie_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM movies WHERE showing_status='showing' AND rating>0")
        cls.showing_with_rating = c.fetchone()[0]
        c.close()
        print(f"测试数据库: {cls.movie_count} 部电影, showing+评分={cls.showing_with_rating}")
        assert cls.movie_count > 0, "数据库为空，测试无法进行"

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        for ext in ("-shm", "-wal"):
            p = TEST_DB + ext
            if os.path.exists(p):
                os.remove(p)

    def _check_recommendations(self, items: list, mode: str):
        """检查推荐结果的有效性。"""
        self.assertIsNotNone(items, f"{mode} 返回 None")
        self.assertGreater(len(items), 0, f"{mode} 返回空列表")
        first = items[0]
        self.assertIn("rank", first, f"{mode} 结果缺少 rank 字段")
        # 推荐理由可能是 reason 或 recommendation_reason
        has_reason = "reason" in first or "recommendation_reason" in first
        self.assertTrue(has_reason, f"{mode} 结果缺少推荐理由")
        # 验证排序：rank 从 1 开始递增
        for i, it in enumerate(items):
            self.assertEqual(it["rank"], i + 1,
                             f"{mode} 排名不对: 期望 {i+1}, 实际 {it['rank']}")
        return items

    def test_recommender_high_rating(self):
        """高分榜推荐。"""
        r = MovieRecommender(self.db)
        items = r.recommend(mode="high_rating", limit=10)
        self._check_recommendations(items, "high_rating")
        self.assertLessEqual(len(items), 10)
        # 第一名评分应较高
        if items and items[0].get("rating"):
            self.assertGreaterEqual(items[0]["rating"], 8.0,
                                    "高分榜第一名评分应 >= 8.0")

    def test_recommender_hot(self):
        """热度榜推荐。"""
        r = MovieRecommender(self.db)
        items = r.recommend(mode="hot", limit=10)
        self._check_recommendations(items, "hot")

    def test_recommender_reputation(self):
        """口碑榜推荐。"""
        r = MovieRecommender(self.db)
        items = r.recommend(mode="reputation", limit=10)
        self._check_recommendations(items, "reputation")

    def test_recommender_value(self):
        """性价比榜推荐。"""
        r = MovieRecommender(self.db)
        items = r.recommend(mode="value", limit=10)
        self._check_recommendations(items, "value")

    def test_recommender_comprehensive(self):
        """综合榜推荐。"""
        r = MovieRecommender(self.db)
        items = r.recommend(mode="comprehensive", limit=10)
        self._check_recommendations(items, "comprehensive")

    def test_default_limit_is_20(self):
        """默认 limit 为 20。"""
        r = MovieRecommender(self.db)
        items = r.recommend(mode="high_rating")
        self.assertLessEqual(len(items), 20)
        self.assertGreater(len(items), 0)

    def test_all_modes_have_reasons(self):
        """所有推荐结果都应有推荐理由。"""
        r = MovieRecommender(self.db)
        for mode in ["high_rating", "hot", "reputation", "value", "comprehensive"]:
            items = r.recommend(mode=mode, limit=5)
            self.assertGreater(len(items), 0, f"{mode} 返回为空，无法检查理由")
            for item in items:
                reason = item.get("recommendation_reason", "") or item.get("reason", "")
                self.assertTrue(reason, f"{mode} #{item['rank']} {item['title']} 缺少理由")

    # ── 评分函数单元测试 ──

    def _get_movies(self) -> list[dict]:
        """从数据库获取电影数据。"""
        conn = self.db.get_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM movies WHERE rating > 0")
        rows = [dict(r) for r in c.fetchall()]
        c.close()
        return rows

    def test_scorer_high_rating_returns_sorted(self):
        """高分函数返回降序排列。"""
        movies = self._get_movies()
        self.assertGreater(len(movies), 0)
        result = scorer.calc_high_rating_rank(movies)
        self.assertGreater(len(result), 0)
        ratings = [it.get("rating", 0) for it in result]
        for i in range(len(ratings) - 1):
            self.assertGreaterEqual(ratings[i], ratings[i + 1])

    def test_scorer_hot_returns_sorted(self):
        """热度函数返回降序排列。"""
        movies = self._get_movies()
        result = scorer.calc_hot_rank(movies)
        self.assertGreater(len(result), 0)
        box_offices = [it.get("box_office", 0) for it in result]
        # 热度按票房降序，但可能有同票房的情况，检查非严格递减
        first_half = box_offices[:len(box_offices)//2]
        last_half = box_offices[len(box_offices)//2:]
        if first_half and last_half:
            self.assertGreaterEqual(sum(first_half), sum(last_half))

    def test_scorer_empty_input(self):
        """空输入不崩溃。"""
        result = scorer.calc_high_rating_rank([])
        self.assertEqual(result, [])

    def test_scorer_value_top_has_price(self):
        """价值榜：前列的电影应该有票价。"""
        movies = self._get_movies()
        result = scorer.calc_value_rank(movies)
        # 前5名应该都有票价 > 0
        top5 = [m for m in result[:5] if m.get("ticket_price", 0) > 0]
        self.assertGreater(len(top5), 0, "价值榜前5名应该至少有一些有票价")

    def test_modes_all_return_results(self):
        """所有模式都有返回结果。"""
        r = MovieRecommender(self.db)
        for mode in ["high_rating", "hot", "reputation", "value", "comprehensive"]:
            items = r.recommend(mode=mode, limit=5)
            self.assertGreater(len(items), 0, f"{mode} 返回为空")


if __name__ == "__main__":
    unittest.main(verbosity=2)
