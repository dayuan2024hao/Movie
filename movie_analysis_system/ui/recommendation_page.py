"""
推荐页面
========
猫眼在映电影推荐。严格按以下规则：
  - 排序：上映日期降序（今日上映 > 近7天 > 更早）
  - 同日：票房降序
  - 状态标签：今日上映 / 热映中 / 长线放映 / 即将上映
  - 海报：本地缓存 → 网络请求 → 渐变背景兜底
  - 数据校验：过滤无效 maoyan_id
"""

import logging
import os
import random
import re
import threading
from datetime import datetime
from typing import Optional

import requests

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
    QScrollArea, QFrame,
)
from PyQt5.QtCore import Qt, pyqtSignal, QRect
from PyQt5.QtGui import (
    QFont, QPixmap, QColor, QPainter, QLinearGradient, QBrush, QFontMetrics,
)

from database.db_manager import DatabaseManager
from recommendation.recommender import Recommender
from crawler.realtime_aggregator import RealtimeAggregator

logger = logging.getLogger("RecommendationPage")

POSTER_W = 120
POSTER_H = 170
TIMEOUT_MS = 8000
AGGREGATOR = RealtimeAggregator()


def _upgrade_poster_url(url: str) -> str:
    """替换海报URL为高清版本（w.h → 1000.1500）。"""
    if not url:
        return ""
    new_url = re.sub(r'w\.h\b', '1000.1500', url)
    new_url = re.sub(r'/w/\d+', '/w/1000', new_url)
    new_url = re.sub(r'/h/\d+', '/h/1500', new_url)
    if new_url != url:
        logger.info("[POSTER_HD] %s → %s", url[:30], new_url[:30])
    return new_url


# 海报缓存目录
CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "cache", "posters",
)

# ─── 渐变配色池 ───
GRADIENTS = [
    ("#667eea", "#764ba2"),
    ("#f093fb", "#f5576c"),
    ("#4facfe", "#00f2fe"),
    ("#43e97b", "#38f9d7"),
    ("#fa709a", "#fee140"),
    ("#a18cd1", "#fbc2eb"),
    ("#fccb90", "#d57eeb"),
    ("#e0c3fc", "#8ec5fc"),
    ("#f5576c", "#ff6f91"),
    ("#667eea", "#4facfe"),
]


