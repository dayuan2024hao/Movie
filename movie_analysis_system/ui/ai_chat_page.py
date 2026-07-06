"""
AI 聊天页面 — 简洁专业风格
========================
全屏对话流布局，气泡消息，大字体，电影链接跳转。
无卡通元素，干净现代。
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

# ── 字号常量 ───────────────────────────────────────────────
SZ_BODY = "16px"
SZ_TITLE = "17px"
SZ_RATING = "18px"
SZ_HEADER = "20px"
SZ_INPUT = "16px"

# ── 配色 ───────────────────────────────────────────────────
USER_BUBBLE_BG = "#1E88E5"
USER_BUBBLE_FG = "white"
AI_BUBBLE_BG = "#F0F0F0"
AI_BUBBLE_FG = "#222222"
LINK_COLOR = "#1E88E5"
RATING_COLOR = "#E53935"

# ── 单条消息气泡 ───────────────────────────────────────────

class _MessageWidget(QFrame):
    """一条聊天消息：左侧 AI 气泡 / 右侧用户气泡。"""

    movie_clicked = pyqtSignal(int)

    def __init__(self, html_content: str, is_user: bool, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent; border: none;")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 6, 20, 6)
        layout.setSpacing(0)

        self._bubble = QLabel()
        self._bubble.setWordWrap(True)
        self._bubble.setOpenExternalLinks(False)
        self._bubble.setTextFormat(Qt.RichText)
        self._bubble.setMaximumWidth(640)
        self._bubble.linkActivated.connect(self._on_link)

        if is_user:
            # ── 用户：右对齐，蓝底白字 ──
            layout.addStretch(1)
            self._bubble.setStyleSheet(
                "QLabel {"
                "  background: " + USER_BUBBLE_BG + ";"
                "  color: " + USER_BUBBLE_FG + ";"
                "  padding: 14px 22px;"
                "  border-radius: 10px;"
                "  font-size: " + SZ_BODY + ";"
                "  line-height: 1.7;"
                "}"
            )
            self._bubble.setText(html_content)
            layout.addWidget(self._bubble)
        else:
            # ── AI：左对齐，灰底深字（无头像） ──
            self._bubble.setStyleSheet(
                "QLabel {"
                "  background: " + AI_BUBBLE_BG + ";"
                "  color: " + AI_BUBBLE_FG + ";"
                "  padding: 14px 22px;"
                "  border-radius: 10px;"
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


# ── 格式化 AI 回复 ─────────────────────────────────────────

def _format_ai_reply(text: str, db: Optional[DatabaseManager]) -> str:
    """将 AI 原始回复转为富文本 HTML：
    - **电影名** → 可点击蓝色链接
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
            if db:
                mv = search_movie(name, db)
                if mv:
                    href = f"mid:{mv['id']}"
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
                    'font-weight: bold; color: #333;">'
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
    '<div style="text-align: center; padding: 28px 0 10px;">'
    '<div style="font-size: ' + SZ_HEADER + '; font-weight: bold; '
    'color: #333; margin-bottom: 10px;">AI 智能推荐</div>'
    '<div style="font-size: ' + SZ_BODY + '; color: #999; '
    'line-height: 2.0;">'
    '描述你的观影偏好，AI 将为你推荐电影<br><br>'
    '<span style="color: #666;">例如：推荐一部高分科幻片</span><br>'
    '<span style="color: #666;">例如：有没有评分高的国产动画？</span><br>'
    '<span style="color: #666;">例如：票价不超过 50 块的喜剧</span>'
    '</div></div>'
)


# ── 主页面 ─────────────────────────────────────────────────

class AIChatPage(QWidget):
    """AI 智能推荐聊天页面。"""

    navigation_requested = pyqtSignal(int)
    _ai_response_ready = pyqtSignal(str, bool)   # (html, is_error)

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
        self._title_bar.setFixedHeight(56)
        self._title_bar.setStyleSheet(
            "QFrame { background: white; border-bottom: 1px solid #E8ECF0; }"
        )
        tl = QHBoxLayout(self._title_bar)
        tl.setContentsMargins(24, 0, 24, 0)
        title_label = QLabel("AI 智能推荐")
        title_label.setFont(QFont("Microsoft YaHei", 20, QFont.Bold))
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
            "QScrollBar:vertical { width: 6px; }"
            "QScrollBar::handle:vertical { background: #CCC; border-radius: 3px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

        self._scroll_content = QWidget()
        self._scroll_content.setStyleSheet("background: transparent;")
        self._scroll_layout = QVBoxLayout(self._scroll_content)
        self._scroll_layout.setContentsMargins(0, 8, 0, 8)
        self._scroll_layout.setSpacing(0)
        self._scroll_layout.addStretch(1)

        self._scroll.setWidget(self._scroll_content)
        layout.addWidget(self._scroll, 1)

        # ═══ 底部 loading 指示 ═══
        self._loading_bar = QFrame()
        self._loading_bar.setFixedHeight(36)
        self._loading_bar.setStyleSheet(
            "QFrame { background: #F5F6F7; border: none; }"
        )
        lb_l = QHBoxLayout(self._loading_bar)
        lb_l.setContentsMargins(24, 0, 20, 4)
        self._loading_label = QLabel("AI 正在思考...")
        self._loading_label.setFont(QFont("Microsoft YaHei", 14))
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
        self._input_frame.setFixedHeight(68)
        input_layout = QHBoxLayout(self._input_frame)
        input_layout.setContentsMargins(16, 12, 16, 12)
        input_layout.setSpacing(10)

        self._input = QLineEdit()
        self._input.setPlaceholderText("输入你喜欢的电影类型、题材、演员...")
        self._input.setFont(QFont("Microsoft YaHei", 15))
        self._input.setStyleSheet(
            "QLineEdit {"
            "  border: 1px solid #DDD; border-radius: 8px;"
            "  padding: 10px 16px; font-size: " + SZ_INPUT + ";"
            "  background: #F5F6F7;"
            "}"
            "QLineEdit:focus {"
            "  border-color: #1E88E5; background: white;"
            "}"
        )
        self._input.returnPressed.connect(self._send_message)
        input_layout.addWidget(self._input, 1)

        self._send_btn = QPushButton("发送")
        self._send_btn.setFixedSize(80, 44)
        self._send_btn.setCursor(Qt.PointingHandCursor)
        self._send_btn.setFont(QFont("Microsoft YaHei", 15, QFont.Bold))
        self._send_btn.setStyleSheet(
            "QPushButton {"
            "  background: #1E88E5; color: white;"
            "  border: none; border-radius: 8px;"
          "  font-size: " + SZ_INPUT + ";"
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
        """插入欢迎消息（居中文字，无气泡）。"""
        w = QLabel(WELCOME_HTML)
        w.setWordWrap(True)
        w.setTextFormat(Qt.RichText)
        w.setStyleSheet("background: transparent; padding: 0 20px;")
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

    def _on_movie_clicked(self, movie_id: int) -> None:
        self.navigation_requested.emit(movie_id)

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
