"""
爬虫控制器
==========
统一调度爬虫任务的后台控制器。

数据合并策略（关键）：
  1. 爬取猫眼当前在映/即将上映列表
  2. 对每部爬取到的电影：
     a. 如数据库中已存在（同名）→ 仅更新爬取到的字段，保留原 rating_count/box_office/price
     b. 如不存在 → 完整插入（含 CSV 备份提供的完整数据）
  3. 再补充 CSV 备份中在映但爬虫未覆盖的电影（保留其完整数据）
  4. 后台尝试 Selenium 详情页爬取（补充评分人数/票房/票价）
"""

import logging
import threading
import time
from typing import Callable, Optional

from database.db_manager import DatabaseManager
from crawler.maoyan_spider import MaoyanSpider
from crawler.maoyan_detail_scraper import scrape_movie_details_sync

logger = logging.getLogger("CrawlController")

ProgressCallback = Callable[[int, int, str], None]

# 爬虫更新的字段列表（不覆盖 rating_count/box_office/ticket_price/summary）
CRAWL_FIELDS = {"title", "genre", "actors", "release_date",
                "poster_url", "rating", "maoyan_id", "showing_status",
                "director", "runtime", "region", "language"}


class CrawlController:
    """爬虫控制器，管理爬虫调度、进度回调和状态记录。"""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ──────────────────── 公开控制方法 ────────────────────

    def crawl_showing_movies(
        self,
        progress_callback: Optional[ProgressCallback] = None,
        background: bool = True,
    ) -> None:
        if self._running:
            logger.warning("爬虫正在运行中，跳过重复请求")
            return
        target = self._crawl_showing_task
        if background:
            self._thread = threading.Thread(
                target=target, args=(progress_callback,), daemon=True
            )
            self._thread.start()
            logger.info("爬虫后台线程已启动")
        else:
            target(progress_callback)

    def stop(self) -> None:
        self._running = False
        logger.info("爬虫已停止")

    @property
    def is_running(self) -> bool:
        return self._running

    # ──────────────────── 主任务 ────────────────────

    def _crawl_showing_task(self, progress_callback: Optional[ProgressCallback]) -> None:
        """后台爬取热映电影的主任务。"""
        self._running = True
        self._record_crawl("maoyan", "running", 0, "开始爬取")

        maoyan = MaoyanSpider()

        try:
            # ---- 阶段 1：翻页爬取列表 ----
            if progress_callback:
                progress_callback(0, 1, "正在从猫眼获取热映电影列表...")
            showing_movies = maoyan.get_showing_list(limit=30)

            if progress_callback:
                progress_callback(0, 1, "正在获取即将上映列表...")
            coming_movies = maoyan.get_coming_list(limit=10)

            all_movies = showing_movies + coming_movies
            total = len(all_movies)

            logger.info("[CRAWL] 列表爬取完成: 热映 %d 部 + 即将上映 %d 部 = %d 部",
                        len(showing_movies), len(coming_movies), total)

            if not all_movies:
                logger.warning("猫眼无数据")
                self._record_crawl("maoyan", "failed", 0, "无数据")
                self._running = False
                return

            # ---- 阶段 2：增量写入（保留已有数据，仅更新爬虫字段） ----
            success_count = 0
            for idx, movie in enumerate(all_movies):
                title = movie.get("title", "未知")
                if progress_callback:
                    progress_callback(idx, total, f"处理: {title}")

                movie.setdefault("showing_status",
                                 "showing" if movie in showing_movies else "coming_soon")
                movie.setdefault("rating", 0.0)

                try:
                    self._upsert_crawl_movie(movie)
                    success_count += 1
                except Exception as e:
                    logger.error("写入失败 %s: %s", title, e)

            logger.info("[CRAWL] 写入完成: %d/%d 成功", success_count, total)

            # ---- 阶段 3：补充 CSV 备份在映电影（含完整数据） ----
            if progress_callback:
                progress_callback(total, total, "正在补充备份数据...")
            csv_count = self._merge_csv_showing_data()
            logger.info("[CRAWL] CSV 备份补充: %d 部", csv_count)

            # ---- 阶段 4：后台爬取详情页（补充评分人数/票房/票价） ----
            showing_ids = [
                m.get("maoyan_id") for m in showing_movies
                if m.get("maoyan_id")
            ]
            if showing_ids:
                if progress_callback:
                    progress_callback(total, total,
                                      f"后台获取 {len(showing_ids)} 部详情数据...")
                self._scrape_details_background(showing_ids)

            # ---- 阶段 5：记录完成 ----
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM movies WHERE showing_status='showing'"
            )
            final_showing = cursor.fetchone()[0]
            cursor.execute(
                "SELECT COUNT(*) FROM movies WHERE showing_status='coming_soon'"
            )
            final_coming = cursor.fetchone()[0]
            cursor.close()

            self._record_crawl(
                "maoyan", "success", success_count,
                f"列表 {success_count}/{total} 部 | "
                f"CSV补充 {csv_count} 部 | "
                f"最终: 热映{final_showing}部/待映{final_coming}部",
            )
            if progress_callback:
                progress_callback(
                    total, total,
                    f"更新完成: 热映{final_showing}部/待映{final_coming}部",
                )

            logger.info("[CRAWL] 全部完成: 写入%d部, CSV补充%d部, "
                        "最终热映%d部/待映%d部",
                        success_count, csv_count, final_showing, final_coming)

        except Exception as e:
            logger.error("爬取失败: %s", e)
            self._record_crawl("maoyan", "failed", 0, str(e))
        finally:
            maoyan.close()
            self._running = False

    # ──────────────────── 增量写入 ────────────────────

    def _upsert_crawl_movie(self, movie: dict) -> None:
        """写入爬取的电影数据（保留数据库中已有的 rating_count/box_office 等）。"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # 检查是否已存在（同名）
            cursor.execute(
                "SELECT * FROM movies WHERE title = ?",
                (movie.get("title", ""),),
            )
            existing = cursor.fetchone()

            if existing:
                # 存在 → 只更新爬虫字段，保留已有数据
                updates = {}
                for field in CRAWL_FIELDS:
                    if field in movie and movie[field] is not None:
                        if field == "rating":
                            # 新评分可能更准确，但保留旧有值（可能来自 CSV 更完整）
                            if movie.get("rating", 0) > 0:
                                updates["rating"] = movie["rating"]
                        else:
                            updates[field] = movie[field]

                # 特殊：poster_url 优先用爬取的
                if movie.get("poster_url"):
                    updates["poster_url"] = movie["poster_url"]

                if updates:
                    set_clause = ", ".join(f"{k} = ?" for k in updates)
                    values = [updates[k] for k in updates]
                    cursor.execute(
                        f"UPDATE movies SET {set_clause}, "
                        f"updated_at = datetime('now','localtime') WHERE title = ?",
                        values + [movie.get("title", "")],
                    )
                conn.commit()
            else:
                # 不存在 → 完整插入
                cursor.close()
                self.db.insert_movie(movie)

        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()

    # ──────────────────── CSV 备份合并 ────────────────────

    def _merge_csv_showing_data(self) -> int:
        """从 CSV 备份补充在映电影的完整数据（评分人数/票房/票价）。

        仅插入爬虫未覆盖的电影，已有同名电影的不重复插入。
        """
        import csv
        import os

        csv_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "data", "backup_movies.csv",
        )
        if not os.path.exists(csv_path):
            return 0

        conn = self.db.get_connection()
        cursor = conn.cursor()
        loaded = 0

        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    status = (row.get("showing_status") or "").strip()
                    if status not in ("showing", "coming_soon"):
                        continue
                    title = (row.get("title") or "").strip()
                    if not title:
                        continue

                    # 检查是否已存在（爬虫已插入）
                    cursor.execute(
                        "SELECT id FROM movies WHERE title = ?", (title,)
                    )
                    if cursor.fetchone():
                        continue  # 已存在，不重复

                    # 不存在 → 插入（含完整数据）
                    cleaned = self._clean_csv_row(row)
                    cleaned["showing_status"] = status
                    cleaned.setdefault("rating", 0.0)
                    cursor.close()

                    try:
                        self.db.insert_movie(cleaned)
                        loaded += 1
                    except Exception:
                        pass

                    cursor = conn.cursor()

            conn.commit()
            logger.info("[MERGE] CSV 补充完成: 新增 %d 部", loaded)
            return loaded

        except Exception as e:
            logger.warning("[MERGE] CSV 补充失败: %s", e)
            return loaded
        finally:
            cursor.close()

    def _clean_csv_row(self, row: dict) -> dict:
        """清洗 CSV 行数据。"""
        cleaned: dict = {}
        numeric_fields = {"rating", "rating_count", "review_count",
                         "box_office", "ticket_price", "runtime"}
        for key, value in row.items():
            key = key.strip()
            if value is None or value.strip() == "":
                cleaned[key] = None
            elif key in numeric_fields:
                try:
                    if key in ("rating", "box_office", "ticket_price"):
                        cleaned[key] = float(value)
                    else:
                        cleaned[key] = int(float(value))
                except (ValueError, TypeError):
                    cleaned[key] = None
            else:
                cleaned[key] = value.strip()
        return cleaned

    # ──────────────────── 详情页爬取（Selenium） ────────────────────

    def _scrape_details_background(self, maoyan_ids: list[str]) -> None:
        """后台线程：用 Selenium 补充评分人数/票房/票价。"""
        def _task():
            time.sleep(5)
            logger.info("[DETAIL] 后台详情页爬取启动: %d 部", len(maoyan_ids))
            details = scrape_movie_details_sync(maoyan_ids)

            updated = 0
            for detail in details:
                if not detail:
                    continue
                try:
                    conn = self.db.get_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT id, title FROM movies WHERE maoyan_id = ?",
                        (detail.get("maoyan_id", ""),),
                    )
                    row = cursor.fetchone()
                    if not row:
                        cursor.close()
                        continue

                    movie_id, title = row["id"], row["title"]
                    updates = []

                    for src_key, db_key in [
                        ("rating_count", "rating_count"),
                        ("box_office", "box_office"),
                        ("price_min", "ticket_price"),
                        ("rating", "rating"),
                        ("summary", "summary"),
                    ]:
                        val = detail.get(src_key, 0)
                        if val:
                            updates.append((db_key, val))

                    if updates:
                        set_clause = ", ".join(f"{k} = ?" for k, _v in updates)
                        vals = [v for _k, v in updates]
                        cursor.execute(
                            f"UPDATE movies SET {set_clause}, "
                            f"updated_at = datetime('now','localtime') WHERE id = ?",
                            vals + [movie_id],
                        )
                        conn.commit()
                        updated += 1
                        logger.info("[DETAIL] 更新《%s}: %s",
                                    title,
                                    " | ".join(f"{k}={v}" for k, v in updates))
                    cursor.close()
                except Exception as e:
                    logger.debug("[DETAIL] 更新失败: %s", e)

            logger.info("[DETAIL] 详情爬取完成: 更新 %d/%d 部", updated, len(details))

        threading.Thread(target=_task, daemon=True).start()

    # ──────────────────── 辅助方法 ────────────────────

    def _record_crawl(self, source: str, status: str, count: int, message: str) -> None:
        """记录爬虫运行状态到数据库。"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO crawl_record (source, status, records_count, message) "
                "VALUES (?, ?, ?, ?)",
                (source, status, count, message),
            )
            conn.commit()
            cursor.close()

            if status in ("success", "failed"):
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE system_config SET value = ? WHERE key = 'last_crawl_time'",
                    (time.strftime("%Y-%m-%d %H:%M:%S"),),
                )
                cursor.execute(
                    "UPDATE system_config SET value = ? WHERE key = 'data_source'",
                    ("crawler",),
                )
                conn.commit()
                cursor.close()
        except Exception as e:
            logger.error("记录爬虫状态失败: %s", e)
