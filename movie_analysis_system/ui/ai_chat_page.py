"""
AI 聊天页面 — 微信风格重构
========================
全屏对话流布局，气泡消息、电影卡片、大字体、自动滚动。
"""

import logging
import re
import threading
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QLineEdit, QSizePolicy, QApplication,
)
from PyQt5.QtCore import Qt, pyqtSignal, QUrl, QTimer
from PyQt5.QtGui import QFont, QPainter, QColor, QFontMetrics

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

# ── 样式常量 ───────────────────────────────────────────────
BODY_FONT_SIZE = "16px"
TITLE_FONT_SIZE = "17px"
RATING_FONT_SIZE = "18px"
HEADER_FONT_SIZE = "20px"

USER_BUBBLE_COLOR = "#1E88E5"
USER_BUBBLE_TEXT = "white"
AI_BUBBLE_COLOR = "#F0F0F0"
AI_BUBBLE_TEXT = "#222222"
AI_AVATAR_COLOR = "#07C160"

CARD_BORDER = "1px solid #E0E0E0"
CARD_BG = "#FAFBFC"

# ── 圆形头像 ────────────────────────────────────────────────

class _AvatarLabel(QLabel):
    """带背景色的圆角头像标签。"""

    def __init__(self, text: str, bg_color: str, size: int = 40, parent=None):
        super().__init__(text, parent)
        self._bg = bg_color
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setFont(QFont("Segoe UI Emoji", int(size * 0.45)))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(self._bg))
        painter.setPen(Qt.NoPen)
        r = self.rect()
        painter.drawRoundedRect(r, 8, 8)
        super().paintEvent(event)


# ── 单条消息气泡 ───────────────────────────────────────────

class _MessageWidget(QFrame):
    """一条聊天消息：左/AI 或 右/用户 气泡。"""

    movie_clicked = pyqtSignal(int)

    def __init__(self, html_content: str, is_user: bool, parent=None):
        super().__init__(parent)
        self._is_user = is_user
        self.setStyleSheet("_MessageWidget { background: transparent; border: none; }")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 16, 6)
        layout.setSpacing(10)

        # 气泡标签（富文本，支持点击链接）
        self._bubble = QLabel()
        self._bubble.setWordWrap(True)
        self._bubble.setOpenExternalLinks(False)
        self._bubble.setTextFormat(Qt.RichText)
        self._bubble.setMaximumWidth(620)
        self._bubble.linkActivated.connect(self._on_link)

        if is_user:
            # ── 用户消息：右侧蓝底白字 ──
            layout.addStretch(2)
            self._bubble.setStyleSheet(
                "QLabel {"
                "  background: " + USER_BUBBLE_COLOR + ";"
                "  color: " + USER_BUBBLE_TEXT + ";"
                "  padding: 12px 18px;"
                "  border-radius: 10px;"
                "  font-size: " + BODY_FONT_SIZE + ";"
                "  line-height: 1.6;"
                "}"
            )
            self._bubble.setText(html_content)
            layout.addWidget(self._bubble)
        else:
            # ── AI 消息：左侧头像 + 灰色气泡 ──
            avatar = _AvatarLabel("🤖", AI_AVATAR_COLOR, 40)
            layout.addWidget(avatar, 0, Qt.AlignTop)

            self._bubble.setStyleSheet(
                "QLabel {"
                "  background: " + AI_BUBBLE_COLOR + ";"
                "  color: " + AI_BUBBLE_TEXT + ";"
                "  padding: 12px 18px;"
                "  border-radius: 10px;"
                "  font-size: " + BODY_FONT_SIZE + ";"
                "  line-height: 1.6;"
                "}"
            )
            self._bubble.setText(html_content)
            layout.addWidget(self._bubble)

            layout.addStretch(3)

    def _on_link(self, url: str) -> None:
        if url.startswith("mid:"):
            try:
                movie_id = int(url[4:])
                self.movie_clicked.emit(movie_id)
            except ValueError:
                pass


# ── 推荐卡片 HTML 工厂 ────────────────────────────────────

def _make_movie_card_html(movie_name: str, link_href: str) -> str:
    """生成一张推荐电影卡片的 HTML（用于嵌入气泡）。"""
    return (
        '<table width="100%" cellpadding="0" cellspacing="0" '
        'style="margin: 8px 0; border: ' + CARD_BORDER + '; '
        'border-radius: 8px; background: ' + CARD_BG + ';">'
        '<tr><td style="padding: 12px 14px;">'
        '<a href="' + link_href + '" style="'
        'font-size: ' + TITLE_FONT_SIZE + '; font-weight: bold; '
        'color: #1E88E5; text-decoration: none; display: block; '
        'margin-bottom: 4px;">🎬  ' + movie_name + '</a>'
        '</td></tr></table>'
    )


