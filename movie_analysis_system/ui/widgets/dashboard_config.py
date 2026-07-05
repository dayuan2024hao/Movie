"""
看板配置管理
============
管理自定义看板的模块可见性和排列顺序。

配置存储为 JSON 文件:
  data/dashboard_config.json
"""

import json
import logging
import os
from typing import Optional

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QCheckBox,
    QDialogButtonBox, QWidget,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

logger = logging.getLogger("DashboardConfig")

# 模块定义
DEFAULT_MODULES = [
    {"id": "top10", "name": "票房 Top 10", "visible": True},
    {"id": "rating_genre", "name": "评分分布 + 类型占比", "visible": True},
    {"id": "bo_price", "name": "票房区间 + 票价分布", "visible": True},
    {"id": "genre_bo", "name": "各类型平均票房", "visible": True},
    {"id": "year_trend", "name": "年份趋势分析", "visible": True},
    {"id": "quadrant", "name": "四象限分析", "visible": True},
    {"id": "scatter", "name": "评分 vs 评价人数", "visible": True},
    {"id": "season", "name": "档期专题分析", "visible": True},
    {"id": "insight", "name": "数据洞察", "visible": True},
    {"id": "movie_table", "name": "电影数据列表", "visible": True},
]

CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "dashboard_config.json")


def _default_config() -> dict:
    return {
        "module_order": [m["id"] for m in DEFAULT_MODULES],
        "hidden_modules": [],
        "version": 1,
    }


def load_config() -> dict:
    """加载看板配置，不存在则返回默认。"""
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # 检查必要字段
            if "module_order" in cfg and "hidden_modules" in cfg:
                return cfg
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("看板配置加载失败，使用默认: %s", e)
    return _default_config()


def save_config(cfg: dict) -> None:
    """保存看板配置。"""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        logger.info("看板配置已保存: %s", CONFIG_PATH)
    except OSError as e:
        logger.error("看板配置保存失败: %s", e)


def is_module_visible(module_id: str) -> bool:
    """查询指定模块是否可见。"""
    cfg = load_config()
    return module_id not in cfg.get("hidden_modules", [])


def get_visible_modules() -> list[str]:
    """获取可见模块 ID 列表（按顺序）。"""
    cfg = load_config()
    order = cfg.get("module_order", [m["id"] for m in DEFAULT_MODULES])
    hidden = set(cfg.get("hidden_modules", []))
    return [mid for mid in order if mid not in hidden]


