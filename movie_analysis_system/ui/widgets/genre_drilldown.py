"""
类型下钻弹窗
============
点击图表中的电影类型，弹窗显示该类型下的电影列表及详细指标。
"""

import logging
from typing import Optional

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QFrame, QWidget, QAbstractItemView,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from database.db_manager import DatabaseManager

logger = logging.getLogger("GenreDrilldown")


class GenreDrilldownDialog(QDialog):
    """类型下钻对话框，显示所有类型列表 + 选中类型的电影详情。"""

    def __init__(self, db: DatabaseManager,
                 initial_genre: str = "",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("类型下钻分析")
        self.setMinimumSize(800, 550)
        self.setStyleSheet("background: #F5F7FA;")

        self._setup_ui()
        self._load_genres(initial_genre)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("🔍 类型下钻分析")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        title.setStyleSheet("color: #37474F;")
        layout.addWidget(title)

        desc = QLabel("左侧选择类型，右侧查看该类型下所有电影的详细数据")
        desc.setFont(QFont("Microsoft YaHei", 11))
        desc.setStyleSheet("color: #757575;")
        layout.addWidget(desc)

        # 分割器：左（类型列表）+ 右（电影表格）
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：类型列表
        left_panel = QFrame()
        left_panel.setStyleSheet("QFrame { background: white; border-radius: 8px; }")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)

        left_title = QLabel("电影类型")
        left_title.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        left_title.setStyleSheet("color: #37474F; padding: 4px;")
        left_layout.addWidget(left_title)

        self._genre_list = QListWidget()
        self._genre_list.setStyleSheet(
            "QListWidget { border: none; font-size: 12px; }"
            "QListWidget::item { padding: 8px; }"
            "QListWidget::item:selected { background: #E3F2FD; color: #1E88E5; }"
            "QListWidget::item:hover { background: #F5F5F5; }"
        )
        self._genre_list.currentRowChanged.connect(self._on_genre_selected)
        left_layout.addWidget(self._genre_list)

        splitter.addWidget(left_panel)

        # 右侧：电影表格
        right_panel = QFrame()
        right_panel.setStyleSheet("QFrame { background: white; border-radius: 8px; }")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)

        self._detail_title = QLabel("选择左侧类型查看电影")
        self._detail_title.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        self._detail_title.setStyleSheet("color: #37474F; padding: 4px;")
        right_layout.addWidget(self._detail_title)

        self._movie_table = QTableWidget()
        self._movie_table.setColumnCount(6)
        self._movie_table.setHorizontalHeaderLabels([
            "电影名称", "评分", "票房(万)", "票价(元)", "上映日期", "状态"
        ])
        self._movie_table.horizontalHeader().setStretchLastSection(True)
        self._movie_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._movie_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._movie_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._movie_table.setAlternatingRowColors(True)
        self._movie_table.setStyleSheet(
            "QTableWidget { border: none; font-size: 11px; }"
            "QHeaderView::section { background: #ECEFF1; padding: 6px; font-weight: bold; }"
        )
        right_layout.addWidget(self._movie_table)

        splitter.addWidget(right_panel)
        splitter.setSizes([200, 600])

        layout.addWidget(splitter, 1)

        # 关闭按钮
        btn_row = QHBoxLayout()
        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(
            "QPushButton { background: #1E88E5; color: white; border: none; "
            "border-radius: 6px; padding: 8px 24px; font-size: 13px; }"
            "QPushButton:hover { background: #1565C0; }"
        )
        close_btn.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _load_genres(self, initial_genre: str = "") -> None:
        """加载所有电影类型到列表。"""
        self._genre_list.blockSignals(True)
        self._genre_list.clear()

        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT TRIM(value) AS genre, COUNT(*) AS cnt,
                       ROUND(AVG(rating),1) AS avg_rating,
                       ROUND(SUM(box_office),0) AS total_bo
                FROM movies, json_each('["' || REPLACE(genre, ',', '","') || '"]')
                GROUP BY TRIM(value) ORDER BY cnt DESC
            """)
            genres = [dict(r) for r in cursor.fetchall()]
            cursor.close()

            for g in genres:
                text = f"{g['genre']}  ({g['cnt']}部 · 均分{g['avg_rating']})"
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, g["genre"])
                self._genre_list.addItem(item)

            # 选中初始类型
            if initial_genre:
                for i in range(self._genre_list.count()):
                    if self._genre_list.item(i).data(Qt.UserRole) == initial_genre:
                        self._genre_list.setCurrentRow(i)
                        break
            elif self._genre_list.count() > 0:
                self._genre_list.setCurrentRow(0)

        except Exception as e:
            logger.error("加载类型列表失败: %s", e)
        finally:
            self._genre_list.blockSignals(False)

    def _on_genre_selected(self, row: int) -> None:
        """选中类型时加载对应电影列表。"""
        if row < 0:
            return
        item = self._genre_list.item(row)
        if not item:
            return
        genre = item.data(Qt.UserRole)
        self._load_movies_for_genre(genre)

    def _load_movies_for_genre(self, genre: str) -> None:
        """加载指定类型的电影列表。"""
        if not genre:
            return

        self._detail_title.setText(f"🎬 {genre} 类型电影")
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT title, rating, box_office, ticket_price,
                       release_date, showing_status
                FROM movies WHERE genre LIKE ?
                ORDER BY box_office DESC
            """, (f"%{genre}%",))
            movies = [dict(r) for r in cursor.fetchall()]
            cursor.close()

            self._movie_table.setRowCount(len(movies))
            for i, m in enumerate(movies):
                self._movie_table.setItem(i, 0, QTableWidgetItem(m["title"] or ""))
                self._movie_table.setItem(i, 1, QTableWidgetItem(
                    f'{m["rating"]:.1f}' if m["rating"] else "—"))
                self._movie_table.setItem(i, 2, QTableWidgetItem(
                    f'{m["box_office"]:,.0f}' if m["box_office"] else "—"))
                self._movie_table.setItem(i, 3, QTableWidgetItem(
                    f'{m["ticket_price"]:.0f}' if m["ticket_price"] else "—"))
                self._movie_table.setItem(i, 4, QTableWidgetItem(
                    (m["release_date"] or "")[:10]))
                status_map = {"showing": "热映中", "coming_soon": "即将上映", "released": "已下映"}
                self._movie_table.setItem(i, 5, QTableWidgetItem(
                    status_map.get(m["showing_status"], m["showing_status"] or "")))
            self._movie_table.resizeRowsToContents()

        except Exception as e:
            logger.error("加载类型电影失败: %s", e)
