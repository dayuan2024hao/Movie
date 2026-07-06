"""
AI 聊天页面 — 简洁专业风格
========================
全屏对话流布局，气泡消息，大字体，电影链接跳转。
无卡通元素，干净现代。
支持外源爬取：不在库的电影自动搜索豆瓣/OMDB。
"""

import logging
import re
import threading
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QLineEdit,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QFont

from database.db_manager import DatabaseManager
from ai_chat.llm_client import chat as llm_chat
from ai_chat.movie_context import build_movie_context, search_movie

logger = logging.getLogger("AIChatPage")

# ── System Prompt ──────────────────────────────────────────
SYSTEM_PROMPT_TPL = """你是"电影票分析系统"的 AI 智能推荐助手，擅长根据用户喜好推荐电影。

## 当前在映电影数据
{context}

## 回复规则
1. 优先推荐列表中存在的电影，给出具体理由（类型匹配、评分、导演风格等）
2. 推荐电影时，电影名请用 **电影名** 格式包裹，例如 **哪吒之魔童闹海**
3. 如果用户需求列表中没有完全匹配的电影，用你的知识推荐并注明"该片暂未收录到本地库"
4. 每次推荐 3-5 部，保持简洁有用
5. 如果用户未指定数量，默认推荐 3 部
"""

MAX_HISTORY_ROUNDS = 10

# ── 字号（大面积提升） ────────────────────────────────────
SZ_BODY = "18px"
SZ_TITLE = "19px"
SZ_RATING = "21px"
SZ_HEADER = "22px"
SZ_INPUT = "17px"
SZ_BTN = "17px"

# ── 配色 ───────────────────────────────────────────────────
USER_BUBBLE_BG = "#1E88E5"
USER_BUBBLE_FG = "white"
AI_BUBBLE_BG  = "#F0F0F0"
AI_BUBBLE_FG  = "#222222"
LINK_COLOR    = "#1E88E5"
RATING_COLOR  = "#E53935"

# ── 外源爬取缓存（线程安全，单例页面） ────────────────────
_crawl_cache: dict[str, dict] = {}


def _crawl_movie_info(title: str) -> Optional[dict]:
    """搜索豆瓣 Suggest API + OMDB，返回电影数据 dict。"""
    import requests

    result: Optional[dict] = None

    # 1) 豆瓣 suggest（中文数据优先）
    try:
        resp = requests.get(
            "https://movie.douban.com/j/subject_suggest",
            params={"q": title},
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            },
            timeout=8,
        )
        if resp.status_code == 200:
            items = resp.json()
            if items:
                item = items[0]
                result = {
                    "title": item.get("title", title),
                    "douban_id": str(item.get("id", "")),
                    "imdb_id": item.get("imdb_id", "") or "",
                    "rating": float(item.get("rating", 0) or 0),
                    "poster_url": item.get("img", "") or "",
                    "year": str(item.get("year", "") or ""),
                    "source": "豆瓣",
                }
                logger.info("豆瓣爬取成功: %s → %s", title, result["title"])
    except Exception as e:
        logger.debug("豆瓣爬取失败 %s: %s", title, e)

    # 2) OMDB 补充（如果有 imdb_id 则获取完整信息）
    if result and result.get("imdb_id"):
        try:
            from crawler.omdb_api import OMDBApi
            api = OMDBApi()
            detail = api.fetch_by_imdb_id(result["imdb_id"])
            if detail:
                app = detail.to_app_format()
                # 合并 OMDB 数据（不覆盖豆瓣已有字段）
                for k, v in app.items():
                    if v and not result.get(k):
                        result[k] = v
                result.setdefault("source", "豆瓣+OMDB")
                logger.info("OMDB 补充成功: %s", result["imdb_id"])
        except Exception as e:
            logger.debug("OMDB 补充失败 %s: %s", title, e)

    if not result:
        logger.info("外源未找到: %s", title)

    return result


# ── 单条消息气泡 ───────────────────────────────────────────

