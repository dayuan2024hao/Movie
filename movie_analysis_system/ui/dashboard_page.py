"""
看板页面
========
数据看板主页面 — 9 张图表 + 5 统计卡片 + 洞察摘要 + 数据表格。

严格布局规则：
  1. 无嵌套 QScrollArea — 每个图表容器为纯 QWidget/QFrame
  2. 每个模块 setFixedHeight(N)，N 保证图表区≥220px
  3. 整个看板只有最外层一个 QScrollArea 可滚动
  4. QVBoxLayout 无任何 stretch 参数
  5. 标题 30px + 图表区 ≥ (N-36)px

模块高度分配：
  统计卡片 × 5          100px
  票房 Top 10           420px  (复杂图 ≥360px)
  评分分布 + 类型占比    350px  (简单图 ≥320px)
  票房区间 + 票价分布    350px  (简单图 ≥320px)
  各类型平均票房         380px  (复杂图 ≥360px)
  年份趋势分析           380px  (复杂图 ≥360px)
  四象限 + 评分vs票房    370px  (复杂图 ≥360px)
  数据洞察               auto
  数据表格               300px
"""

import logging
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWebEngineWidgets import QWebEngineView

from database.db_manager import DatabaseManager
from ui.widgets.stat_card import StatCard
from ui.widgets.movie_table import MovieTable
from charts import (
    top10_chart, rating_distribution, genre_pie, scatter_plot,
    box_office_range, price_distribution, genre_box_office,
    four_quadrant, year_trend,
)

logger = logging.getLogger("DashboardPage")


