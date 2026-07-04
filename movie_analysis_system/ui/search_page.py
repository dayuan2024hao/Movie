"""
搜索页面 — QThread 异步搜索
===========================
架构：
  - SearchWorker (QObject) 在 QThread 中执行网络请求
  - 内部信号 _search_requested 自动路由到工作者线程
  - 结果通过 Qt 信号安全返回主线程
  - 搜索时 UI 永不冻结

用法：
  输入关键词后回车或点击搜索按钮 → 异步搜索 → 卡片列表展示
  点击卡片 → 导航到详情页
"""

import logging
import os
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QScrollArea, QFrame,
)
from PyQt5.QtCore import Qt, pyqtSignal, QThread
from PyQt5.QtGui import QFont

from ui.search_worker import SearchWorker

logger = logging.getLogger("SearchPage")

# 打印文件绝对路径防止缓存/副本问题
print(f"[SEARCH_PAGE] 加载路径: {os.path.abspath(__file__)}")


def _make_source_badge(source: str) -> QLabel:
    """创建来源标签。

    Args:
        source: 数据来源（"猫眼"/"豆瓣"/"猫眼+豆瓣"）

    Returns:
        配置好的 QLabel
    """
    badge = QLabel(f"[{source}]")
    badge.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
    if "猫眼" in source and "豆瓣" in source:
        color = "#FF6B6B"
    elif "猫眼" in source:
        color = "#E53E3E"
    elif "豆瓣" in source:
        color = "#38A169"
    else:
        color = "#78909C"  # 本地数据灰色
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

        info = QVBoxLayout()
        info.setSpacing(4)

        # 标题行 + 来源标签
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_lbl = QLabel(self._data.get("title", "未知"))
        title_lbl.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        title_lbl.setStyleSheet("color: #333;")
        title_row.addWidget(title_lbl)
        source = self._data.get("source", "?")
        title_row.addWidget(_make_source_badge(source))
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

        # 数据源提示
        maoyan_id = self._data.get("maoyan_id", "")
        douban_id = self._data.get("douban_id", "")
        if maoyan_id:
            tip = QLabel("✅ 可查看详情和购票")
            tip.setFont(QFont("Microsoft YaHei", 10))
            tip.setStyleSheet("color: #38A169;")
            info.addWidget(tip)
        elif douban_id:
            tip = QLabel("📖 豆瓣数据")
            tip.setFont(QFont("Microsoft YaHei", 10))
            tip.setStyleSheet("color: #38A169;")
            info.addWidget(tip)

        info.addStretch()
        layout.addLayout(info, 1)


