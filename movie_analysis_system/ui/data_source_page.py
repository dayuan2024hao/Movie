"""
数据源配置页面
==============
展示数据来源、更新时间戳、手动刷新/爬取按钮、爬取日志。

功能：
  - 数据概览卡片（电影总数 / 热映 / 即将上映 / 已下映）
  - 数据源信息（来源类型 + 更新时间）
  - 手动刷新按钮（重新爬取热映数据）
  - 爬取历史日志列表
  - 数据修复按钮（补全缺失票价等）
"""

import logging
import threading
from datetime import datetime
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QProgressBar,
)
from PyQt5.QtCore import Qt, QMetaObject, Q_ARG, pyqtSignal, QTimer
from PyQt5.QtGui import QFont

from database.db_manager import DatabaseManager
from crawler.crawl_controller import CrawlController
from crawler.realtime_aggregator import RealtimeAggregator

logger = logging.getLogger("DataSourcePage")


class DataSourcePage(QWidget):
    """数据源配置与管理页面。"""

    # 跨线程信号
    show_result_signal = pyqtSignal(str)
    update_progress_signal = pyqtSignal(int, str)
    repair_done_signal = pyqtSignal(int, int)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db: Optional[DatabaseManager] = None
        self._controller: Optional[CrawlController] = None
        self._aggregator = RealtimeAggregator()
        self._setup_ui()
        self._connect_signals()

    def set_db(self, db: DatabaseManager) -> None:
        self.db = db
        self._refresh_display()

    def _setup_ui(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName("dataSourceScroll")
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # ── 页面标题 ──
        title = QLabel("数据源管理")
        title.setFont(QFont("Microsoft YaHei", 20, QFont.Bold))
        title.setStyleSheet("color: #37474F;")
        layout.addWidget(title)
        layout.addSpacing(8)

        # ══════════════════════════════════════
        #  数据概览卡片
        # ══════════════════════════════════════
        overview_title = QLabel("📊 数据概览")
        overview_title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        overview_title.setStyleSheet("color: #37474F;")
        layout.addWidget(overview_title)

        card_row = QWidget()
        card_row.setFixedHeight(90)
        cl = QHBoxLayout(card_row)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(12)

        self._cards = {}
        card_defs = [
            ("total", "电影总数", "0", "#1E88E5"),
            ("showing", "热映中", "0", "#43A047"),
            ("coming", "即将上映", "0", "#FB8C00"),
            ("released", "已下映", "0", "#757575"),
        ]
        for key, label, default, color in card_defs:
            card = self._make_info_card(label, default, color)
            self._cards[key] = card
            cl.addWidget(card)
        layout.addWidget(card_row)

        # ══════════════════════════════════════
        #  数据源信息
        # ══════════════════════════════════════
        source_title = QLabel("🔌 数据源信息")
        source_title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        source_title.setStyleSheet("color: #37474F;")
        layout.addWidget(source_title)

        info_frame = QFrame()
        info_frame.setObjectName("infoFrame")
        info_frame.setStyleSheet(
            "QFrame#infoFrame { background: white; border-radius: 8px; "
            "border: 1px solid #E0E0E0; }"
        )
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(16, 12, 16, 12)
        info_layout.setSpacing(8)

        self._source_label = QLabel("数据来源: 加载中...")
        self._source_label.setFont(QFont("Microsoft YaHei", 12))
        self._source_label.setStyleSheet("color: #555;")
        info_layout.addWidget(self._source_label)

        self._time_label = QLabel("上次更新: 加载中...")
        self._time_label.setFont(QFont("Microsoft YaHei", 12))
        self._time_label.setStyleSheet("color: #555;")
        info_layout.addWidget(self._time_label)

        self._price_coverage_label = QLabel("票价覆盖率: 加载中...")
        self._price_coverage_label.setFont(QFont("Microsoft YaHei", 12))
        self._price_coverage_label.setStyleSheet("color: #555;")
        info_layout.addWidget(self._price_coverage_label)

        layout.addWidget(info_frame)

        # ══════════════════════════════════════
        #  操作按钮
        # ══════════════════════════════════════
        action_title = QLabel("⚙️ 操作")
        action_title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        action_title.setStyleSheet("color: #37474F;")
        layout.addWidget(action_title)

        action_frame = QFrame()
        action_frame.setObjectName("actionFrame")
        action_frame.setStyleSheet(
            "QFrame#actionFrame { background: white; border-radius: 8px; "
            "border: 1px solid #E0E0E0; }"
        )
        action_layout = QVBoxLayout(action_frame)
        action_layout.setContentsMargins(16, 12, 16, 12)
        action_layout.setSpacing(10)

        # 进度条
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.hide()
        action_layout.addWidget(self._progress_bar)

        self._status_label = QLabel("")
        self._status_label.setFont(QFont("Microsoft YaHei", 11))
        self._status_label.setStyleSheet("color: #666;")
        self._status_label.hide()
        action_layout.addWidget(self._status_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        self._refresh_btn = QPushButton("🔄 重新爬取热映数据")
        self._refresh_btn.setObjectName("primaryBtn")
        self._refresh_btn.setCursor(Qt.PointingHandCursor)
        self._refresh_btn.setFixedHeight(38)
        self._refresh_btn.setStyleSheet(
            "QPushButton#primaryBtn { background: #1E88E5; color: white; "
            "border: none; border-radius: 6px; padding: 0 20px; font-size: 13px; }"
            "QPushButton#primaryBtn:hover { background: #1565C0; }"
            "QPushButton#primaryBtn:disabled { background: #BBDEFB; }"
        )
        self._refresh_btn.clicked.connect(self._on_refresh)
        btn_row.addWidget(self._refresh_btn)

        self._repair_btn = QPushButton("🔧 补全票价数据")
        self._repair_btn.setObjectName("secondaryBtn")
        self._repair_btn.setCursor(Qt.PointingHandCursor)
        self._repair_btn.setFixedHeight(38)
        self._repair_btn.setStyleSheet(
            "QPushButton#secondaryBtn { background: #43A047; color: white; "
            "border: none; border-radius: 6px; padding: 0 20px; font-size: 13px; }"
            "QPushButton#secondaryBtn:hover { background: #388E3C; }"
            "QPushButton#secondaryBtn:disabled { background: #C8E6C9; }"
        )
        self._repair_btn.clicked.connect(self._on_repair_prices)
        btn_row.addWidget(self._repair_btn)

        btn_row.addStretch()
        action_layout.addLayout(btn_row)

        layout.addWidget(action_frame)

        # ══════════════════════════════════════
        #  爬取历史日志
        # ══════════════════════════════════════
        log_title = QLabel("📋 爬取历史")
        log_title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        log_title.setStyleSheet("color: #37474F;")
        layout.addWidget(log_title)

        self._log_table = QTableWidget()
        self._log_table.setColumnCount(4)
        self._log_table.setHorizontalHeaderLabels(["来源", "状态", "记录数", "时间"])
        self._log_table.horizontalHeader().setStretchLastSection(True)
        self._log_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._log_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._log_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._log_table.setAlternatingRowColors(True)
        self._log_table.setMaximumHeight(240)
        self._log_table.setStyleSheet(
            "QTableWidget { border: 1px solid #E0E0E0; border-radius: 4px; }"
            "QHeaderView::section { background: #ECEFF1; padding: 6px; }"
        )
        layout.addWidget(self._log_table)

        layout.addStretch()
        scroll.setWidget(content)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    @staticmethod
    def _make_info_card(label: str, value: str, color: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: white; border-radius: 8px; "
            f"border: 1px solid #E0E0E0; }}"
        )
        card.setFixedHeight(80)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 8, 12, 8)
        cl.setAlignment(Qt.AlignCenter)

        num = QLabel(value)
        num.setFont(QFont("Microsoft YaHei", 22, QFont.Bold))
        num.setStyleSheet(f"color: {color};")
        num.setAlignment(Qt.AlignCenter)
        cl.addWidget(num)

        lbl = QLabel(label)
        lbl.setFont(QFont("Microsoft YaHei", 11))
        lbl.setStyleSheet("color: #666;")
        lbl.setAlignment(Qt.AlignCenter)
        cl.addWidget(lbl)
        return card

    def _refresh_display(self) -> None:
        """刷新所有数据展示。"""
        if self.db is None:
            return

        try:
            status = self.db.get_data_status()
            conn = self.db.get_connection()
            cursor = conn.cursor()

            # 各状态计数
            cursor.execute("SELECT showing_status, COUNT(*) FROM movies GROUP BY showing_status")
            status_map = {r[0]: r[1] for r in cursor.fetchall()}

            total = status.get("total_movies", 0)
            showing = status_map.get("showing", 0)
            coming = status_map.get("coming_soon", 0)
            released = status_map.get("released", 0)

            # 更新概览卡片
            self._cards["total"].findChildren(QLabel)[0].setText(str(total))
            self._cards["showing"].findChildren(QLabel)[0].setText(str(showing))
            self._cards["coming"].findChildren(QLabel)[0].setText(str(coming))
            self._cards["released"].findChildren(QLabel)[0].setText(str(released))

            # 更新数据源信息
            source = status.get("data_source", "unknown")
            last_crawl = status.get("last_crawl_time") or "从未爬取"
            source_label = {"backup": "CSV 备份数据", "crawler": "实时爬取数据"}.get(source, source)
            self._source_label.setText(f"数据来源: {source_label}")
            self._time_label.setText(f"上次更新: {last_crawl}")

            # 票价覆盖率
            cursor.execute(
                "SELECT COUNT(*) FROM movies WHERE ticket_price > 0"
            )
            has_price = cursor.fetchone()[0]
            coverage = (has_price / total * 100) if total > 0 else 0
            self._price_coverage_label.setText(
                f"票价覆盖率: {has_price}/{total} ({coverage:.1f}%)"
            )

            # 爬取历史
            cursor.execute(
                "SELECT source, status, records_count, created_at "
                "FROM crawl_record ORDER BY id DESC LIMIT 20"
            )
            logs = cursor.fetchall()
            self._log_table.setRowCount(len(logs))
            for i, row in enumerate(logs):
                self._log_table.setItem(i, 0, QTableWidgetItem(row["source"]))
                self._log_table.setItem(i, 1, QTableWidgetItem(row["status"]))
                self._log_table.setItem(i, 2, QTableWidgetItem(str(row["records_count"])))
                self._log_table.setItem(i, 3, QTableWidgetItem(row["created_at"]))
            self._log_table.resizeRowsToContents()

            cursor.close()

        except Exception as e:
            logger.error("刷新数据源显示失败: %s", e)

    def _on_refresh(self) -> None:
        """手动触发重新爬取。"""
        if self.db is None:
            QMessageBox.warning(self, "提示", "数据库未初始化")
            return

        self._refresh_btn.setEnabled(False)
        self._repair_btn.setEnabled(False)
        self._progress_bar.setValue(0)
        self._progress_bar.show()
        self._status_label.setText("正在爬取热映数据...")
        self._status_label.show()

        def progress_cb(current: int, total: int, message: str) -> None:
            """进度回调 — 跨线程安全更新 UI。"""
            pct = int(current / max(total, 1) * 100)
            QMetaObject.invokeMethod(
                self._progress_bar, "setValue", Qt.QueuedConnection,
                Q_ARG(int, pct),
            )
            QMetaObject.invokeMethod(
                self._status_label, "setText", Qt.QueuedConnection,
                Q_ARG(str, f"{message} ({current}/{total})"),
            )

        def done_cb(success: bool) -> None:
            """完成后恢复 UI。"""
            self._refresh_btn.setEnabled(True)
            self._repair_btn.setEnabled(True)
            self._progress_bar.hide()
            if success:
                self._status_label.setText("✅ 数据更新完成")
                self._refresh_display()
                QMessageBox.information(self, "完成", "热映数据更新完成！")
            else:
                self._status_label.setText("❌ 爬取失败，请重试")
                QMessageBox.warning(self, "错误", "数据爬取失败，请检查网络连接")
            logger.info("手动爬取完成: success=%s", success)

        def task():
            try:
                self._controller = CrawlController(self.db)
                self._controller.crawl_showing_movies(
                    progress_callback=progress_cb,
                    background=False,
                )
                done_cb(True)
            except Exception as e:
                logger.error("手动爬取异常: %s", e)
                done_cb(False)

        threading.Thread(target=task, daemon=True).start()

    def _on_repair_prices(self) -> None:
        """补全缺失的票价数据。"""
        if self.db is None:
            QMessageBox.warning(self, "提示", "数据库未初始化")
            return

        QMessageBox.information(
            self, "票价补全",
            "正在尝试补全缺失票价数据，这可能需要几分钟时间...\n"
            "补全完成后会自动刷新显示。"
        )

        self._repair_btn.setEnabled(False)
        self._status_label.setText("正在补全票价数据...")
        self._status_label.show()
        self._progress_bar.show()

        def task():
            try:
                conn = self.db.get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, title, maoyan_id FROM movies "
                    "WHERE (ticket_price IS NULL OR ticket_price = 0) "
                    "AND maoyan_id IS NOT NULL AND maoyan_id != ''"
                )
                movies = cursor.fetchall()
                total = len(movies)
                fixed = 0

                for idx, row in enumerate(movies):
                    pct = int((idx + 1) / max(total, 1) * 100)
                    QMetaObject.invokeMethod(
                        self._progress_bar, "setValue", Qt.QueuedConnection,
                        Q_ARG(int, pct),
                    )
                    QMetaObject.invokeMethod(
                        self._status_label, "setText", Qt.QueuedConnection,
                        Q_ARG(str, f"正在处理: {row['title']} ({idx+1}/{total})"),
                    )

                    price = self._aggregator.get_ticket_price(
                        str(row["maoyan_id"]), movie_title=row["title"]
                    )
                    if price and price > 0:
                        cursor.execute(
                            "UPDATE movies SET ticket_price = ?, "
                            "updated_at = datetime('now','localtime') WHERE id = ?",
                            (price, row["id"]),
                        )
                        conn.commit()
                        fixed += 1

                cursor.close()

                QMetaObject.invokeMethod(
                    self._repair_btn, "setEnabled", Qt.QueuedConnection,
                    Q_ARG(bool, True),
                )
                QMetaObject.invokeMethod(
                    self._progress_bar, "hide", Qt.QueuedConnection,
                )
                QMetaObject.invokeMethod(
                    self._status_label, "setText", Qt.QueuedConnection,
                    Q_ARG(str, f"✅ 票价补全完成: 修复 {fixed}/{total} 部"),
                )

                if fixed > 0:
                    self._refresh_display()

                self.show_result_signal.emit(
                    f"票价补全完成！\n共处理 {total} 部，成功修复 {fixed} 部"
                )

            except Exception as e:
                logger.error("票价补全异常: %s", e)
                QMetaObject.invokeMethod(
                    self._repair_btn, "setEnabled", Qt.QueuedConnection,
                    Q_ARG(bool, True),
                )
                QMetaObject.invokeMethod(
                    self._progress_bar, "hide", Qt.QueuedConnection,
                )
                QMetaObject.invokeMethod(
                    self._status_label, "setText", Qt.QueuedConnection,
                    Q_ARG(str, "❌ 票价补全失败"),
                )

        threading.Thread(target=task, daemon=True).start()

    def _connect_signals(self) -> None:
        """连接跨线程信号到主线程槽。"""
        self.show_result_signal.connect(self._show_result)
        self.update_progress_signal.connect(self._on_progress_update)

    @staticmethod
    def _on_progress_update(pct: int, msg: str) -> None:
        """更新进度（主线程）。"""
        pass

    def _show_result(self, msg: str) -> None:
        """显示操作结果（主线程）。"""
        QMessageBox.information(self, "完成", msg)