def _format_ai_reply(text: str, db: Optional[DatabaseManager]) -> str:
    """将 AI 原始回复转为增强 HTML：
    - **电影名** → 可点击卡片链接
    - 数字评分 → 加粗放大
    - 普通文本 → 保留换行
    """
    if not text:
        return ""

    # 1) 转义 HTML
    def escape(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 2) 保护 **...** 标记，转义其余部分
    parts = re.split(r"(\*\*.+?\*\*)", text)
    processed = []
    for part in parts:
        m = re.match(r"\*\*(.+?)\*\*", part)
        if m:
            name = m.group(1)
            link_href = ""
            if db:
                movie = search_movie(name, db)
                if movie:
                    link_href = f"mid:{movie['id']}"
            if link_href:
                processed.append(
                    '<a href="' + link_href + '" style="'
                    'font-size: ' + TITLE_FONT_SIZE + '; font-weight: bold; '
                    'color: #1E88E5; text-decoration: underline;">'
                    + escape(name) + '</a>'
                )
            else:
                processed.append(
                    '<span style="font-size: ' + TITLE_FONT_SIZE + '; '
                    'font-weight: bold; color: #333;">'
                    + escape(name) + '</span>'
                )
        else:
            # 3) 高亮评分数字（如 9.5、8.7 等）
            line = escape(part)
            line = re.sub(
                r'(\b\d{1,2}\.\d\b)',
                r'<span style="font-size: ' + RATING_FONT_SIZE + '; '
                r'font-weight: bold; color: #E53935;">\1</span>',
                line,
            )
            processed.append(line)

    result = "".join(processed)
    # 换行 → <br>
    result = result.replace("\n", "<br>")
    return result


# ── 欢迎消息 ─────────────────────────────────────────────

WELCOME_HTML = (
    '<div style="text-align: center; padding: 20px 0;">'
    '<div style="font-size: 36px; margin-bottom: 8px;">🎬</div>'
    '<div style="font-size: ' + HEADER_FONT_SIZE + '; font-weight: bold; '
    'color: #333; margin-bottom: 8px;">AI 智能推荐</div>'
    '<div style="font-size: ' + BODY_FONT_SIZE + '; color: #999; '
    'line-height: 1.8;">'
    '描述你的观影偏好，AI 将为你推荐<br>'
    '试试这样说：<br>'
    '<span style="color: #666;">"推荐一部高分科幻片"</span><br>'
    '<span style="color: #666;">"有没有评分高的国产动画？"</span><br>'
    '<span style="color: #666;">"我想看票价不超过 50 块的喜剧"</span>'
    '</div></div>'
)


# ── 主页面 ─────────────────────────────────────────────────

