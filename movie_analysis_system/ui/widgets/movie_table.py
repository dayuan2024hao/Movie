"""
电影数据表格组件
=================
基于 QTableWidget 实现，支持点击表头排序。
"""

import logging
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel,
)
from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtGui import QFont, QColor

from database.db_manager import DatabaseManager

logger = logging.getLogger("MovieTable")


class MovieTable(QWidget):
    """电影数据表格组件，显示电影列表并支持排序。"""

    # 双击电影行时发射信号（参数为电影 ID）
    movie_double_clicked = pyqtSignal(int)

    # 列定义：（标题, 宽度, 数据键名）
    COLUMNS = [
        ("电影名称", 200, "title"),
        ("评分", 60, "rating"),
        ("票房(万)", 100, "box_office"),
        ("票价(元)", 80, "ticket_price"),
        ("类型", 120, "genre"),
        ("上映年份", 80, "release_date"),
    ]

    def __init__(self, db: DatabaseManager, parent: Optional[QWidget] = None) -> None:
        """初始化表格组件。

        Args:
            db: 数据库管理器实例
            parent: 父组件
        """
        super().__init__(parent)
        self.db = db
        self._data: list[dict] = []
        self._sort_column: int = -1
        self._sort_order: Qt.SortOrder = Qt.AscendingOrder

        self.setup_ui()

    def setup_ui(self) -> None:
        """构建表格布局。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 表格
        self.table = QTableWidget()
        self.table.setObjectName("movieTable")
        self.table.setColumnCount(len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([c[0] for c in self.COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.cellDoubleClicked.connect(self._on_double_click)

        # 表头排序
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header_clicked)

        # 设置列宽
        for i, (_, width, _) in enumerate(self.COLUMNS):
            self.table.setColumnWidth(i, width)

        layout.addWidget(self.table)

    def _on_double_click(self, row: int, column: int) -> None:
        """双击行时发射电影 ID。

        Args:
            row: 行索引
            column: 列索引
        """
        if row < len(self._data):
            movie_id = self._data[row].get("id")
            if movie_id:
                self.movie_double_clicked.emit(movie_id)

    def load_data(self, limit: int = 50) -> None:
        """从数据库加载电影数据并显示。

        Args:
            limit: 加载条数上限
        """
        try:
            total, records = self.db.query_movies(
                sort_by="box_office", sort_order="DESC", limit=limit
            )
            self._data = records
            self._refresh_table()
            logger.debug("加载了 %d 条电影数据", len(records))
        except Exception as e:
            logger.error("加载电影数据失败: %s", e)

    def _refresh_table(self) -> None:
        """刷新表格显示。"""
        self.table.setRowCount(len(self._data))

        for row_idx, movie in enumerate(self._data):
            # 电影名称
            title_item = QTableWidgetItem(str(movie.get("title", "")))
            title_item.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
            self.table.setItem(row_idx, 0, title_item)

            # 评分
            rating = movie.get("rating", 0) or 0
            rating_item = QTableWidgetItem(f"{rating:.1f}")
            rating_item.setTextAlignment(Qt.AlignCenter)
            # 评分颜色：高分绿色，低分红色
            if rating >= 8.0:
                rating_item.setForeground(QColor("#43A047"))
            elif rating >= 6.0:
                rating_item.setForeground(QColor("#FB8C00"))
            else:
                rating_item.setForeground(QColor("#E53935"))
            self.table.setItem(row_idx, 1, rating_item)

            # 票房
            box_office = movie.get("box_office", 0) or 0
            bo_item = QTableWidgetItem(f"{box_office:,.0f}")
            bo_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row_idx, 2, bo_item)

            # 票价
            price = movie.get("ticket_price", 0) or 0
            price_item = QTableWidgetItem(f"{price:.0f}" if price else "-")
            price_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 3, price_item)

            # 类型
            genre_item = QTableWidgetItem(str(movie.get("genre", "")))
            genre_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 4, genre_item)

            # 上映年份
            release = movie.get("release_date", "") or ""
            year = release[:4] if release else "-"
            year_item = QTableWidgetItem(year)
            year_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row_idx, 5, year_item)

    def _on_header_clicked(self, column: int) -> None:
        """表头点击排序。

        Args:
            column: 点击的列索引
        """
        if column == self._sort_column:
            # 切换排序方向
            self._sort_order = (
                Qt.DescendingOrder
                if self._sort_order == Qt.AscendingOrder
                else Qt.AscendingOrder
            )
        else:
            self._sort_column = column
            self._sort_order = Qt.DescendingOrder

        # 根据点击的列排序数据
        key = self.COLUMNS[column][2]
        reverse = self._sort_order == Qt.DescendingOrder
        try:
            self._data.sort(
                key=lambda x: (x.get(key) is not None, x.get(key) or 0),
                reverse=reverse,
            )
        except TypeError:
            pass

        self._refresh_table()
