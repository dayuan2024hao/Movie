"""
看板页面
========
数据看板主页面 — 9 张图表 + 5 统计卡片 + 洞察摘要 + 数据表格。

增强功能：
  - 工具栏（导出PDF/图片/报告 + 自定义布局）
  - 模块可见性控制
  - 数据源状态指示

严格布局规则：
  1. 无嵌套 QScrollArea — 每个图表容器为纯 QWidget/QFrame
  2. 每个模块 setFixedHeight(N)，N 保证图表区≥220px
  3. 整个看板只有最外层一个 QScrollArea 可滚动
  4. QVBoxLayout 无任何 stretch 参数
  5. 标题 30px + 图表区 ≥ (N-36)px

模块高度分配：
  统计卡片 × 5          100px
  票房 Top 10           420px
  评分分布 + 类型占比    350px
  票房区间 + 票价分布    350px
  各类型平均票房         380px
  年份趋势分析           380px
  四象限 + 评分vs票房    370px
  数据洞察               auto
  数据表格               300px
"""

import logging
import os
import threading
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QFrame, QPushButton, QFileDialog, QMessageBox,
    QComboBox, QSpinBox,
)
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QFont, QDesktopServices
from PyQt5.QtWebEngineWidgets import QWebEngineView

from database.db_manager import DatabaseManager
from ui.widgets.stat_card import StatCard
from ui.widgets.movie_table import MovieTable
from ui.widgets.dashboard_config import (
    load_config, save_config, is_module_visible,
    open_dashboard_config, get_visible_modules,
)
from ui.widgets.genre_drilldown import GenreDrilldownDialog
from ui.widgets.compare_tool import CompareToolDialog
from reporting import report_generator
from charts import (
    top10_chart, rating_distribution, genre_pie, scatter_plot,
    box_office_range, price_distribution, genre_box_office,
    four_quadrant, year_trend, season_chart,
)

logger = logging.getLogger("DashboardPage")