def _get_cache_path(movie_id: int) -> str:
    """获取海报缓存文件路径。"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{movie_id}.jpg")


def _validate_movie(movie: dict) -> bool:
    """验证电影数据合法性：过滤无效 maoyan_id。"""
    maoyan_id = movie.get("maoyan_id", "")
    mid_str = str(maoyan_id).strip()
    if not maoyan_id or not mid_str.isdigit() or len(mid_str) < 5:
        logger.warning("[VALIDATION] 过滤非法电影: id=%s, title=%s, maoyan_id=%s",
                       movie.get("id"), movie.get("title"), maoyan_id)
        return False
    return True


def get_status_tag(release_date: str,
                   showing_status: str = "showing") -> Optional[str]:
    """根据上映日期返回状态标签。

    Returns:
        "今日上映" / "热映中" / "长线放映" / 带日期的即将上映 / None
    """
    if showing_status == "coming_soon":
        date_str = (release_date or "")[:10]
        return f"即将上映 ({date_str})" if date_str else "即将上映"

    if not release_date or len(release_date) < 10:
        return None
    try:
        date = datetime.strptime(release_date[:10], "%Y-%m-%d").date()
        today = datetime.now().date()
        delta = (today - date).days
        if delta == 0:
            return "今日上映"
        elif 1 <= delta <= 7:
            return "热映中"
        elif delta > 7:
            return "长线放映"
        return None
    except ValueError:
        return None


def get_status_style(tag: str) -> tuple:
    """返回 (背景色, 前景色) 配置。"""
    styles = {
        "今日上映":      ("#E53E3E", "white"),
        "热映中":       ("#38A169", "white"),
        "长线放映":     ("#4299E1", "white"),
    }
    if tag.startswith("即将上映"):
        return ("#ED8936", "white")
    return styles.get(tag, ("#999999", "white"))


def sort_movies(movies: list[dict]) -> list[dict]:
    """按上映日期降序排列，同日按票房降序。
    入口处校验数据合法性。
    """
    # 数据校验 + 过滤
    valid = [m for m in movies if _validate_movie(m)]
    invalid_count = len(movies) - len(valid)
    if invalid_count > 0:
        logger.warning("[VALIDATION] 过滤 %d 条非法电影数据", invalid_count)

    def sort_key(m: dict) -> tuple:
        rd = m.get("release_date", "") or ""
        if rd and len(rd) >= 10:
            try:
                d = datetime.strptime(rd[:10], "%Y-%m-%d").date()
                date_score = d.toordinal()
            except ValueError:
                date_score = 0
        else:
            date_score = 0
        box = m.get("box_office") or 0
        return (-date_score, -box)

    valid.sort(key=sort_key)
    return valid


# ─── 海报组件 ───

class PosterWidget(QLabel):
    """电影海报——本地缓存 → 网络请求 → 渐变背景兜底。"""

    _loaded = pyqtSignal(bytes, int)  # (image_data, movie_id)
    _failed = pyqtSignal(int)         # (movie_id)

    def __init__(self, poster_url: str = "", movie_id: int = 0,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(POSTER_W, POSTER_H)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            "background: #F5F5F5; border-radius: 4px; border: 1px solid #E0E0E0;"
        )
        self._poster_url = poster_url
        self._movie_id = movie_id
        self._loaded.connect(self._on_image_data)
        self._failed.connect(lambda _: self._show_gradient())

        # 1) 尝试本地缓存
        if self._try_cache():
            return

        # 2) 尝试网络请求
        if poster_url:
            self._show_loading()
            self._start_download(poster_url, movie_id)
        else:
            self._show_gradient()

    def _try_cache(self) -> bool:
        """尝试从本地缓存加载海报。"""
        if not self._movie_id:
            return False
        cache_path = _get_cache_path(self._movie_id)
        if os.path.exists(cache_path):
            pix = QPixmap(cache_path)
            if not pix.isNull():
                scaled = pix.scaled(
                    POSTER_W, POSTER_H,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation,
                )
                self.setPixmap(scaled)
                logger.info("[POSTER] 缓存命中: id=%d, path=%s",
                            self._movie_id, cache_path)
                return True
        return False

    def _show_loading(self) -> None:
        """加载中显示浅灰占位。"""
        pix = QPixmap(POSTER_W, POSTER_H)
        pix.fill(QColor("#F0F0F0"))
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor("#CCC"))
        font = QFont("Segoe UI Emoji", 24)
        painter.setFont(font)
        painter.drawText(pix.rect(), Qt.AlignCenter, "🎬")
        painter.end()
        self.setPixmap(pix)

    def _show_gradient(self) -> None:
        """所有方案失败 → 渐变背景 + 首字。"""
        title = ""
        p = self.parent()
        while p:
            if hasattr(p, "movie") and p.movie:
                title = p.movie.get("title", "")
                break
            p = p.parent()

        pix = QPixmap(POSTER_W, POSTER_H)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)

        c1, c2 = random.choice(GRADIENTS)
        grad = QLinearGradient(0, 0, POSTER_W, POSTER_H)
        grad.setColorAt(0.0, QColor(c1))
        grad.setColorAt(1.0, QColor(c2))
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, POSTER_W, POSTER_H, 4, 4)

        if title:
            painter.setPen(Qt.white)
            font = QFont("Microsoft YaHei", POSTER_W // 3, QFont.Bold)
            painter.setFont(font)
            painter.drawText(QRect(0, 0, POSTER_W, POSTER_H),
                             Qt.AlignCenter, title[0])

        painter.setPen(QColor(255, 255, 255, 60))
        painter.drawLine(10, POSTER_H - 20, POSTER_W - 10, POSTER_H - 20)
        painter.end()
        self.setPixmap(pix)

    def _start_download(self, url: str, movie_id: int) -> None:
        """在线程中下载海报（高清URL）。"""
        url = _upgrade_poster_url(url)
        logger.info("[POSTER] 请求: %s", url[:60] + "..." if len(url) > 60 else url)

        def download():
            try:
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
                    "Referer": "https://www.maoyan.com/",
                }
                resp = requests.get(url, headers=headers, timeout=10)
                logger.info("[POSTER] HTTP %s: %s", resp.status_code,
                            url[:50] + "..." if len(url) > 50 else url)

                if resp.status_code == 200 and len(resp.content) > 100:
                    self._loaded.emit(resp.content, movie_id)
                    logger.info("[POSTER] 成功: id=%d, size=%d, HTTP=%d",
                                movie_id, len(resp.content), resp.status_code)
                else:
                    logger.warning("[POSTER] 无效响应: id=%d, HTTP=%d, size=%d",
                                   movie_id, resp.status_code, len(resp.content))
                    self._failed.emit(movie_id)
            except Exception as e:
                logger.warning("[POSTER] 下载异常: id=%d, err=%s", movie_id, e)
                self._failed.emit(movie_id)

        threading.Thread(target=download, daemon=True).start()

    def _on_image_data(self, data: bytes, movie_id: int) -> None:
        """主线程接收图片数据并更新 UI。"""
        pix = QPixmap()
        if pix.loadFromData(data):
            scaled = pix.scaled(
                POSTER_W, POSTER_H,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            self.setPixmap(scaled)

            # 写入本地缓存
            if movie_id:
                cache_path = _get_cache_path(movie_id)
                scaled.save(cache_path, "JPG", quality=85)
                logger.info("[POSTER] 已缓存: %s", cache_path)

    def update_poster(self, poster_url: str, movie_id: int = 0) -> None:
        """更新海报（支持复用组件）。"""
        self._poster_url = poster_url
        self._movie_id = movie_id

        if self._try_cache():
            return

        if poster_url:
            self._show_loading()
            self._start_download(poster_url, movie_id)
        else:
            self._show_gradient()


class StatusBadge(QLabel):
    """上映状态标签——自适应宽度。"""

    def __init__(self, tag: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        bg, fg = get_status_style(tag)
        self.setText(tag)
        self.setAlignment(Qt.AlignCenter)
        font = QFont("Microsoft YaHei", 9, QFont.Bold)
        self.setFont(font)
        fm = QFontMetrics(font)
        tw = fm.horizontalAdvance(tag) + 14
        self.setFixedSize(max(tw, 48), 22)
        self.setStyleSheet(
            f"background: {bg}; color: {fg}; border-radius: 4px;"
            f"padding: 0 4px;"
        )


class MovieCard(QFrame):
    """电影卡片（含状态标签 + 实时票价）。"""

    clicked = pyqtSignal(int)
    price_ready = pyqtSignal(object)  # float or None

    def __init__(self, movie: dict, rank: int = 0,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.movie = movie
        self.rank = rank

        # 🔍 诊断：票价字段原始值
        raw_price = movie.get("ticket_price", movie.get("price"))
        print(f"[PRICE_FIELD] movie_id={movie.get('id')} "
              f"title={movie.get('title','?')} "
              f"raw_price={repr(raw_price)} "
              f"type={type(raw_price).__name__}")
        # 🔍 诊断：演员字段
        actors_raw = movie.get("actors", "")
        print(f"[CAST_FIELD] title={movie.get('title','?')} "
              f"actors_raw={repr(actors_raw[:60])}")

        self.setObjectName("movieCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "QFrame#movieCard { background: white; border-radius: 8px; "
            "border: 1px solid #E8E8E8; }"
            "QFrame#movieCard:hover { border: 1px solid #BDBDBD; }"
        )
        self._price_label_ref: Optional[QLabel] = None
        self.price_ready.connect(self._on_price_result)
        self._setup_ui()
        self._start_price_fetch()

    def _on_price_result(self, value) -> None:
        """更新票价显示（主线程）。"""
        if self._price_label_ref is None:
            return
        if value and isinstance(value, (int, float)) and value > 0:
            self._price_label_ref.setText(f"🎫 票价 ¥{value:.0f} 起")
            self._price_label_ref.setStyleSheet("color: #E53E3E;")
        else:
            self._price_label_ref.setText("🎫 暂无票价")
            self._price_label_ref.setStyleSheet("color: #999;")

    def _start_price_fetch(self) -> None:
        """异步获取实时票价（先用title搜索H5正确ID）。"""
        maoyan_id = str(self.movie.get("maoyan_id", "") or "")
        if not maoyan_id or not maoyan_id.isdigit() or len(maoyan_id) < 5:
            return

        movie_title = self.movie.get("title", "")

        def task():
            import time as _time
            _time.sleep(0.3)
            result = [None]

            def _fetch():
                try:
                    result[0] = AGGREGATOR.get_ticket_price(maoyan_id, movie_title=movie_title)
                except Exception:
                    pass

            t = threading.Thread(target=_fetch, daemon=True)
            t.start()
            t.join(timeout=8.0)

            if t.is_alive():
                logger.info("[PRICE] get_ticket_price: %s 超时", maoyan_id)
                self.price_ready.emit(None)
            else:
                self.price_ready.emit(result[0])

        threading.Thread(target=task, daemon=True).start()

    def mousePressEvent(self, event) -> None:
        mid = self.movie.get("id", 0)
        if mid:
            self.clicked.emit(mid)
        super().mousePressEvent(event)

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 16, 12)
        layout.setSpacing(16)

        # 海报
        poster_url = self.movie.get("poster_url", "")
        movie_id = self.movie.get("id", 0)
        poster = PosterWidget(poster_url=poster_url, movie_id=movie_id)
        layout.addWidget(poster)

        # 信息区
        info = QVBoxLayout()
        info.setSpacing(4)

        title = self.movie.get("title", "未知")

        # 标题行 + 状态标签
        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        title_label = QLabel(title)
        title_label.setFont(QFont("Microsoft YaHei", 15, QFont.Bold))
        title_label.setStyleSheet("color: #333;")
        title_row.addWidget(title_label)

        # 状态标签
        release_date = self.movie.get("release_date", "")
        showing_status = self.movie.get("showing_status", "showing")
        tag = get_status_tag(release_date, showing_status)
        if tag:
            title_row.addWidget(StatusBadge(tag))
        title_row.addStretch()
        info.addLayout(title_row)

        # 演员
        actors = self.movie.get("actors", "")
        if actors:
            actor_list = actors.split(";")[:3]
            actor_label = QLabel(f"主演: {' / '.join(actor_list)}")
            actor_label.setFont(QFont("Microsoft YaHei", 11))
            actor_label.setStyleSheet("color: #666;")
            actor_label.setWordWrap(True)
            info.addWidget(actor_label)

        # 类型/年份
        genre = self.movie.get("genre", "")
        year = (self.movie.get("release_date") or "")[:4]
        tags_text = " / ".join(filter(None, [genre, year]))
        if tags_text:
            tags_label = QLabel(tags_text)
            tags_label.setFont(QFont("Microsoft YaHei", 11))
            tags_label.setStyleSheet("color: #999;")
            info.addWidget(tags_label)

        # 评分 · 票房
        rating = self.movie.get("rating") or 0
        rating_count = self.movie.get("rating_count") or 0
        box_office = self.movie.get("box_office") or 0

        meta_parts = []
        if rating > 0:
            meta_parts.append(f"猫眼评分 {rating:.1f}")
        if box_office > 0:
            meta_parts.append(f"累计票房 {box_office:,.0f} 万")
        if rating_count > 0:
            meta_parts.append(f"{rating_count:,} 人评")

        if meta_parts:
            meta_label = QLabel(" · ".join(meta_parts))
            meta_label.setFont(QFont("Microsoft YaHei", 11))
            meta_label.setStyleSheet("color: #795548;")
            info.addWidget(meta_label)

        # 票价行 — raw_price=0.0(无数据) → 直接删除不显示
        # 诊断: [PRICE_FIELD] raw_price=0.0 type=float, 票价接口全返回空
        # 结论: 数据层无有效票价, 删除该QLabel
        self._price_label_ref = None
        # (如需恢复: 取消注释下方代码)
        # price_label = QLabel("🎫 暂无票价")
        # price_label.setFont(QFont("Microsoft YaHei", 11))
        # price_label.setStyleSheet("color: #999;")
        # info.addWidget(price_label)

        # 推荐理由
        reason = self.movie.get("recommendation_reason", "")
        if reason:
            reason_row = QHBoxLayout()
            reason_row.setSpacing(6)

            reason_label = QLabel(reason)
            reason_label.setFont(QFont("Microsoft YaHei", 11))
            reason_label.setStyleSheet(
                "color: #1E88E5; background: #E3F2FD; "
                "padding: 4px 8px; border-radius: 4px;"
            )
            reason_label.setWordWrap(True)
            reason_row.addWidget(reason_label, 1)

            info.addLayout(reason_row)

        info.addStretch()
        layout.addLayout(info, 1)


class RecommendationPage(QWidget):
    """推荐页面——5 个榜单各有独立排序逻辑 + 数据可用性标注。"""

    navigation_requested = pyqtSignal(int)

    MODES = [
        ("comprehensive", "综合推荐"),
        ("hot", "热门推荐"),
        ("high_rating", "高分推荐"),
        ("best_value", "口碑推荐"),
        ("value", "性价比推荐"),
    ]

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db: Optional[DatabaseManager] = None
        self._card_layouts: dict = {}
        self._setup_ui()

    def set_db(self, db: DatabaseManager) -> None:
        self.db = db
        self._load_recommendations(0)

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        title_label = QLabel("电影推荐")
        title_label.setFont(QFont("Microsoft YaHei", 20, QFont.Bold))
        title_label.setStyleSheet("color: #37474F; padding: 20px 24px 0 24px;")
        layout.addWidget(title_label)

        self._count_label = QLabel()
        self._count_label.setFont(QFont("Microsoft YaHei", 12))
        self._count_label.setStyleSheet("color: #38A169; padding: 0 24px;")
        self._count_label.hide()
        layout.addWidget(self._count_label)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("recommendTabs")
        self.tabs.currentChanged.connect(self._load_recommendations)

        for mode_key, mode_name in self.MODES:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setStyleSheet("background: #F5F7FA; border: none;")

            container = QWidget()
            container.setObjectName(f"recContainer_{mode_key}")
            card_layout = QVBoxLayout(container)
            card_layout.setContentsMargins(24, 16, 24, 16)
            card_layout.setSpacing(12)
            card_layout.addStretch()

            self._card_layouts[mode_key] = card_layout
            scroll.setWidget(container)
            self.tabs.addTab(scroll, mode_name)

        layout.addWidget(self.tabs)

    def _load_recommendations(self, tab_index: int) -> None:
        if self.db is None:
            return

        mode_key, _ = self.MODES[tab_index]
        card_layout = self._card_layouts.get(mode_key)
        if card_layout is None:
            return

        # 清空旧卡片
        while card_layout.count() > 1:
            item = card_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        try:
            recommender = Recommender(self.db)
            movies = recommender.recommend(mode=mode_key, limit=50)

            if not movies:
                empty_label = QLabel("暂无在映电影推荐")
                empty_label.setFont(QFont("Microsoft YaHei", 12))
                empty_label.setStyleSheet("color: #757575; padding: 40px;")
                empty_label.setAlignment(Qt.AlignCenter)
                card_layout.insertWidget(0, empty_label)
                self._count_label.hide()
                return

            # 数据校验 + 按上映日期排序
            movies = sort_movies(movies)

            if not movies:
                empty_label = QLabel("暂无符合条件的在映电影推荐")
                empty_label.setFont(QFont("Microsoft YaHei", 12))
                empty_label.setStyleSheet("color: #757575; padding: 40px;")
                empty_label.setAlignment(Qt.AlignCenter)
                card_layout.insertWidget(0, empty_label)
                self._count_label.hide()
                return

            showing_count = len(movies)
            self._count_label.setText(f"✅ 在映电影（共 {showing_count} 部）")
            self._count_label.show()

            for rank, movie in enumerate(movies, 1):
                card = MovieCard(movie, rank=rank)
                card.clicked.connect(self._on_card_clicked)
                card_layout.insertWidget(card_layout.count() - 1, card)

            logger.info("推荐加载完成: mode=%s, %d 条（过滤后）", mode_key, showing_count)

        except Exception as e:
            logger.error("推荐加载失败: %s", e)

    def _on_card_clicked(self, movie_id: int) -> None:
        self.navigation_requested.emit(movie_id)
