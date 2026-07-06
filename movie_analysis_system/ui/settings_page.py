"""
系统设置页面
============
包含两个标签页：
  1. 数据源管理 — 数据概览、来源信息、手动刷新、爬取日志
  2. 关于系统 — 系统信息、版本号、技术栈
"""

import logging
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
    QFrame, QPushButton, QScrollArea,
)
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QFont, QDesktopServices

from database.db_manager import DatabaseManager
from ui.data_source_page import DataSourcePage

logger = logging.getLogger("SettingsPage")


class AboutSection(QWidget):
    """关于系统 — 系统定位、核心功能、数据说明。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db: Optional[DatabaseManager] = None
        self._setup_ui()

    def set_db(self, db: DatabaseManager) -> None:
        self.db = db
        self._refresh_count()

    def _refresh_count(self) -> None:
        """刷新电影总数显示。"""
        if not self.db:
            return
        try:
            conn = self.db.get_connection()
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM movies")
            total = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM movies WHERE showing_status='showing'")
            showing = c.fetchone()[0]
            c.close()
            self._count_label.setText(
                f"📊 当前覆盖 <b>{total}</b> 部电影（<b>{showing}</b> 部在映）"
            )
        except Exception:
            self._count_label.setText("📊 当前覆盖 <b>--</b> 部电影")

    def _make_card(self, icon: str, title: str, items: list) -> QFrame:
        """创建带标题的内容卡片。"""
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: white; border-radius: 8px; "
            "border: 1px solid #E0E0E0; }"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 14, 20, 14)
        cl.setSpacing(6)

        header = QLabel(f"{icon}  {title}")
        header.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        header.setStyleSheet("color: #37474F;")
        cl.addWidget(header)

        for text in items:
            lbl = QLabel(text)
            lbl.setFont(QFont("Microsoft YaHei", 11))
            lbl.setStyleSheet("color: #555; padding: 1px 0;")
            lbl.setWordWrap(True)
            cl.addWidget(lbl)
        return card

    def _setup_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: #F5F7FA; border: none; }")

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(40, 28, 40, 28)
        layout.setSpacing(14)

        # ════════════════════════════════════
        #  标题区
        # ════════════════════════════════════
        title = QLabel("🎬  电影票分析系统")
        title.setFont(QFont("Microsoft YaHei", 24, QFont.Bold))
        title.setStyleSheet("color: #1E88E5;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        version = QLabel("版本 3.0  ·  教学实训项目")
        version.setFont(QFont("Microsoft YaHei", 13))
        version.setStyleSheet("color: #90A4AE;")
        version.setAlignment(Qt.AlignCenter)
        layout.addWidget(version)

        layout.addSpacing(6)

        # ════════════════════════════════════
        #  ① 系统定位
        # ════════════════════════════════════
        layout.addWidget(self._make_card("🎯", "系统定位", [
            "电影数据分析与可视化工具，实时聚合猫眼、豆瓣、OMDB 多源数据，"
            "帮助用户洞察电影市场趋势、对比影片表现、辅助观影决策。"
        ]))

        # ════════════════════════════════════
        #  ② 核心功能
        # ════════════════════════════════════
        layout.addWidget(self._make_card("⚡", "核心功能", [
            "📊  数据看板 — 9 种交互式图表 + 5 项统计指标 + 数据洞察",
            "🏆  智能推荐 — 高分 / 热门 / 口碑 / 性价比 / 综合 五维榜单",
            "🔍  多维搜索 — 猫眼 + 豆瓣异步并发搜索，结果自动去重",
            "📤  报告导出 — 数据看板导出为 PDF / 图片 / HTML 报告",
            "🎬  电影详情 — 多源降级聚合（OMDB → TMDB → 豆瓣 Frodo）",
        ]))

        # ════════════════════════════════════
        #  ③ 数据说明
        # ════════════════════════════════════
        self._count_label = QLabel("📊 当前覆盖 <b>--</b> 部电影")
        self._count_label.setFont(QFont("Microsoft YaHei", 11))
        self._count_label.setStyleSheet("color: #555;")

        data_card = QFrame()
        data_card.setObjectName("dataCard")
        data_card.setStyleSheet(
            "QFrame#dataCard { background: white; border-radius: 8px; "
            "border: 1px solid #E0E0E0; }"
        )
        dl = QVBoxLayout(data_card)
        dl.setContentsMargins(20, 14, 20, 14)
        dl.setSpacing(6)

        dh = QLabel("📡  数据说明")
        dh.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        dh.setStyleSheet("color: #37474F;")
        dl.addWidget(dh)

        for t in [
            "🎬  在映电影 — 猫眼桌面站实时爬取（每次启动自动更新）",
            "⭐  评分数据 — 猫眼 H5 API + OMDB API 综合评分",
            "📝  剧情简介 — OMDB 为主，TMDB 降级补充",
            "🖼  海报资源 — 猫眼 CDN + OMDB 双源获取",
        ]:
            lbl = QLabel(t)
            lbl.setFont(QFont("Microsoft YaHei", 11))
            lbl.setStyleSheet("color: #555; padding: 1px 0;")
            dl.addWidget(lbl)

        dl.addSpacing(4)
        self._count_label.setFont(QFont("Microsoft YaHei", 12))
        self._count_label.setStyleSheet("color: #37474F; padding: 4px 0;")
        dl.addWidget(self._count_label)

        layout.addWidget(data_card)

        # ════════════════════════════════════
        #  ④ 反馈与声明
        # ════════════════════════════════════
        layout.addWidget(self._make_card("📬", "反馈与声明", [
            "📧  联系邮箱：movie_analysis@example.com",
            "",
            "⚠️  本系统为学校教学实训项目，数据来源于猫眼电影、豆瓣电影及 OMDB 公开 API，"
            "所有数据仅供学习参考，不代表真实市场情况。",
        ]))

        layout.addStretch()
        scroll.setWidget(content)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)


class SettingsPage(QWidget):
    """系统设置页面 — 数据源 + 关于 两个标签页。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._data_source_page = DataSourcePage()
        self._about_section = AboutSection()
        self._setup_ui()

    def set_db(self, db: DatabaseManager) -> None:
        self._data_source_page.set_db(db)
        self._about_section.set_db(db)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tabs = QTabWidget()
        tabs.setObjectName("settingsTabs")
        tabs.setStyleSheet(
            "QTabWidget::pane { border: none; background: #F5F7FA; }"
            "QTabBar::tab { font-size: 15px; padding: 10px 24px; "
            "  font-family: 'Microsoft YaHei'; }"
            "QTabBar::tab:selected { border-bottom: 2px solid #1E88E5; "
            "  color: #1E88E5; }"
        )

        tabs.addTab(self._data_source_page, "🔌 数据源管理")
        tabs.addTab(self._about_section, "ℹ️ 关于系统")

        layout.addWidget(tabs)