class _ChartWebView(QWebEngineView):
    """QWebEngineView 子类：wheel 事件转发给全局 QScrollArea。

    默认情况下 QWebEngineView 会吞掉鼠标滚轮事件，
    导致鼠标停留在图表上时无法滚动页面。此子类捕获 wheel 事件，
    找到最近的 QScrollArea 并驱动其滚动条，实现「滚轮穿透」。
    """

    def __init__(self, height: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setStyleSheet("background: white; border-radius: 4px;")

    def wheelEvent(self, event) -> None:
        """将滚轮事件转发给最近的 QScrollArea。"""
        scroll_area = self._find_scroll_area()
        if scroll_area:
            delta = event.angleDelta().y()
            sb = scroll_area.verticalScrollBar()
            sb.setValue(sb.value() - delta)
            event.accept()
            return
        super().wheelEvent(event)

    def _find_scroll_area(self) -> Optional[QScrollArea]:
        """向上遍历父控件，找到第一个 QScrollArea。"""
        p: Optional[QWidget] = self.parent()
        while p is not None:
            if isinstance(p, QScrollArea):
                return p
            p = p.parent()
        return None


class DashboardPage(QWidget):
    """数据看板 — 仅最外层 QScrollArea 可滚动，模块无内部滚动条。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db: Optional[DatabaseManager] = None
        self._stat_cards: list[StatCard] = []
        self._setup_ui()

    def set_db(self, db: DatabaseManager) -> None:
        self.db = db
        self._load_data()

    # ──────────── 工具方法 ────────────

    @staticmethod
    def _make_webview(height: int) -> QWebEngineView:
        """创建图表 WebView（滚轮穿透 + 固定高度）。"""
        return _ChartWebView(height)

    @staticmethod
    def _make_card() -> QFrame:
        """纯白底圆角容器，无滚动条。"""
        w = QFrame()
        w.setObjectName("chartCard")
        w.setStyleSheet("QFrame#chartCard { background: white; border-radius: 8px; }")
        return w

    @staticmethod
    def _make_section_title(text: str) -> QLabel:
        """图表区域标题，固定 30px。"""
        lbl = QLabel(text)
        lbl.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        lbl.setFixedHeight(30)
        lbl.setStyleSheet("color: #37474F; margin: 0;")
        return lbl

    # ──────────── 布局构建 ────────────

    def _setup_ui(self) -> None:
        """构建看板 — 严格流式布局，无 stretch，无嵌套滚动。"""
        # 最外层全局滚动 — 这是唯一允许的滚动条
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("dashboardScroll")
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("dashboardContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 20, 28, 20)
        layout.setSpacing(0)

        # ────────── 页面标题 ──────────
        title = QLabel("数据看板")
        title.setFont(QFont("Microsoft YaHei", 20, QFont.Bold))
        title.setFixedHeight(36)
        title.setStyleSheet("color: #37474F;")
        layout.addWidget(title)
        layout.addSpacing(12)

        # ═════════════════════════════════════════
        #  行 1：统计卡片（100px）
        # ═════════════════════════════════════════
        card_row = QWidget()
        card_row.setFixedHeight(100)
        cl = QHBoxLayout(card_row)
        cl.setContentsMargins(0, 0, 0, 8)
        cl.setSpacing(16)

        cards_def = [
            ("电影总数", "0", "🎬", "#1E88E5"),
            ("总票房(万)", "0", "💰", "#43A047"),
            ("平均评分", "0.0", "⭐", "#FB8C00"),
            ("平均票价(元)", "0", "🎫", "#8E24AA"),
            ("最高评分", "0.0", "🏆", "#E53935"),
        ]
        for t, v, ic, co in cards_def:
            card = StatCard(t, v, ic, co)
            self._stat_cards.append(card)
            cl.addWidget(card)
        cl.addStretch()
        layout.addWidget(card_row)
        layout.addSpacing(20)

        # ═════════════════════════════════════════
        #  行 2：票房 Top 10（420px）
        #  复杂图 ≥ 360px → 420px 足量
        # ═════════════════════════════════════════
        layout.addWidget(self._make_section_title("🏆 票房 Top 10"))
        layout.addSpacing(4)
        self.top10_view = self._make_webview(384)
        layout.addWidget(self.top10_view)
        layout.addSpacing(20)

        # ═════════════════════════════════════════
        #  行 3：评分分布（左） + 类型占比（右）— 350px
        #  简单图 ≥ 320px → 350px 充足
        # ═════════════════════════════════════════
        row3 = QWidget()
        row3.setFixedHeight(350)
        r3l = QHBoxLayout(row3)
        r3l.setContentsMargins(0, 0, 0, 0)
        r3l.setSpacing(16)

        # 左：评分分布
        r3_left = self._make_card()
        r3ll = QVBoxLayout(r3_left)
        r3ll.setContentsMargins(0, 0, 0, 0)
        r3ll.setSpacing(0)
        r3t1 = QLabel("评分分布")
        r3t1.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        r3t1.setFixedHeight(30)
        r3t1.setStyleSheet("color: #37474F; padding: 6px 12px 0;")
        r3ll.addWidget(r3t1)
        self.rating_view = self._make_webview(314)
        r3ll.addWidget(self.rating_view)
        r3l.addWidget(r3_left, 1)

        # 右：类型占比
        r3_right = self._make_card()
        r3rl = QVBoxLayout(r3_right)
        r3rl.setContentsMargins(0, 0, 0, 0)
        r3rl.setSpacing(0)
        r3t2 = QLabel("电影类型占比")
        r3t2.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        r3t2.setFixedHeight(30)
        r3t2.setStyleSheet("color: #37474F; padding: 6px 12px 0;")
        r3rl.addWidget(r3t2)
        self.genre_view = self._make_webview(314)
        r3rl.addWidget(self.genre_view)
        r3l.addWidget(r3_right, 1)

        layout.addWidget(row3)
        layout.addSpacing(20)

        # ═════════════════════════════════════════
        #  行 4：票房区间（左） + 票价分布（右）— 350px
        #  简单图 ≥ 320px → 350px 充足
        # ═════════════════════════════════════════
        row4 = QWidget()
        row4.setFixedHeight(350)
        r4l = QHBoxLayout(row4)
        r4l.setContentsMargins(0, 0, 0, 0)
        r4l.setSpacing(16)

        r4_left = self._make_card()
        r4ll = QVBoxLayout(r4_left)
        r4ll.setContentsMargins(0, 0, 0, 0)
        r4ll.setSpacing(0)
        r4t1 = QLabel("票房区间分布")
        r4t1.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        r4t1.setFixedHeight(30)
        r4t1.setStyleSheet("color: #37474F; padding: 6px 12px 0;")
        r4ll.addWidget(r4t1)
        self.box_office_range_view = self._make_webview(314)
        r4ll.addWidget(self.box_office_range_view)
        r4l.addWidget(r4_left, 1)

        r4_right = self._make_card()
        r4rl = QVBoxLayout(r4_right)
        r4rl.setContentsMargins(0, 0, 0, 0)
        r4rl.setSpacing(0)
        r4t2 = QLabel("票价区间分布")
        r4t2.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        r4t2.setFixedHeight(30)
        r4t2.setStyleSheet("color: #37474F; padding: 6px 12px 0;")
        r4rl.addWidget(r4t2)
        self.price_dist_view = self._make_webview(314)
        r4rl.addWidget(self.price_dist_view)
        r4l.addWidget(r4_right, 1)

        layout.addWidget(row4)
        layout.addSpacing(20)

        # ═════════════════════════════════════════
        #  行 5：各类型平均票房（380px）
        #  复杂图（双柱+图例≥ 360px）→ 380px
        # ═════════════════════════════════════════
        layout.addWidget(self._make_section_title("🎬 各类型平均票房"))
        layout.addSpacing(4)
        self.genre_bo_view = self._make_webview(344)
        layout.addWidget(self.genre_bo_view)
        layout.addSpacing(20)

        # ═════════════════════════════════════════
        #  行 6：年份趋势分析（380px）
        #  复杂图（双轴+图例≥360px）→ 380px
        # ═════════════════════════════════════════
        layout.addWidget(self._make_section_title("📈 年份趋势分析"))
        layout.addSpacing(4)
        self.year_trend_view = self._make_webview(344)
        layout.addWidget(self.year_trend_view)
        layout.addSpacing(20)

        # ═════════════════════════════════════════
        #  行 7：四象限（左） + 评分vs票房（右）— 370px
        #  复杂图 ≥ 360px → 370px
        # ═════════════════════════════════════════
        row7 = QWidget()
        row7.setFixedHeight(370)
        r7l = QHBoxLayout(row7)
        r7l.setContentsMargins(0, 0, 0, 0)
        r7l.setSpacing(16)

        r7_left = self._make_card()
        r7ll = QVBoxLayout(r7_left)
        r7ll.setContentsMargins(0, 0, 0, 0)
        r7ll.setSpacing(0)
        r7t1 = QLabel("四象限分析")
        r7t1.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        r7t1.setFixedHeight(30)
        r7t1.setStyleSheet("color: #37474F; padding: 6px 12px 0;")
        r7ll.addWidget(r7t1)
        self.quadrant_view = self._make_webview(334)
        r7ll.addWidget(self.quadrant_view)
        r7l.addWidget(r7_left, 1)

        r7_right = self._make_card()
        r7rl = QVBoxLayout(r7_right)
        r7rl.setContentsMargins(0, 0, 0, 0)
        r7rl.setSpacing(0)
        r7t2 = QLabel("评分 vs 评价人数")
        r7t2.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        r7t2.setFixedHeight(30)
        r7t2.setStyleSheet("color: #37474F; padding: 6px 12px 0;")
        r7rl.addWidget(r7t2)
        self.scatter_view = self._make_webview(334)
        r7rl.addWidget(self.scatter_view)
        r7l.addWidget(r7_right, 1)

        layout.addWidget(row7)
        layout.addSpacing(20)

        # ═════════════════════════════════════════
        #  行 8：数据洞察（自适应）
        # ═════════════════════════════════════════
        self._insight_box = QFrame()
        self._insight_box.setObjectName("insightBox")
        self._insight_box.setStyleSheet(
            "QFrame#insightBox { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            "stop:0 #1a1a2e, stop:1 #16213e); border-radius: 8px; }"
        )
        ib = QVBoxLayout(self._insight_box)
        ib.setContentsMargins(24, 14, 24, 14)
        ib.setSpacing(4)

        ins_title = QLabel("📊 数据洞察")
        ins_title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        ins_title.setFixedHeight(26)
        ins_title.setStyleSheet("color: #FFD700;")
        ib.addWidget(ins_title)

        self._insight_text = QLabel("加载中...")
        self._insight_text.setFont(QFont("Microsoft YaHei", 12))
        self._insight_text.setStyleSheet("color: #E0E0E0;")
        self._insight_text.setWordWrap(True)
        ib.addWidget(self._insight_text)

        layout.addWidget(self._insight_box)
        layout.addSpacing(20)

        # ═════════════════════════════════════════
        #  行 9：数据表格（300px）
        # ═════════════════════════════════════════
        layout.addWidget(self._make_section_title("📋 电影数据列表"))
        layout.addSpacing(4)
        self.movie_table = MovieTable(DatabaseManager())
        self.movie_table.setMinimumHeight(300)
        layout.addWidget(self.movie_table)

        layout.addStretch(0)  # 确保无弹性空间
        scroll.setWidget(content)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    # ──────────── 数据加载 ────────────

    def _load_data(self) -> None:
        if self.db is None:
            return
        try:
            stats = self.db.get_statistics()

            vals = [
                str(stats["total_movies"]),
                f'{stats["total_box_office"]:,.0f} 万',
                f'{stats["avg_rating"]:.1f}',
                f'{stats["avg_ticket_price"]:.0f} 元',
                f'{stats["highest_rated_score"]:.1f}',
            ]
            for card, v in zip(self._stat_cards, vals):
                card.set_value(v)

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

            self._generate_insights(stats)
            self.movie_table.db = self.db
            self.movie_table.load_data()
            logger.info("看板加载完成（9 图表 + 洞察，无内部滚动条）")
        except Exception as e:
            logger.error("看板加载失败: %s", e)
            import traceback
            traceback.print_exc()

    def _render_chart(self, view: QWebEngineView, chart_func, name: str) -> None:
        if self.db is None:
            return
        try:
            html = chart_func(self.db)
            view.setHtml(html)
        except Exception as e:
            logger.error("图表 '%s' 失败: %s", name, e)
            view.setHtml(
                f"<div style='padding:40px;text-align:center;color:#757575;'>"
                f"图表加载失败</div>"
            )

    def _generate_insights(self, stats: dict) -> None:
        if not stats:
            self._insight_text.setText("暂无足够数据")
            return
        lines = []
        lines.append(f"📌 收录 {stats['total_movies']} 部电影")
        ar = stats["avg_rating"]
        tag = "优秀" if ar >= 8.0 else "良好" if ar >= 7.0 else "有提升空间"
        hn = stats.get('highest_rated', '')
        hs = stats['highest_rated_score']
        line = f"⭐ 均分 {ar:.1f}（{tag}），最高 {hs:.1f}"
        if hn:
            line += f"（{hn}）"
        lines.append(line)

        tb = stats['total_box_office']
        hb = stats.get('highest_box_office', '')
        hbv = stats.get('highest_box_office_value', 0)
        line = f"💰 总票房 {tb:,.0f} 万"
        if hb:
            line += f"，最高 {hb}（{hbv:,.0f} 万）"
        lines.append(line)

        ap = stats.get('avg_ticket_price')
        if ap:
            lv = "经济" if ap < 35 else "中等" if ap < 50 else "偏高"
            lines.append(f"🎫 均价 {ap:.0f} 元（{lv}）")
        try:
            c = self.db.get_connection().cursor()
            c.execute("SELECT COUNT(*) FROM movies WHERE showing_status='showing'")
            showing = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM movies WHERE showing_status='coming_soon'")
            coming = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM movies WHERE showing_status='released'")
            released = c.fetchone()[0]
            c.close()
            if showing > 0:
                lines.append(f"🎬 热映 {showing} 部 · 待映 {coming} 部 · 下映 {released} 部")
        except Exception:
            pass
        self._insight_text.setText("\n".join(lines))
