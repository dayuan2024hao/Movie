"""
AI 聊天页面
===========
基于 DeepSeek 大模型的对话式电影推荐。
支持本地数据上下文、多轮对话、可点击电影名跳转详情。
"""

import logging
import re
import threading
from typing import Optional

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextBrowser, QLineEdit, QScrollArea, QFrame,
)
from PyQt5.QtCore import Qt, pyqtSignal, QUrl
from PyQt5.QtGui import QFont, QTextCursor

from database.db_manager import DatabaseManager
from ai_chat.llm_client import chat as llm_chat
from ai_chat.movie_context import build_movie_context, search_movie

logger = logging.getLogger("AIChatPage")

# System prompt 模板
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

# 保留的最大对话轮数（user + assistant = 1 轮）
MAX_HISTORY_ROUNDS = 10


class AIChatPage(QWidget):
    """AI 智能推荐聊天页面。"""

    # 点击电影名 → 导航到详情
    navigation_requested = pyqtSignal(int)
    # AI 回复就绪（跨线程信号）
    _ai_response_ready = pyqtSignal(str)
    _ai_error = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db: Optional[DatabaseManager] = None
        self._messages: list[dict] = []  # 对话历史（API 格式）
        self._sending = False  # 是否正在发送
        self._setup_ui()
        self._connect_signals()

    def set_db(self, db: DatabaseManager) -> None:
        """设置数据库引用。"""
        self.db = db

    def _setup_ui(self) -> None:
        """构建聊天界面布局。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(0)

        # ═══════════════════════════════════════
        #  页面标题
        # ═══════════════════════════════════════
        title = QLabel("🤖  AI 智能推荐")
        title.setFont(QFont("Microsoft YaHei", 20, QFont.Bold))
        title.setStyleSheet("color: #37474F;")
        title.setFixedHeight(40)
        layout.addWidget(title)

        subtitle = QLabel(
            "描述你的观影偏好，AI 将结合本地数据为你推荐电影"
        )
        subtitle.setFont(QFont("Microsoft YaHei", 12))
        subtitle.setStyleSheet("color: #90A4AE; margin-bottom: 12px;")
        layout.addWidget(subtitle)
        layout.addSpacing(8)

        # ═══════════════════════════════════════
        #  对话展示区
        # ═══════════════════════════════════════
        self._browser = QTextBrowser()
        self._browser.setObjectName("chatBrowser")
        self._browser.setOpenLinks(False)  # 拦截链接点击自行处理
        self._browser.setReadOnly(True)
        self._browser.setStyleSheet(
            "QTextBrowser#chatBrowser {"
            "  background: #FAFBFC;"
            "  border: 1px solid #E8ECF0;"
            "  border-radius: 8px;"
            "  padding: 16px;"
            "  font-size: 14px;"
            "}"
        )
        layout.addWidget(self._browser, 1)

        layout.addSpacing(12)

        # ═══════════════════════════════════════
        #  输入区
        # ═══════════════════════════════════════
        input_frame = QFrame()
        input_frame.setStyleSheet(
            "QFrame { background: white; border: 1px solid #E0E0E0; "
            "border-radius: 8px; }"
        )
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(8, 6, 8, 6)
        input_layout.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText("描述你想看的电影类型、题材、演员...")
        self._input.setFont(QFont("Microsoft YaHei", 13))
        self._input.setStyleSheet(
            "QLineEdit { border: none; padding: 8px 12px; "
            "background: transparent; font-size: 14px; }"
        )
        self._input.returnPressed.connect(self._send_message)
        input_layout.addWidget(self._input, 1)

        self._send_btn = QPushButton("发送")
        self._send_btn.setFixedHeight(36)
        self._send_btn.setCursor(Qt.PointingHandCursor)
        self._send_btn.setStyleSheet(
            "QPushButton { background: #1E88E5; color: white; "
            "border: none; border-radius: 6px; padding: 0 20px; "
            "font-size: 14px; font-weight: bold; }"
            "QPushButton:hover { background: #1565C0; }"
            "QPushButton:disabled { background: #BBDEFB; }"
        )
        self._send_btn.clicked.connect(self._send_message)
        input_layout.addWidget(self._send_btn)

        self._clear_btn = QPushButton("清空对话")
        self._clear_btn.setFixedHeight(36)
        self._clear_btn.setCursor(Qt.PointingHandCursor)
        self._clear_btn.setStyleSheet(
            "QPushButton { background: #F5F5F5; color: #666; "
            "border: 1px solid #DDD; border-radius: 6px; padding: 0 16px; "
            "font-size: 13px; }"
            "QPushButton:hover { background: #EEEEEE; color: #333; }"
        )
        self._clear_btn.clicked.connect(self._clear_conversation)
        input_layout.addWidget(self._clear_btn)

        layout.addWidget(input_frame)

        # 显示欢迎消息
        self._append_welcome()

    def _connect_signals(self) -> None:
        """连接跨线程信号。"""
        self._ai_response_ready.connect(self._on_ai_response)
        self._ai_error.connect(self._on_ai_error)
        self._browser.anchorClicked.connect(self._on_anchor_clicked)

    # ──────────── 欢迎消息 ────────────

    def _append_welcome(self) -> None:
        """显示初始欢迎消息。"""
        welcome = (
            "<div style='margin:8px 0; text-align:center;'>"
            "<div style='display:inline-block; background:#E8F5E9; color:#2E7D32; "
            "padding:14px 20px; border-radius:12px; font-size:14px; max-width:80%;'>"
            "👋 你好！我是 AI 推荐助手。<br><br>"
            "告诉我你想看什么样的电影，例如：<br>"
            "• \"推荐一部高分科幻片\"<br>"
            "• \"有没有评分高的国产动画？\"<br>"
            "• \"我想看票价不超过 50 块的喜剧\"<br>"
            "• \"最近上映的悬疑片有哪些推荐？\""
            "</div></div>"
        )
        self._browser.setHtml(welcome)

    # ──────────── 发送消息 ────────────

    def _send_message(self) -> None:
        """发送用户输入到 AI。"""
        text = self._input.text().strip()
        if not text or self._sending:
            return

        self._input.clear()
        self._set_sending_state(True)

        # 1. 添加用户消息到界面
        user_html = self._format_message(text, is_user=True)
        self._append_html(user_html)

        # 2. 添加到历史
        self._messages.append({"role": "user", "content": text})

        # 3. 在线程中调用 LLM
        threading.Thread(
            target=self._do_llm_call,
            args=(list(self._messages),),
            daemon=True,
        ).start()

    def _do_llm_call(self, history: list[dict]) -> None:
        """在后台线程中执行 LLM 调用。"""
        try:
            # 构建系统提示（含本地电影数据）
            context_text = build_movie_context(self.db) if self.db else "【暂无数据库连接】"
            system_prompt = SYSTEM_PROMPT_TPL.format(context=context_text)

            messages = [{"role": "system", "content": system_prompt}] + history

            # 限制历史长度
            if len(messages) > MAX_HISTORY_ROUNDS * 2 + 1:  # system + N轮
                messages = [messages[0]] + messages[-(MAX_HISTORY_ROUNDS * 2):]

            reply = llm_chat(messages)

            if reply.startswith("⚠️") or reply.startswith("⏱️") or \
               reply.startswith("🔌") or reply.startswith("🔑") or \
               reply.startswith("❌") or reply.startswith("⏳"):
                self._ai_error.emit(reply)
                return

            # 处理回复中的电影名 → 可点击链接
            processed = self._process_movie_links(reply)

            # 添加 assistant 到历史
            self._messages.append({"role": "assistant", "content": reply})

            self._ai_response_ready.emit(processed)

        except Exception as e:
            logger.error("LLM 调用异常: %s", e)
            self._ai_error.emit(f"❌ 处理异常: {e}")

    def _on_ai_response(self, html_content: str) -> None:
        """AI 回复就绪（主线程）。"""
        ai_html = self._format_message(html_content, is_user=False)
        self._append_html(ai_html)
        self._set_sending_state(False)

    def _on_ai_error(self, error_msg: str) -> None:
        """AI 调用出错（主线程）。"""
        err_html = self._format_message(
            f"<span style='color:#E53935;'>{error_msg}</span>",
            is_user=False,
        )
        self._append_html(err_html)
        self._set_sending_state(False)

    # ──────────── 电影链接处理 ────────────

    def _process_movie_links(self, text: str) -> str:
        """将回复中 **电影名** 转为可点击的 HTML 链接。

        Args:
            text: AI 原始回复文本

        Returns:
            处理后的 HTML
        """
        def _replace(m: re.Match) -> str:
            name = m.group(1)
            if not self.db:
                return f"<b>{name}</b>"
            movie = search_movie(name, self.db)
            if movie:
                mid = movie["id"]
                return (
                    f'<a href="mid:{mid}" style="color:#1E88E5; '
                    f'text-decoration:underline; font-weight:bold;">{name}</a>'
                )
            return f"<b>{name}</b>"

        # 转义 HTML 特殊字符，但保留 ** 标记
        # 先把 ** 标记保护起来，再转义其余部分
        parts = re.split(r"(\*\*.+?\*\*)", text)
        escaped_parts = []
        for part in parts:
            if part.startswith("**") and part.endswith("**"):
                escaped_parts.append(part)
            else:
                escaped_parts.append(self._escape_html(part))
        text = "".join(escaped_parts)

        # 替换 **电影名** 为链接
        result = re.sub(r"\*\*(.+?)\*\*", _replace, text)
        # 处理普通换行
        result = result.replace("\n", "<br>")
        return result

    @staticmethod
    def _escape_html(text: str) -> str:
        """转义 HTML 特殊字符。"""
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    def _on_anchor_clicked(self, url: QUrl) -> None:
        """点击链接 → 导航到电影详情。"""
        scheme = url.scheme()
        if scheme == "mid":
            try:
                movie_id = int(url.path())
                logger.info("AI 推荐页跳转到电影详情: id=%d", movie_id)
                self.navigation_requested.emit(movie_id)
            except (ValueError, IndexError):
                logger.warning("无效的电影链接: %s", url.toString())

    # ──────────── UI 辅助方法 ────────────

    def _format_message(self, content: str, is_user: bool) -> str:
        """将消息包装为气泡样式的 HTML。"""
        if is_user:
            return (
                f"<div style='text-align:right; margin:8px 0;'>"
                f"<div style='display:inline-block; background:#E3F2FD; color:#1565C0; "
                f"padding:10px 16px; border-radius:12px 12px 4px 12px; "
                f"font-size:14px; max-width:75%; text-align:left; line-height:1.6;'>"
                f"{content}"
                f"</div></div>"
            )
        else:
            return (
                f"<div style='margin:8px 0;'>"
                f"<div style='display:inline-block; background:#F5F5F5; color:#333; "
                f"padding:10px 16px; border-radius:12px 12px 12px 4px; "
                f"font-size:14px; max-width:85%; text-align:left; line-height:1.6;'>"
                f"{content}"
                f"</div></div>"
            )

    def _append_html(self, html: str) -> None:
        """追加 HTML 到对话浏览器。"""
        cursor = self._browser.textCursor()
        cursor.movePosition(QTextCursor.End)
        # 插入 HTML 块
        cursor.insertHtml(html)
        # 确保新增内容可见
        self._browser.ensureCursorVisible()

    def _set_sending_state(self, sending: bool) -> None:
        """切换发送状态。"""
        self._sending = sending
        self._send_btn.setEnabled(not sending)
        self._input.setEnabled(not sending)
        if sending:
            self._input.setPlaceholderText("AI 思考中...")
        else:
            self._input.setPlaceholderText("描述你想看的电影类型、题材、演员...")
            self._input.setFocus()

    def _clear_conversation(self) -> None:
        """清空对话历史。"""
        self._messages.clear()
        self._browser.clear()
        self._append_welcome()
        self._input.setFocus()
        logger.info("对话已清空")

    def refresh_context(self) -> None:
        """刷新电影上下文（外部调用，例如爬取新数据后）。"""
        from ai_chat.movie_context import invalidate_cache
        invalidate_cache()
        logger.info("AI 聊天电影上下文缓存已刷新")
