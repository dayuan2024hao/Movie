"""
主窗口
======
QMainWindow 主框架，包含左侧导航栏和右侧页面容器（QStackedWidget）。

布局结构：
  ┌──────────────────────────────────────┐
  │  [200px nav]    [content area]       │
  │  ┌──────────┐  ┌──────────────────┐  │
  │  │ 📊 看板   │  │                  │  │
  │  │ 🔍 搜索   │  │   QStackedWidget │  │
  │  │ ⭐ 推荐   │  │   (页面容器)     │  │
  │  │ 👤 关于   │  │                  │  │
  │  └──────────┘  └──────────────────┘  │
  │              状态栏                   │
  └──────────────────────────────────────┘
"""

import logging
from typing import Optional

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QStackedWidget, QLabel, QStatusBar,
    QSizePolicy, QSpacerItem, QApplication,
)
from PyQt5.QtCore import Qt, QSize, QPropertyAnimation, pyqtSignal
from PyQt5.QtGui import QFont, QIcon

from database.db_manager import DatabaseManager
from ui.search_page import SearchPage
from ui.recommendation_page import RecommendationPage
from ui.detail_page import DetailPage
from ui.about_page import AboutPage

logger = logging.getLogger("MainWindow")


# ──────────────────────────── 导航按钮 ────────────────────────────

class NavButton(QPushButton):
    """自定义导航按钮，支持选中高亮 + 左侧蓝色竖条。"""

    def __init__(self, text: str, icon_text: str, parent: Optional[QWidget] = None) -> None:
        """初始化导航按钮。

        Args:
            text: 按钮文字
            icon_text: 图标 emoji 字符
            parent: 父组件
        """
        super().__init__(f"  {icon_text}  {text}", parent)
        self.setCheckable(True)
        self.setFixedHeight(48)
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("navButton")
        self.setFont(QFont("Microsoft YaHei", 13))
        # 字体大小由 QSS 中 font-size:10pt 控制（覆盖此设置）
        # 保留 setFont 防止 QSS 未加载时的默认字体过小

    def sizeHint(self) -> QSize:
        """返回按钮推荐尺寸。"""
        return QSize(200, 48)


# ──────────────────────────── 页面占位组件 ────────────────────────────

class PlaceholderPage(QWidget):
    """占位页面，用于尚未实现的页面。"""

    def __init__(self, title: str, message: str, parent: Optional[QWidget] = None) -> None:
        """初始化占位页面。

        Args:
            title: 页面标题
            message: 提示信息
            parent: 父组件
        """
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        label_title = QLabel(title)
        label_title.setFont(QFont("Microsoft YaHei", 24, QFont.Bold))
        label_title.setAlignment(Qt.AlignCenter)
        label_title.setObjectName("pageTitle")

        label_msg = QLabel(message)
        label_msg.setFont(QFont("Microsoft YaHei", 13))
        label_msg.setAlignment(Qt.AlignCenter)
        label_msg.setObjectName("pageMessage")
        label_msg.setStyleSheet("color: #757575; margin-top: 12px;")

        layout.addWidget(label_title)
        layout.addWidget(label_msg)


# ──────────────────────────── 主窗口 ────────────────────────────