class DashboardConfigDialog(QDialog):
    """看板自定义配置对话框。

    允许用户:
      - 勾选/取消勾选以显示/隐藏模块
      - 点击上下按钮调整模块顺序
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("自定义看板")
        self.setMinimumSize(420, 480)
        self.setModal(True)
        self.setStyleSheet("background: #F5F7FA;")

        self._cfg = load_config()
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("⚙️ 自定义看板布局")
        title.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        title.setStyleSheet("color: #37474F;")
        layout.addWidget(title)

        desc = QLabel("勾选要显示的模块，取消勾选隐藏。选中后可用上下按钮调整顺序。")
        desc.setFont(QFont("Microsoft YaHei", 11))
        desc.setStyleSheet("color: #757575;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # 模块列表
        list_container = QWidget()
        list_container.setStyleSheet(
            "QWidget { background: white; border-radius: 8px; "
            "border: 1px solid #E0E0E0; }"
        )
        list_layout = QHBoxLayout(list_container)
        list_layout.setContentsMargins(12, 12, 12, 12)

        self._list_widget = QListWidget()
        self._list_widget.setAlternatingRowColors(True)
        self._list_widget.setStyleSheet(
            "QListWidget { border: none; font-size: 13px; }"
            "QListWidget::item { padding: 6px 4px; }"
            "QListWidget::item:selected { background: #E3F2FD; }"
        )
        list_layout.addWidget(self._list_widget, 1)

        # 右侧按钮区域
        btn_area = QVBoxLayout()
        btn_area.setSpacing(8)

        self._up_btn = QPushButton("↑ 上移")
        self._up_btn.setFixedSize(80, 32)
        self._up_btn.setStyleSheet(
            "QPushButton { background: #1E88E5; color: white; border: none; "
            "border-radius: 4px; font-size: 12px; }"
            "QPushButton:hover { background: #1565C0; }"
            "QPushButton:disabled { background: #BBDEFB; }"
        )
        self._up_btn.clicked.connect(self._move_up)
        btn_area.addWidget(self._up_btn)

        self._down_btn = QPushButton("↓ 下移")
        self._down_btn.setFixedSize(80, 32)
        self._down_btn.setStyleSheet(
            "QPushButton { background: #1E88E5; color: white; border: none; "
            "border-radius: 4px; font-size: 12px; }"
            "QPushButton:hover { background: #1565C0; }"
            "QPushButton:disabled { background: #BBDEFB; }"
        )
        self._down_btn.clicked.connect(self._move_down)
        btn_area.addWidget(self._down_btn)

        btn_area.addStretch()
        list_layout.addLayout(btn_area)

        layout.addWidget(list_container, 1)

        # 底部按钮
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_save)
        btns.rejected.connect(self.reject)
        btns.setStyleSheet(
            "QPushButton { padding: 6px 20px; font-size: 13px; }"
        )
        layout.addWidget(btns)

        # 填充列表
        self._populate_list()

    def _populate_list(self) -> None:
        """根据配置填充列表。"""
        self._list_widget.clear()
        order = self._cfg.get("module_order", [m["id"] for m in DEFAULT_MODULES])
        hidden = set(self._cfg.get("hidden_modules", []))
        module_map = {m["id"]: m["name"] for m in DEFAULT_MODULES}

        for mid in order:
            name = module_map.get(mid, mid)
            item = QListWidgetItem()
            cb = QCheckBox(name)
            cb.setChecked(mid not in hidden)
            cb.setStyleSheet("font-size: 13px; padding: 4px;")
            # 点击复选框时更新配置
            cb.stateChanged.connect(lambda checked, m=mid: self._on_toggle(m, checked))
            item.setSizeHint(cb.sizeHint())
            self._list_widget.addItem(item)
            self._list_widget.setItemWidget(item, cb)

        if self._list_widget.count() > 0:
            self._list_widget.setCurrentRow(0)

    def _on_toggle(self, module_id: str, checked: bool) -> None:
        """切换模块可见性。"""
        hidden = set(self._cfg.get("hidden_modules", []))
        if checked:
            hidden.discard(module_id)
        else:
            hidden.add(module_id)
        self._cfg["hidden_modules"] = list(hidden)

    def _move_up(self) -> None:
        """上移选中项。"""
        row = self._list_widget.currentRow()
        if row <= 0:
            return
        order = self._cfg.get("module_order", [])
        order[row], order[row - 1] = order[row - 1], order[row]
        self._cfg["module_order"] = order
        self._populate_list()
        self._list_widget.setCurrentRow(row - 1)

    def _move_down(self) -> None:
        """下移选中项。"""
        row = self._list_widget.currentRow()
        order = self._cfg.get("module_order", [])
        if row < 0 or row >= len(order) - 1:
            return
        order[row], order[row + 1] = order[row + 1], order[row]
        self._cfg["module_order"] = order
        self._populate_list()
        self._list_widget.setCurrentRow(row + 1)

    def _on_save(self) -> None:
        """保存配置并关闭。"""
        save_config(self._cfg)
        self.accept()


def open_dashboard_config(parent: Optional[QWidget] = None) -> bool:
    """打开看板配置对话框。

    Returns:
        True 如果用户保存了配置，False 如果取消
    """
    dialog = DashboardConfigDialog(parent)
    return dialog.exec_() == QDialog.Accepted
