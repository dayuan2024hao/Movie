"""
统计卡片组件
============
可复用的统计卡片，用于展示关键指标数字。
包含图标、大号数字和文字标签。

用法：
    card = StatCard("电影总数", "1,250", "🎬")
    card.set_value("1,260")  # 动态更新
"""

import logging
from typing import Optional

from PyQt5.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QWidget
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QFont, QFontMetrics

logger = logging.getLogger("StatCard")


class StatCard(QFrame):
    """统计卡片组件。"""

    def __init__(
        self,
        title: str,
        value: str = "0",
        icon: str = "📊",
        color: str = "#1E88E5",
        parent: Optional[QWidget] = None,
    ) -> None:
        """初始化统计卡片。

        Args:
            title: 卡片标题（如"电影总数"）
            value: 显示的数字（如"1,250"）
            icon: 图标 emoji
            color: 数字的强调色
            parent: 父组件
        """
        super().__init__(parent)
        self._title = title
        self._value = value
        self._icon = icon
        self._color = color

        self.setObjectName("statCard")
        self.setFixedSize(230, 90)
        self.setup_ui()

    def setup_ui(self) -> None:
        """构建卡片内部布局。"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        # 图标区
        icon_label = QLabel(self._icon)
        icon_label.setFont(QFont("Microsoft YaHei", 20))
        icon_label.setFixedSize(36, 36)
        icon_label.setAlignment(Qt.AlignCenter)

        # 文字区
        text_layout = QVBoxLayout()
        text_layout.setSpacing(0)

        value_label = QLabel()
        value_label.setStyleSheet(f"color: {self._color};")
        value_label.setObjectName("statValue")
        self._adjust_font_size(value_label, self._value)

        title_label = QLabel(self._title)
        title_label.setFont(QFont("Microsoft YaHei", 10))
        title_label.setStyleSheet("color: #757575;")
        title_label.setObjectName("statTitle")

        text_layout.addWidget(value_label)
        text_layout.addWidget(title_label)

        layout.addWidget(icon_label)
        layout.addLayout(text_layout)
        layout.addStretch()

    def _adjust_font_size(self, label: QLabel, text: str,
                          max_width: int = 180, base_size: int = 18) -> None:
        """根据文本宽度自动调整字号，防止溢出不显示。"""
        font = label.font()
        for size in range(base_size, 9, -1):  # 向下试探到 9pt
            font.setPointSize(size)
            metrics = QFontMetrics(font)
            text_width = metrics.horizontalAdvance(text)
            if text_width <= max_width:
                break
        label.setFont(font)
        label.setText(text)

    def set_value(self, value: str) -> None:
        """动态更新卡片显示的数字（自动调整字号防截断）。

        Args:
            value: 新的数字字符串
        """
        self._value = value
        value_label = self.findChild(QLabel, "statValue")
        if value_label:
            self._adjust_font_size(value_label, value)

    def set_title(self, title: str) -> None:
        """动态更新卡片标题。

        Args:
            title: 新的标题文字
        """
        self._title = title
        title_label = self.findChild(QLabel, "statTitle")
        if title_label:
            title_label.setText(title)
