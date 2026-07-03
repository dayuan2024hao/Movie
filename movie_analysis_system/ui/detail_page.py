"""
电影详情页面 — 实时数据 + 多源降级 + 像素级UI
===========================================
  海报: 300×450px 固定容器, KeepAspectRatioByExpanding, 高清URL
  数据: RealtimeAggregator (H5 → 豆瓣Frodo → TMDB)
  主演: ActorCircleWidget (纯QLabel + QSS, 无QPainter)
  评分: 单分支渲染（评分X.X / 评分待更新）
  剧情: 猫眼H5 → 豆瓣Frodo → TMDB 三级降级
  短评: 猫眼 → 豆瓣Frodo 二级降级
  跳转: webbrowser.open(new=0), _clean_signal()
"""

import logging
import os
import random
import re
import threading
import webbrowser
from typing import Optional

import requests

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QMenu, QAction, QApplication,
)
from PyQt5.QtCore import Qt, pyqtSignal, QRect
from PyQt5.QtGui import (
    QFont, QPixmap, QPainter, QColor, QBrush, QFontMetrics,
    QLinearGradient,
)

from database.db_manager import DatabaseManager
from crawler.realtime_aggregator import RealtimeAggregator

logger = logging.getLogger("DetailPage")

POSTER_W = 300
POSTER_H = 450
ACTOR_COLORS = ["#4ECDC4", "#FF6B6B", "#45B7D1", "#FFA07A",
                "#98D8C8", "#DDA0DD", "#87CEEB", "#F0E68C"]

CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "cache", "posters",
)

# TMDB API 配置（默认为空，需自行申请 Key）
# 申请地址：https://www.themoviedb.org/settings/api
TMDB_API_KEY = ""

AGGREGATOR = RealtimeAggregator()


def _upgrade_poster_url(url: str) -> str:
    """替换海报URL为高清版本（w.h → 1000.1500）。"""
    if not url:
        return ""
    new_url = re.sub(r'w\.h\b', '1000.1500', url)
    new_url = re.sub(r'/w/\d+', '/w/1000', new_url)
    new_url = re.sub(r'/h/\d+', '/h/1500', new_url)
    if new_url != url:
        logger.info("[POSTER_HD] %s → %s", url[:40], new_url[:40])
    return new_url


def make_separator() -> QFrame:
    """创建 8px 灰色分割线。"""
    sep = QFrame()
    sep.setFixedHeight(8)
    sep.setStyleSheet("QFrame { background: #F5F6FA; border: none; }")
    return sep


def make_section_title(text: str) -> QLabel:
    """创建区块标题。"""
    lbl = QLabel(text)
    lbl.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
    lbl.setStyleSheet("color: #222;")
    return lbl



# ═══════════════════════════════════════════════
#  详情页
# ═══════════════════════════════════════════════

