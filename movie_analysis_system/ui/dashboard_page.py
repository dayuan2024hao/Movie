"""
看板页面
========
数据看板主页面 — 9 张图表 + 5 统计卡片 + 洞察摘要 + 数据表格。

布局原则：
  1. 每个图表模块分配充足固定高度，确保标签/图例/数据点完整可见
  2. 禁止模块内独立滚动条，仅通过页面右侧全局垂直滚动条浏览
  3. 自上而下流式堆叠，不强制适配单屏，优先展示完整性

模块高度分配：
  标题区          40px
  统计卡片 × 5    110px
  ──────────────────
  票房 Top 10     400px  (10根横向柱 + 片名标签 + 数值标签)
  评分分布        300px  (10个评分区间柱 + 顶部数值)
  类型占比        320px  (饼图 + 图例 + 百分比)
  票房区间分布    300px  (6个区间柱 + 标签)
  票价分布        300px  (6个区间柱 + 标签)
  各类型平均票房  320px  (双柱对比 + 图例)
  年份趋势分析    340px  (双轴折线 + 图例)
  四象限分析      320px  (散点 + 四象限分割 + 图例)
  评分 vs 票房    300px  (散点 + 标签)
  数据洞察        auto   (自适应高度)
  数据表格        280px
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

CHART_HEIGHT_DEFAULT = 300


class DashboardPage(QWidget):
    """数据看板 — 9 图表 + 卡片 + 洞察 + 表格，全局滚动。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db: Optional[DatabaseManager] = None
        self._stat_cards: list[StatCard] = []
        self._setup_ui()

    def set_db(self, db: DatabaseManager) -> None:
        self.db = db
        self._load_data()

    # ──────────── 工具 ────────────

    @staticmethod
    def _webview(height: int, obj_name: str = "") -> QWebEngineView:
        v = QWebEngineView()
        v.setObjectName(obj_name or "chartView")
        v.setFixedHeight(height)
        v.setStyleSheet("background: white; border-radius: 8px;")
        return v

    @staticmethod
    def _chart_card() -> QFrame:
        w = QFrame()
        w.setObjectName("chartCard")
        w.setStyleSheet("QFrame#chartCard { background: white; border-radius: 8px; }")
        return w

    @staticmethod
    def _section_title(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        lbl.setStyleSheet("color: #37474F; margin: 4px 0;")
        return lbl

    # ──────────── UI 构建 ────────────

    def _setup_ui(self) -> None:
        """构建看板页面 — 所有模块自上而下流式排列，全局滚动。"""
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

        # ── 标题 ──
        title = self._section_title("📊 数据看板")
        title.setFixedHeight(36)
        layout.addWidget(title)
        layout.addSpacing(8)

        # ═══════════════════════════════════
        #  行 1：统计卡片（110px）
        # ═══════════════════════════════════
        card_row = QWidget()
        card_row.setFixedHeight(110)
        cl = QHBoxLayout(card_row)
        cl.setContentsMargins(0, 0, 0, 12)
        cl.setSpacing(16)

        cards = [
            ("电影总数", "0", "🎬", "#1E88E5"),
            ("总票房(万)", "0", "💰", "#43A047"),
            ("平均评分", "0.0", "⭐", "#FB8C00"),
            ("平均票价(元)", "0", "🎫", "#8E24AA"),
            ("最高评分", "0.0", "🏆", "#E53935"),
        ]
        for t, v, ic, co in cards:
            card = StatCard(t, v, ic, co)
            self._stat_cards.append(card)
            cl.addWidget(card)
        cl.addStretch()
        layout.addWidget(card_row)
        layout.addSpacing(16)

        # ═══════════════════════════════════
        #  行 2：票房 Top 10（400px）
        # ═══════════════════════════════════
        layout.addWidget(self._section_title("🏆 票房 Top 10"))
        layout.addSpacing(6)
        self.top10_view = self._webview(400, "chartTop10")
        layout.addWidget(self.top10_view)
        layout.addSpacing(20)

        # ═══════════════════════════════════
        #  行 3：评分分布(左) + 类型占比(右) — 320px
        # ═══════════════════════════════════
        row3 = QWidget()
        row3.setFixedHeight(320)
        r3l = QHBoxLayout(row3)
        r3l.setContentsMargins(0, 0, 0, 0)
        r3l.setSpacing(16)

        # 左：评分分布
        r3_left = self._chart_card()
        r3ll = QVBoxLayout(r3_left)
        r3ll.setContentsMargins(0, 0, 0, 0)
        r3_title1 = QLabel("评分分布")
        r3_title1.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        r3_title1.setStyleSheet("color: #37474F; padding: 8px 12px 0;")
        r3ll.addWidget(r3_title1)
        self.rating_view = self._webview(280)
        r3ll.addWidget(self.rating_view)
        r3l.addWidget(r3_left, 3)

        # 右：类型占比
        r3_right = self._chart_card()
        r3rl = QVBoxLayout(r3_right)
        r3rl.setContentsMargins(0, 0, 0, 0)
        r3_title2 = QLabel("电影类型占比")
        r3_title2.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        r3_title2.setStyleSheet("color: #37474F; padding: 8px 12px 0;")
        r3rl.addWidget(r3_title2)
        self.genre_view = self._webview(280)
        r3rl.addWidget(self.genre_view)
        r3l.addWidget(r3_right, 2)

        layout.addWidget(row3)
        layout.addSpacing(20)

        # ═══════════════════════════════════
        #  行 4：票房区间(左) + 票价分布(右) — 300px
        # ═══════════════════════════════════
        row4 = QWidget()
        row4.setFixedHeight(300)
        r4l = QHBoxLayout(row4)
        r4l.setContentsMargins(0, 0, 0, 0)
        r4l.setSpacing(16)

        r4_left = self._chart_card()
        r4ll = QVBoxLayout(r4_left)
        r4ll.setContentsMargins(0, 0, 0, 0)
        r4t1 = QLabel("票房区间分布")
        r4t1.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        r4t1.setStyleSheet("color: #37474F; padding: 8px 12px 0;")
        r4ll.addWidget(r4t1)
        self.box_office_range_view = self._webview(260)
        r4ll.addWidget(self.box_office_range_view)
        r4l.addWidget(r4_left, 1)

        r4_right = self._chart_card()
        r4rl = QVBoxLayout(r4_right)
        r4rl.setContentsMargins(0, 0, 0, 0)
        r4t2 = QLabel("票价区间分布")
        r4t2.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        r4t2.setStyleSheet("color: #37474F; padding: 8px 12px 0;")
        r4rl.addWidget(r4t2)
        self.price_dist_view = self._webview(260)
        r4rl.addWidget(self.price_dist_view)
        r4l.addWidget(r4_right, 1)

        layout.addWidget(row4)
        layout.addSpacing(20)

        # ═══════════════════════════════════
        #  行 5：各类型平均票房（320px）
        # ═══════════════════════════════════
        layout.addWidget(self._section_title("🎬 各类型平均票房"))
        layout.addSpacing(6)
        self.genre_bo_view = self._webview(320, "chartGenreBO")
        layout.addWidget(self.genre_bo_view)
        layout.addSpacing(20)

        # ═══════════════════════════════════
        #  行 6：年份趋势分析（340px）
        # ═══════════════════════════════════
        layout.addWidget(self._section_title("📈 年份趋势分析"))
        layout.addSpacing(6)
        self.year_trend_view = self._webview(340, "chartYearTrend")
        layout.addWidget(self.year_trend_view)
        layout.addSpacing(20)

        # ═══════════════════════════════════
        #  行 7：四象限(左) + 评分vs票房(右) — 320px
        # ═══════════════════════════════════
        row7 = QWidget()
        row7.setFixedHeight(320)
        r7l = QHBoxLayout(row7)
        r7l.setContentsMargins(0, 0, 0, 0)
        r7l.setSpacing(16)

        r7_left = self._chart_card()
        r7ll = QVBoxLayout(r7_left)
        r7ll.setContentsMargins(0, 0, 0, 0)
        r7t1 = QLabel("四象限分析")
        r7t1.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        r7t1.setStyleSheet("color: #37474F; padding: 8px 12px 0;")
        r7ll.addWidget(r7t1)
        self.quadrant_view = self._webview(280)
        r7ll.addWidget(self.quadrant_view)
        r7l.addWidget(r7_left, 1)

        r7_right = self._chart_card()
        r7rl = QVBoxLayout(r7_right)
        r7rl.setContentsMargins(0, 0, 0, 0)
        r7t2 = QLabel("评分 vs 票房")
        r7t2.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        r7t2.setStyleSheet("color: #37474F; padding: 8px 12px 0;")
        r7rl.addWidget(r7t2)
        self.scatter_view = self._webview(280)
        r7rl.addWidget(self.scatter_view)
        r7l.addWidget(r7_right, 1)

        layout.addWidget(row7)
        layout.addSpacing(20)

        # ═══════════════════════════════════
        #  行 8：数据洞察
        # ═══════════════════════════════════
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
        ins_title.setStyleSheet("color: #FFD700;")
        ib.addWidget(ins_title)

        self._insight_text = QLabel("加载中...")
        self._insight_text.setFont(QFont("Microsoft YaHei", 12))
        self._insight_text.setStyleSheet("color: #E0E0E0;")
        self._insight_text.setWordWrap(True)
        ib.addWidget(self._insight_text)

        layout.addWidget(self._insight_box)
        layout.addSpacing(20)

        # ═══════════════════════════════════
        #  行 9：数据表格（280px）
        # ═══════════════════════════════════
        layout.addWidget(self._section_title("📋 电影数据列表"))
        layout.addSpacing(6)
        self.movie_table = MovieTable(DatabaseManager())
        self.movie_table.setMinimumHeight(280)
        layout.addWidget(self.movie_table)

        layout.addStretch()
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

            # 更新卡片
            vals = [
                str(stats["total_movies"]),
                f'{stats["total_box_office"]:,.0f}',
                f'{stats["avg_rating"]:.1f}',
                f'{stats["avg_ticket_price"]:.0f}',
                f'{stats["highest_rated_score"]:.1f}',
            ]
            for card, v in zip(self._stat_cards, vals):
                card.set_value(v)

            # 渲染图表
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
            logger.info("看板加载完成（9 张图表 + 洞察）")
        except Exception as e:
            import traceback
            logger.error("看板加载失败: %s", e)
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
                f"<div style='padding:40px;text-align:center;color:#757575;font-size:14px;'>"
                f"图表加载失败</div>"
            )

    def _generate_insights(self, stats: dict) -> None:
        if not stats:
            self._insight_text.setText("暂无足够数据生成洞察")
            return
        lines = []
        total = stats.get("total_movies", 0)
        lines.append(f"📌 目前收录 **{total} 部电影**")
        avg_r = stats.get("avg_rating", 0)
        hs = stats.get("highest_rated_score", 0)
        hn = stats.get("highest_rated", "")
        tag = "优秀 🎉" if avg_r >= 8.0 else "良好" if avg_r >= 7.0 else "有待提升"
        lines.append(f"⭐ 平均评分 **{avg_r:.1f}**（{tag}），最高评分 **{hs:.1f}**"
                     + (f" 《{hn}》" if hn else ""))
        tb = stats.get("total_box_office", 0)
        hb = stats.get("highest_box_office", "")
        hbv = stats.get("highest_box_office_value", 0)
        lines.append(f"💰 总票房 **{tb:,.0f} 万元**"
                     + (f"，最高 《{hb}》{hbv:,.0f} 万" if hb else ""))
        ap = stats.get("avg_ticket_price", 0)
        if ap:
            lv = "经济实惠" if ap < 35 else "中等价位" if ap < 50 else "偏高价位"
            lines.append(f"🎫 平均票价 **{ap:.0f} 元**（{lv}）")
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
                lines.append(f"🎬 正在热映 **{showing} 部**，即将上映 **{coming} 部**，已下映 **{released} 部**")
        except Exception:
            pass
        self._insight_text.setText("　　".join(lines))
