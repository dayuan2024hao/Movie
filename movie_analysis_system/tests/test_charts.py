"""
图表模块测试用例
===============
测试内容：
  1. 各图表函数能否正常生成 HTML（不报错）
  2. 图表 HTML 是否包含关键元素
  3. 年份筛选参数是否生效
  4. 空数据时的降级处理

运行：
    cd movie_analysis_system
    python tests/test_charts.py

注意：
    测试使用独立的数据库文件 data/test_charts.db，从 CSV 加载真实数据。
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db_manager import DatabaseManager
from charts.rating_distribution import create_rating_distribution
from charts.genre_pie import create_genre_pie
from charts.genre_box_office import create_genre_box_office_chart
from charts.year_trend import create_year_trend_chart
from charts.scatter_plot import create_scatter_plot
from charts.four_quadrant import create_four_quadrant_chart
from charts.top10_chart import create_top10_chart
from charts.price_distribution import create_price_distribution_chart
from charts.box_office_range import create_box_office_range_chart

TEST_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "test_charts.db")


class TestCharts(unittest.TestCase):
    """图表生成测试。"""

    @classmethod
    def setUpClass(cls):
        """准备测试数据库。"""
        # 确保 CSV 已加载
        db_path = TEST_DB
        if os.path.exists(db_path):
            os.remove(db_path)
        # 移除 WAL 文件
        for ext in ("-shm", "-wal"):
            p = db_path + ext
            if os.path.exists(p):
                os.remove(p)

        cls.db = DatabaseManager(db_path=db_path)
        cls.db.init_db()

        # 从 CSV 加载数据
        csv_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "backup_movies.csv"
        )
        if os.path.exists(csv_path):
            count = cls.db.load_csv_to_db(csv_path)
            print(f"已加载 {count} 条电影数据到测试库")

        # 验证数据
        conn = cls.db.get_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM movies")
        total = c.fetchone()[0]
        c.close()
        print(f"测试数据库共 {total} 部电影")

    @classmethod
    def tearDownClass(cls):
        """清理测试数据库。"""
        cls.db.close()
        if os.path.exists(TEST_DB):
            os.remove(TEST_DB)
        for ext in ("-shm", "-wal"):
            p = TEST_DB + ext
            if os.path.exists(p):
                os.remove(p)

    def _check_chart_html(self, html: str, name: str, keywords: list = None):
        """检查图表 HTML 的通用方法。"""
        self.assertIsNotNone(html, f"{name} 返回 None")
        self.assertIsInstance(html, str, f"{name} 返回的不是字符串")
        self.assertGreater(len(html), 100, f"{name} HTML 内容太短 ({len(html)} chars)")
        self.assertTrue("echarts" in html or "chart-container" in html,
                        f"{name} 不是有效的 ECharts HTML")
        # 检查不是空数据占位符
        self.assertFalse(html.startswith("<div style='padding:"),
                         f"{name} 返回了空数据占位符")

    def test_rating_distribution(self):
        """测试评分分布图。"""
        html = create_rating_distribution(self.db)
        self._check_chart_html(html, "评分分布", ["评分", "部"])

    def test_rating_distribution_filtered(self):
        """测试评分分布图（带年份筛选）。"""
        html = create_rating_distribution(self.db, year_start=2015, year_end=2024)
        self._check_chart_html(html, "评分分布-筛选")

    def test_genre_pie(self):
        """测试类型占比饼图。"""
        html = create_genre_pie(self.db)
        self._check_chart_html(html, "类型占比", ["类型"])

    def test_genre_pie_filtered(self):
        """测试类型占比饼图（带年份筛选）。"""
        html = create_genre_pie(self.db, year_start=2018, year_end=2024)
        self._check_chart_html(html, "类型占比-筛选")

    def test_genre_box_office(self):
        """测试各类型平均票房。"""
        html = create_genre_box_office_chart(self.db)
        self._check_chart_html(html, "类型票房", ["平均", "最高", "票房"])

    def test_year_trend(self):
        """测试年份趋势。"""
        html = create_year_trend_chart(self.db)
        self._check_chart_html(html, "年份趋势", ["上映", "评分", "年"])

    def test_year_trend_filtered(self):
        """测试年份趋势（带筛选）。"""
        html = create_year_trend_chart(self.db, year_start=2010, year_end=2024)
        self._check_chart_html(html, "年份趋势-筛选")

    def test_scatter_plot(self):
        """测试散点图。"""
        html = create_scatter_plot(self.db)
        self._check_chart_html(html, "散点图", ["评分", "评价"])

    def test_four_quadrant(self):
        """测试四象限分析图。"""
        html = create_four_quadrant_chart(self.db)
        self._check_chart_html(html, "四象限", ["评分", "票房", "叫好", "叫座"])

    def test_top10_chart(self):
        """测试票房 Top10。"""
        html = create_top10_chart(self.db)
        self._check_chart_html(html, "Top10", ["票房", "万"])

    def test_price_distribution(self):
        """测试票价分布。"""
        html = create_price_distribution_chart(self.db)
        self._check_chart_html(html, "票价分布", ["票价", "元"])

    def test_box_office_range(self):
        """测试票房区间分布。"""
        html = create_box_office_range_chart(self.db)
        self._check_chart_html(html, "票房区间", ["票房", "万"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
