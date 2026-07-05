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
    QFrame, QPushButton,
)
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QFont, QDesktopServices

from database.db_manager import DatabaseManager
from ui.data_source_page import DataSourcePage

logger = logging.getLogger("SettingsPage")


class AboutSection(QWidget):
    """关于系统 — 系统信息与版本。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 24, 40, 24)
        layout.setSpacing(16)

        # Logo / 标题
        title = QLabel("🎬 电影票分析系统")
        title.setFont(QFont("Microsoft YaHei", 22, QFont.Bold))
        title.setStyleSheet("color: #1E88E5;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        version = QLabel("版本 2.12")
        version.setFont(QFont("Microsoft YaHei", 14))
        version.setStyleSheet("color: #757575;")
        version.setAlignment(Qt.AlignCenter)
        layout.addWidget(version)

        # 分隔
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #E0E0E0;")
        layout.addWidget(sep)

        # 技术栈卡片
        stack_card = QFrame()
        stack_card.setStyleSheet(
            "QFrame { background: white; border-radius: 8px; "
            "border: 1px solid #E0E0E0; }"
        )
        stack_layout = QVBoxLayout(stack_card)
        stack_layout.setContentsMargins(20, 16, 20, 16)
        stack_layout.setSpacing(8)

        stack_layout.addWidget(QLabel("📦 技术栈"))
        techs = [
            ("🖥️ 界面框架", "PyQt5 — 桌面 GUI，QSS 自定义样式"),
            ("📊 数据可视化", "PyECharts — 9 种交互式图表 (QWebEngineView 渲染)"),
            ("🗄️ 数据存储", "SQLite — WAL 模式，线程安全 (RLock)"),
            ("🐍 爬虫引擎", "Requests + BeautifulSoup + Selenium，多源降级"),
            ("🧠 推荐算法", "多因子加权评分 (热度/口碑/性价比/综合)"),
            ("🔍 搜索", "猫眼H5 + 豆瓣搜索异步并发，缓存合并"),
        ]
        for icon, desc in techs:
            lbl = QLabel(f"  {icon}  {desc}")
            lbl.setFont(QFont("Microsoft YaHei", 11))
            lbl.setStyleSheet("color: #555; padding: 2px 0;")
            stack_layout.addWidget(lbl)

        layout.addWidget(stack_card)

        # 功能列表
        feat_card = QFrame()
        feat_card.setStyleSheet(
            "QFrame { background: white; border-radius: 8px; "
            "border: 1px solid #E0E0E0; }"
        )
        feat_layout = QVBoxLayout(feat_card)
        feat_layout.setContentsMargins(20, 16, 20, 16)
        feat_layout.setSpacing(8)

        feat_layout.addWidget(QLabel("✨ 核心功能"))
        features = [
            "📊 数据看板 — 9 张图表 + 5 统计卡片 + 数据洞察",
            "⭐ 智能推荐 — 综合 / 热门 / 高分 / 口碑 / 性价比",
            "🔍 实时搜索 — 猫眼 + 豆瓣多源合并，异步不卡 UI",
            "🎬 电影详情 — 海报缓存、多源简介降级、实时票价",
            "📑 自定义看板 — 图表布局调整、模块隐藏",
            "📤 报告导出 — PDF / 图片 / 结构化 HTML 报告",
            "🔄 数据管理 — 手动刷新、票价补全、爬取日志",
        ]
        for f in features:
            lbl = QLabel(f"  {f}")
            lbl.setFont(QFont("Microsoft YaHei", 11))
            lbl.setStyleSheet("color: #555; padding: 2px 0;")
            feat_layout.addWidget(lbl)

        layout.addWidget(feat_card)

        # 底部版权
        layout.addStretch()
        footer = QLabel(
            "© 2026 电影票分析系统 · 学校实训项目\n"
            "数据来源: 猫眼电影 / 豆瓣电影 / OMDB API"
        )
        footer.setFont(QFont("Microsoft YaHei", 10))
        footer.setStyleSheet("color: #999;")
        footer.setAlignment(Qt.AlignCenter)
        layout.addWidget(footer)


class SettingsPage(QWidget):
    """系统设置页面 — 数据源 + 关于 两个标签页。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._data_source_page = DataSourcePage()
        self._about_section = AboutSection()
        self._setup_ui()

    def set_db(self, db: DatabaseManager) -> None:
        self._data_source_page.set_db(db)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        tabs = QTabWidget()
        tabs.setObjectName("settingsTabs")
        tabs.setStyleSheet(
            "QTabWidget::pane { border: none; background: #F5F7FA; }"
            "QTabBar::tab { font-size: 13px; padding: 10px 24px; "
            "  font-family: 'Microsoft YaHei'; }"
            "QTabBar::tab:selected { border-bottom: 2px solid #1E88E5; "
            "  color: #1E88E5; }"
        )

        tabs.addTab(self._data_source_page, "🔌 数据源管理")
        tabs.addTab(self._about_section, "ℹ️ 关于系统")

        layout.addWidget(tabs)
