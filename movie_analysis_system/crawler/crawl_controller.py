"""
爬虫控制器
==========
开机时自动执行：
  1. 爬取猫眼桌面站 → 实时热映+即将上映列表
  2. 对每部电影 → OMDB 补充简介/评分/类型
  3. 合并写入数据库
  4. 旧数据标记为 released（已下映）
"""

import logging
import threading
import time
from typing import Callable, Optional

from database.db_manager import DatabaseManager
from crawler.maoyan_spider import MaoyanSpider
from crawler.omdb_api import OMDBApi

logger = logging.getLogger("CrawlController")

ProgressCallback = Callable[[int, int, str], None]


class CrawlController:
    """爬虫控制器，管理开机自动爬取 + OMDB 补充。"""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db
        self._running = False

    def crawl_showing_movies(
        self,
        progress_callback: Optional[ProgressCallback] = None,
        background: bool = True,
    ) -> None:
        """启动爬取。

        Args:
            progress_callback: 进度回调
            background: 是否后台执行
        """
        if self._running:
            return
        target = self._task
        if background:
            threading.Thread(target=target, args=(progress_callback,), daemon=True).start()
        else:
            target(progress_callback)

    def stop(self) -> None:
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def _task(self, progress_callback: Optional[ProgressCallback]) -> None:
        """主任务。"""
        self._running = True
        try:
            # ── 阶段1：爬取猫眼热映列表 ──
            if progress_callback:
                progress_callback(0, 1, "正在从猫眼获取热映电影...")

            spider = MaoyanSpider()
            showing = spider.get_showing_list(limit=30)
            coming = spider.get_coming_list(limit=10)
            all_movies = showing + coming
            spider.close()

            if not all_movies:
                logger.warning("[CRAWL] 猫眼无数据，跳过")
                return

            total = len(all_movies)
            logger.info("[CRAWL] 猫眼列表: %d 部 (热映%d + 即将%d)",
                        total, len(showing), len(coming))

            # ── 阶段2：写入数据库（仅写猫眼数据，OMDB等用户在详情页按需获取）──
            for idx, movie in enumerate(all_movies):
                title = movie.get("title", "未知")
                if progress_callback:
                    progress_callback(idx, total, f"正在保存: {title}")

                movie["showing_status"] = (
                    "showing" if movie in showing else "coming_soon"
                )

                try:
                    self.db.insert_movie(movie)
                except Exception as e:
                    logger.warning("[CRAWL] 写入失败 %s: %s", title, e)

            # ── 阶段3：标记旧数据为 released ──
            self._mark_old_released(all_movies)

            if progress_callback:
                progress_callback(total, total, f"更新完成: {total} 部")

            logger.info("[CRAWL] 完成: %d 部", total)

        except Exception as e:
            logger.error("[CRAWL] 失败: %s", e)
        finally:
            self._running = False

    def _mark_old_released(self, current_movies: list[dict]) -> None:
        """将不在当前列表中的 showing 电影标记为 released。

        Args:
            current_movies: 当前爬取到的电影列表
        """
        current_ids = set()
        for m in current_movies:
            mid = m.get("maoyan_id", "")
            if mid:
                current_ids.add(mid)

        if not current_ids:
            return

        try:
            conn = self.db.get_connection()
            c = conn.cursor()
            # 查出数据库中 showing 状态但不在当前列表的电影
            placeholders = ",".join("?" for _ in current_ids)
            c.execute(
                f"UPDATE movies SET showing_status='released', "
                f"updated_at=datetime('now','localtime') "
                f"WHERE showing_status='showing' "
                f"AND maoyan_id NOT IN ({placeholders})",
                list(current_ids),
            )
            affected = c.rowcount
            conn.commit()
            c.close()
            if affected > 0:
                logger.info("[CRAWL] 已标记 %d 部旧电影为 released", affected)
        except Exception as e:
            logger.warning("[CRAWL] 标记旧数据失败: %s", e)