class AIChatPage(QWidget):
    """AI 智能推荐聊天页面（微信风格）。"""

    navigation_requested = pyqtSignal(int)
    _ai_response_ready = pyqtSignal(str, bool)   # (html, is_error)
    _ai_loading = pyqtSignal(bool)                # True=开始loading

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
        """构建全屏对话流布局。"""
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
        tl.setContentsMargins(20, 0, 20, 0)
        title_label = QLabel("🤖  AI 智能推荐")
        title_label.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))
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

        # 占位 stretch 使消息从顶部开始
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
        lb_l.setContentsMargins(66, 0, 20, 4)
        self._loading_label = QLabel("🤖  AI 正在思考...")
        self._loading_label.setFont(QFont("Microsoft YaHei", 13))
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
        self._input_frame.setFixedHeight(64)
        input_layout = QHBoxLayout(self._input_frame)
        input_layout.setContentsMargins(16, 10, 16, 10)
        input_layout.setSpacing(10)

        self._input = QLineEdit()
        self._input.setPlaceholderText("输入你喜欢的电影类型、题材、演员...")
        self._input.setFont(QFont("Microsoft YaHei", 15))
        self._input.setStyleSheet(
            "QLineEdit {"
            "  border: 1px solid #DDD; border-radius: 8px;"
            "  padding: 10px 16px; font-size: 16px;"
            "  background: #F5F6F7;"
            "}"
            "QLineEdit:focus {"
            "  border-color: #1E88E5; background: white;"
            "}"
        )
        self._input.returnPressed.connect(self._send_message)
        input_layout.addWidget(self._input, 1)

        self._send_btn = QPushButton("发送")
        self._send_btn.setFixedSize(72, 42)
        self._send_btn.setCursor(Qt.PointingHandCursor)
        self._send_btn.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        self._send_btn.setStyleSheet(
            "QPushButton {"
            "  background: #1E88E5; color: white;"
            "  border: none; border-radius: 8px;"
            "}"
            "QPushButton:hover { background: #1565C0; }"
            "QPushButton:disabled { background: #BBDEFB; }"
            "QPushButton:pressed { background: #0D47A1; }"
        )
        self._send_btn.clicked.connect(self._send_message)
        input_layout.addWidget(self._send_btn)

        self._clear_btn = QPushButton("清空")
        self._clear_btn.setFixedSize(60, 42)
        self._clear_btn.setCursor(Qt.PointingHandCursor)
        self._clear_btn.setFont(QFont("Microsoft YaHei", 13))
        self._clear_btn.setStyleSheet(
            "QPushButton {"
            "  background: #F5F6F7; color: #666;"
            "  border: 1px solid #DDD; border-radius: 8px;"
            "}"
            "QPushButton:hover { background: #EEE; color: #333; }"
        )
        self._clear_btn.clicked.connect(self._clear_conversation)
        input_layout.addWidget(self._clear_btn)

        layout.addWidget(self._input_frame)

        # 显示欢迎
        self._add_welcome()

    def _connect_signals(self) -> None:
        self._ai_response_ready.connect(self._on_ai_response)
        self._ai_loading.connect(self._on_loading_changed)

    # ──────────────── 消息管理 ────────────────

    def _add_welcome(self) -> None:
        """插入欢迎消息。"""
        w = _MessageWidget(WELCOME_HTML, is_user=False)
        # 为欢迎消息隐藏头像（用 stretch 占位对齐）
        self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, w)

    def _add_message(self, html: str, is_user: bool) -> _MessageWidget:
        """添加一条消息到对话流。"""
        w = _MessageWidget(html, is_user)
        w.movie_clicked.connect(self._on_movie_clicked)
        self._scroll_layout.insertWidget(self._scroll_layout.count() - 1, w)
        # 自动滚到底
        QTimer.singleShot(60, self._scroll_to_bottom)
        return w

    def _scroll_to_bottom(self) -> None:
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_movie_clicked(self, movie_id: int) -> None:
        logger.info("AI 推荐页跳转到电影详情: id=%d", movie_id)
        self.navigation_requested.emit(movie_id)

    # ──────────────── 发送消息 ────────────────

    def _send_message(self) -> None:
        text = self._input.text().strip()
        if not text or self._sending:
            return

        self._input.clear()
        self._set_sending_state(True)

        # 显示用户消息
        escaped = self._escape_html(text)
        user_html = '<span style="font-size: ' + BODY_FONT_SIZE + ';">' + escaped + '</span>'
        self._add_message(user_html, is_user=True)

        # 存历史
        self._messages.append({"role": "user", "content": text})

        # 后台调用
        threading.Thread(
            target=self._do_llm_call,
            args=(list(self._messages),),
            daemon=True,
        ).start()

    def _do_llm_call(self, history: list[dict]) -> None:
        """后台线程：调用 LLM。"""
        try:
            ctx = build_movie_context(self.db) if self.db else "【暂无数据库】"
            system_prompt = SYSTEM_PROMPT_TPL.format(context=ctx)
            msgs = [{"role": "system", "content": system_prompt}] + history

            if len(msgs) > MAX_HISTORY_ROUNDS * 2 + 1:
                msgs = [msgs[0]] + msgs[-(MAX_HISTORY_ROUNDS * 2):]

            reply = llm_chat(msgs)

            # 判断是否错误
            if reply and (reply[0] in ("⚠", "⏱", "🔌", "🔑", "❌", "⏳")):
                self._ai_response_ready.emit(reply, True)
                return

            # 格式化回复
            formatted = _format_ai_reply(reply, self.db)
            self._messages.append({"role": "assistant", "content": reply})
            self._ai_response_ready.emit(formatted, False)

        except Exception as e:
            logger.error("LLM 调用异常: %s", e)
            self._ai_response_ready.emit(f"❌ 处理异常: {e}", True)

    def _on_ai_response(self, html: str, is_error: bool) -> None:
        """AI 回复就绪（主线程）。"""
        self._set_sending_state(False)
        if is_error:
            html = (
                '<span style="font-size: ' + BODY_FONT_SIZE + '; '
                'color: #E53935;">' + self._escape_html(html) + '</span>'
            )
        self._add_message(html, is_user=False)

    def _on_loading_changed(self, loading: bool) -> None:
        self._loading_bar.setVisible(loading)

    # ──────────────── UI 状态 ────────────────

    def _set_sending_state(self, sending: bool) -> None:
        self._sending = sending
        self._send_btn.setEnabled(not sending)
        self._input.setEnabled(not sending)
        self._loading_bar.setVisible(sending)
        if not sending:
            self._input.setFocus()

    def _clear_conversation(self) -> None:
        """清空对话。"""
        self._messages.clear()
        # 移除所有消息 widget（保留 stretch）
        while self._scroll_layout.count() > 1:
            item = self._scroll_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self._add_welcome()
        self._input.setFocus()
        logger.info("对话已清空")

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
