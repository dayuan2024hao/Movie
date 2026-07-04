"""
看板页面
========
数据看板主页面 — 9 张图表 + 5 统计卡片 + 洞察摘要 + 数据表格。
布局：
  行1: 5 个统计卡片
  行2: 票房 Top 10（全宽）
  行3: 评分分布（左3/5）| 类型占比（右2/5）
  行4: 票房区间分布（左1/2）| 票价分布（右1/2）
  行5: 各类型平均票房（全宽）
  行6: 年份趋势分析（全宽，双轴折线图）
  行7: 四象限分析（左1/2）| 评分 vs 票房散点（右1/2）
  行8: 数据洞察摘要
  行9: 数据表格
"""

import logging
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QSizePolicy, QFrame,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWebEngineWidgets import QWebEngineView

from database.db_manager import DatabaseManager
from ui.widgets.stat_card import StatCard
from ui.widgets.movie_table import MovieTable
from charts.chart_engine import ChartEngine
from charts import (
    top10_chart, rating_distribution, genre_pie, scatter_plot,
    box_office_range, price_distribution, genre_box_office,
    four_quadrant, year_trend,
)

logger = logging.getLogger("DashboardPage")

# 图表通用背景样式
CHART_CARD_STYLE = "background: white; border-radius: 8px; min-height: 300px;"


