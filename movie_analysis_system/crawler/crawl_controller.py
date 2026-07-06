"""
爬虫控制器
==========
开机时自动执行，也支持手动触发重新爬取。

流程：
  1. 爬取猫眼桌面站 → 实时热映+即将上映列表
  2. 对每部电影 → 写入数据库
  3. 旧数据标记为 released（已下映）
  4. 记录爬取日志到 crawl_record 表
"""

import logging
import threading
import time
from datetime import datetime
from typing import Callable, Optional

from database.db_manager import DatabaseManager
from crawler.maoyan_spider import MaoyanSpider

logger = logging.getLogger("CrawlController")

ProgressCallback = Callable[[int, int, str], None]


class CrawlController:
    """爬虫控制器，管理自动/手动爬取 + 状态追踪。"""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db
        self._running = False
        self._last_result: Optional[bool] = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_result(self) -> Optional[bool]:
        """最近一次爬取结果: True=成功, False=失败, None=未运行。"""
        return self._last_result

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
            logger.warning("[CRAWL] 爬取已在进行中，跳过重复请求")
            if progress_callback:
                progress_callback(0, 1, "爬取正在进行中...")
            return

        target = self._task
        if background:
            threading.Thread(target=target, args=(progress_callback,), daemon=True).start()
        else:
            target(progress_callback)

    def stop(self) -> None:
        """停止爬取（标记位方式）。"""
        self._running = False
        logger.info("[CRAWL] 已请求停止")

    def _task(self, progress_callback: Optional[ProgressCallback]) -> None:
        """主爬取任务。"""
        self._running = True
        self._last_result = False
        start_time = time.time()
        success = False
        total_records = 0
        error_msg = ""

        try:
            # ── 阶段1：爬取猫眼热映列表 ──
            if progress_callback:
                progress_callback(0, 1, "正在从猫眼获取热映电影...")

            spider = MaoyanSpider()
            try:
                showing = spider.get_showing_list(limit=30)
                coming = spider.get_coming_list(limit=10)
            finally:
                spider.close()

            all_movies = showing + coming

            if not all_movies:
                logger.warning("[CRAWL] 猫眼无数据，跳过")
                self._record_log("maoyan", "failed", 0, "猫眼返回空列表")
                return

            total = len(all_movies)
            logger.info("[CRAWL] 猫眼列表: %d 部 (热映%d + 即将%d)",
                        total, len(showing), len(coming))

            # ── 阶段2：写入数据库 ──
            for idx, movie in enumerate(all_movies):
                title = movie.get("title", "未知")
                if progress_callback:
                    progress_callback(idx, total, f"正在保存: {title}")

                movie["showing_status"] = (
                    "showing" if movie in showing else "coming_soon"
                )

                try:
                    self.db.insert_movie(movie)
                    total_records += 1
                except Exception as e:
                    logger.warning("[CRAWL] 写入失败 %s: %s", title, e)

            # ── 阶段3：更新 last_crawl_time ──
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                conn = self.db.get_connection()
                c = conn.cursor()
                c.execute(
                    "UPDATE system_config SET value = ? WHERE key = 'last_crawl_time'",
                    (now_str,),
                )
                c.execute(
                    "UPDATE system_config SET value = 'crawler' WHERE key = 'data_source'",
                )
                conn.commit()
                c.close()
            except Exception as e:
                logger.warning("[CRAWL] 更新配置失败: %s", e)

            success = True
            elapsed = time.time() - start_time

            if progress_callback:
                progress_callback(total, total, f"更新完成: {total} 部 ({elapsed:.0f}s)")

            logger.info("[CRAWL] 完成: %d 部, 耗时 %.1fs", total, elapsed)

        except Exception as e:
            error_msg = str(e)
            logger.error("[CRAWL] 失败: %s", e)
        finally:
            self._running = False
            self._last_result = success
            # 记录爬取日志
            status = "success" if success else "failed"
            message = error_msg or f"爬取完成，共 {total_records} 部"
            self._record_log("maoyan", status, total_records, message)

    def _mark_old_released(self, current_movies: list[dict]) -> None:
        """将不在当前列表中的 showing 电影标记为 released。"""
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

    def _record_log(self, source: str, status: str,
                    records_count: int, message: str) -> None:
        """记录爬取日志到 crawl_record 表。"""
        try:
            conn = self.db.get_connection()
            c = conn.cursor()
            c.execute(
                "INSERT INTO crawl_record (source, status, records_count, message, created_at) "
                "VALUES (?, ?, ?, ?, datetime('now','localtime'))",
                (source, status, records_count, message),
            )
            conn.commit()
            c.close()
            logger.info("[CRAWL_LOG] source=%s status=%s records=%d",
                        source, status, records_count)
        except Exception as e:
            logger.warning("[CRAWL_LOG] 写入失败: %s", e)
