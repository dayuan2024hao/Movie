"""
数据库管理器
=============
单例模式管理 SQLite 连接，提供建表、CRUD、统计查询等功能。

线程安全策略：
  - check_same_thread=False 允许多线程共用连接
  - PRAGMA journal_mode=WAL 实现读写不互斥
  - RLock 保护所有写操作，防止死锁

数据去重：
  1. 优先按 douban_id 匹配 → 更新
  2. 无 douban_id 则按 title UPSERT（ON CONFLICT 原子操作）

用法：
    from database.db_manager import DatabaseManager
    db = DatabaseManager()
    db.init_db()
    db.insert_movie({"title": "电影名", "genre": "剧情", ...})
"""

import sqlite3
import threading
import logging
from typing import Any, Optional

logger = logging.getLogger("Database")


class DatabaseError(Exception):
    """数据库操作异常基类。"""
    pass


class DatabaseManager:
    """数据库管理器（单例），管理 SQLite 连接与所有数据操作。

    线程安全策略：
      - 同一 sqlite3.Connection 不可被多线程并发使用，
        因此所有公开方法均使用 _db_lock 串行化访问。
      - check_same_thread=False + WAL 模式 + 统一锁 = 安全且无死锁。
    """

    _instance: Optional["DatabaseManager"] = None
    _singleton_lock = threading.Lock()

    def __new__(cls, db_path: str = "data/movie_analysis.db") -> "DatabaseManager":
        """单例：全局只创建一个实例。"""
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance

    def __init__(self, db_path: str = "data/movie_analysis.db") -> None:
        """初始化数据库管理器。

        Args:
            db_path: 数据库文件路径，默认 data/movie_analysis.db
        """
        if self._initialized:
            return
        self._initialized = True

        self.db_path: str = db_path
        self._conn: Optional[sqlite3.Connection] = None
        # 全局数据库锁：所有读写操作串行化，避免多线程竞争
        self._db_lock = threading.RLock()

        logger.info("数据库管理器已创建，路径: %s", self.db_path)

    # ──────────────────────────── 连接管理 ────────────────────────────

    def get_connection(self) -> sqlite3.Connection:
        """获取数据库连接（延迟初始化）。

        - check_same_thread=False：允许其他线程使用同一连接
        - row_factory = sqlite3.Row：按列名访问查询结果
        - WAL 模式：写不阻塞读

        Returns:
            已连接的 sqlite3.Connection 对象
        """
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            # WAL 模式：写入时读取不受阻塞
            self._conn.execute("PRAGMA journal_mode=WAL")
            # synchronous=NORMAL：性能与安全平衡，崩溃最多丢一帧数据
            self._conn.execute("PRAGMA synchronous=NORMAL")
            # 外键约束启用
            self._conn.execute("PRAGMA foreign_keys=ON")
            logger.info("数据库连接已建立: %s", self.db_path)
        return self._conn

    def close(self) -> None:
        """关闭数据库连接并释放资源。"""
        with self._db_lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
                logger.info("数据库连接已关闭")

    # ──────────────────────────── 建表 ────────────────────────────

    def init_db(self) -> None:
        """初始化数据库表结构。

        创建 5 张表（IF NOT EXISTS）：
          - movies：电影主表
          - reviews：短评表
          - box_office_log：票房日志表
          - crawl_record：爬虫记录表
          - system_config：系统配置表

        同时插入默认配置数据。
        """
        with self._db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            try:
                # 2.1 movies — 电影主表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS movies (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL UNIQUE,
                        genre TEXT NOT NULL,
                        director TEXT,
                        actors TEXT,
                        release_date TEXT,
                        runtime INTEGER,
                        region TEXT,
                        language TEXT,
                        rating REAL DEFAULT 0.0 CHECK(rating >= 0 AND rating <= 10),
                        rating_count INTEGER DEFAULT 0,
                        review_count INTEGER DEFAULT 0,
                        box_office REAL DEFAULT 0,
                        ticket_price REAL DEFAULT 0,
                        poster_url TEXT,
                        summary TEXT,
                        douban_id TEXT,
                        maoyan_id TEXT,
                        showing_status TEXT DEFAULT 'released'
                                   CHECK(showing_status IN ('showing','released','coming_soon')),
                        created_at TEXT DEFAULT (datetime('now','localtime')),
                        updated_at TEXT DEFAULT (datetime('now','localtime'))
                    )
                """)

                # 2.2 reviews — 短评表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS reviews (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
                        content TEXT NOT NULL,
                        rating REAL,
                        thumbs_up INTEGER DEFAULT 0,
                        sentiment_score REAL,
                        created_at TEXT DEFAULT (datetime('now','localtime'))
                    )
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_reviews_movie_id ON reviews(movie_id)
                """)

                # 2.3 box_office_log — 票房日志表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS box_office_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
                        date TEXT NOT NULL,
                        daily_box_office REAL DEFAULT 0,
                        total_box_office REAL DEFAULT 0
                    )
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_box_office_movie_date
                    ON box_office_log(movie_id, date)
                """)

                # 2.4 crawl_record — 爬虫记录表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS crawl_record (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        source TEXT NOT NULL,
                        status TEXT NOT NULL CHECK(status IN ('success', 'failed', 'running')),
                        records_count INTEGER DEFAULT 0,
                        message TEXT,
                        created_at TEXT DEFAULT (datetime('now','localtime'))
                    )
                """)

                # 2.5 system_config — 系统配置表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS system_config (
                        key TEXT PRIMARY KEY,
                        value TEXT,
                        description TEXT
                    )
                """)
                # 默认配置数据
                cursor.executemany("""
                    INSERT OR IGNORE INTO system_config (key, value, description)
                    VALUES (?, ?, ?)
                """, [
                    ("db_version", "1.0", "数据库版本"),
                    ("last_crawl_time", "", "上次爬取时间"),
                    ("data_source", "backup", "数据来源: backup/crawler"),
                ])

                conn.commit()
                logger.info("数据库表结构初始化完成（共 5 张表）")
            except sqlite3.Error as e:
                conn.rollback()
                logger.error("数据库初始化失败: %s", e)
                raise DatabaseError(f"数据库初始化失败: {e}") from e
            finally:
                cursor.close()

    # ──────────────────────────── 单条插入/更新 ────────────────────────────

    def insert_movie(self, data: dict) -> int:
        """插入或更新一部电影。

        去重策略（两阶段）：
          1. 优先按 douban_id 匹配 → 找到则 UPDATE
          2. 按 title 匹配 → ON CONFLICT(title) DO UPDATE
          3. 都未匹配 → INSERT

        Args:
            data: 电影数据字典，需包含 title 和 genre，其余字段可选

        Returns:
            电影 ID（自增主键）

        Raises:
            DatabaseError: 插入失败
        """
        with self._db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            try:
                movie_id: Optional[int] = None

                # 阶段一：按 douban_id 精确定位（爬虫数据走此路径）
                douban_id = data.get("douban_id")
                if douban_id:
                    cursor.execute(
                        "SELECT id FROM movies WHERE douban_id = ?", (douban_id,)
                    )
                    row = cursor.fetchone()
                    if row:
                        movie_id = row["id"]

                if movie_id is not None:
                    # 按 ID 更新（外键关联不中断）
                    self._update_by_id(cursor, movie_id, data)
                else:
                    # 阶段二：按 title UPSERT（ON CONFLICT 原子操作）
                    movie_id = self._upsert_by_title(cursor, data)

                conn.commit()
                logger.info("电影写入成功: id=%d, title=%s", movie_id, data.get("title"))
                return movie_id
            except sqlite3.Error as e:
                conn.rollback()
                logger.error("插入电影失败: %s", e)
                raise DatabaseError(f"插入电影失败: {e}") from e
            finally:
                cursor.close()

    def _update_by_id(self, cursor: sqlite3.Cursor, movie_id: int, data: dict) -> None:
        """按主键 ID 更新电影字段。"""
        # 排除 id 和自动管理的时间字段（updated_at 由触发器或手动管理）
        fields = [k for k in data.keys() if k not in ("id", "created_at")]
        if not fields:
            return
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = [data[k] for k in fields]
        cursor.execute(
            f"UPDATE movies SET {set_clause}, updated_at = datetime('now','localtime') "
            f"WHERE id = ?",
            values + [movie_id],
        )

    def _upsert_by_title(self, cursor: sqlite3.Cursor, data: dict) -> int:
        """按 title 执行 UPSERT（原子操作，消除 TOCTOU 竞态）。"""
        fields = [k for k in data.keys() if k not in ("id", "created_at")]
        placeholders = ", ".join("?" for _ in fields)
        columns = ", ".join(fields)
        # excluded 引用待插入的新值
        updates = ", ".join(f"{k} = excluded.{k}" for k in fields if k != "title")
        updates += ", updated_at = datetime('now','localtime')"

        sql = f"""
            INSERT INTO movies ({columns}) VALUES ({placeholders})
            ON CONFLICT(title) DO UPDATE SET
                {updates}
        """
        cursor.execute(sql, [data.get(k) for k in fields])

        # 返回插入/更新后的 ID（按 title 回查）
        cursor.execute("SELECT id FROM movies WHERE title = ?", (data.get("title"),))
        row = cursor.fetchone()
        if row is None:
            raise DatabaseError(f"UPSERT 后无法回查电影: {data.get('title')}")
        return row["id"]

    # ──────────────────────────── 批量插入 ────────────────────────────

    def insert_movies_batch(self, movies: list[dict]) -> dict:
        """批量插入电影。逐条尝试，失败项不回滚已成功项。

        Args:
            movies: 电影数据字典列表

        Returns:
            包含成功/失败统计的字典：
            {"success": int, "fail": int, "errors": list[str]}
        """
        result: dict = {"success": 0, "fail": 0, "errors": []}

        for index, movie in enumerate(movies):
            try:
                self.insert_movie(movie)
                result["success"] += 1
            except (DatabaseError, sqlite3.Error) as e:
                result["fail"] += 1
                title = movie.get("title", "未知")
                result["errors"].append(f"[{index + 1}] 《{title}》: {e}")
                logger.warning("批量插入跳过第 %d 条 '%s': %s", index + 1, title, e)

        logger.info(
            "批量插入完成: 成功 %d 条, 失败 %d 条",
            result["success"],
            result["fail"],
        )
        return result

    # ──────────────────────────── 综合查询 ────────────────────────────

    def query_movies(
        self,
        genre: Optional[str] = None,
        rating_min: float = 0,
        rating_max: float = 10,
        price_min: float = 0,
        price_max: float = 999,
        box_office_min: float = 0,
        box_office_max: float = 1e9,
        year_start: Optional[int] = None,
        year_end: Optional[int] = None,
        keyword: Optional[str] = None,
        sort_by: str = "rating",
        sort_order: str = "DESC",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[int, list[dict]]:
        """电影综合查询，支持多条件筛选和排序。

        Args:
            genre: 电影类型（模糊匹配，如 "动作" 会匹配 "动作,科幻"）
            rating_min: 最低评分
            rating_max: 最高评分
            price_min: 最低票价
            price_max: 最高票价
            box_office_min: 最低票房
            box_office_max: 最高票房
            year_start: 起始年份（含）
            year_end: 结束年份（含）
            keyword: 电影名称关键词（LIKE 模糊搜索）
            sort_by: 排序字段（rating / box_office / title / release_date）
            sort_order: 排序方向（ASC / DESC）
            limit: 每页条数
            offset: 偏移量

        Returns:
            (总记录数, 当前页记录列表)
        """
        allowed_sort = {"rating", "box_office", "title", "release_date"}
        if sort_by not in allowed_sort:
            sort_by = "rating"
        if sort_order.upper() not in ("ASC", "DESC"):
            sort_order = "DESC"

        conditions: list[str] = []
        params: list[Any] = []

        if genre:
            conditions.append("genre LIKE ?")
            params.append(f"%{genre}%")
        if rating_min > 0:
            conditions.append("rating >= ?")
            params.append(rating_min)
        if rating_max < 10:
            conditions.append("rating <= ?")
            params.append(rating_max)
        if price_min > 0:
            conditions.append("ticket_price >= ?")
            params.append(price_min)
        if price_max < 999:
            conditions.append("ticket_price <= ?")
            params.append(price_max)
        if box_office_min > 0:
            conditions.append("box_office >= ?")
            params.append(box_office_min)
        if box_office_max < 1e9:
            conditions.append("box_office <= ?")
            params.append(box_office_max)
        if year_start:
            conditions.append("CAST(strftime('%Y', release_date) AS INTEGER) >= ?")
            params.append(year_start)
        if year_end:
            conditions.append("CAST(strftime('%Y', release_date) AS INTEGER) <= ?")
            params.append(year_end)
        if keyword:
            conditions.append("title LIKE ?")
            params.append(f"%{keyword}%")

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        with self._db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()

            try:
                # 查询总数
                cursor.execute(f"SELECT COUNT(*) AS total FROM movies {where_clause}", params)
                total = cursor.fetchone()["total"]

                # 查询当前页
                sql = f"""
                    SELECT * FROM movies
                    {where_clause}
                    ORDER BY {sort_by} {sort_order}
                    LIMIT ? OFFSET ?
                """
                cursor.execute(sql, params + [limit, offset])
                rows = cursor.fetchall()
                records = [dict(row) for row in rows]

                return total, records
            except sqlite3.Error as e:
                logger.error("查询电影失败: %s", e)
                raise DatabaseError(f"查询电影失败: {e}") from e
            finally:
                cursor.close()

    # ──────────────────────────── 统计数据 ────────────────────────────

    def get_statistics(self) -> dict:
        """获取看板统计卡片数据。

        Returns:
            {
                "total_movies": 电影总数,
                "total_box_office": 总票房（万元）,
                "avg_rating": 平均评分,
                "avg_ticket_price": 平均票价（元）,
                "highest_rated": 最高评分电影名,
                "highest_rated_score": 最高评分,
                "highest_box_office": 最高票房电影名,
                "highest_box_office_value": 最高票房,
            }
        """
        with self._db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            try:
                stats: dict = {}

                # 基本统计
                cursor.execute("""
                    SELECT
                        COUNT(*) AS total_movies,
                        COALESCE(SUM(box_office), 0) AS total_box_office,
                        COALESCE(AVG(rating), 0) AS avg_rating,
                        COALESCE(AVG(ticket_price), 0) AS avg_ticket_price
                    FROM movies
                """)
                row = cursor.fetchone()
                stats["total_movies"] = row["total_movies"]
                stats["total_box_office"] = round(row["total_box_office"], 2)
                stats["avg_rating"] = round(row["avg_rating"], 2)
                stats["avg_ticket_price"] = round(row["avg_ticket_price"], 2)

                # 最高评分电影
                cursor.execute("""
                    SELECT title, rating FROM movies
                    WHERE rating > 0
                    ORDER BY rating DESC LIMIT 1
                """)
                row = cursor.fetchone()
                stats["highest_rated"] = row["title"] if row else "无数据"
                stats["highest_rated_score"] = row["rating"] if row else 0

                # 最高票房电影
                cursor.execute("""
                    SELECT title, box_office FROM movies
                    WHERE box_office > 0
                    ORDER BY box_office DESC LIMIT 1
                """)
                row = cursor.fetchone()
                stats["highest_box_office"] = row["title"] if row else "无数据"
                stats["highest_box_office_value"] = row["box_office"] if row else 0

                return stats
            except sqlite3.Error as e:
                logger.error("获取统计数据失败: %s", e)
                raise DatabaseError(f"获取统计数据失败: {e}") from e
            finally:
                cursor.close()

    def get_top10_box_office(self) -> list[dict]:
        """获取票房 Top 10 电影列表。

        Returns:
            按票房降序排列的 Top 10 电影字典列表
        """
        with self._db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    SELECT id, title, box_office, rating, genre
                    FROM movies
                    WHERE box_office > 0
                    ORDER BY box_office DESC
                    LIMIT 10
                """)
                return [dict(row) for row in cursor.fetchall()]
            except sqlite3.Error as e:
                logger.error("获取 Top 10 票房失败: %s", e)
                raise DatabaseError(f"获取 Top 10 票房失败: {e}") from e
            finally:
                cursor.close()

    def get_genre_stats(self) -> list[dict]:
        """获取各类型电影数量和平均评分统计。

        注意：多类型电影（如"动作,科幻"）会分别计入各类型中。

        Returns:
            [{"genre": "动作", "count": 12, "avg_rating": 7.5}, ...]
        """
        with self._db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    SELECT
                        TRIM(value) AS genre,
                        COUNT(*) AS count,
                        ROUND(AVG(rating), 2) AS avg_rating
                    FROM movies, json_each('["' || REPLACE(genre, ',', '","') || '"]')
                    WHERE rating > 0
                    GROUP BY TRIM(value)
                    ORDER BY count DESC
                """)
                return [dict(row) for row in cursor.fetchall()]
            except sqlite3.Error as e:
                logger.error("获取类型统计失败: %s", e)
                raise DatabaseError(f"获取类型统计失败: {e}") from e
            finally:
                cursor.close()

    # ──────────────────────────── 数据加载 ────────────────────────────

    def load_csv_to_db(self, csv_path: str) -> int:
        """从 CSV 文件加载电影数据到数据库。

        Args:
            csv_path: CSV 文件路径

        Returns:
            成功导入的记录数

        Raises:
            DatabaseError: 文件读取或数据库写入失败
        """
        import csv

        with self._db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            loaded: int = 0
            try:
                with open(csv_path, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    rows = list(reader)

                if not rows:
                    logger.warning("CSV 文件为空: %s", csv_path)
                    return 0

                for row in rows:
                    try:
                        # 清洗：空字符串转 None，数字字段转型
                        cleaned = self._clean_csv_row(row)
                        self._upsert_by_title(cursor, cleaned)
                        loaded += 1
                    except (sqlite3.Error, DatabaseError) as e:
                        logger.warning("CSV 第 %d 行导入失败: %s", loaded + 1, e)
                        continue

                conn.commit()
                logger.info("CSV 数据加载完成: %s, 共 %d 条", csv_path, loaded)
                return loaded
            except (FileNotFoundError, csv.Error) as e:
                logger.error("CSV 文件读取失败: %s", e)
                raise DatabaseError(f"CSV 文件读取失败: {e}") from e
            except sqlite3.Error as e:
                conn.rollback()
                logger.error("CSV 数据写入数据库失败: %s", e)
                raise DatabaseError(f"CSV 数据写入失败: {e}") from e
            finally:
                cursor.close()

    def _clean_csv_row(self, row: dict) -> dict:
        """清洗 CSV 行数据：空字符串转 None，数字字段转型。

        Args:
            row: 原始行字典

        Returns:
            清洗后的行字典
        """
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

    # ──────────────────────────── 数据状态 ────────────────────────────

    def get_data_status(self) -> dict:
        """检查数据库中电影数据的状态。

        Returns:
            {
                "has_data": bool,
                "total_movies": int,
                "data_source": str,
                "last_crawl_time": str,
            }
        """
        with self._db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT COUNT(*) AS cnt FROM movies")
                total = cursor.fetchone()["cnt"]

                cursor.execute(
                    "SELECT value FROM system_config WHERE key = 'data_source'"
                )
                row = cursor.fetchone()
                data_source = row["value"] if row else "unknown"

                cursor.execute(
                    "SELECT value FROM system_config WHERE key = 'last_crawl_time'"
                )
                row = cursor.fetchone()
                last_crawl = row["value"] if row else ""

                return {
                    "has_data": total > 0,
                    "total_movies": total,
                    "data_source": data_source,
                    "last_crawl_time": last_crawl,
                }
            except sqlite3.Error as e:
                logger.error("获取数据状态失败: %s", e)
                raise DatabaseError(f"获取数据状态失败: {e}") from e
            finally:
                cursor.close()

    # ──────────────────────────── 数据库版本 ────────────────────────────

    def check_and_migrate(self) -> None:
        """检查数据库版本并执行迁移（如有）。

        当前版本 v1.0，暂无需迁移，预留接口供后续扩展。
        """
        with self._db_lock:
            conn = self.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT value FROM system_config WHERE key = 'db_version'")
                row = cursor.fetchone()
                current_version = row["value"] if row else "0.0"

                # 迁移字典：key=版本号, value=SQL 列表
                migrations: dict = {
                    "1.1": [
                        "ALTER TABLE movies ADD COLUMN showing_status TEXT DEFAULT 'released' CHECK(showing_status IN ('showing','released','coming_soon'))",
                    ],
                    "1.2": [
                        "ALTER TABLE movies ADD COLUMN maoyan_id TEXT",
                    ],
                }

                for version, sqls in sorted(migrations.items()):
                    if not sqls:
                        continue  # 跳过无迁移项的版本
                    if version > current_version:
                        for sql in sqls:
                            try:
                                cursor.execute(sql)
                            except sqlite3.OperationalError as e:
                                if "duplicate column" in str(e).lower():
                                    logger.warning("列已存在，跳过迁移: %s", e)
                                    continue
                                raise
                        cursor.execute(
                            "UPDATE system_config SET value = ? WHERE key = 'db_version'",
                            (version,),
                        )
                        logger.info("数据库已迁移至版本 %s", version)

                conn.commit()
            except sqlite3.Error as e:
                conn.rollback()
                logger.error("数据库迁移失败: %s", e)
                raise DatabaseError(f"数据库迁移失败: {e}") from e
            finally:
                cursor.close()
