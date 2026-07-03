"""
搜索页面 — 实时跨站搜索
======================
猫眼H5 + 豆瓣 并发搜索，去重合并，实时结果展示。
"""

import logging
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QScrollArea, QFrame, QSizePolicy,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont, QPixmap, QColor, QPainter

from crawler.realtime_aggregator import RealtimeAggregator

logger = logging.getLogger("SearchPage")

SEARCH_W = 380  # 搜索框宽度


def _make_source_badge(source: str) -> QLabel:
    """创建来源标签。"""
    badge = QLabel(f"[{source}]")
    badge.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
    if "猫眼" in source:
        color = "#E53E3E"
    else:
        color = "#38A169"
    if "猫眼+豆瓣" in source:
        color = "#FF6B6B"
    badge.setStyleSheet(f"color: {color}; background: transparent;")
    return badge


class SearchResultCard(QFrame):
    """单条搜索结果卡片。"""

    clicked = pyqtSignal(dict)

    def __init__(self, data: dict, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._data = data
        self.setObjectName("searchResultCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "QFrame#searchResultCard { background: white; border-radius: 8px; "
            "border: 1px solid #E8E8E8; }"
            "QFrame#searchResultCard:hover { border: 1px solid #BDBDBD; }"
        )
        self._setup_ui()

    def mousePressEvent(self, event) -> None:
        self.clicked.emit(self._data)
        super().mousePressEvent(event)

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 16, 10)
        layout.setSpacing(12)

        # 信息区
        info = QVBoxLayout()
        info.setSpacing(4)

        # 标题行 + 来源标签
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_lbl = QLabel(self._data.get("title", "未知"))
        title_lbl.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        title_lbl.setStyleSheet("color: #333;")
        title_row.addWidget(title_lbl)
        title_row.addWidget(_make_source_badge(self._data.get("source", "?")))
        title_row.addStretch()
        info.addLayout(title_row)

        # 评分 + 年份
        parts = []
        rating = self._data.get("rating") or 0
        if rating:
            parts.append(f"评分 {rating:.1f}")
        year = self._data.get("year", "")
        if year:
            parts.append(year)
        if parts:
            meta = QLabel(" · ".join(parts))
            meta.setFont(QFont("Microsoft YaHei", 11))
            meta.setStyleSheet("color: #999;")
            info.addWidget(meta)

        # maoyan_id 有效性提示
        maoyan_id = self._data.get("maoyan_id", "")
        if maoyan_id:
            tip = QLabel("✅ 可查看详情和购票")
            tip.setFont(QFont("Microsoft YaHei", 10))
            tip.setStyleSheet("color: #38A169;")
            info.addWidget(tip)

        info.addStretch()
        layout.addLayout(info, 1)


class SearchPage(QWidget):
    """搜索页面 — 实时跨站搜索。"""

    navigation_requested = pyqtSignal(dict)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._aggregator = RealtimeAggregator()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 标题
        title = QLabel("搜索电影")
        title.setFont(QFont("Microsoft YaHei", 20, QFont.Bold))
        title.setStyleSheet("color: #37474F; padding: 20px 24px 0 24px;")
        layout.addWidget(title)

        # 搜索栏
        search_bar = QHBoxLayout()
        search_bar.setContentsMargins(24, 12, 24, 8)
        search_bar.setSpacing(8)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("输入电影名称、演员...")
        self._search_input.setFixedHeight(40)
        self._search_input.setFont(QFont("Microsoft YaHei", 12))
        self._search_input.setStyleSheet(
            "QLineEdit { border: 2px solid #E0E0E0; border-radius: 6px; "
            "padding: 0 12px; background: white; }"
            "QLineEdit:focus { border-color: #1E88E5; }"
        )
        self._search_input.returnPressed.connect(self._do_search)
        search_bar.addWidget(self._search_input, 1)

        self._search_btn = QPushButton("搜索")
        self._search_btn.setFixedSize(100, 40)
        self._search_btn.setCursor(Qt.PointingHandCursor)
        self._search_btn.setStyleSheet(
            "QPushButton { background: #1E88E5; color: white; border: none; "
            "border-radius: 6px; font: 13pt; font-weight: bold; }"
            "QPushButton:hover { background: #1565C0; }"
        )
        self._search_btn.clicked.connect(self._do_search)
        search_bar.addWidget(self._search_btn)

        layout.addLayout(search_bar)

        # 结果标签
        self._result_label = QLabel("输入关键词开始搜索")
        self._result_label.setFont(QFont("Microsoft YaHei", 12))
        self._result_label.setStyleSheet("color: #999; padding: 0 24px;")
        layout.addWidget(self._result_label)

        # 结果区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: #F5F7FA; border: none; }")

        self._results_container = QWidget()
        self._results_layout = QVBoxLayout(self._results_container)
        self._results_layout.setContentsMargins(24, 12, 24, 24)
        self._results_layout.setSpacing(8)
        self._results_layout.addStretch()

        scroll.setWidget(self._results_container)
        layout.addWidget(scroll, 1)

    def _do_search(self) -> None:
        """执行搜索。"""
        keyword = self._search_input.text().strip()
        if not keyword:
            return

        self._search_btn.setEnabled(False)
        self._search_btn.setText("搜索中...")
        self._result_label.setText(f"正在搜索「{keyword}」...")

        # 清空旧结果（保留 stretch）
        while self._results_layout.count() > 1:
            item = self._results_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        # 异步搜索
        from PyQt5.QtCore import QTimer

        def do_search():
            try:
                results = self._aggregator.search_all(keyword)
                return results
            except Exception as e:
                logger.error("[SEARCH] 搜索异常: %s", e)
                return []

        def on_results(results):
            self._search_btn.setEnabled(True)
            self._search_btn.setText("搜索")

            if not results:
                self._result_label.setText("未找到相关电影")
                self._result_label.setStyleSheet("color: #999; padding: 0 24px;")
                return

            self._result_label.setText(f"搜索到 {len(results)} 条结果")
            self._result_label.setStyleSheet("color: #38A169; padding: 0 24px;")

            for r in results:
                card = SearchResultCard(r)
                card.clicked.connect(self._on_result_clicked)
                self._results_layout.insertWidget(self._results_layout.count() - 1, card)

            logger.info("[SEARCH] 搜索完成: %s → %d 条", keyword, len(results))

        # 在后台线程执行搜索，主线程更新UI
        import threading

        def task():
            res = do_search()
            QTimer.singleShot(0, lambda: on_results(res))

        threading.Thread(target=task, daemon=True).start()

    def _on_result_clicked(self, data: dict) -> None:
        """搜索结果被点击 → 导航到详情页。"""
        self.navigation_requested.emit(data)
