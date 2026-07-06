"""
爬虫模块测试用例
===============
测试内容：
  1. OMDB API 标题映射（不依赖网络）
  2. 爬虫数据解析逻辑（模拟 HTML）
  3. 数据清洗函数

运行：
    cd movie_analysis_system
    python tests/test_crawler.py
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawler.omdb_api import OMDBApi
from crawler.maoyan_spider import MaoyanSpider


class TestOMDBAPIMapping(unittest.TestCase):
    """OMDB API 英文片名映射测试（不联网）。"""

    def setUp(self):
        self.api = OMDBApi()

    def test_en_title_map_contains_chinese_movies(self):
        """验证英文片名映射表包含关键电影。"""
        important_movies = {
            "流浪地球2": "The Wandering Earth 2",
            "哪吒之魔童降世": "Ne Zha",
            "我不是药神": "Dying to Survive",
            "你好李焕英": "Hi Mom",
            "长津湖": "The Battle at Lake Changjin",
        }
        for cn, en in important_movies.items():
            mapped = self.api.get_en_title(cn)
            self.assertEqual(mapped, en, f"映射缺失: {cn} → 应得 {en}, 实际 {mapped}")

    def test_unknown_title_returns_original(self):
        """未知电影返回原中文标题（get_en_title 不回退 None）。"""
        result = self.api.get_en_title("一部不存在的电影xxxxxxxx")
        self.assertEqual(result, "一部不存在的电影xxxxxxxx")

    def test_empty_title_returns_empty(self):
        """空标题返回空字符串。"""
        result = self.api.get_en_title("")
        self.assertEqual(result, "")

    def test_extract_plot_from_omdb_data(self):
        """测试从 OMDB 数据中提取剧情简介。"""
        data = {"Plot": "A test plot for unit testing."}
        plot = OMDBApi.extract_plot(data)
        self.assertEqual(plot, "A test plot for unit testing.")

    def test_extract_plot_missing(self):
        """缺失 Plot 字段返回空字符串。"""
        data = {"Title": "Test"}
        plot = OMDBApi.extract_plot(data)
        self.assertEqual(plot, "")

    def test_extract_plot_na(self):
        """Plot 为 N/A 返回 'N/A'。"""
        data = {"Plot": "N/A"}
        plot = OMDBApi.extract_plot(data)
        self.assertEqual(plot, "N/A")

    def test_extract_genre(self):
        """测试提取类型（保持英文格式）。"""
        data = {"Genre": "Action, Sci-Fi, Thriller"}
        genre = OMDBApi.extract_genre(data)
        self.assertEqual(genre, "Action;Sci-Fi;Thriller")

    def test_extract_genre_na(self):
        """类型为 N/A 返回 'N/A'。"""
        data = {"Genre": "N/A"}
        genre = OMDBApi.extract_genre(data)
        self.assertEqual(genre, "N/A")

    def test_extract_actors(self):
        """测试提取演员表。"""
        data = {"Actors": "Robert Downey Jr., Chris Evans, Scarlett Johansson"}
        actors = OMDBApi.extract_actors(data)
        self.assertIn("Robert Downey Jr.", actors)
        self.assertIn(";", actors)

    def test_extract_poster(self):
        """测试提取海报 URL。"""
        data = {"Poster": "https://example.com/poster.jpg"}
        poster = OMDBApi.extract_poster(data)
        self.assertEqual(poster, "https://example.com/poster.jpg")

    def test_extract_poster_na(self):
        """海报为 N/A 返回 'N/A'。"""
        data = {"Poster": "N/A"}
        poster = OMDBApi.extract_poster(data)
        self.assertEqual(poster, "N/A")

    def test_extract_rating(self):
        """测试提取 IMDB 评分。"""
        data = {"imdbRating": "8.5"}
        rating = OMDBApi.extract_rating(data)
        self.assertEqual(rating, 8.5)

    def test_extract_rating_na(self):
        """评分为 N/A 返回 0。"""
        data = {"imdbRating": "N/A"}
        rating = OMDBApi.extract_rating(data)
        self.assertEqual(rating, 0)

    def test_extract_runtime(self):
        """测试提取片长。"""
        data = {"Runtime": "142 min"}
        runtime = OMDBApi.extract_runtime(data)
        self.assertEqual(runtime, 142)

    def test_extract_runtime_na(self):
        """片长为 N/A 返回 0。"""
        data = {"Runtime": "N/A"}
        runtime = OMDBApi.extract_runtime(data)
        self.assertEqual(runtime, 0)


class TestMaoyanSpiderParsing(unittest.TestCase):
    """猫眼爬虫 HTML 解析测试（模拟数据，不联网）。"""

    def setUp(self):
        self.spider = MaoyanSpider()

    def test_parse_empty_html(self):
        """空 HTML 返回空列表。"""
        movies = self.spider._parse_list("")
        self.assertEqual(movies, [])

    def test_parse_no_movie_items(self):
        """没有 movie-item 的 HTML 返回空列表。"""
        html = "<html><body><p>no movies here</p></body></html>"
        movies = self.spider._parse_list(html)
        self.assertEqual(movies, [])

    def test_parse_mock_html(self):
        """模拟一个简单的电影条目 HTML。"""
        html = """
        <div class="movie-item film-channel">
            <a href="/films/12345"></a>
            <span class="name">测试电影</span>
            <span class="score">8.5</span>
            类型:</span>动作,科幻
            主演:</span>演员A,演员B
            上映时间:</span>2026-01-15
            <img data-src="https://example.com/poster.jpg" />
        </div>
        """
        movies = self.spider._parse_list(html)
        self.assertEqual(len(movies), 1)
        self.assertEqual(movies[0]["title"], "测试电影")
        self.assertEqual(movies[0]["maoyan_id"], "12345")
        self.assertEqual(movies[0]["rating"], 8.5)
        self.assertIn("动作", movies[0]["genre"])
        self.assertIn("演员A", movies[0]["actors"])
        self.assertEqual(movies[0]["release_date"], "2026-01-15")
        self.assertIn("poster.jpg", movies[0]["poster_url"])

    def test_parse_missing_fields(self):
        """解析时缺失字段不报错。"""
        html = """
        <div class="movie-item film-channel">
            <span class="name">只有标题</span>
        </div>
        """
        movies = self.spider._parse_list(html)
        # 没有 maoyan_id 的有效电影
        self.assertEqual(len(movies), 0)

    def test_parse_multiple_movies(self):
        """多个电影条目。"""
        html = """
        <div class="movie-item film-channel">
            <a href="/films/1"></a>
            <span class="name">电影A</span>
            <img data-src="https://example.com/a.jpg" />
        </div>
        <div class="movie-item film-channel">
            <a href="/films/2"></a>
            <span class="name">电影B</span>
            <img data-src="https://example.com/b.jpg" />
        </div>
        """
        movies = self.spider._parse_list(html)
        self.assertEqual(len(movies), 2)
        self.assertEqual(movies[0]["title"], "电影A")
        self.assertEqual(movies[1]["title"], "电影B")


if __name__ == "__main__":
    unittest.main(verbosity=2)