class _ChartWebView(QWebEngineView):
    """QWebEngineView 子类：wheel 事件转发给全局 QScrollArea。"""

    def __init__(self, height: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setStyleSheet("background: white; border-radius: 4px;")

    def wheelEvent(self, event) -> None:
        scroll_area = self._find_scroll_area()
        if scroll_area:
            delta = event.angleDelta().y()
            sb = scroll_area.verticalScrollBar()
            sb.setValue(sb.value() - delta)
            event.accept()
            return
        super().wheelEvent(event)

    def _find_scroll_area(self) -> Optional[QScrollArea]:
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
        # 模块引用字典 {module_id: wrapper_widget}
        self._modules: dict[str, QWidget] = {}
        self._content_layout: Optional[QVBoxLayout] = None
        self._year_start: Optional[int] = None
        self._year_end: Optional[int] = None
        self._year_combo: Optional[QComboBox] = None
        self._setup_ui()

    def set_db(self, db: DatabaseManager) -> None:
        self.db = db
        self._load_data()

    # ──────────── 工具方法 ────────────

    @staticmethod
    def _make_webview(height: int) -> QWebEngineView:
        return _ChartWebView(height)

    @staticmethod
    def _make_card() -> QFrame:
        w = QFrame()
        w.setObjectName("chartCard")
        w.setStyleSheet("QFrame#chartCard { background: white; border-radius: 8px; }")
        return w

    @staticmethod
    def _make_section_title(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(QFont("Microsoft YaHei", 15, QFont.Bold))
        lbl.setFixedHeight(38)
        lbl.setStyleSheet("color: #37474F; padding: 6px 0 0 0;")
        return lbl

    # ──────────── 工具栏 ────────────

    def _setup_toolbar(self, layout: QVBoxLayout) -> None:
        """创建工具栏：数据源状态 + 年份筛选 + 功能按钮组。"""
        toolbar = QWidget()
        toolbar.setObjectName("dashboardToolbar")
        toolbar.setStyleSheet(
            "QWidget#dashboardToolbar { background: white; border-radius: 8px; "
            "border: 1px solid #E0E0E0; }"
        )
        # 主布局：HBoxLayout 实现 flex 效果
        toolbar.setMinimumWidth(700)  # 保证所有控件完整显示的最小宽度
        t_layout = QHBoxLayout(toolbar)
        t_layout.setContentsMargins(14, 6, 14, 6)
        t_layout.setSpacing(8)

        # ── 左侧区：状态标签（flex: 1，可收缩，不换行） ──
        self._status_indicator = QLabel("📡 数据就绪")
        self._status_indicator.setFont(QFont("Microsoft YaHei", 13))
        self._status_indicator.setStyleSheet(
            "color: #43A047; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;"
        )
        self._status_indicator.setMinimumWidth(280)
        t_layout.addWidget(self._status_indicator, 1)  # flex: 1

        # ── 年份筛选区 ──
        year_label = QLabel("年份:")
        year_label.setFont(QFont("Microsoft YaHei", 13))
        year_label.setStyleSheet("color: #555;")
        t_layout.addWidget(year_label)

        self._year_combo = QComboBox()
        self._year_combo.setMinimumWidth(120)
        self._year_combo.setStyleSheet(
            "QComboBox { border: 1px solid #CCC; border-radius: 4px; "
            "padding: 4px 8px; font-size: 13px; background: white; min-height: 28px; }"
            "QComboBox:hover { border-color: #1E88E5; }"
            "QComboBox::drop-down { border: none; width: 24px; }"
        )
        for text, data in [
            ("全部年份", ""), ("2026年", 2026), ("2025年", 2025),
            ("2024年", 2024), ("2023年", 2023), ("2022年", 2022),
            ("2021年", 2021), ("2020年", 2020), ("2010年以前", -1),
        ]:
            self._year_combo.addItem(text, data)
        self._year_combo.currentIndexChanged.connect(self._on_year_changed)
        t_layout.addWidget(self._year_combo)

        # ── 右侧按钮组（flex: 0 0 auto，不收缩） ──
        btn_container = QWidget()
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(6)

        btn_defs = [
            ("📤 导出报表", self._export_report),
            ("📄 导出 PDF", self._export_pdf),
            ("🖼️ 导出图片", self._export_image),
            ("🔍 类型下钻", self._open_genre_drilldown),
            ("📊 多片对比", self._open_compare_tool),
        ]
        for text, callback in btn_defs:
            btn = QPushButton(text)
            btn.setStyleSheet(self._toolbar_btn_style())
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(callback)
            btn_layout.addWidget(btn)

        # 分隔 + 自定义
        sep = QLabel("|")
        sep.setStyleSheet("color: #DDD; padding: 0 4px;")
        btn_layout.addWidget(sep)

        settings_btn = QPushButton("⚙️ 自定义")
        settings_btn.setStyleSheet(
            "QPushButton { background: #F8F9FA; color: #444; border: 1px solid #DEE2E6; "
            "border-radius: 4px; padding: 4px 14px; font-size: 13px; min-height: 30px; }"
            "QPushButton:hover { background: #E3F2FD; border-color: #1E88E5; color: #1E88E5; }"
        )
        settings_btn.setCursor(Qt.PointingHandCursor)
        settings_btn.clicked.connect(self._open_dashboard_config)
        btn_layout.addWidget(settings_btn)

        t_layout.addWidget(btn_container, 0)  # flex: 0 0 auto

        layout.addWidget(toolbar)
        layout.addSpacing(12)

    @staticmethod
    def _toolbar_btn_style() -> str:
        return (
            "QPushButton { background: #F8F9FA; color: #444; border: 1px solid #DEE2E6; "
            "border-radius: 4px; padding: 4px 14px; font-size: 13px; min-height: 30px; }"
            "QPushButton:hover { background: #E3F2FD; border-color: #1E88E5; color: #1E88E5; }"
        )

    # ──────────── 导出方法 ────────────

    def _export_image(self) -> None:
        """导出看板为 PNG 图片。"""
        filepath, _ = QFileDialog.getSaveFileName(
            self, "导出为图片", "dashboard_snapshot.png",
            "PNG 图片 (*.png)",
        )
        if not filepath:
            return

        # 找 content widget（QScrollArea 内部）
        scroll = self.findChild(QScrollArea, "dashboardScroll")
        if scroll and scroll.widget():
            ok = report_generator.export_image(scroll.widget(), filepath)
            if ok:
                QMessageBox.information(self, "导出成功", f"图片已保存到:\n{filepath}")
            else:
                QMessageBox.warning(self, "导出失败", "图片导出失败，请重试")

    def _export_pdf(self) -> None:
        """导出结构化报告为 PDF（通过 QWebEngineView）。"""
        if self.db is None:
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self, "导出为 PDF", "analysis_report.pdf",
            "PDF 文件 (*.pdf)",
        )
        if not filepath:
            return

        # 先生成 HTML 报告
        html_path = filepath.replace(".pdf", "_temp.html")
        ok = report_generator.generate_report(self.db, html_path)
        if not ok:
            QMessageBox.warning(self, "导出失败", "报告生成失败")
            return

        # 用 QWebEngineView 加载 HTML 并导出 PDF
        self._status_indicator.setText("📄 正在生成 PDF...")
        view = QWebEngineView()
        view.setFixedSize(1200, 1600)
        view.load(QUrl.fromLocalFile(os.path.abspath(html_path)))

        def on_pdf_printed(path: str, success: bool) -> None:
            self._status_indicator.setText("📡 PDF 导出完成")
            try:
                os.remove(html_path)
            except OSError:
                pass
            if success:
                QMessageBox.information(self, "导出成功", f"PDF 已保存到:\n{filepath}")
            else:
                QMessageBox.warning(self, "导出失败", "PDF 生成失败")

        view.page().pdfPrintingFinished.connect(on_pdf_printed)
        view.page().printToPdf(filepath)

    def _export_report(self) -> None:
        """导出结构化分析报告（HTML）。"""
        if self.db is None:
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self, "导出分析报告", "data_analysis_report.html",
            "HTML 文件 (*.html)",
        )
        if not filepath:
            return

        self._status_indicator.setText("📝 正在生成报告...")
        ok = report_generator.generate_report(self.db, filepath)
        if ok:
            self._status_indicator.setText("📡 报告就绪")
            # 询问是否打开
            reply = QMessageBox.question(
                self, "导出成功",
                f"报告已保存到:\n{filepath}\n\n是否立即打开？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(filepath)))
        else:
            self._status_indicator.setText("📡 报告生成失败")
            QMessageBox.warning(self, "导出失败", "报告生成失败")

    # ──────────── 类型下钻 ────────────

    def _open_genre_drilldown(self) -> None:
        if self.db is None:
            return
        dialog = GenreDrilldownDialog(self.db, parent=self)
        dialog.exec_()

    # ──────────── 多片对比 ────────────

    def _open_compare_tool(self) -> None:
        if self.db is None:
            return
        dialog = CompareToolDialog(self.db, parent=self)
        dialog.exec_()

    # ──────────── 自定义看板 ────────────

    def _open_dashboard_config(self) -> None:
        """打开看板自定义对话框并应用配置。"""
        if open_dashboard_config(self):
            self._apply_config()

    def _apply_config(self) -> None:
        """根据配置显示/隐藏模块。"""
        cfg = load_config()
        hidden = set(cfg.get("hidden_modules", []))

        for module_id, widget in self._modules.items():
            should_hide = module_id in hidden
            widget.setVisible(not should_hide)

        # 更新状态
        total = len(self._modules)
        visible = total - len(hidden)
        logger.info("看板布局已应用: %d/%d 模块可见", visible, total)

    # ──────────── 布局构建 ────────────

    def _setup_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("dashboardScroll")
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("dashboardContent")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(20, 20, 20, 20)
        self._content_layout.setSpacing(0)

        # ═════════════════════════════════════════
        #  页面标题
        # ═════════════════════════════════════════
        title_row = QWidget()
        title_row_layout = QHBoxLayout(title_row)
        title_row_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("数据看板")
        title.setFont(QFont("Microsoft YaHei", 20, QFont.Bold))
        title.setFixedHeight(36)
        title.setStyleSheet("color: #37474F;")
        title_row_layout.addWidget(title)
        title_row_layout.addStretch()

        self._content_layout.addWidget(title_row)
        self._content_layout.addSpacing(8)

        # 工具栏
        self._setup_toolbar(self._content_layout)

        # ═════════════════════════════════════════
        #  行 1：统计卡片（100px）
        # ═════════════════════════════════════════
        card_row = QWidget()
        card_row.setFixedHeight(90)
        cl = QHBoxLayout(card_row)
        cl.setContentsMargins(0, 0, 0, 8)
        cl.setSpacing(10)

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
        self._content_layout.addWidget(card_row)
        self._content_layout.addSpacing(16)

        # ═════════════════════════════════════════
        #  模块化图表布局
        # ═════════════════════════════════════════

        # 模块 1: 票房 Top 10
        m1 = QWidget()
        m1_layout = QVBoxLayout(m1)
        m1_layout.setContentsMargins(0, 0, 0, 0)
        m1_layout.setSpacing(0)
        m1_layout.addWidget(self._make_section_title("🏆 票房 Top 10"))
        m1_layout.addSpacing(4)
        self.top10_view = self._make_webview(440)
        m1_layout.addWidget(self.top10_view)
        self._content_layout.addWidget(m1)
        self._content_layout.addSpacing(16)
        self._modules["top10"] = m1

        # 模块 2: 评分分布 + 类型占比
        m2 = QWidget()
        m2.setFixedHeight(420)
        m2_layout = QHBoxLayout(m2)
        m2_layout.setContentsMargins(0, 0, 0, 0)
        m2_layout.setSpacing(16)
        # 评分分布（左）
        r3_left = self._make_card()
        r3ll = QVBoxLayout(r3_left)
        r3ll.setContentsMargins(0, 0, 0, 0)
        r3ll.setSpacing(0)
        r3t1 = QLabel("评分分布")
        r3t1.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        r3t1.setFixedHeight(36)
        r3t1.setStyleSheet("color: #37474F; padding: 8px 12px 0;")
        r3ll.addWidget(r3t1)
        self.rating_view = self._make_webview(370)
        r3ll.addWidget(self.rating_view)
        m2_layout.addWidget(r3_left, 1)
        # 类型占比（右）
        r3_right = self._make_card()
        r3rl = QVBoxLayout(r3_right)
        r3rl.setContentsMargins(0, 0, 0, 0)
        r3rl.setSpacing(0)
        r3t2 = QLabel("电影类型占比")
        r3t2.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        r3t2.setFixedHeight(36)
        r3t2.setStyleSheet("color: #37474F; padding: 8px 12px 0;")
        r3rl.addWidget(r3t2)
        self.genre_view = self._make_webview(370)
        r3rl.addWidget(self.genre_view)
        m2_layout.addWidget(r3_right, 1)
        self._content_layout.addWidget(m2)
        self._content_layout.addSpacing(16)
        self._modules["rating_genre"] = m2

        # 模块 3: 票房区间 + 票价分布
        m3 = QWidget()
        m3.setFixedHeight(420)
        m3_layout = QHBoxLayout(m3)
        m3_layout.setContentsMargins(0, 0, 0, 0)
        m3_layout.setSpacing(16)
        # 票房区间（左）
        r4_left = self._make_card()
        r4ll = QVBoxLayout(r4_left)
        r4ll.setContentsMargins(0, 0, 0, 0)
        r4ll.setSpacing(0)
        r4t1 = QLabel("票房区间分布")
        r4t1.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        r4t1.setFixedHeight(30)
        r4t1.setStyleSheet("color: #37474F; padding: 6px 12px 0;")
        r4ll.addWidget(r4t1)
        self.box_office_range_view = self._make_webview(370)
        r4ll.addWidget(self.box_office_range_view)
        m3_layout.addWidget(r4_left, 1)
        # 票价分布（右）
        r4_right = self._make_card()
        r4rl = QVBoxLayout(r4_right)
        r4rl.setContentsMargins(0, 0, 0, 0)
        r4rl.setSpacing(0)
        r4t2 = QLabel("票价区间分布")
        r4t2.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        r4t2.setFixedHeight(30)
        r4t2.setStyleSheet("color: #37474F; padding: 6px 12px 0;")
        r4rl.addWidget(r4t2)
        self.price_dist_view = self._make_webview(370)
        r4rl.addWidget(self.price_dist_view)
        m3_layout.addWidget(r4_right, 1)
        self._content_layout.addWidget(m3)
        self._content_layout.addSpacing(16)
        self._modules["bo_price"] = m3

        # 模块 4: 各类型平均票房
        m4 = QWidget()
        m4_layout = QVBoxLayout(m4)
        m4_layout.setContentsMargins(0, 0, 0, 0)
        m4_layout.setSpacing(0)
        m4_layout.addWidget(self._make_section_title("🎬 各类型平均票房"))
        m4_layout.addSpacing(4)
        self.genre_bo_view = self._make_webview(420)
        m4_layout.addWidget(self.genre_bo_view)
        self._content_layout.addWidget(m4)
        self._content_layout.addSpacing(16)
        self._modules["genre_bo"] = m4

        # 模块 5: 年份趋势分析
        m5 = QWidget()
        m5_layout = QVBoxLayout(m5)
        m5_layout.setContentsMargins(0, 0, 0, 0)
        m5_layout.setSpacing(0)
        m5_layout.addWidget(self._make_section_title("📈 年份趋势分析"))
        m5_layout.addSpacing(4)
        self.year_trend_view = self._make_webview(420)
        m5_layout.addWidget(self.year_trend_view)
        self._content_layout.addWidget(m5)
        self._content_layout.addSpacing(16)
        self._modules["year_trend"] = m5

        # 模块 6: 四象限分析（独立全宽）
        m6 = QWidget()
        m6_layout = QVBoxLayout(m6)
        m6_layout.setContentsMargins(0, 0, 0, 0)
        m6_layout.setSpacing(0)
        m6_layout.addWidget(self._make_section_title("🎯 四象限分析"))
        m6_layout.addSpacing(4)
        self.quadrant_view = self._make_webview(410)
        m6_layout.addWidget(self.quadrant_view)
        self._content_layout.addWidget(m6)
        self._content_layout.addSpacing(16)
        self._modules["quadrant"] = m6

        # 模块 7: 评分 vs 评价人数（独立全宽）
        m7 = QWidget()
        m7_layout = QVBoxLayout(m7)
        m7_layout.setContentsMargins(0, 0, 0, 0)
        m7_layout.setSpacing(0)
        m7_layout.addWidget(self._make_section_title("📊 评分 vs 评价人数"))
        m7_layout.addSpacing(4)
        self.scatter_view = self._make_webview(410)
        m7_layout.addWidget(self.scatter_view)
        self._content_layout.addWidget(m7)
        self._content_layout.addSpacing(16)
        self._modules["scatter"] = m7

        # 模块 8: 档期专题分析
        m7 = QWidget()
        m7_layout = QVBoxLayout(m7)
        m7_layout.setContentsMargins(0, 0, 0, 0)
        m7_layout.setSpacing(0)
        m7_layout.addWidget(self._make_section_title("📅 档期专题分析"))
        m7_layout.addSpacing(4)
        self.season_view = self._make_webview(420)
        m7_layout.addWidget(self.season_view)
        self._content_layout.addWidget(m7)
        self._content_layout.addSpacing(16)
        self._modules["season"] = m7

        # 模块 9: 数据洞察
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
        ins_title.setFont(QFont("Microsoft YaHei", 15, QFont.Bold))
        ins_title.setFixedHeight(30)
        ins_title.setStyleSheet("color: #FFD700;")
        ib.addWidget(ins_title)
        self._insight_text = QLabel("加载中...")
        self._insight_text.setFont(QFont("Microsoft YaHei", 13))
        self._insight_text.setStyleSheet("color: #E0E0E0;")
        self._insight_text.setWordWrap(True)
        ib.addWidget(self._insight_text)
        self._content_layout.addWidget(self._insight_box)
        self._content_layout.addSpacing(16)
        self._modules["insight"] = self._insight_box

        # 模块 9: 数据表格
        m8 = QWidget()
        m8_layout = QVBoxLayout(m8)
        m8_layout.setContentsMargins(0, 0, 0, 0)
        m8_layout.setSpacing(0)
        m8_layout.addWidget(self._make_section_title("📋 电影数据列表"))
        m8_layout.addSpacing(4)
        self.movie_table = MovieTable(DatabaseManager())
        self.movie_table.setMinimumHeight(300)
        m8_layout.addWidget(self.movie_table)
        self._content_layout.addWidget(m8)
        self._modules["movie_table"] = m8

        scroll.setWidget(content)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    # ──────────── 年份筛选 ────────────

    def _on_year_changed(self) -> None:
        """年份筛选变化时重新加载图表。"""
        if self._year_combo is None:
            return
        year_val = self._year_combo.currentData()
        if year_val == "" or year_val is None:
            self._year_start = None
            self._year_end = None
        elif year_val == -1:
            self._year_start = None
            self._year_end = 2009
        else:
            self._year_start = year_val
            self._year_end = year_val

        # 保留统计卡片全量数据，只刷新图表
        if self.db is not None:
            try:
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
                    (self.season_view, season_chart.create_season_chart, "档期分析"),
                ]
                for view, func, name in chart_map:
                    self._render_chart(view, func, name,
                                       year_start=self._year_start,
                                       year_end=self._year_end)
                logger.info("年份筛选已应用: %s-%s", self._year_start, self._year_end)
            except Exception as e:
                logger.error("年份筛选刷新失败: %s", e)

    # ──────────── 数据加载 ────────────

    def _load_data(self) -> None:
        if self.db is None:
            return
        try:
            stats = self.db.get_statistics()

            vals = [
                str(stats["total_movies"]),
                f'{stats["total_box_office"]:,.0f}',
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
                (self.season_view, season_chart.create_season_chart, "档期分析"),
            ]
            for view, func, name in chart_map:
                self._render_chart(view, func, name,
                                   year_start=self._year_start,
                                   year_end=self._year_end)

            self._generate_insights(stats)
            self.movie_table.db = self.db
            self.movie_table.load_data()

            # 更新数据源状态
            try:
                status = self.db.get_data_status()
                last_crawl = status.get("last_crawl_time") or "未知"
                source = status.get("data_source", "unknown")
                self._status_indicator.setText(
                    f"📡 数据来源: {source} · 更新: {last_crawl}"
                )
            except Exception:
                pass

            # 应用自定义布局
            self._apply_config()

            logger.info("看板加载完成（9 图表 + 洞察，模块化布局）")
        except Exception as e:
            logger.error("看板加载失败: %s", e)
            import traceback
            traceback.print_exc()

    def _render_chart(self, view: QWebEngineView, chart_func, name: str,
                      year_start=None, year_end=None) -> None:
        if self.db is None:
            return
        try:
            html = chart_func(self.db, year_start=year_start, year_end=year_end)
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
