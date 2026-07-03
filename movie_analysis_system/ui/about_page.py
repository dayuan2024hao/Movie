"""
关于页面（占位）
================
系统信息 + 版本号 + 技术栈介绍。
"""

import logging
from typing import Optional

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

logger = logging.getLogger("AboutPage")


class AboutPage(QWidget):
    """关于页面（占位）。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        title = QLabel("关于系统")
        title.setFont(QFont("Microsoft YaHei", 24, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)

        msg = QLabel("系统信息 + 版本号 + 技术栈介绍（阶段 7 完善）")
        msg.setFont(QFont("Microsoft YaHei", 13))
        msg.setAlignment(Qt.AlignCenter)
        msg.setStyleSheet("color: #757575; margin-top: 12px;")

        layout.addWidget(title)
        layout.addWidget(msg)
