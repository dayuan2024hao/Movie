"""
电影票分析系统入口
==================
启动流程：
  1. 清理 __pycache__ 缓存（防止代码修改不生效）
  2. 初始化数据库（建表 + 检查数据）
  3. 启动 PyQt5 主窗口
  4. 进入事件循环

用法：
    python main.py
"""

import sys
import logging
import os
import shutil

# ═══════════════════════════════════════════════════════════
#  缓存清理：删除所有 __pycache__ 目录
#  目的：防止 Python 缓存旧版 .pyc 文件导致代码修改不生效
# ═══════════════════════════════════════════════════════════
def _clean_pycache(root_dir: str) -> None:
    """递归删除指定目录下所有 __pycache__ 文件夹。

    Args:
        root_dir: 起始目录
    """
    removed = 0
    for dirpath, dirnames, _ in os.walk(root_dir):
        if "__pycache__" in dirnames:
            cache_path = os.path.join(dirpath, "__pycache__")
            try:
                shutil.rmtree(cache_path)
                removed += 1
            except PermissionError:
                pass  # 某些 .pyc 可能被占用，跳过
    if removed > 0:
        print(f"[CACHE] 已清理 {removed} 个 __pycache__ 目录")

# ═══════════════════════════════════════════════════════════
#  路径验证：打印当前加载的入口文件绝对路径
#  目的：确认加载的是正确目录下的文件，非缓存副本
# ═══════════════════════════════════════════════════════════
_this_file = os.path.abspath(__file__)
print(f"[ENTRY] 入口文件路径: {_this_file}")
print(f"[ENTRY] 工作目录: {os.getcwd()}")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont

# Windows GBK 控制台兼容：设置 stdout 编码为 utf-8
if sys.platform == "win32" and sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        os.environ["PYTHONIOENCODING"] = "utf-8"

# 将项目根目录加入模块搜索路径
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _PROJECT_ROOT)

# 清理缓存
_clean_pycache(_PROJECT_ROOT)


def setup_logging() -> None:
    """配置全局日志：输出到控制台 + 文件。"""
    # 清除已有 handlers，防止重复
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)

    log_dir = os.path.join(os.path.dirname(__file__), "..", "dev_log")
    os.makedirs(log_dir, exist_ok=True)

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)
    root.addHandler(console_handler)

    # 文件 handler（UTF-8 编码）
    file_handler = logging.FileHandler(
        os.path.join(log_dir, "system.log"), encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)
    root.addHandler(file_handler)

    root.setLevel(logging.INFO)


def main() -> None:
    """系统入口函数。"""
    setup_logging()
    logger = logging.getLogger("Main")
    logger.info("系统启动 ...")

    # 提前导入 QWebEngineView（必须在 QApplication 创建之前）
    from PyQt5.QtWebEngineWidgets import QWebEngineView

    # 创建 QApplication
    app = QApplication(sys.argv)
    app.setFont(QFont("Microsoft YaHei", 12))

    # 初始化数据库
    from database.db_manager import DatabaseManager
    db = DatabaseManager()
    db.init_db()
    db.check_and_migrate()
    data_status = db.get_data_status()
    logger.info("数据库已有 %d 条数据，实时数据由 RealtimeAggregator 提供", data_status["total_movies"])

    # 启动主窗口（传入数据库实例，供看板页面使用）
    from ui.main_window import MainWindow
    window = MainWindow(db=db)
    window.show()

    # 后台静默爬取热映电影（通过信号安全更新 UI）
    from crawler.crawl_controller import CrawlController
    controller = CrawlController(db)

    from PyQt5.QtCore import QMetaObject, Qt, Q_ARG

    def crawl_progress(current: int, total: int, message: str) -> None:
        """爬虫进度回调，通过 QMetaObject 跨线程安全更新状态栏。"""
        QMetaObject.invokeMethod(
            window.statusBar(), "showMessage",
            Qt.QueuedConnection,
            Q_ARG(str, (
                f"正在获取热映电影数据 ({current}/{total}): {message}"
                if total > 0 and current < total
                else f"热映数据更新完成: {message}"
            )),
        )

    controller.crawl_showing_movies(
        progress_callback=crawl_progress,
        background=True,
    )

    logger.info("主窗口已显示")
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