class SearchPage(QWidget):
    """搜索页面 — QThread 异步搜索，UI 永不冻结。"""

    navigation_requested = pyqtSignal(dict)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        # ── 初始化异步工作者 ──
        self._search_worker = SearchWorker()
        self._search_thread = QThread()
        self._search_worker.moveToThread(self._search_thread)
        self._search_thread.start()

        # 连接信号
        self._search_worker.finished.connect(self._on_search_finished)
        self._search_worker.error_happened.connect(self._on_search_error)
        self._search_worker.progress.connect(self._on_search_progress)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建搜索页面布局。"""
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
            "QPushButton:disabled { background: #BBDEFB; }"
        )
        self._search_btn.clicked.connect(self._do_search)
        search_bar.addWidget(self._search_btn)

        layout.addLayout(search_bar)

        # 状态标签
        self._result_label = QLabel("输入关键词开始搜索")
        self._result_label.setFont(QFont("Microsoft YaHei", 12))
        self._result_label.setStyleSheet("color: #999; padding: 0 24px;")
        layout.addWidget(self._result_label)

        # 加载进度标签（默认隐藏）
        self._loading_label = QLabel()
        self._loading_label.setFont(QFont("Microsoft YaHei", 11))
        self._loading_label.setStyleSheet(
            "color: #1E88E5; padding: 8px 24px; background: #E3F2FD;"
        )
        self._loading_label.setVisible(False)
        layout.addWidget(self._loading_label)

        # 结果滚动区
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

    # ──────────────── 搜索操作 ────────────────

    def _do_search(self) -> None:
        """启动异步搜索（UI 永不冻结）。"""
        keyword = self._search_input.text().strip()
        if not keyword:
            return
        print(f"[DEBUG_STEP_2] _do_search called with: '{keyword}'")

        # 清空旧结果
        self._clear_results()

        # 切换为加载状态（_loading_label 显示进度，_result_label 保留为结果统计用）
        self._set_loading_state(True)

        # 跨线程安全启动搜索
        self._search_worker.search(keyword)

    def _set_loading_state(self, loading: bool) -> None:
        """切换加载/就绪状态。

        Args:
            loading: True=加载中, False=就绪
        """
        self._search_btn.setEnabled(not loading)
        self._search_input.setEnabled(not loading)
        if loading:
            self._search_btn.setText("搜索中...")
            self._loading_label.setText("⏳ 正在查询猫眼和豆瓣数据，请稍候...")
            self._loading_label.setVisible(True)
        else:
            self._search_btn.setText("搜索")
            self._loading_label.setVisible(False)

    def _clear_results(self) -> None:
        """清空搜索结果列表（保留最后的 stretch）。"""
        while self._results_layout.count() > 1:
            item = self._results_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    # ──────────────── 回调（主线程） ────────────────

    def _on_search_progress(self, msg: str) -> None:
        """搜索进度更新（主线程回调）。

        Args:
            msg: 进度消息
        """
        print(f"[DEBUG_STEP_2] progress signal: {msg}")
        self._loading_label.setText(f"⏳ {msg}")
        self._loading_label.setStyleSheet(
            "color: #1E88E5; padding: 8px 24px; background: #E3F2FD;"
        )
        self._loading_label.setVisible(True)

    def _on_search_finished(self, results: list) -> None:
        """搜索完成（主线程回调）。

        Args:
            results: 搜索结果列表
        """
        print(f"[DEBUG_STEP_2] finished signal: {len(results)} items, type={type(results).__name__}")
        self._set_loading_state(False)

        if not results:
            self._result_label.setText("未找到相关电影")
            self._result_label.setStyleSheet("color: #999; padding: 0 24px;")
            logger.info("[SEARCH] 搜索结果为空")
            return

        self._result_label.setText(f"搜索到 {len(results)} 条结果")
        self._result_label.setStyleSheet("color: #38A169; padding: 0 24px;")

        for idx, r in enumerate(results):
            card = SearchResultCard(r)
            card.clicked.connect(self._on_result_clicked)
            self._results_layout.insertWidget(
                self._results_layout.count() - 1, card
            )
            if idx == 0:
                print(f"[DEBUG_STEP_2] first card: title={r.get('title','?')}")

        logger.info("[SEARCH] 显示 %d 条结果", len(results))

    def _on_search_error(self, error_msg: str) -> None:
        """搜索出错（主线程回调）。

        Args:
            error_msg: 错误消息
        """
        print(f"[DEBUG_STEP_2] error signal: {error_msg}")
        self._set_loading_state(False)
        self._result_label.setText("搜索出错")
        self._result_label.setStyleSheet("color: #E53935; padding: 0 24px;")
        self._loading_label.setText(f"❌ {error_msg}")
        self._loading_label.setStyleSheet(
            "color: #E53935; padding: 8px 24px; background: #FFEBEE;"
        )
        self._loading_label.setVisible(True)

    def _on_result_clicked(self, data: dict) -> None:
        """搜索结果被点击 → 导航到详情页。

        Args:
            data: 电影数据字典
        """
        self.navigation_requested.emit(data)

    # ──────────────── 生命周期 ────────────────

    def cleanup(self) -> None:
        """清理资源（窗口关闭时调用）。"""
        if self._search_thread.isRunning():
            self._search_thread.quit()
            self._search_thread.wait(2000)