class _MessageWidget(QFrame):
    """一条聊天消息：左侧 AI 气泡 / 右侧用户气泡。"""

    movie_clicked = pyqtSignal(object)   # int(movie_id) 或 str("crawl:title")

    def __init__(self, html_content: str, is_user: bool, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent; border: none;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 8, 24, 8)
        layout.setSpacing(0)

        self._bubble = QLabel()
        self._bubble.setWordWrap(True)
        self._bubble.setOpenExternalLinks(False)
        self._bubble.setTextFormat(Qt.RichText)
        self._bubble.setMaximumWidth(720)
        self._bubble.linkActivated.connect(self._on_link)

        if is_user:
            layout.addStretch(1)
            self._bubble.setStyleSheet(
                "QLabel {"
                "  background: " + USER_BUBBLE_BG + ";"
                "  color: " + USER_BUBBLE_FG + ";"
                "  padding: 16px 26px;"
                "  border-radius: 12px;"
                "  font-size: " + SZ_BODY + ";"
                "  line-height: 1.7;"
                "}"
            )
            self._bubble.setText(html_content)
            layout.addWidget(self._bubble)
        else:
            self._bubble.setStyleSheet(
                "QLabel {"
                "  background: " + AI_BUBBLE_BG + ";"
                "  color: " + AI_BUBBLE_FG + ";"
                "  padding: 16px 26px;"
                "  border-radius: 12px;"
                "  font-size: " + SZ_BODY + ";"
                "  line-height: 1.7;"
                "}"
            )
            self._bubble.setText(html_content)
            layout.addWidget(self._bubble)
            layout.addStretch(1)

    def _on_link(self, url: str) -> None:
        if url.startswith("mid:"):
            try:
                self.movie_clicked.emit(int(url[4:]))
            except ValueError:
                pass
        elif url.startswith("crawl:"):
            self.movie_clicked.emit(url)   # 透传 "crawl:电影名"


# ── 格式化 AI 回复 ─────────────────────────────────────────

def _format_ai_reply(text: str, db: Optional[DatabaseManager]) -> str:
    """将 AI 原始回复转为富文本 HTML：
    - **电影名** → 可点击蓝色链接（先查库，未找到则爬取）
    - 评分数字 → 加粗放大标红
    """
    if not text:
        return ""

    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    parts = re.split(r"(\*\*.+?\*\*)", text)
    out = []
    for part in parts:
        m = re.match(r"\*\*(.+?)\*\*", part)
        if m:
            name = m.group(1)
            href = ""

            # ① 先查本地库
            if db:
                mv = search_movie(name, db)
                if mv:
                    href = f"mid:{mv['id']}"

            # ② 未命中 → 爬取外源
            if not href:
                crawled = _crawl_movie_info(name)
                if crawled:
                    _crawl_cache[name] = crawled
                    href = f"crawl:{name}"

            if href:
                out.append(
                    '<a href="' + href + '" style="'
                    'font-size: ' + SZ_TITLE + '; font-weight: bold; '
                    'color: ' + LINK_COLOR + '; text-decoration: underline;">'
                    + esc(name) + '</a>'
                )
            else:
                out.append(
                    '<span style="font-size: ' + SZ_TITLE + '; '
                    'font-weight: bold; color: #999;">'
                    + esc(name) + '</span>'
                )
        else:
            line = esc(part)
            line = re.sub(
                r'(\b\d{1,2}\.\d\b)',
                r'<span style="font-size: ' + SZ_RATING + '; '
                r'font-weight: bold; color: ' + RATING_COLOR + ';">\1</span>',
                line,
            )
            out.append(line)

    result = "".join(out).replace("\n", "<br>")
    return result


# ── 欢迎消息 ─────────────────────────────────────────────

WELCOME_HTML = (
    '<div style="text-align: center; padding: 32px 0 12px;">'
    '<div style="font-size: ' + SZ_HEADER + '; font-weight: bold; '
    'color: #333; margin-bottom: 12px;">AI 智能推荐</div>'
    '<div style="font-size: ' + SZ_BODY + '; color: #999; '
    'line-height: 2.2;">'
    '描述你的观影偏好，AI 将为你推荐电影<br><br>'
    '<span style="color: #666;">例如：推荐一部高分科幻片</span><br>'
    '<span style="color: #666;">例如：有没有评分高的国产动画？</span><br>'
    '<span style="color: #666;">例如：票价不超过 50 块的喜剧</span>'
    '</div></div>'
)


