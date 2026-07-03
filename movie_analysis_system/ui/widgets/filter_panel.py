"""
筛选面板组件
============
可折叠的筛选面板，支持类型、评分、票房、票价、年份等多维度筛选。
与 db_manager.query_movies() 的筛选参数对应。
"""

import logging
from typing import Optional, Callable

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QSlider, QSpinBox, QPushButton, QLineEdit, QScrollArea,
    QFrame, QSizePolicy,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

from database.db_manager import DatabaseManager

logger = logging.getLogger("FilterPanel")


class FilterPanel(QFrame):
    """筛选面板组件。"""

    def __init__(
        self, db: DatabaseManager,
        on_filter_changed: Optional[Callable] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        """初始化筛选面板。

        Args:
            db: 数据库管理器实例
            on_filter_changed: 筛选条件变化时的回调函数
            parent: 父组件
        """
        super().__init__(parent)
        self.db = db
        self.on_filter_changed = on_filter_changed

        self.setObjectName("filterPanel")
        self.setFixedWidth(260)

        # 防抖定时器
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._emit_filter_changed)

        self._setup_ui()
        self._load_genres()

    def _setup_ui(self) -> None:
        """构建筛选面板布局。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 标题
        title = QLabel("筛选条件")
        title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        title.setStyleSheet("color: #37474F;")
        layout.addWidget(title)

        # ── 搜索框 ──
        search_label = QLabel("关键词搜索")
        search_label.setStyleSheet("color: #616161; font-size: 12px;")
        layout.addWidget(search_label)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入电影名称...")
        self.search_input.setObjectName("searchInput")
        self.search_input.textChanged.connect(self._on_change)
        layout.addWidget(self.search_input)

        # ── 类型多选 ──
        genre_label = QLabel("电影类型")
        genre_label.setStyleSheet("color: #616161; font-size: 12px; margin-top: 8px;")
        layout.addWidget(genre_label)

        self._genre_checkboxes: dict[str, QCheckBox] = {}
        genre_container = QWidget()
        genre_container.setObjectName("genreContainer")
        genre_layout = QVBoxLayout(genre_container)
        genre_layout.setContentsMargins(0, 0, 0, 0)
        genre_layout.setSpacing(2)
        self._genre_layout = genre_layout
        layout.addWidget(genre_container)

        # ── 评分范围 ──
        self._add_range_section(layout, "评分范围", "rating_min", "rating_max", 0, 10)

        # ── 票房范围（万） ──
        self._add_range_section(layout, "票房范围(万)", "bo_min", "bo_max", 0, 500000, step=1000)

        # ── 票价范围（元） ──
        self._add_range_section(layout, "票价范围(元)", "price_min", "price_max", 0, 200)

        # ── 年份范围 ──
        self._add_range_section(layout, "年份范围", "year_min", "year_max", 1990, 2026)

        # ── 按钮 ──
        btn_layout = QHBoxLayout()
        reset_btn = QPushButton("重置")
        reset_btn.setObjectName("secondaryBtn")
        reset_btn.clicked.connect(self._reset)
        btn_layout.addWidget(reset_btn)
        layout.addLayout(btn_layout)

        layout.addStretch()

    def _add_range_section(
        self, layout, label: str, min_attr: str, max_attr: str,
        min_val: int, max_val: int, step: int = 1
    ) -> None:
        """添加一个范围选择行（两个 QSpinBox）。

        Args:
            layout: 父布局
            label: 节标题
            min_attr: 最小值属性名
            max_attr: 最大值属性名
            min_val: 最小值
            max_val: 最大值
            step: 步长
        """
        section_label = QLabel(label)
        section_label.setStyleSheet("color: #616161; font-size: 12px; margin-top: 8px;")
        layout.addWidget(section_label)

        range_layout = QHBoxLayout()
        range_layout.setSpacing(8)

        min_spin = QSpinBox()
        min_spin.setRange(min_val, max_val)
        min_spin.setValue(min_val)
        min_spin.setSingleStep(step)
        min_spin.valueChanged.connect(self._on_change)
        setattr(self, f"_{min_attr}", min_spin)
        range_layout.addWidget(min_spin)

        sep = QLabel("—")
        sep.setAlignment(Qt.AlignCenter)
        sep.setStyleSheet("color: #9E9E9E;")
        range_layout.addWidget(sep)

        max_spin = QSpinBox()
        max_spin.setRange(min_val, max_val)
        max_spin.setValue(max_val)
        max_spin.setSingleStep(step)
        max_spin.valueChanged.connect(self._on_change)
        setattr(self, f"_{max_attr}", max_spin)
        range_layout.addWidget(max_spin)

        layout.addLayout(range_layout)

    def _load_genres(self) -> None:
        """从数据库加载类型列表并生成复选框。"""
        try:
            genres = self.db.get_genre_stats()
            for item in genres:
                genre = item["genre"]
                cb = QCheckBox(genre)
                cb.setChecked(True)
                cb.stateChanged.connect(self._on_change)
                self._genre_checkboxes[genre] = cb
                self._genre_layout.addWidget(cb)
        except Exception as e:
            logger.error("加载类型列表失败: %s", e)

    def _on_change(self) -> None:
        """值变化时启动防抖定时器（300ms）。"""
        self._debounce.start(300)

    def _emit_filter_changed(self) -> None:
        """发射筛选条件变化事件。"""
        filters = self.get_filters()
        if self.on_filter_changed:
            self.on_filter_changed(filters)

    def get_filters(self) -> dict:
        """获取当前筛选条件字典。

        Returns:
            可直接传递给 query_movies 的筛选条件字典
        """
        filters: dict = {}

        # 关键词
        keyword = self.search_input.text().strip()
        if keyword:
            filters["keyword"] = keyword

        # 类型（只传选中的）
        selected_genres = [
            g for g, cb in self._genre_checkboxes.items() if cb.isChecked()
        ]
        if selected_genres and len(selected_genres) < len(self._genre_checkboxes):
            filters["genre"] = selected_genres[0]  # 传第一个选中类型

        # 评分范围
        rating_min = self._rating_min.value()
        rating_max = self._rating_max.value()
        if rating_min > 0:
            filters["rating_min"] = rating_min
        if rating_max < 10:
            filters["rating_max"] = rating_max

        # 票房范围
        bo_min = self._bo_min.value()
        bo_max = self._bo_max.value()
        if bo_min > 0:
            filters["box_office_min"] = bo_min
        if bo_max < 500000:
            filters["box_office_max"] = bo_max

        # 票价范围
        price_min = self._price_min.value()
        price_max = self._price_max.value()
        if price_min > 0:
            filters["price_min"] = price_min
        if price_max < 200:
            filters["price_max"] = price_max

        # 年份范围
        year_min = self._year_min.value()
        year_max = self._year_max.value()
        if year_min > 1990:
            filters["year_start"] = year_min
        if year_max < 2026:
            filters["year_end"] = year_max

        return filters

    def _reset(self) -> None:
        """重置所有筛选条件为默认值。"""
        self.search_input.clear()
        for cb in self._genre_checkboxes.values():
            cb.setChecked(True)
        self._rating_min.setValue(0)
        self._rating_max.setValue(10)
        self._bo_min.setValue(0)
        self._bo_max.setValue(500000)
        self._price_min.setValue(0)
        self._price_max.setValue(200)
        self._year_min.setValue(1990)
        self._year_max.setValue(2026)
        self._emit_filter_changed()