class MainWindow(QMainWindow):
    """系统主窗口。"""

    # 页面切换信号（供外部监听）
    page_changed = pyqtSignal(int)

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        """初始化主窗口：设置尺寸、导航栏、页面容器、样式。

        Args:
            db: 数据库管理器实例（看板页面需要）
        """
        super().__init__()
        self.db = db or DatabaseManager()
        self.setWindowTitle("电影票分析系统")
        self.setMinimumSize(1200, 700)
        self.resize(1400, 900)

        # 页面索引映射
        self.PAGE_RECOMMEND = 0
        self.PAGE_SEARCH = 1
        self.PAGE_ABOUT = 2
        self.PAGE_DETAIL = 3

        # 导航按钮列表
        self._nav_buttons: list[NavButton] = []
        # 默认选中推荐页
        self._prev_page: int = self.PAGE_RECOMMEND

        # 构建界面
        self._setup_ui()
        self._load_styles()

        # 窗口居中
        self._center_window()

        logger.info("主窗口初始化完成")

    # ──────────────────────── UI 构建 ────────────────────────

    def _setup_ui(self) -> None:
        """构建主界面布局。"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 左侧导航栏 ──
        nav_widget = self._create_nav_bar()
        main_layout.addWidget(nav_widget)

        # ── 右侧内容区 ──
        content_widget = self._create_content_area()
        main_layout.addWidget(content_widget, 1)  # stretch=1 占满剩余空间

        # ── 状态栏 ──
        self.statusBar().showMessage("就绪")

    def _create_nav_bar(self) -> QWidget:
        """创建左侧导航栏。

        Returns:
            包含导航按钮的 QWidget
        """
        nav_widget = QWidget()
        nav_widget.setObjectName("navBar")
        nav_widget.setFixedWidth(200)

        nav_layout = QVBoxLayout(nav_widget)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(0)

        # Logo / 标题区
        logo_label = QLabel("  电影票分析系统")
        logo_label.setObjectName("navLogo")
        logo_label.setFixedHeight(64)
        logo_label.setFont(QFont("Microsoft YaHei", 13, QFont.Bold))
        nav_layout.addWidget(logo_label)

        # 分隔线
        separator = QLabel()
        separator.setFixedHeight(1)
        separator.setObjectName("navSeparator")
        nav_layout.addWidget(separator)

        # 导航按钮
        nav_items = [
            ("电影推荐", "⭐"),
            ("搜索筛选", "🔍"),
            ("关于系统", "👤"),
        ]

        # 按钮组
        btn_group = QWidget()
        btn_group.setObjectName("navButtonGroup")
        btn_layout = QVBoxLayout(btn_group)
        btn_layout.setContentsMargins(0, 8, 0, 8)
        btn_layout.setSpacing(2)

        for i, (text, icon) in enumerate(nav_items):
            btn = NavButton(text, icon)
            btn.clicked.connect(lambda checked, idx=i: self.switch_page(idx))
            self._nav_buttons.append(btn)
            btn_layout.addWidget(btn)

        btn_layout.addStretch()
        nav_layout.addWidget(btn_group)

        # 默认选中看板
        if self._nav_buttons:
            self._nav_buttons[0].setChecked(True)

        return nav_widget

    def _create_content_area(self) -> QWidget:
        """创建右侧内容区域（页面容器）。

        Returns:
            包含 QStackedWidget 的 QWidget
        """
        content_widget = QWidget()
        content_widget.setObjectName("contentArea")

        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        self.stack = QStackedWidget()
        self.stack.setObjectName("pageStack")

        # 创建页面
        recommendation = RecommendationPage()
        recommendation.set_db(self.db)
        search = SearchPage()
        self.detail_page = DetailPage()
        self.detail_page.db = self.db
        self.detail_page.back_requested.connect(
            lambda: self.switch_page(self._prev_page)
        )

        # 添加 4 个页面
        self.stack.addWidget(recommendation)
        self.stack.addWidget(search)
        self.stack.addWidget(AboutPage())
        self.stack.addWidget(self.detail_page)

        # 连接推荐卡片 → 详情导航
        recommendation.navigation_requested.connect(self.show_movie_detail)

        # 连接搜索 → 详情导航（支持 dict 数据传递）
        search.navigation_requested.connect(self.show_movie_detail_from_data)

        content_layout.addWidget(self.stack)

        return content_widget

    # ──────────────────────── 页面切换 ────────────────────────

    def switch_page(self, index: int) -> None:
        """切换到指定页面。

        Args:
            index: 页面索引（0=看板, 1=搜索, 2=推荐, 3=关于, 4=详情）
        """
        if index < 0 or index >= self.stack.count():
            logger.warning("无效页面索引: %d", index)
            return

        # 记录前页（供详情页返回用），详情页本身不记录
        if index != self.PAGE_DETAIL:
            self._prev_page = index

        # 更新导航按钮状态（详情页不选中任何导航）
        for i, btn in enumerate(self._nav_buttons):
            btn.setChecked(i == index if index < 4 else False)

        # 切换页面
        self.stack.setCurrentIndex(index)
        self.page_changed.emit(index)

        # 状态栏更新
        page_names = ["电影推荐", "搜索筛选", "关于系统", "电影详情"]
        if index < len(page_names):
            self.statusBar().showMessage(f"当前页面: {page_names[index]}")

        logger.info("切换到页面: %s", page_names[index])

    def show_movie_detail(self, movie_id: int) -> None:
        """导航到电影详情页（按 DB ID）。"""
        self.detail_page.show_movie(movie_id)
        self.switch_page(self.PAGE_DETAIL)

    def show_movie_detail_from_data(self, data: dict) -> None:
        """导航到电影详情页（按实时搜索数据）。"""
        self.detail_page.show_movie_data(data)
        self.switch_page(self.PAGE_DETAIL)

    # ──────────────────────── 样式加载 ────────────────────────

    def _load_styles(self) -> None:
        """从 QSS 文件加载样式表。"""
        qss_paths = [
            "resources/styles/main.qss",
        ]

        combined_styles = ""
        for path in qss_paths:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    combined_styles += f.read() + "\n"
            except FileNotFoundError:
                logger.warning("样式文件未找到: %s", path)

        if combined_styles:
            self.setStyleSheet(combined_styles)
            logger.info("样式表已加载")

    # ──────────────────────── 工具方法 ────────────────────────

    def _center_window(self) -> None:
        """将窗口居中显示。"""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        screen_rect = screen.availableGeometry()
        window_rect = self.frameGeometry()
        center = screen_rect.center()
        window_rect.moveCenter(center)
        self.move(window_rect.topLeft())
