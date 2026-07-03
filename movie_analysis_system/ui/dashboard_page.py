"""
看板页面
========
数据看板主页面，包含：
- 顶部：5 个统计卡片（总数、总票房、平均评分、平均票价、最高评分）
- 中部：票房 Top 10 横向柱状图
- 中下部：左=评分分布直方图，右=类型占比饼图
- 底部：评分 vs 票房散点图 + 电影数据表格
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
from charts import top10_chart, rating_distribution, genre_pie, scatter_plot

logger = logging.getLogger("DashboardPage")


class DashboardPage(QWidget):
    """数据看板页面。"""

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

        # ─── 第一行：统计卡片 ───
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

        # ─── 第二行：Top 10 图表（全宽） ───
        self.top10_view = QWebEngineView()
        self.top10_view.setObjectName("chartTop10")
        self.top10_view.setMinimumHeight(380)
        self.top10_view.setStyleSheet("background: white; border-radius: 8px;")
        layout.addWidget(self.top10_view, 1)

        # ─── 第三行：双列图表（评分分布 + 类型占比） ───
        charts_row = QWidget()
        charts_row.setObjectName("chartsRow")
        charts_layout = QHBoxLayout(charts_row)
        charts_layout.setContentsMargins(0, 16, 0, 16)
        charts_layout.setSpacing(16)

        # 左：评分分布
        rating_widget = QWidget()
        rating_widget.setObjectName("chartCard")
        rating_widget.setStyleSheet(
            "QWidget#chartCard { background: white; border-radius: 8px; }"
        )
        r_layout = QVBoxLayout(rating_widget)
        r_layout.setContentsMargins(0, 0, 0, 0)
        self.rating_view = QWebEngineView()
        self.rating_view.setMinimumHeight(300)
        r_layout.addWidget(self.rating_view)
        charts_layout.addWidget(rating_widget, 3)

        # 右：类型占比
        genre_widget = QWidget()
        genre_widget.setObjectName("chartCard")
        genre_widget.setStyleSheet(
            "QWidget#chartCard { background: white; border-radius: 8px; }"
        )
        g_layout = QVBoxLayout(genre_widget)
        g_layout.setContentsMargins(0, 0, 0, 0)
        self.genre_view = QWebEngineView()
        self.genre_view.setMinimumHeight(300)
        g_layout.addWidget(self.genre_view)
        charts_layout.addWidget(genre_widget, 2)

        layout.addWidget(charts_row)

        # ─── 第四行：散点图（全宽） ───
        self.scatter_view = QWebEngineView()
        self.scatter_view.setObjectName("chartScatter")
        self.scatter_view.setMinimumHeight(300)
        self.scatter_view.setStyleSheet("background: white; border-radius: 8px;")
        layout.addWidget(self.scatter_view)

        # ─── 第五行：数据表格 ───
        self.movie_table = MovieTable(DatabaseManager())  # 单例，init时先创建占位
        self.movie_table.setMinimumHeight(250)
        layout.addWidget(self.movie_table)

        scroll.setWidget(content)

        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

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

            # 更新图表
            self._render_chart(self.top10_view, top10_chart.create_top10_chart, "Top10")
            self._render_chart(
                self.rating_view, rating_distribution.create_rating_distribution, "评分分布"
            )
            self._render_chart(self.genre_view, genre_pie.create_genre_pie, "类型占比")
            self._render_chart(self.scatter_view, scatter_plot.create_scatter_plot, "散点图")

            # 更新表格
            self.movie_table.db = self.db
            self.movie_table.load_data()

            logger.info("看板数据加载完成")

        except Exception as e:
            logger.error("看板数据加载失败: %s", e)

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