class DashboardPage(QWidget):
    """数据看板页面 — 8 张图表 + 统计卡片。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db: Optional[DatabaseManager] = None
        self._stat_cards: list[StatCard] = []

        self._setup_ui()

    def set_db(self, db: DatabaseManager) -> None:
        """设置数据库引用并加载数据。

        Args:
            db: 数据库管理器实例
        """
        self.db = db
        self._load_data()

    def _setup_ui(self) -> None:
        """构建页面布局（内容放入 ScrollArea）。"""
        # 外层滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("dashboardScroll")
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        content.setObjectName("dashboardContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(0)

        # 页面标题
        title = QLabel("数据看板")
        title.setFont(QFont("Microsoft YaHei", 20, QFont.Bold))
        title.setStyleSheet("color: #37474F; margin-bottom: 16px;")
        layout.addWidget(title)

        # ─── 行 1：统计卡片 ───
        card_row = QWidget()
        card_row.setObjectName("statCardRow")
        card_layout = QHBoxLayout(card_row)
        card_layout.setContentsMargins(0, 0, 0, 16)
        card_layout.setSpacing(16)

        card_configs = [
            ("电影总数", "0", "🎬", "#1E88E5"),
            ("总票房(万)", "0", "💰", "#43A047"),
            ("平均评分", "0.0", "⭐", "#FB8C00"),
            ("平均票价(元)", "0", "🎫", "#8E24AA"),
            ("最高评分", "0.0", "🏆", "#E53935"),
        ]
        for title_text, default_val, icon, color in card_configs:
            card = StatCard(title_text, default_val, icon, color)
            self._stat_cards.append(card)
            card_layout.addWidget(card)

        card_layout.addStretch()
        layout.addWidget(card_row)

        # ─── 行 2：票房 Top 10（全宽） ───
        self.top10_view = QWebEngineView()
        self.top10_view.setObjectName("chartTop10")
        self.top10_view.setMinimumHeight(380)
        self.top10_view.setStyleSheet(CHART_CARD_STYLE)
        layout.addWidget(self.top10_view, 1)

        # ─── 行 3：评分分布（左） + 类型占比（右） ───
        row3 = QWidget()
        r3l = QHBoxLayout(row3)
        r3l.setContentsMargins(0, 16, 0, 16)
        r3l.setSpacing(16)

        # 左：评分分布
        r3_left = self._make_chart_card()
        r3_left_l = QVBoxLayout(r3_left)
        r3_left_l.setContentsMargins(0, 0, 0, 0)
        self.rating_view = QWebEngineView()
        self.rating_view.setMinimumHeight(300)
        r3_left_l.addWidget(self.rating_view)
        r3l.addWidget(r3_left, 3)

        # 右：类型占比
        r3_right = self._make_chart_card()
        r3_right_l = QVBoxLayout(r3_right)
        r3_right_l.setContentsMargins(0, 0, 0, 0)
        self.genre_view = QWebEngineView()
        self.genre_view.setMinimumHeight(300)
        r3_right_l.addWidget(self.genre_view)
        r3l.addWidget(r3_right, 2)

        layout.addWidget(row3)

        # ─── 行 4：票房区间分布（左1/2） + 票价分布（右1/2） ───
        row4 = QWidget()
        r4l = QHBoxLayout(row4)
        r4l.setContentsMargins(0, 0, 0, 16)
        r4l.setSpacing(16)

        # 左：票房区间分布
        r4_left = self._make_chart_card()
        r4_left_l = QVBoxLayout(r4_left)
        r4_left_l.setContentsMargins(0, 0, 0, 0)
        self.box_office_range_view = QWebEngineView()
        self.box_office_range_view.setMinimumHeight(300)
        r4_left_l.addWidget(self.box_office_range_view)
        r4l.addWidget(r4_left, 1)

        # 右：票价分布
        r4_right = self._make_chart_card()
        r4_right_l = QVBoxLayout(r4_right)
        r4_right_l.setContentsMargins(0, 0, 0, 0)
        self.price_dist_view = QWebEngineView()
        self.price_dist_view.setMinimumHeight(300)
        r4_right_l.addWidget(self.price_dist_view)
        r4l.addWidget(r4_right, 1)

        layout.addWidget(row4)

        # ─── 行 5：各类型平均票房（全宽） ───
        self.genre_bo_view = QWebEngineView()
        self.genre_bo_view.setObjectName("chartGenreBO")
        self.genre_bo_view.setMinimumHeight(340)
        self.genre_bo_view.setStyleSheet(CHART_CARD_STYLE)
        layout.addWidget(self.genre_bo_view)

        # ─── 行 6：年份趋势分析（全宽） ───
        self.year_trend_view = QWebEngineView()
        self.year_trend_view.setObjectName("chartYearTrend")
        self.year_trend_view.setMinimumHeight(340)
        self.year_trend_view.setStyleSheet(CHART_CARD_STYLE)
        layout.addWidget(self.year_trend_view)

        # ─── 行 7：数据洞察摘要 ───
        self._insight_box = QFrame()
        self._insight_box.setObjectName("insightBox")
        self._insight_box.setStyleSheet(
            "QFrame#insightBox { background: linear-gradient(135deg, #1a1a2e, #16213e); "
            "border-radius: 10px; padding: 0px; margin: 16px 0px; }"
        )
        ib_layout = QVBoxLayout(self._insight_box)
        ib_layout.setContentsMargins(28, 20, 28, 20)
        ib_layout.setSpacing(6)

        insight_title = QLabel("📊 数据洞察")
        insight_title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        insight_title.setStyleSheet("color: #FFD700;")
        ib_layout.addWidget(insight_title)

        self._insight_text = QLabel("加载中...")
        self._insight_text.setFont(QFont("Microsoft YaHei", 12))
        self._insight_text.setStyleSheet("color: #E0E0E0; line-height: 1.8;")
        self._insight_text.setWordWrap(True)
        ib_layout.addWidget(self._insight_text)

        layout.addWidget(self._insight_box)

        # ─── 行 8：四象限分析（左1/2） + 评分 vs 票房散点（右1/2） ───
        row6 = QWidget()
        r6l = QHBoxLayout(row6)
        r6l.setContentsMargins(0, 16, 0, 16)
        r6l.setSpacing(16)

        # 左：四象限分析
        r6_left = self._make_chart_card()
        r6_left_l = QVBoxLayout(r6_left)
        r6_left_l.setContentsMargins(0, 0, 0, 0)
        self.quadrant_view = QWebEngineView()
        self.quadrant_view.setMinimumHeight(300)
        r6_left_l.addWidget(self.quadrant_view)
        r6l.addWidget(r6_left, 1)

        # 右：评分 vs 票房散点
        r6_right = self._make_chart_card()
        r6_right_l = QVBoxLayout(r6_right)
        r6_right_l.setContentsMargins(0, 0, 0, 0)
        self.scatter_view = QWebEngineView()
        self.scatter_view.setMinimumHeight(300)
        r6_right_l.addWidget(self.scatter_view)
        r6l.addWidget(r6_right, 1)

        layout.addWidget(row6)

        # ─── 行 7：数据表格 ───
        self.movie_table = MovieTable(DatabaseManager())
        self.movie_table.setMinimumHeight(250)
        layout.addWidget(self.movie_table)

        scroll.setWidget(content)

        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _make_chart_card(self) -> QWidget:
        """创建带白色背景和圆角的图表容器。

        Returns:
            空白容器 QWidget
        """
        w = QWidget()
        w.setObjectName("chartCard")
        w.setStyleSheet(
            "QWidget#chartCard { background: white; border-radius: 8px; }"
        )
        return w

    def _load_data(self) -> None:
        """从数据库加载所有数据并刷新 UI。"""
        if self.db is None:
            logger.warning("数据库未设置，跳过数据加载")
            return

        try:
            stats = self.db.get_statistics()

            # 更新统计卡片
            card_values = [
                str(stats["total_movies"]),
                f'{stats["total_box_office"]:,.0f}',
                f'{stats["avg_rating"]:.1f}',
                f'{stats["avg_ticket_price"]:.0f}',
                f'{stats["highest_rated_score"]:.1f}',
            ]
            for card, value in zip(self._stat_cards, card_values):
                card.set_value(value)

            # 渲染所有图表
            chart_map = [
                (self.top10_view, top10_chart.create_top10_chart, "票房Top10"),
                (self.rating_view, rating_distribution.create_rating_distribution, "评分分布"),
                (self.genre_view, genre_pie.create_genre_pie, "类型占比"),
                (self.box_office_range_view, box_office_range.create_box_office_range_chart, "票房区间"),
                (self.price_dist_view, price_distribution.create_price_distribution_chart, "票价分布"),
                (self.genre_bo_view, genre_box_office.create_genre_box_office_chart, "类型平均票房"),
                (self.year_trend_view, year_trend.create_year_trend_chart, "年份趋势"),
                (self.quadrant_view, four_quadrant.create_four_quadrant_chart, "四象限分析"),
                (self.scatter_view, scatter_plot.create_scatter_plot, "评分vs票房"),
            ]

            for view, func, name in chart_map:
                self._render_chart(view, func, name)

            # 生成数据洞察
            self._generate_insights(stats)

            # 更新表格
            self.movie_table.db = self.db
            self.movie_table.load_data()

            logger.info("看板数据加载完成（9 张图表 + 洞察）")

        except Exception as e:
            import traceback
            logger.error("看板数据加载失败: %s", e)
            traceback.print_exc()

    def _generate_insights(self, stats: dict) -> None:
        """根据统计数据自动生成数据洞察文本。

        Args:
            stats: get_statistics() 返回的统计信息字典
        """
        if not stats:
            self._insight_text.setText("暂无足够数据生成洞察")
            return

        lines = []

        # 1. 基础统计
        total = stats.get("total_movies", 0)
        lines.append(f"📌 目前共收录 **{total} 部电影**")

        # 2. 评分
        avg_r = stats.get("avg_rating", 0)
        highest = stats.get("highest_rated", "")
        highest_s = stats.get("highest_rated_score", 0)
        lines.append(
            f"⭐ 平均评分 **{avg_r:.1f}**，最高评分 **{highest_s:.1f}**"
            f"{' 《' + highest + '》' if highest else ''}"
        )
        if avg_r >= 8.0:
            lines[-1] += "，整体评分水平优秀 🎉"
        elif avg_r >= 7.0:
            lines[-1] += "，评分水平良好"
        else:
            lines[-1] += "，评分空间有待提升"

        # 3. 票房
        total_bo = stats.get("total_box_office", 0)
        highest_bo = stats.get("highest_box_office", "")
        highest_bo_v = stats.get("highest_box_office_value", 0)
        lines.append(
            f"💰 总票房 **{total_bo:,.0f} 万元**"
            f"{'，最高《' + highest_bo + '》' + f'{highest_bo_v:,.0f} 万' if highest_bo else ''}"
        )

        # 4. 票价
        avg_price = stats.get("avg_ticket_price", 0)
        if avg_price:
            level = "经济实惠" if avg_price < 35 else "中等价位" if avg_price < 50 else "偏高价位"
            lines.append(f"🎫 平均票价 **{avg_price:.0f} 元**（{level}）")

        # 5. 上映状态
        try:
            conn = self.db.get_connection()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM movies WHERE showing_status='showing'")
            showing = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM movies WHERE showing_status='coming_soon'")
            coming = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM movies WHERE showing_status='released'")
            released = c.fetchone()[0]
            c.close()
            if showing > 0:
                lines.append(f"🎬 正在热映 **{showing} 部**，即将上映 **{coming} 部**，已下映 **{released} 部**")
        except Exception:
            pass

        self._insight_text.setText("\n".join(lines))

    def _render_chart(
        self, view: QWebEngineView, chart_func, name: str
    ) -> None:
        """渲染图表到 WebView。

        Args:
            view: 目标 QWebEngineView
            chart_func: 图表创建函数，接收 db 返回 HTML
            name: 图表名称（日志用）
        """
        if self.db is None:
            return
        try:
            html = chart_func(self.db)
            view.setHtml(html)
        except Exception as e:
            logger.error("渲染图表 '%s' 失败: %s", name, e)
            view.setHtml(
                f"<div style='padding:40px;text-align:center;color:#757575;'>"
                f"图表加载失败: {e}</div>"
            )
