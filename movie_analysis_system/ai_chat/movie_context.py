"""
本地电影数据上下文构建
=====================
将数据库中在映电影格式化为 AI 可读的上下文文本，
并提供电影标题模糊查找（用于点击跳转详情）。
"""

import logging
from typing import Optional

from database.db_manager import DatabaseManager

logger = logging.getLogger("MovieContext")

# 在映电影上下文缓存（避免每次对话都查库）
_context_cache: Optional[str] = None
_cache_count: int = 0


def build_movie_context(db: DatabaseManager) -> str:
    """查询数据库，返回格式化的在映电影摘要文本。

    Args:
        db: 数据库管理器

    Returns:
        格式化的电影列表文本
    """
    global _context_cache, _cache_count

    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        # 查询所有在映电影，按评分降序
        cursor.execute("""
            SELECT title, genre, rating, box_office, ticket_price,
                   director, release_date, id
            FROM movies
            WHERE showing_status = 'showing'
            ORDER BY rating DESC
        """)
        rows = cursor.fetchall()

        total = len(rows)

        lines = [f"【当前在映电影】（共 {total} 部，按评分排序）：\n"]
        for i, row in enumerate(rows, 1):
            t = row["title"]
            g = row["genre"] or "未知类型"
            r = row["rating"] or 0
            bo = row["box_office"] or 0
            tp = row["ticket_price"] or 0
            d = row["director"] or "未知"
            rd = (row["release_date"] or "")[:10]

            parts = [
                f"{i}. {t}",
                f"类型: {g.replace(';', '/')}",
                f"评分: {r:.1f}",
            ]
            if bo > 0:
                parts.append(f"票房: {bo:.0f}万")
            if tp > 0:
                parts.append(f"票价: {tp:.0f}元")
            if d != "未知":
                parts.append(f"导演: {d}")
            if rd:
                parts.append(f"上映: {rd}")
            lines.append(" | ".join(parts))

        lines.append(
            "\n\n注意：推荐时电影名请用 **电影名** 格式包裹，"
            "例如 **哪吒之魔童闹海**。"
        )

        result = "\n".join(lines)

        # 缓存
        _context_cache = result
        _cache_count = total

        return result

    except Exception as e:
        logger.error("构建电影上下文失败: %s", e)
        return "【提示】暂时无法获取在映电影数据，请稍后再试。"
    finally:
        cursor.close()


def invalidate_cache() -> None:
    """使上下文缓存失效（爬取新数据后调用）。"""
    global _context_cache, _cache_count
    _context_cache = None
    _cache_count = 0


def search_movie(title: str, db: DatabaseManager) -> Optional[dict]:
    """模糊匹配电影标题，返回第一条匹配的电影数据。

    Args:
        title: 电影名（支持模糊匹配）
        db: 数据库管理器

    Returns:
        电影字典，未找到返回 None
    """
    conn = db.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, title, rating, genre, box_office, ticket_price, "
            "director, release_date, showing_status "
            "FROM movies WHERE title LIKE ? LIMIT 1",
            (f"%{title}%",),
        )
        row = cursor.fetchone()
        if row:
            return {
                "id": row[0],
                "title": row[1],
                "rating": row[2],
                "genre": row[3],
                "box_office": row[4],
                "ticket_price": row[5],
                "director": row[6],
                "release_date": row[7],
                "showing_status": row[8],
            }
        return None
    except Exception as e:
        logger.error("搜索电影失败 '%s': %s", title, e)
        return None
    finally:
        cursor.close()
