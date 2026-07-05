"""
多片对比工具
============
允许用户勾选 2-4 部电影，横向对比票房、评分、票价等维度。
"""

import logging
from typing import Optional

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QListWidget, QListWidgetItem, QFrame, QMessageBox,
    QWidget, QSplitter, QScrollArea,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor

from database.db_manager import DatabaseManager

logger = logging.getLogger("CompareTool")


class CompareToolDialog(QDialog):
    """多片对比对话框。"""

    def __init__(self, db: DatabaseManager, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("多片对比工具")
        self.setMinimumSize(900, 600)
        self.setStyleSheet("background: #F5F7FA;")

        self._selected_movies: list[dict] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 标题
        title = QLabel("📊 多片对比分析")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        title.setStyleSheet("color: #37474F;")
        layout.addWidget(title)

        desc = QLabel("搜索并添加 2-4 部电影，横向对比票房、评分、票价等指标")
        desc.setFont(QFont("Microsoft YaHei", 11))
        desc.setStyleSheet("color: #757575;")
        layout.addWidget(desc)

        # 搜索区 + 已选电影区
        splitter = QSplitter(Qt.Horizontal)

        # 左：搜索区
        left_panel = QFrame()
        left_panel.setStyleSheet("QFrame { background: white; border-radius: 8px; }")
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 8, 8)

        left_title = QLabel("🔍 搜索电影")
        left_title.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        left_title.setStyleSheet("color: #37474F;")
        left_layout.addWidget(left_title)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("输入片名搜索...")
        self._search_input.setStyleSheet(
            "QLineEdit { border: 1px solid #DDD; border-radius: 4px; "
            "padding: 6px 10px; font-size: 12px; }"
            "QLineEdit:focus { border-color: #1E88E5; }"
        )
        self._search_input.returnPressed.connect(self._do_search)
        left_layout.addWidget(self._search_input)

        self._search_results = QListWidget()
        self._search_results.setStyleSheet(
            "QListWidget { border: none; font-size: 12px; }"
            "QListWidget::item { padding: 6px; }"
            "QListWidget::item:selected { background: #E3F2FD; }"
            "QListWidget::item:hover { background: #F5F5F5; }"
        )
        self._search_results.itemDoubleClicked.connect(self._add_movie)
        left_layout.addWidget(self._search_results, 1)

        splitter.addWidget(left_panel)

        # 右：对比区
        right_panel = QFrame()
        right_panel.setStyleSheet("QFrame { background: white; border-radius: 8px; }")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)

        right_title = QLabel("📋 对比列表（点击已选电影移除）")
        right_title.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        right_title.setStyleSheet("color: #37474F;")
        right_layout.addWidget(right_title)

        self._selected_list = QListWidget()
        self._selected_list.setStyleSheet(
            "QListWidget { border: none; font-size: 12px; }"
            "QListWidget::item { padding: 8px; background: #E3F2FD; "
            "border-radius: 4px; margin: 2px; }"
        )
        self._selected_list.itemClicked.connect(self._remove_movie)
        self._selected_list.setMaximumHeight(120)
        right_layout.addWidget(self._selected_list)

        # 对比表格
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        self._compare_table = QTableWidget()
        self._compare_table.setColumnCount(1)
        self._compare_table.setRowCount(0)
        self._compare_table.verticalHeader().setVisible(False)
        self._compare_table.horizontalHeader().setVisible(False)
        self._compare_table.horizontalHeader().setStretchLastSection(True)
        self._compare_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._compare_table.setStyleSheet(
            "QTableWidget { border: none; font-size: 12px; }"
            "QTableWidget::item { padding: 8px 12px; }"
        )
        scroll.setWidget(self._compare_table)
        right_layout.addWidget(scroll, 1)

        splitter.addWidget(right_panel)
        splitter.setSizes([280, 620])
        layout.addWidget(splitter, 1)

        # 初始加载全部电影
        self._load_all_movies()

    def _load_all_movies(self) -> None:
        """加载所有电影到搜索结果。"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, title, rating, box_office FROM movies "
                "ORDER BY box_office DESC LIMIT 50"
            )
            all_movies = [dict(r) for r in cursor.fetchall()]
            cursor.close()

            self._search_results.clear()
            for m in all_movies:
                text = f"{m['title']}  ⭐{m['rating'] or '—'}  💰{m['box_office'] or 0:,.0f}万"
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, dict(m))
                self._search_results.addItem(item)
        except Exception as e:
            logger.error("加载电影列表失败: %s", e)

    def _do_search(self) -> None:
        """按关键词搜索电影。"""
        keyword = self._search_input.text().strip()
        if not keyword:
            self._load_all_movies()
            return

        try:
            total, movies = self.db.query_movies(
                keyword=keyword, limit=30,
                sort_by="box_office", sort_order="DESC",
            )
            self._search_results.clear()
            for m in movies:
                text = f"{m['title']}  ⭐{m['rating'] or '—'}  💰{m['box_office'] or 0:,.0f}万"
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, dict(m))
                self._search_results.addItem(item)
        except Exception as e:
            logger.error("搜索失败: %s", e)

    def _add_movie(self, item: QListWidgetItem) -> None:
        """将电影添加到对比列表。"""
        movie_data = item.data(Qt.UserRole)
        if not movie_data:
            return

        if len(self._selected_movies) >= 4:
            QMessageBox.warning(self, "提示", "最多对比 4 部电影")
            return

        if any(m.get("id") == movie_data.get("id") for m in self._selected_movies):
            return

        self._selected_movies.append(movie_data)
        self._update_selected_list()
        self._update_compare_table()

    def _remove_movie(self, item: QListWidgetItem) -> None:
        """点击已选电影移除。"""
        title = item.text().split("  ")[0].strip()
        self._selected_movies = [
            m for m in self._selected_movies
            if m.get("title") != title
        ]
        self._update_selected_list()
        self._update_compare_table()

    def _update_selected_list(self) -> None:
        """更新已选电影列表显示。"""
        self._selected_list.clear()
        for m in self._selected_movies:
            item = QListWidgetItem(f"❌ {m['title']}")
            self._selected_list.addItem(item)

    def _update_compare_table(self) -> None:
        """更新对比表格。"""
        movies = self._selected_movies
        n = len(movies)
        if n == 0:
            self._compare_table.setColumnCount(1)
            self._compare_table.setHorizontalHeaderLabels(["请添加电影到对比列表"])
            self._compare_table.setRowCount(0)
            return

        # 指标行：维度, 电影1, 电影2, ...
        rows_data = [
            ("电影名称", [m.get("title", "—") for m in movies]),
            ("评分", [f'{m.get("rating") or 0:.1f}' for m in movies]),
            ("评分人数", [f'{m.get("rating_count") or 0:,}' for m in movies]),
            ("票房(万)", [f'{m.get("box_office") or 0:,.0f}' for m in movies]),
            ("票价(元)", [f'{m.get("ticket_price") or 0:.0f}' for m in movies]),
            ("类型", [m.get("genre", "—") for m in movies]),
            ("上映日期", [(m.get("release_date") or "")[:10] for m in movies]),
            ("导演", [m.get("director", "—") for m in movies]),
            ("地区", [m.get("region", "—") for m in movies]),
        ]

        self._compare_table.setColumnCount(n)
        self._compare_table.setRowCount(len(rows_data))
        self._compare_table.setHorizontalHeaderLabels([m.get("title", "电影") for m in movies])
        self._compare_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        for i, (dim, vals) in enumerate(rows_data):
            dim_item = QTableWidgetItem(f"  {dim}")
            dim_item.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
            dim_item.setBackground(QColor("#F5F5F5"))
            dim_item.setFlags(dim_item.flags() & ~Qt.ItemIsSelectable)
            self._compare_table.setVerticalHeaderItem(i, QTableWidgetItem(dim))

            for j, val in enumerate(vals):
                item = QTableWidgetItem(f"  {val}")
                item.setFont(QFont("Microsoft YaHei", 11))
                item.setTextAlignment(Qt.AlignCenter)
                self._compare_table.setItem(i, j, item)

        self._compare_table.resizeRowsToContents()
