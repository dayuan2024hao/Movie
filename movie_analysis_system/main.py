"""
电影票分析系统入口
==================
启动流程：
  1. 初始化数据库（建表 + 检查数据）
  2. 启动 PyQt5 主窗口
  3. 进入事件循环

用法：
    python main.py
"""

import sys
import logging
import os

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont

# Windows GBK 控制台兼容：设置 stdout 编码为 utf-8
if sys.platform == "win32" and sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        os.environ["PYTHONIOENCODING"] = "utf-8"

# 将项目根目录加入模块搜索路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


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

    # 后台静默爬取热映电影（仅在窗口显示后触发）
    from crawler.crawl_controller import CrawlController
    controller = CrawlController(db)

    def crawl_progress(current: int, total: int, message: str) -> None:
        """爬虫进度回调，更新状态栏。"""
        if total > 0 and current < total:
            window.statusBar().showMessage(
                f"正在获取热映电影数据 ({current}/{total}): {message}"
            )
        else:
            window.statusBar().showMessage(f"热映数据更新完成: {message}")

    controller.crawl_showing_movies(
        progress_callback=crawl_progress,
        background=True,
    )

    logger.info("主窗口已显示")
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
