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
from PyQt5.QtGui import QFont

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
        self.setFixedSize(210, 100)
        self.setup_ui()

    def setup_ui(self) -> None:
        """构建卡片内部布局。"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        # 图标区
        icon_label = QLabel(self._icon)
        icon_label.setFont(QFont("Microsoft YaHei", 24))
        icon_label.setFixedSize(40, 40)
        icon_label.setAlignment(Qt.AlignCenter)

        # 文字区
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        value_label = QLabel(self._value)
        value_label.setFont(QFont("Microsoft YaHei", 22, QFont.Bold))
        value_label.setStyleSheet(f"color: {self._color};")
        value_label.setObjectName("statValue")

        title_label = QLabel(self._title)
        title_label.setFont(QFont("Microsoft YaHei", 12))
        title_label.setStyleSheet("color: #757575;")
        title_label.setObjectName("statTitle")

        text_layout.addWidget(value_label)
        text_layout.addWidget(title_label)

        layout.addWidget(icon_label)
        layout.addLayout(text_layout)
        layout.addStretch()

    def set_value(self, value: str) -> None:
        """动态更新卡片显示的数字。

        Args:
            value: 新的数字字符串
        """
        self._value = value
        value_label = self.findChild(QLabel, "statValue")
        if value_label:
            value_label.setText(value)

    def set_title(self, title: str) -> None:
        """动态更新卡片标题。

        Args:
            title: 新的标题文字
        """
        self._title = title
        title_label = self.findChild(QLabel, "statTitle")
        if title_label:
            title_label.setText(title)