class DetailPage(QWidget):
    """电影详情页 — 300×450海报 + 多源降级 + 主演QLabel。"""

    back_requested = pyqtSignal()
    _poster_ready = pyqtSignal(bytes)
    _plot_ready = pyqtSignal(str)
    _reviews_ready = pyqtSignal(list)  # 多源短评（已恢复）
    _price_ready = pyqtSignal(object)  # float or None

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db: Optional[DatabaseManager] = None
        self._movie_data: Optional[dict] = None  # 当前电影数据
        self._poster_ready.connect(self._on_poster_data)
        self._plot_ready.connect(self._on_plot_data)
        self._reviews_ready.connect(self._on_reviews_data)
        self._price_ready.connect(self._on_price_data)
        self._setup_ui()

    def _setup_ui(self) -> None:
        """构建完整详情页布局。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 返回栏 ──
        top_bar = QFrame()
        top_bar.setFixedHeight(44)
        top_bar.setStyleSheet("QFrame { background: white; border-bottom: 1px solid #EEE; }")
        tb = QHBoxLayout(top_bar)
        tb.setContentsMargins(12, 4, 20, 4)
        self.back_btn = QPushButton("←  返回")
        self.back_btn.setCursor(Qt.PointingHandCursor)
        self.back_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #333; font: 13pt; }"
            "QPushButton:hover { color: #1E88E5; }"
        )
        self.back_btn.clicked.connect(self.back_requested.emit)
        tb.addWidget(self.back_btn)
        tb.addStretch()
        layout.addWidget(top_bar)

        # ── 滚动容器 ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: #F5F6FA; border: none; }")
        content = QWidget()
        self.cl = QVBoxLayout(content)
        self.cl.setContentsMargins(0, 0, 0, 0)
        self.cl.setSpacing(0)

        # ════════════════════════════════════
        #  ① 海报区域（300×450 固定容器，居中）
        # ════════════════════════════════════
        poster_container = QWidget()
        poster_container.setFixedHeight(POSTER_H + 20)
        poster_container.setStyleSheet("background: #1a1a2e;")
        pc = QHBoxLayout(poster_container)
        pc.setContentsMargins(0, 0, 0, 0)
        pc.setAlignment(Qt.AlignCenter)

        self._poster_label = QLabel()
        self._poster_label.setFixedSize(POSTER_W, POSTER_H)
        self._poster_label.setScaledContents(False)
        self._poster_label.setAlignment(Qt.AlignCenter)
        self._poster_label.setStyleSheet("background: #1a1a2e; border-radius: 4px;")
        pc.addWidget(self._poster_label)
        self.cl.addWidget(poster_container)

        # ════════════════════════════════════
        #  ② 白色信息面板
        # ════════════════════════════════════
        self._info_panel = QFrame()
        self._info_panel.setStyleSheet("QFrame { background: white; }")
        ip = QVBoxLayout(self._info_panel)
        ip.setContentsMargins(32, 24, 32, 20)
        ip.setSpacing(10)

        # 来源标记（仅搜索数据使用）
        self._source_label = QLabel()
        self._source_label.setFont(QFont("Microsoft YaHei", 11, QFont.Bold))
        self._source_label.setStyleSheet("color: #999;")
        ip.addWidget(self._source_label)

        # 标题
        self._title_label = QLabel()
        self._title_label.setFont(QFont("Microsoft YaHei", 28, QFont.Bold))
        self._title_label.setStyleSheet("color: #222;")
        ip.addWidget(self._title_label)

        # 元信息行（类型 / 时长 / 上映日期）
        self._meta_label = QLabel()
        self._meta_label.setFont(QFont("Microsoft YaHei", 13))
        self._meta_label.setStyleSheet("color: #999;")
        ip.addWidget(self._meta_label)

        # ── 评分行 — 单分支：评分X.X / 评分待更新 ──
        rating_row = QHBoxLayout()
        rating_row.setSpacing(24)

        left_r = QVBoxLayout()
        left_r.setSpacing(0)
        self._score_num = QLabel("评分待更新")
        self._score_num.setStyleSheet("color: #A0AEC0; font-size: 24pt;")
        left_r.addWidget(self._score_num)
        self._score_source = QLabel("猫眼评分")
        self._score_source.setFont(QFont("Microsoft YaHei", 12))
        self._score_source.setStyleSheet("color: #999;")
        left_r.addWidget(self._score_source)
        rating_row.addLayout(left_r)

        right_s = QVBoxLayout()
        right_s.setSpacing(4)
        self._rc_label = QLabel()
        self._rc_label.setFont(QFont("Microsoft YaHei", 14))
        self._rc_label.setStyleSheet("color: #555;")
        right_s.addWidget(self._rc_label)
        self._bo_label = QLabel("")
        self._bo_label.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        self._bo_label.setStyleSheet("color: #222;")
        right_s.addWidget(self._bo_label)
        # 票价行（默认隐藏，实时票价获取成功才显示）
        self._price_label = QLabel()
        self._price_label.setFont(QFont("Microsoft YaHei", 13))
        self._price_label.setStyleSheet("color: #999;")
        self._price_label.setVisible(False)
        right_s.addWidget(self._price_label)

        rating_row.addLayout(right_s)
        rating_row.addStretch()
        ip.addLayout(rating_row)

        # ── 按钮行 ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch()

        # 特惠购票（仅 maoyan_id 存在时显示）
        self._buy_btn = QPushButton("特惠购票")
        self._buy_btn.setFixedSize(280, 48)
        self._buy_btn.setCursor(Qt.PointingHandCursor)
        self._buy_btn.setStyleSheet(
            "QPushButton { background: #E53E3E; color: white; border: none; "
            "border-radius: 6px; font: 16pt; font-weight: bold; }"
            "QPushButton:hover { background: #C62828; }"
            "QPushButton:disabled { background: #CCC; color: white; }"
        )
        btn_row.addWidget(self._buy_btn)

        # 豆瓣详情（douban_id 存在时启用，否则禁用+ForbiddenCursor）
        self._douban_btn = QPushButton("豆瓣详情")
        self._douban_btn.setFixedSize(280, 48)
        self._douban_btn.setCursor(Qt.ForbiddenCursor)
        self._douban_btn.setEnabled(False)
        self._douban_btn.setToolTip("豆瓣ID未获取")
        self._douban_btn.setStyleSheet(
            "QPushButton { background: #F5F6FA; color: #718096; border: 1px solid #E2E8F0; "
            "border-radius: 6px; font: 13pt; }"
            "QPushButton:hover { background: #EDF2F7; }"
            "QPushButton:disabled { background: #F5F6FA; color: #CBD5E0; border: 1px solid #E2E8F0; }"
        )
        btn_row.addWidget(self._douban_btn)

        ip.addLayout(btn_row)
        self.cl.addWidget(self._info_panel)

        # ════════════════════════════════════
        #  ③ 主演阵容
        # ════════════════════════════════════
        self.cl.addWidget(make_separator())
        self._cast_frame = QFrame()
        self._cast_frame.setStyleSheet("QFrame { background: white; }")
        cv = QVBoxLayout(self._cast_frame)
        cv.setContentsMargins(32, 20, 32, 20)
        cv.setSpacing(12)
        cv.addWidget(make_section_title("主演阵容"))

        self._cast_scroll = QScrollArea()
        self._cast_scroll.setWidgetResizable(True)
        self._cast_scroll.setFrameShape(QFrame.NoFrame)
        self._cast_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._cast_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cast_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        self._cast_box = QWidget()
        self._cast_box.setStyleSheet("background: transparent;")
        self._cast_row = QHBoxLayout(self._cast_box)
        self._cast_row.setContentsMargins(0, 0, 0, 0)
        self._cast_row.setSpacing(16)
        self._cast_row.addStretch()
        self._cast_scroll.setWidget(self._cast_box)
        cv.addWidget(self._cast_scroll)
        self.cl.addWidget(self._cast_frame)

        # ════════════════════════════════════
        #  ④ 剧情简介 — 多源降级（保留区块）
        # ════════════════════════════════════
        self.cl.addWidget(make_separator())
        self._plot_frame = QFrame()
        self._plot_frame.setStyleSheet("QFrame { background: white; }")
        pv = QVBoxLayout(self._plot_frame)
        pv.setContentsMargins(32, 20, 32, 24)
        pv.setSpacing(10)
        pv.addWidget(make_section_title("剧情简介"))
        self._plot_label = QLabel()
        self._plot_label.setWordWrap(True)
        self._plot_label.setFont(QFont("Microsoft YaHei", 13))
        self._plot_label.setStyleSheet("color: #555;")
        self._plot_label.setOpenExternalLinks(False)
        self._plot_label.setContextMenuPolicy(Qt.CustomContextMenu)
        self._plot_label.customContextMenuRequested.connect(self._show_plot_context_menu)
        pv.addWidget(self._plot_label)
        self.cl.addWidget(self._plot_frame)

        # ════════════════════════════════════
        #  ⑤ 观众热评 — 已恢复，多源降级
        # ════════════════════════════════════
        self.cl.addWidget(make_separator())
        self._reviews_frame = QFrame()
        self._reviews_frame.setStyleSheet("QFrame { background: white; }")
        rv = QVBoxLayout(self._reviews_frame)
        rv.setContentsMargins(32, 20, 32, 24)
        rv.setSpacing(10)
        rv.addWidget(make_section_title("观众热评"))
        self._reviews_container = QVBoxLayout()
        self._reviews_container.setSpacing(8)
        rv.addLayout(self._reviews_container)
        self.cl.addWidget(self._reviews_frame)

        self.cl.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

    # ═══════════════════════════════════════
    #  公开 API
    # ═══════════════════════════════════════

    def show_movie(self, movie_id: int) -> None:
        """从 DB 加载电影详情。"""
        if self.db is None:
            return
        try:
            conn = self.db.get_connection()
            c = conn.cursor()
            c.execute("SELECT * FROM movies WHERE id = ?", (movie_id,))
            row = c.fetchone()
            c.close()
            if not row:
                return
            self._movie_data = dict(row)
            m = self._movie_data
            self._render()
        except Exception as e:
            logger.error("加载详情失败: %s", e)

    def show_movie_data(self, data: dict) -> None:
        """从实时搜索数据加载详情（跳过 DB）。"""
        self._movie_data = data
        self._render()

    # ═══════════════════════════════════════
    #  渲染主逻辑
    # ═══════════════════════════════════════

    def _render(self) -> None:
        """渲染详情页所有内容（每次切换电影时调用）。"""
        m = self._movie_data
        if not m:
            return
        title = m.get("title", "")

        # ── 来源标记 ──
        source = m.get("source", "")
        self._source_label.setText(f"[{source}]" if source else "")
        self._source_label.setVisible(bool(source))

        # ── 海报 ──
        poster_url = m.get("poster_url", "")
        poster_url = _upgrade_poster_url(poster_url)
        self._load_poster(poster_url, title)

        # ── 标题 ──
        self._title_label.setText(title)

        # ── 元信息 ──
        parts = []
        genre = m.get("genre", "")
        if genre:
            parts.append(genre.replace(";", " / "))
        runtime = m.get("runtime") or 0
        if runtime:
            parts.append(f"{runtime:.0f}分钟")
        release = m.get("release_date", "")
        if release:
            parts.append(release[:10])
        self._meta_label.setText(" / ".join(parts) if parts else "")

        # ════════════════════════════════════
        #  评分单分支渲染（彻底消除视觉冲突）
        # ════════════════════════════════════
        rating = m.get("rating") or 0
        rc = m.get("rating_count") or 0
        bo = m.get("box_office") or 0

        if rating and rating > 0:
            self._score_num.setText(f"评分 {rating:.1f}")
            self._score_num.setStyleSheet("color: #FF6B35; font-size: 36pt; font-weight: bold;")
            self._score_source.setVisible(True)
            self._rc_label.setText(f"{rc:,} 人评" if rc else "")
            self._rc_label.setVisible(bool(rc))
        else:
            # 无评分显示「评分待更新」，隐藏所有其他评分标签
            self._score_num.setText("评分待更新")
            self._score_num.setStyleSheet("color: #A0AEC0; font-size: 24pt;")
            self._score_source.setVisible(False)
            self._rc_label.setVisible(False)

        self._bo_label.setText(f"累计票房 {bo:,.2f} 万" if bo else "")

        # ── 票价（默认隐藏，实时获取成功才显示） ──
        self._price_label.setVisible(False)

        maoyan_id = str(m.get("maoyan_id", "") or "")
        douban_id = str(m.get("douban_id", "") or "")

        # ════════════════════════════════════
        #  按钮 — 动态按数据源显示
        # ════════════════════════════════════
        maoyan_valid = bool(maoyan_id and maoyan_id.isdigit() and len(maoyan_id) >= 5)

        self._clean_signal(self._buy_btn)
        self._clean_signal(self._douban_btn)

        if maoyan_valid:
            url = f"https://www.maoyan.com/films/{maoyan_id}"
            self._buy_btn.setVisible(True)
            self._buy_btn.setEnabled(True)
            self._buy_btn.setStyleSheet(
                "QPushButton { background: #E53E3E; color: white; border: none; "
                "border-radius: 6px; font: 16pt; font-weight: bold; }"
                "QPushButton:hover { background: #C62828; }"
            )
            self._buy_btn.clicked.connect(lambda: webbrowser.open(url, new=0))
        else:
            self._buy_btn.setVisible(False)

        if douban_id:
            self._douban_btn.setVisible(True)
            self._douban_btn.setEnabled(True)
            self._douban_btn.setCursor(Qt.PointingHandCursor)
            self._douban_btn.setToolTip("")
            self._douban_btn.setStyleSheet(
                "QPushButton { background: #F5F6FA; color: #333; border: 1px solid #E2E8F0; "
                "border-radius: 6px; font: 13pt; }"
                "QPushButton:hover { background: #EDF2F7; }"
            )
            self._douban_btn.clicked.connect(
                lambda: webbrowser.open(
                    f"https://movie.douban.com/subject/{douban_id}/", new=0
                )
            )
        else:
            # 豆瓣ID为空 → 降级为手动搜索（永不禁用）
            self._douban_btn.setVisible(True)
            self._douban_btn.setEnabled(True)
            self._douban_btn.setCursor(Qt.PointingHandCursor)
            self._douban_btn.setToolTip("点击在豆瓣搜索本片")
            search_text = f"{title} 豆瓣"
            self._douban_btn.clicked.connect(
                lambda checked, q=search_text: webbrowser.open(
                    f"https://www.douban.com/search?q={requests.utils.quote(q)}", new=0
                )
            )

        # 若仅有豆瓣源（无猫眼ID），仅显示豆瓣按钮
        if not maoyan_valid and douban_id:
            self._buy_btn.setVisible(False)
            self._source_label.setText("[豆瓣]")

        # ── 主演 ──
        self._build_cast(m)

        # ════════════════════════════════════
        #  剧情简介（异步多源降级）
        # ════════════════════════════════════
        self._plot_label.setText("⏳ 加载中...")
        self._plot_label.setStyleSheet("color: #999;")
        self._plot_frame.setVisible(True)
        threading.Thread(
            target=self._fetch_plot,
            args=(maoyan_id, douban_id, title),
            daemon=True,
        ).start()

        # ════════════════════════════════════
        #  短评（异步多源降级，已恢复）
        # ════════════════════════════════════
        self._clear_reviews()
        loading_label = QLabel("⏳ 加载短评...")
        loading_label.setStyleSheet("color: #999;")
        self._reviews_container.addWidget(loading_label)
        threading.Thread(
            target=self._fetch_reviews,
            args=(maoyan_id, douban_id),
            daemon=True,
        ).start()

    # ═══════════════════════════════════════
    #  多源降级：剧情简介
    # ═══════════════════════════════════════

    def _fetch_douban_frodo_summary(self, douban_id: str) -> Optional[str]:
        """从豆瓣 Frodo API 获取剧情简介。"""
        try:
            url = f"https://frodo.douban.com/api/v2/movie/{douban_id}"
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Linux; Android 10; K) "
                    "AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36"
                ),
                "Referer": "https://movie.douban.com/",
            }
            resp = requests.get(url, headers=headers, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                summary = data.get("summary", "") or ""
                if summary.strip():
                    logger.info("[SUMMARY] 豆瓣Frodo获取成功: douban_id=%s", douban_id)
                    return summary.strip()
            else:
                logger.debug("[SUMMARY] 豆瓣Frodo HTTP %d", resp.status_code)
            return None
        except Exception as e:
            logger.debug("[SUMMARY] 豆瓣Frodo异常: %s", e)
            return None

    def _fetch_tmdb_summary(self, title: str) -> Optional[str]:
        """从 TMDB API 获取剧情简介。"""
        if not TMDB_API_KEY or not title:
            return None
        try:
            search_url = (
                f"https://api.themoviedb.org/3/search/movie"
                f"?api_key={TMDB_API_KEY}"
                f"&query={requests.utils.quote(title)}&language=zh-CN"
            )
            resp = requests.get(search_url, timeout=8)
            if resp.status_code != 200:
                logger.debug("[SUMMARY] TMDB搜索失败: HTTP %d", resp.status_code)
                return None
            data = resp.json()
            results = data.get("results", [])
            if not results:
                logger.debug("[SUMMARY] TMDB无搜索结果: %s", title)
                return None
            tmdb_id = results[0].get("id")
            if not tmdb_id:
                return None
            detail_url = (
                f"https://api.themoviedb.org/3/movie/{tmdb_id}"
                f"?api_key={TMDB_API_KEY}&language=zh-CN"
            )
            resp2 = requests.get(detail_url, timeout=8)
            if resp2.status_code == 200:
                detail = resp2.json()
                overview = detail.get("overview", "") or ""
                if overview.strip():
                    logger.info("[SUMMARY] TMDB获取成功: title=%s", title)
                    return overview.strip()
            return None
        except Exception as e:
            logger.debug("[SUMMARY] TMDB异常: %s", e)
            return None

    def _fetch_plot(self, maoyan_id: str, douban_id: str = "", title: str = "") -> None:
        """异步获取剧情简介（猫眼H5 → 豆瓣Frodo → TMDB 三级降级）。"""
        reasons = []

        # ─── 主源：猫眼 H5 ───
        if maoyan_id and maoyan_id.isdigit():
            summary = AGGREGATOR.get_summary(maoyan_id)
            if summary and summary.strip():
                logger.info("[SUMMARY] 猫眼H5获取成功, len=%d", len(summary))
                self._plot_ready.emit(summary)
                return
            reasons.append("maoyan=404")
        else:
            reasons.append("maoyan=id_missing")

        # ─── 备源1：豆瓣 Frodo API ───
        if douban_id:
            try:
                frodo_summary = self._fetch_douban_frodo_summary(douban_id)
                if frodo_summary:
                    self._plot_ready.emit(frodo_summary)
                    return
                reasons.append("douban=no_data")
            except Exception:
                reasons.append("douban=auth_required")
        else:
            reasons.append("douban=id_missing")

        # ─── 备源2：TMDB API ───
        tmdb_summary = self._fetch_tmdb_summary(title)
        if tmdb_summary:
            self._plot_ready.emit(tmdb_summary)
            return
        if not TMDB_API_KEY:
            reasons.append("tmdb=api_key_missing")
        else:
            reasons.append("tmdb=rate_limited")

        # 三级全部失败 → 输出归因日志 + 占位UI
        fallback_msg = "summary: " + ", ".join(reasons)
        self._plot_ready.emit("")

    # ═══════════════════════════════════════
    #  多源降级：短评
    # ═══════════════════════════════════════

    def _fetch_reviews(self, maoyan_id: str, douban_id: str = "") -> None:
        """异步获取短评（猫眼 → 豆瓣Frodo 二级降级）。"""
        reasons = []

        # ─── 主源：猫眼 H5 ───
        if maoyan_id and maoyan_id.isdigit():
            reviews = AGGREGATOR.get_reviews(maoyan_id, limit=3)
            if reviews:
                logger.info("[REVIEWS] 猫眼H5获取成功: %d 条", len(reviews))
                self._reviews_ready.emit(reviews)
                return
            reasons.append("maoyan=empty_array")
        else:
            reasons.append("maoyan=no_id")

        # ─── 备源：豆瓣 Frodo API ───
        if douban_id:
            try:
                url = f"https://frodo.douban.com/api/v2/movie/{douban_id}/comments?limit=3"
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Linux; Android 10; K) "
                        "AppleWebKit/537.36 Chrome/120.0.0.0 Mobile Safari/537.36"
                    ),
                    "Referer": "https://movie.douban.com/",
                }
                resp = requests.get(url, headers=headers, timeout=8)
                if resp.status_code == 200:
                    data = resp.json()
                    comments = data.get("comments", data.get("items", []))[:3]
                    if comments:
                        reviews = []
                        for c in comments:
                            author_obj = c.get("author", {})
                            if isinstance(author_obj, dict):
                                author = author_obj.get("name", "匿名")
                            else:
                                author = str(author_obj) or "匿名"
                            rating_raw = c.get("rating", 0)
                            rating_val = rating_raw // 2 if rating_raw else 0
                            content = c.get("content", "").strip()
                            if content:
                                reviews.append({
                                    "author": author,
                                    "rating": min(rating_val, 5),
                                    "content": content,
                                })
                        if reviews:
                            logger.info("[REVIEWS] 豆瓣Frodo获取成功: %d 条", len(reviews))
                            self._reviews_ready.emit(reviews)
                            return
                        reasons.append("douban=empty_array")
                    else:
                        reasons.append("douban=empty_array")
                else:
                    reasons.append("douban=auth_required")
            except Exception:
                reasons.append("douban=auth_required")
        else:
            reasons.append("douban=id_missing")

        # 全部失败 → 输出归因日志 + 占位UI
        fallback_msg = "comments: " + ", ".join(reasons)
        self._reviews_ready.emit([])

    # ═══════════════════════════════════════
    #  信号处理（主线程）
    # ═══════════════════════════════════════

    def _on_price_data(self, value) -> None:
        """票价回调：有数据显示，无数据隐藏。"""
        if value and isinstance(value, (int, float)) and value > 0:
            self._price_label.setText(f"🎫 票价 ¥{value:.0f} 起")
            self._price_label.setStyleSheet("color: #E53E3E; font-weight: bold;")
            self._price_label.setVisible(True)
        else:
            self._price_label.setVisible(False)

    def _on_plot_data(self, text: str) -> None:
        """剧情简介回调：有数据显示，无数据可复制片名搜索。"""
        if text and text.strip():
            self._plot_label.setText(text)
            self._plot_label.setStyleSheet("color: #555;")
        else:
            title = self._movie_data.get("title", "") if self._movie_data else ""
            release = self._movie_data.get("release_date", "") if self._movie_data else ""
            year = release[:4] if release else ""
            display_text = (
                f"📖 简介暂未收录\n"
                f"片名：{title}（{year}）\n"
                f"📋 右键点击 → 复制片名搜索"
            )
            self._plot_label.setText(display_text)
            self._plot_label.setStyleSheet("color: #718096; font-size: 14px; line-height: 1.8; padding: 12px 0;")
            self._plot_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._plot_frame.setVisible(True)

    def _show_plot_context_menu(self, pos):
        """右键菜单：复制片名到剪贴板。"""
        if not self._movie_data:
            return
        menu = QMenu(self._plot_label)
        action = QAction("📋 复制片名", self._plot_label)
        action.triggered.connect(self._copy_film_name)
        menu.addAction(action)
        menu.exec_(self._plot_label.mapToGlobal(pos))

    def _copy_film_name(self) -> None:
        """复制电影名到剪贴板。"""
        clipboard = QApplication.clipboard()
        title = self._movie_data.get("title", "") if self._movie_data else ""
        release = self._movie_data.get("release_date", "") if self._movie_data else ""
        year = release[:4] if release else ""
        text = f"{title} {year}".strip()
        if text:
            clipboard.setText(text)

    def _on_reviews_data(self, reviews: list) -> None:
        """短评回调：有数据显示，无数据显示可复制片名标识。"""
        self._clear_reviews()

        if reviews:
            for r in reviews:
                card = self._make_review_card(r)
                self._reviews_container.addWidget(card)
        else:
            title = self._movie_data.get("title", "") if self._movie_data else ""
            release = self._movie_data.get("release_date", "") if self._movie_data else ""
            year = release[:4] if release else ""
            placeholder = QLabel(
                f"💬 本片暂无观众短评\n片名：{title}（{year}）"
            )
            placeholder.setStyleSheet(
                "color: #A0AEC0; font-size: 13px; padding: 8px 0; line-height: 1.6;"
            )
            placeholder.setWordWrap(True)
            placeholder.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._reviews_container.addWidget(placeholder)

        self._reviews_container.addStretch()

    def _clear_reviews(self) -> None:
        """清空短评容器。"""
        while self._reviews_container.count():
            item = self._reviews_container.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

    def _make_review_card(self, review: dict) -> QFrame:
        """创建单条短评卡片。"""
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #F9F9FB; border-radius: 8px; }"
        )
        cl = QVBoxLayout(card)
        cl.setContentsMargins(16, 10, 16, 10)
        cl.setSpacing(4)

        header = QHBoxLayout()
        author = QLabel(review.get("author", "匿名"))
        author.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        author.setStyleSheet("color: #333;")
        header.addWidget(author)

        rating_val = review.get("rating", 0)
        if rating_val:
            stars = "★" * rating_val + "☆" * (5 - rating_val)
            stars_label = QLabel(stars)
            stars_label.setStyleSheet("color: #FF9800; font-size: 12px;")
            header.addWidget(stars_label)
        header.addStretch()
        cl.addLayout(header)

        content = QLabel(review.get("content", ""))
        content.setWordWrap(True)
        content.setFont(QFont("Microsoft YaHei", 12))
        content.setStyleSheet("color: #555;")
        cl.addWidget(content)

        return card

    # ═══════════════════════════════════════
    #  海报 — 300×450
    # ═══════════════════════════════════════

    def _load_poster(self, url: str, title: str = "") -> None:
        """异步加载海报（本地缓存 → HTTP → 渐变兜底）。"""
        if not url:
            self._show_poster_fallback(title)
            return

        # 检查本地缓存
        movie_id = self._movie_data.get("id", 0) if self._movie_data else 0
        cache_path = os.path.join(CACHE_DIR, f"{movie_id}.jpg") if movie_id else ""
        if cache_path and os.path.exists(cache_path):
            pix = QPixmap(cache_path)
            if not pix.isNull():
                scaled = pix.scaled(
                    POSTER_W, POSTER_H,
                    Qt.KeepAspectRatioByExpanding,
                    Qt.SmoothTransformation,
                )
                self._poster_label.setPixmap(scaled)
                logger.info("[DETAIL_POSTER] 缓存命中: %s", cache_path)
                return

        # 线程下载
        logger.info("[DETAIL_POSTER] 请求: %s", (url[:60] + "...") if len(url) > 60 else url)

        def download():
            try:
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "image/*",
                    "Referer": "https://www.maoyan.com/",
                }
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code == 200 and len(resp.content) > 100:
                    self._poster_ready.emit(resp.content)
                    if movie_id:
                        os.makedirs(CACHE_DIR, exist_ok=True)
                        cp = os.path.join(CACHE_DIR, f"{movie_id}.jpg")
                        with open(cp, "wb") as f:
                            f.write(resp.content)
                        logger.info("[DETAIL_POSTER] 已缓存: %s", cp)
            except Exception as e:
                logger.warning("[DETAIL_POSTER] 下载异常: %s", e)

        threading.Thread(target=download, daemon=True).start()

    def _on_poster_data(self, data: bytes) -> None:
        """主线程接收海报数据。"""
        pix = QPixmap()
        if pix.loadFromData(data):
            scaled = pix.scaled(
                POSTER_W, POSTER_H,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            self._poster_label.setPixmap(scaled)

    def _show_poster_fallback(self, title: str) -> None:
        """海报兜底：暗色渐变 + 首字。"""
        pix = QPixmap(POSTER_W, POSTER_H)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)

        grad = QLinearGradient(0, 0, POSTER_W, POSTER_H)
        grad.setColorAt(0.0, QColor("#1a1a2e"))
        grad.setColorAt(1.0, QColor("#16213e"))
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.NoPen)
        painter.drawRect(0, 0, POSTER_W, POSTER_H)

        if title:
            painter.setPen(QColor(255, 255, 255, 200))
            font = QFont("Microsoft YaHei", POSTER_W // 4, QFont.Bold)
            painter.setFont(font)
            painter.drawText(QRect(0, 0, POSTER_W, POSTER_H),
                             Qt.AlignCenter, title[0])

        painter.end()
        self._poster_label.setPixmap(pix)

    # ═══════════════════════════════════════
    #  主演阵容 — QLabel方案（无QPainter）
    # ═══════════════════════════════════════

    def _build_cast(self, m: dict) -> None:
        """渲染主演列表（QPainter手动裁剪正圆头像 + 姓名无截断）。"""
        # 清空旧的 avatar 容器（保留最后的 addStretch）
        while self._cast_row.count() > 1:
            it = self._cast_row.takeAt(0)
            if it and it.widget():
                it.widget().deleteLater()

        actors = m.get("actors", "")
        if not actors:
            empty = QLabel("暂无主演信息")
            empty.setFont(QFont("Microsoft YaHei", 12))
            empty.setStyleSheet("color: #999; padding: 8px 0;")
            self._cast_row.insertWidget(0, empty)
            return

        # 支持 ; 和 ／ 两种分隔符
        names = [n.strip() for n in actors.replace(";", "／").split("／") if n.strip()]

        for name in names[:8]:
            w = QWidget()
            wl = QVBoxLayout(w)
            wl.setContentsMargins(4, 0, 4, 0)
            wl.setSpacing(6)
            wl.setAlignment(Qt.AlignCenter)

            # ═══════════════════════════════════════
            # 头像：QPixmap + QPainter 手动绘制正圆
            # （Windows Qt 5.15.2 下 QSS border-radius
            #  不可靠，改用像素级裁剪）
            # ═══════════════════════════════════════
            char = name[0] if name and name.strip() else "?"
            color = random.choice(ACTOR_COLORS) if name and name.strip() else "#E0E0E0"

            pixmap = QPixmap(48, 48)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QColor(color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(0, 0, 48, 48)
            painter.setPen(QColor("white"))
            font = QFont("Microsoft YaHei", 18, QFont.Bold)
            painter.setFont(font)
            painter.drawText(QRect(0, 0, 48, 48), Qt.AlignCenter, char)
            painter.end()

            avatar = QLabel()
            avatar.setFixedSize(48, 48)
            avatar.setPixmap(pixmap)
            avatar.setAlignment(Qt.AlignCenter)
            wl.addWidget(avatar, 0, Qt.AlignCenter)

            # ═══════════════════════════════════════
            # 姓名：不设最大宽度，保证完整显示
            # ═══════════════════════════════════════
            nl = QLabel(name)
            nl.setFont(QFont("Microsoft YaHei", 10))
            nl.setStyleSheet("color: #555;")
            nl.setAlignment(Qt.AlignCenter)
            nl.setWordWrap(False)
            nl.setMinimumWidth(0)
            wl.addWidget(nl)

            wl.addStretch()
            self._cast_row.insertWidget(self._cast_row.count() - 1, w)

    # ═══════════════════════════════════════
    #  工具方法
    # ═══════════════════════════════════════

    def _clean_signal(self, widget) -> None:
        """断开 widget 的所有 clicked 信号连接。"""
        try:
            widget.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