# ── 主页面 ─────────────────────────────────────────────────

class AIChatPage(QWidget):
    """AI 智能推荐聊天页面。"""

    navigation_requested     = pyqtSignal(int)   # DB movie_id
    external_movie_requested = pyqtSignal(object) # dict → show_movie_data
    _ai_response_ready       = pyqtSignal(str, bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db: Optional[DatabaseManager] = None
        self._messages: list[dict] = []
        self._sending = False
        self._setup_ui()
        self._connect_signals()

    def set_db(self, db: DatabaseManager) -> None:
        self.db = db

    # ──────────────── UI 构建 ────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ═══ 顶部标题栏 ═══
        self._title_bar = QFrame()
        self._title_bar.setFixedHeight(64)
        self._title_bar.setStyleSheet(
            "QFrame { background: white; border-bottom: 1px solid #E8ECF0; }"
        )
        tl = QHBoxLayout(self._title_bar)
        tl.setContentsMargins(28, 0, 28, 0)
        title_label = QLabel("AI 智能推荐")
        title_label.setFont(QFont("Microsoft YaHei", 22, QFont.Bold))
        title_label.setStyleSheet("color: #333;")
        tl.addWidget(title_label)
        tl.addStretch()
        layout.addWidget(self._title_bar)

        # ═══ 中央消息区域 ═══
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setStyleSheet(
            "QScrollArea { background: #F5F6F7; border: none; }"
            "QScrollBar:vertical { width: 8px; }"
            "QScrollBar::handle:vertical { background: #CCC; border-radius: 4px; min-height: 40px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

        self._scroll_content = QWidget()
        self._scroll_content.setStyleSheet("background: transparent;")
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setContentsMargins(0, 12, 0, 12)
        self._scroll_layout.setSpacing(0)
        self._scroll_layout.addStretch(1)

        self._scroll.setWidget(self._scroll_content)
        layout.addWidget(self._scroll, 1)

        # ═══ 底部 loading 指示 ═══
        self._loading_bar = QFrame()
        self._loading_bar.setFixedHeight(40)
        self._loading_bar.setStyleSheet(
            "QFrame { background: #F5F6F7; border: none; }"
        )
        lb_l = QHBoxLayout(self._loading_bar)
        lb_l.setContentsMargins(28, 0, 20, 6)
        self._loading_label = QLabel("AI 正在思考...")
        self._loading_label.setFont(QFont("Microsoft YaHei", 15))
        self._loading_label.setStyleSheet("color: #999;")
        lb_l.addWidget(self._loading_label)
        lb_l.addStretch()
        self._loading_bar.hide()
        layout.addWidget(self._loading_bar)

        # ═══ 底部输入区 ═══
        self._input_frame = QFrame()
        self._input_frame.setStyleSheet(
            "QFrame { background: white; border-top: 1px solid #E8ECF0; }"
        )
        self._input_frame.setFixedHeight(80)
        input_layout = QHBoxLayout(self._input_frame)
        input_layout.setContentsMargins(20, 12, 20, 12)
        input_layout.setSpacing(12)

        self._input = QLineEdit()
        self._input.setPlaceholderText("输入你喜欢的电影类型、题材、演员...")
        self._input.setFont(QFont("Microsoft YaHei", 16))
        self._input.setStyleSheet(
            "QLineEdit {"
            "  border: 1px solid #DDD; border-radius: 10px;"
            "  padding: 12px 18px; font-size: " + SZ_INPUT + ";"
            "  background: #F5F6F7;"
            "}"
            "QLineEdit:focus {"
            "  border-color: #1E88E5; background: white;"
            "}"
        )
        self._input.returnPressed.connect(self._send_message)
        input_layout.addWidget(self._input, 1)

        self._send_btn = QPushButton("发送")
        self._send_btn.setFixedSize(90, 50)
        self._send_btn.setCursor(Qt.PointingHandCursor)
        self._send_btn.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        self._send_btn.setStyleSheet(
            "QPushButton {"
            "  background: #1E88E5; color: white;"
            "  border: none; border-radius: 10px;"
            "  font-size: " + SZ_BTN + ";"
            "}"
            "QPushButton:hover { background: #1565C0; }"
            "QPushButton:disabled { background: #BBDEFB; }"
            "QPushButton:pressed { background: #0D47A1; }"
        )
        self._send_btn.clicked.connect(self._send_message)
        input_layout.addWidget(self._send_btn)

        layout.addWidget(self._input_frame)

        # 显示欢迎
        self._add_welcome()

    def _connect_signals(self) -> None:
        self._ai_response_ready.connect(self._on_ai_response)

    # ──────────────── 消息管理 ────────────────

    def _add_welcome(self) -> None:
        w = QLabel(WELCOME_HTML)
        w.setWordWrap(True)
        w.setTextFormat(Qt.RichText)
        w.setStyleSheet("background: transparent; padding: 0 24px;")
        self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, w)

    def _add_message(self, html: str, is_user: bool) -> _MessageWidget:
        w = _MessageWidget(html, is_user)
        w.movie_clicked.connect(self._on_movie_clicked)
        self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, w)
        QTimer.singleShot(60, self._scroll_to_bottom)
        return w

    def _scroll_to_bottom(self) -> None:
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_movie_clicked(self, data: object) -> None:
        """处理电影点击：int → DB 详情；str(crawl:…) → 外源数据详情。"""
        if isinstance(data, int):
            self.navigation_requested.emit(data)
        elif isinstance(data, str) and data.startswith("crawl:"):
            title = data[6:]
            movie_data = _crawl_cache.get(title)
            if movie_data:
                logger.info("外源电影跳转: %s → %s", title, movie_data.get("title"))
                self.external_movie_requested.emit(movie_data)
            else:
                logger.warning("外源缓存未找到: %s", title)

    # ──────────────── 发送消息 ────────────────

    def _send_message(self) -> None:
        text = self._input.text().strip()
        if not text or self._sending:
            return

        self._input.clear()
        self._set_sending_state(True)

        escaped = self._escape_html(text)
        user_html = '<span style="font-size: ' + SZ_BODY + ';">' + escaped + '</span>'
        self._add_message(user_html, is_user=True)

        self._messages.append({"role": "user", "content": text})

        threading.Thread(
            target=self._do_llm_call,
            args=(list(self._messages),),
            daemon=True,
        ).start()

    def _do_llm_call(self, history: list[dict]) -> None:
        try:
            ctx = build_movie_context(self.db) if self.db else "【暂无数据库】"
            system_prompt = SYSTEM_PROMPT_TPL.format(context=ctx)
            msgs = [{"role": "system", "content": system_prompt}] + history

            if len(msgs) > MAX_HISTORY_ROUNDS * 2 + 1:
                msgs = [msgs[0]] + msgs[-(MAX_HISTORY_ROUNDS * 2):]

            reply = llm_chat(msgs)

            if reply and (reply[0] in ("⚠", "⏱", "🔌", "🔑", "❌", "⏳")):
                self._ai_response_ready.emit(reply, True)
                return

            formatted = _format_ai_reply(reply, self.db)
            self._messages.append({"role": "assistant", "content": reply})
            self._ai_response_ready.emit(formatted, False)

        except Exception as e:
            logger.error("LLM 调用异常: %s", e)
            self._ai_response_ready.emit(f"处理异常: {e}", True)

    def _on_ai_response(self, html: str, is_error: bool) -> None:
        self._set_sending_state(False)
        if is_error:
            html = (
                '<span style="font-size: ' + SZ_BODY + '; '
                'color: #E53935;">' + self._escape_html(html) + '</span>'
            )
        self._add_message(html, is_user=False)

    # ──────────────── UI 状态 ────────────────

    def _set_sending_state(self, sending: bool) -> None:
        self._sending = sending
        self._send_btn.setEnabled(not sending)
        self._input.setEnabled(not sending)
        self._loading_bar.setVisible(sending)
        if not sending:
            self._input.setFocus()

    # ──────────────── 工具 ────────────────

    @staticmethod
    def _escape_html(text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def refresh_context(self) -> None:
        from ai_chat.movie_context import invalidate_cache
        invalidate_cache()
