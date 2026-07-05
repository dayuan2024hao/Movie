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
from PyQt5.QtCore import Qt, pyqtSignal, QRect, QUrl
from PyQt5.QtGui import (
    QFont, QPixmap, QPainter, QColor, QBrush, QFontMetrics,
    QLinearGradient, QDesktopServices,
)

from database.db_manager import DatabaseManager
from crawler.realtime_aggregator import RealtimeAggregator
from crawler.omdb_api import OMDBApi

logger = logging.getLogger("DetailPage")

POSTER_W = 300
POSTER_H = 450
# 头像样式已移除（主演用纯文本展示）

CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "cache", "posters",
)

# TMDB API 配置（用户已提供 Key）
# 申请地址：https://www.themoviedb.org/settings/api
TMDB_API_KEY = "689c6bb83710eee417a14d457d92e86d"

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
    _reviews_ready = pyqtSignal(list)
    _price_ready = pyqtSignal(object)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db: Optional[DatabaseManager] = None
        self._movie_data: Optional[dict] = None
        self._poster_ready.connect(self._on_poster_data)
        self._plot_ready.connect(self._on_plot_data)
        # _reviews_ready 信号已弃用（保留连接避免 AttributeError）
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
        self._bo_label.setStyleSheet("color: #222; font-size: 16pt; font-weight: bold;")
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
            "border-radius: 6px; font: 10pt; font-weight: bold; }"
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
            "QPushButton { background: #007722; color: white; border: none; "
            "border-radius: 6px; font: 10pt; font-weight: bold; }"
            "QPushButton:hover { background: #005F1A; }"
            "QPushButton:disabled { background: #A8D8B5; color: white; border: none; }"
        )
        btn_row.addWidget(self._douban_btn)

        ip.addLayout(btn_row)
        self.cl.addWidget(self._info_panel)

        # ════════════════════════════════════
        #  ③ 主演阵容 — 纯文本换行展示
        # ════════════════════════════════════
        self.cl.addWidget(make_separator())
        self._cast_frame = QFrame()
        self._cast_frame.setStyleSheet("QFrame { background: white; }")
        cv = QVBoxLayout(self._cast_frame)
        cv.setContentsMargins(32, 20, 32, 20)
        cv.setSpacing(12)
        cv.addWidget(make_section_title("主演阵容"))

        self._cast_label = QLabel()
        self._cast_label.setFont(QFont("Microsoft YaHei", 11))
        self._cast_label.setStyleSheet("color: #555;")
        self._cast_label.setWordWrap(True)
        cv.addWidget(self._cast_label)
        self.cl.addWidget(self._cast_frame)

        # ════════════════════════════════════
        #  ④ 口碑标签（关键词标签云）
        # ════════════════════════════════════
        self.cl.addWidget(make_separator())
        self._tag_frame = QFrame()
        self._tag_frame.setStyleSheet("QFrame { background: white; }")
        tv = QVBoxLayout(self._tag_frame)
        tv.setContentsMargins(32, 20, 32, 20)
        tv.setSpacing(10)
        tv.addWidget(make_section_title("口碑标签"))
        self._tag_container = QWidget()
        self._tag_layout = QHBoxLayout(self._tag_container)
        self._tag_layout.setContentsMargins(0, 0, 0, 0)
        self._tag_layout.setSpacing(8)
        self._tag_layout.addStretch()
        tv.addWidget(self._tag_container)
        self.cl.addWidget(self._tag_frame)

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
        import traceback
        print(f"[DETAIL] show_movie_data 收到数据: title={data.get('title','?')} "
              f"source={data.get('source','?')} rating={data.get('rating',0)} "
              f"imdb_id={data.get('imdb_id','')[:10]} poster={data.get('poster_url','')[:30]}")
        try:
            self._movie_data = dict(data)

            # 优先用 imdb_id 查 OMDB 完整详情
            imdb_id = self._movie_data.get("imdb_id", "")
            if imdb_id:
                try:
                    omdb = OMDBApi()
                    omdb_data = omdb.fetch_by_imdb_id(imdb_id)
                    if omdb_data:
                        self._movie_data.update(
                            {k: v for k, v in omdb.to_app_format(omdb_data).items() if v}
                        )
                except Exception:
                    pass

            # 没有 imdb_id 但有 douban_id 且没评分，尝试用中文片名查 OMDB
            if not self._movie_data.get("rating") and not imdb_id:
                try:
                    title = self._movie_data.get("title", "")
                    if title:
                        omdb = OMDBApi()
                        omdb_data = omdb.fetch(title)  # 内部会查 EN_TITLE_MAP
                        if omdb_data:
                            self._movie_data.update(
                                {k: v for k, v in omdb.to_app_format(omdb_data).items() if v}
                            )
                except Exception:
                    pass

            # 尝试从数据库补全数据（精确匹配优先）
            if self.db:
                try:
                    title = data.get("title", "")
                    if title:
                        conn = self.db.get_connection()
                        c = conn.cursor()
                        # 先精确匹配
                        c.execute("SELECT * FROM movies WHERE title = ?", (title,))
                        row = c.fetchone()
                        # 再模糊匹配（去掉特殊字符）
                        if not row:
                            clean = title.replace("(上)", "").replace("(下)", "").replace(" ", "")
                            c.execute("SELECT * FROM movies WHERE title LIKE ? LIMIT 1",
                                      (f"%{clean}%",))
                            row = c.fetchone()
                        c.close()
                        if row:
                            db_data = dict(row)
                            print(f"[DETAIL] 数据库匹配: {db_data.get('title','?')} (搜索: {title})")
                            for key in ["showing_status", "maoyan_id", "genre",
                                        "actors", "summary", "box_office",
                                        "runtime", "poster_url", "rating_count"]:
                                if db_data.get(key):
                                    self._movie_data[key] = db_data[key]
                except Exception:
                    pass
            self._render()
        except Exception as e:
            logger.error("渲染详情失败: %s", e)
            traceback.print_exc()

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
            self._score_num.setStyleSheet("color: #FF6B35; font-size: 16pt; font-weight: bold;")
            self._score_source.setVisible(True)
            self._rc_label.setText(f"{rc:,} 人评" if rc else "")
            self._rc_label.setVisible(bool(rc))
        else:
            self._score_num.setText("评分待更新")
            self._score_num.setStyleSheet("color: #A0AEC0; font-size: 14pt;")
            self._score_source.setVisible(False)
            self._rc_label.setVisible(False)

        # box_office 可能是字符串（来自 OMDB），统一转数字
        try:
            bo_num = float(bo) if bo else 0
        except (ValueError, TypeError):
            bo_num = 0
        self._bo_label.setText(f"累计票房 {bo_num:,.0f} 万" if bo_num else "")

        # ── 票价（默认隐藏，实时获取成功才显示） ──
        self._price_label.setVisible(False)

        maoyan_id = str(m.get("maoyan_id", "") or "")
        douban_id = str(m.get("douban_id", "") or "")

        # ════════════════════════════════════
        #  按钮 — 上映=双按钮, 下映=仅豆瓣
        # ════════════════════════════════════
        maoyan_valid = bool(maoyan_id and maoyan_id.isdigit() and len(maoyan_id) >= 5)
        showing_status = m.get("showing_status", "")
        is_showing = showing_status in ("showing", "coming_soon") or maoyan_valid

        self._clean_signal(self._buy_btn)
        self._clean_signal(self._douban_btn)

        # 特惠购票：仅上映中且有所需ID时显示
        if is_showing and maoyan_valid:
            url = f"https://www.maoyan.com/films/{maoyan_id}"
            self._buy_btn.setVisible(True)
            self._buy_btn.setEnabled(True)
            self._buy_btn.setStyleSheet(
                "QPushButton { background: #E53E3E; color: white; border: none; "
                "border-radius: 6px; font: 10pt; font-weight: bold; }"
                "QPushButton:hover { background: #C62828; }"
            )
            self._buy_btn.clicked.connect(lambda checked, u=url: self._safe_open_url(u))
        else:
            self._buy_btn.setVisible(False)

        # 豆瓣详情：始终显示（ID存在→直跳，不存在→手动搜索）
        if douban_id:
            self._douban_btn.setVisible(True)
            self._douban_btn.setEnabled(True)
            self._douban_btn.setCursor(Qt.PointingHandCursor)
            self._douban_btn.setToolTip("")
            self._douban_btn.setStyleSheet(
                "QPushButton { background: #007722; color: white; border: none; "
                "border-radius: 6px; font: 10pt; font-weight: bold; }"
                "QPushButton:hover { background: #005F1A; }"
            )
            douban_url = f"https://movie.douban.com/subject/{douban_id}/"
            self._douban_btn.clicked.connect(
                lambda checked, u=douban_url: self._safe_open_url(u)
            )
        else:
            self._douban_btn.setVisible(True)
            self._douban_btn.setEnabled(True)
            self._douban_btn.setCursor(Qt.PointingHandCursor)
            self._douban_btn.setToolTip("点击在豆瓣搜索本片")
            search_text = title
            encoded = requests.utils.quote(search_text)
            search_url = f"https://www.douban.com/search?q={encoded}"
            self._douban_btn.clicked.connect(
                lambda checked, u=search_url: self._safe_open_url(u)
            )

        # ── 主演 ──
        self._build_cast(m)

        # ── 口碑标签 ──
        self._build_tags(m)

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

        # 短评功能已移除

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
        """异步获取剧情简介（OMDB → 本地DB → 猫眼/豆瓣/TMDB 降级）。"""
        movie_title = (self._movie_data or {}).get("title", "") or title

        # ─── 第0优先级：OMDB API（英文片名搜索，含完整剧情）───
        if movie_title:
            try:
                omdb = OMDBApi()
                omdb_data = omdb.fetch(movie_title)
                if omdb_data:
                    plot = OMDBApi.extract_plot(omdb_data)
                    if plot:
                        logger.info("[SUMMARY] OMDB获取成功: %s, len=%d", movie_title, len(plot))
                        self._enrich_from_omdb(omdb_data)
                        # 翻译英文简介为中文
                        chinese_plot = self._translate_text(plot)
                        display = chinese_plot if chinese_plot else f"[英文]\n{plot}"
                        self._plot_ready.emit(display)
                        return
            except Exception as e:
                logger.debug("[SUMMARY] OMDB异常: %s", e)

        # ─── 第1优先级：本地数据库已有简介 ───
        local_summary = (self._movie_data or {}).get("summary", "") or ""
        if local_summary.strip():
            logger.info("[SUMMARY] 使用本地数据库简介, len=%d", len(local_summary))
            self._plot_ready.emit(local_summary.strip())
            return

        reasons = []

        # ─── 降级：猫眼 H5 ───
        if maoyan_id and maoyan_id.isdigit():
            summary = AGGREGATOR.get_summary(maoyan_id)
            if summary and summary.strip():
                logger.info("[SUMMARY] 猫眼H5获取成功, len=%d", len(summary))
                self._plot_ready.emit(summary)
                return
            reasons.append("maoyan=404")
        else:
            reasons.append("maoyan=id_missing")

        # ─── 降级：豆瓣 Frodo API ───
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

        # ─── 降级：TMDB API ───
        tmdb_summary = self._fetch_tmdb_summary(movie_title)
        if tmdb_summary:
            self._plot_ready.emit(tmdb_summary)
            return

        reasons.append("tmdb=unavailable")

        # 全部失败 → 空简介
        self._plot_ready.emit("")

    def _enrich_from_omdb(self, omdb_data: dict) -> None:
        """用 OMDB 数据更新当前电影信息。

        Args:
            omdb_data: OMDB API 返回的数据
        """
        if not self._movie_data:
            return

        # 只补充空字段
        plot = OMDBApi.extract_plot(omdb_data)
        if plot and not self._movie_data.get("summary"):
            self._movie_data["summary"] = plot

        genre = OMDBApi.extract_genre(omdb_data)
        if genre and not self._movie_data.get("genre"):
            self._movie_data["genre"] = genre

        actors = OMDBApi.extract_actors(omdb_data)
        if actors and not self._movie_data.get("actors"):
            self._movie_data["actors"] = actors

        poster = OMDBApi.extract_poster(omdb_data)
        if poster and not self._movie_data.get("poster_url"):
            self._movie_data["poster_url"] = poster

        rating = OMDBApi.extract_rating(omdb_data)
        if rating and not self._movie_data.get("rating"):
            self._movie_data["rating"] = rating

        runtime = OMDBApi.extract_runtime(omdb_data)
        if runtime and not self._movie_data.get("runtime"):
            self._movie_data["runtime"] = runtime

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

    @staticmethod
    def _clean_summary(text: str) -> str:
        """清理简介文本，去掉演职人员/票房/宣传语等垃圾，修复标点。

        Args:
            text: 原始简介文本

        Returns:
            清理后的纯剧情文本
        """
        if not text:
            return ""

        # 去掉 "演职人员" 及之后所有内容
        text = re.split(r'演职人员|演职员表|全部\s*导演|全部\s*演员', text)[0]

        # 去掉票房相关行
        text = re.sub(r'票房.*?(?:详情|昨日排名|首周|累计).*?\n', '\n', text)
        text = re.sub(r'图集\s*全部\s*\n', '\n', text)
        text = re.sub(r'影片资料.*?\n', '\n', text)
        text = re.sub(r'预告片.*?\n', '\n', text)
        text = re.sub(r'出品发行.*?\n', '\n', text)

        # 去掉短促宣传标语行（单独成行，含感叹号）
        text = re.sub(r'^[^。！？\n]{1,30}[！!]\s*\n', '', text, flags=re.MULTILINE)

        # 修复重复标点：多个句号→一个，多个感叹号→一个
        text = re.sub(r'[。]{2,}', '。', text)
        text = re.sub(r'[！]{2,}', '！', text)
        text = re.sub(r'[。][！]', '。', text)
        text = re.sub(r'[，,]{2,}', '，', text)

        # 去掉开头为"【xxx】"的营销标签行
        text = re.sub(r'^【[^】]*】\s*', '', text)

        # 去掉空行
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        text = '\n'.join(lines)

        # 不限长度，完整显示
        return text.strip()

    def _on_plot_data(self, text: str) -> None:
        """剧情简介回调。"""
        if text and text.strip():
            cleaned = self._clean_summary(text.strip())
            self._plot_label.setText(cleaned)
            self._plot_label.setStyleSheet("color: #555; line-height: 1.8;")
        else:
            self._plot_label.setText("暂无简介")
            self._plot_label.setStyleSheet("color: #A0AEC0;")
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
            placeholder = QLabel("暂无观众短评")
            placeholder.setStyleSheet(
                "color: #A0AEC0; font-size: 13px; padding: 8px 0; line-height: 1.6;"
            )
            placeholder.setWordWrap(True)
            placeholder.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._reviews_container.addWidget(placeholder)

        self._reviews_container.addStretch()

    def _clear_reviews(self) -> None:
        """清空短评容器（已弃用，兼容保留）。"""
        pass

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

        # 豆瓣海报全部被反爬拦截(HTTP 418)，直接跳过用渐变兜底
        if "doubanio.com" in url:
            self._show_poster_fallback(title)
            return

        # 检查本地缓存（但若URL已被升级为高清，旧缓存需重新下载）
        movie_id = self._movie_data.get("id", 0) if self._movie_data else 0
        cache_path = os.path.join(CACHE_DIR, f"{movie_id}.jpg") if movie_id else ""
        is_hd_url = "/w/1000" in url or "/h/1500" in url
        if cache_path and os.path.exists(cache_path):
            file_size = os.path.getsize(cache_path)
            # 旧缓存太小(<30KB)说明是低清版，删除重新下载
            if is_hd_url and file_size < 30000:
                try:
                    os.remove(cache_path)
                    logger.info("[DETAIL_POSTER] 旧缓存太小(%d bytes)，删除重下", file_size)
                except Exception:
                    pass
            else:
                pix = QPixmap(cache_path)
                if not pix.isNull():
                    scaled = pix.scaled(
                        POSTER_W, POSTER_H,
                        Qt.KeepAspectRatioByExpanding,
                        Qt.SmoothTransformation,
                    )
                    self._poster_label.setPixmap(scaled)
                    logger.info("[DETAIL_POSTER] 缓存命中: %s (%d bytes)", cache_path, file_size)
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

    def _build_cast(self, m: dict) -> None:
        """渲染主演列表（纯文本，自动换行）。

        Args:
            m: 电影数据字典
        """
        actors = m.get("actors", "")
        if not actors:
            self._cast_label.setText("暂无主演信息")
            return

        names = [n.strip() for n in actors.replace(";", "／").split("／") if n.strip()]
        names_str = " ／ ".join(names[:8])
        self._cast_label.setText(names_str)

    def _build_tags(self, m: dict) -> None:
        """生成口碑标签（关键词标签云）。

        Args:
            m: 电影数据字典
        """
        # 清空旧标签
        while self._tag_layout.count() > 1:
            item = self._tag_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        tags = []

        # 类型标签
        genre = m.get("genre", "")
        if genre:
            for g in genre.replace(";", ",").split(","):
                g = g.strip()
                if g:
                    tags.append((g, "#1E88E5"))

        # 评分等级标签
        rating = m.get("rating") or 0
        if rating >= 9:
            tags.append(("🏆 神作", "#E53935"))
        elif rating >= 8:
            tags.append(("⭐ 佳作", "#FB8C00"))
        elif rating >= 7:
            tags.append(("👍 好评", "#43A047"))
        elif rating > 0:
            tags.append(("📊 普通", "#757575"))

        # 票房等级标签
        bo = m.get("box_office") or 0
        if bo >= 300000:
            tags.append(("💥 爆款", "#E53935"))
        elif bo >= 100000:
            tags.append(("🔥 热卖", "#FB8C00"))
        elif bo >= 10000:
            tags.append(("📈 畅销", "#43A047"))
        elif bo > 0:
            tags.append(("📉 小众", "#757575"))

        # 上映状态标签
        status = m.get("showing_status", "")
        if status == "showing":
            tags.append(("🎬 热映中", "#43A047"))
        elif status == "coming_soon":
            tags.append(("📅 即将上映", "#FB8C00"))

        # 地区标签
        region = m.get("region", "")
        if region:
            tags.append((f"🌍 {region}", "#8E24AA"))

        # 语言标签
        lang = m.get("language", "")
        if lang:
            tags.append((f"🗣 {lang}", "#00ACC1"))

        # 创建标签组件
        for text, color in tags:
            tag = QLabel(f"  {text}  ")
            tag.setFont(QFont("Microsoft YaHei", 10))
            tag.setStyleSheet(
                f"background: {color}20; color: {color}; "
                f"border: 1px solid {color}40; border-radius: 10px; "
                f"padding: 2px 6px; margin: 2px;"
            )
            self._tag_layout.insertWidget(self._tag_layout.count() - 1, tag)

    # ═══════════════════════════════════════
    #  工具方法
    # ═══════════════════════════════════════

    def _clean_signal(self, widget) -> None:
        """断开 widget 的所有 clicked 信号连接。"""
        try:
            widget.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass

    def _safe_open_url(self, url: str) -> None:
        """安全打开 URL（带异常捕获 + traceback 输出）。

        Args:
            url: 要打开的 URL 字符串
        """
        import traceback
        try:
            print(f"[DEBUG_STEP_1] _safe_open_url called with: {repr(url)}")
            if not url or not url.strip():
                print("[DEBUG_STEP_1] ERROR: url is empty!")
                return
            qurl = QUrl(url)
            if not qurl.isValid():
                print(f"[DEBUG_STEP_1] ERROR: invalid QUrl: {qurl.errorString()}")
                return
            print(f"[DEBUG_STEP_1] QUrl valid: {qurl.toString()}")
            result = QDesktopServices.openUrl(qurl)
            print(f"[DEBUG_STEP_1] openUrl result: {result}")
        except Exception as e:
            print(f"[DEBUG_STEP_1] CRASH: {e}")
            traceback.print_exc()

    @staticmethod
    def _translate_text(text: str) -> str:
        """翻译英文文本为中文（使用 translators 库）。

        Args:
            text: 英文文本

        Returns:
            中文翻译，失败返回空字符串
        """
        if not text or not text.strip():
            return ""
        try:
            import translators as ts
            result = ts.translate_text(
                text[:1500],  # 限制长度
                from_language='en',
                to_language='zh',
                translator='bing',
            )
            if result:
                return result.strip()
        except Exception:
            pass
        # 降级到阿里翻译
        try:
            import translators as ts
            result = ts.translate_text(
                text[:1500],
                from_language='en',
                to_language='zh',
                translator='alibaba',
            )
            if result:
                return result.strip()
        except Exception:
            pass
        return ""
