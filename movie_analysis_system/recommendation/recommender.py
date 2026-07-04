"""
推荐逻辑
========
基于电影真实数据提供推荐，不虚构任何评论或数据。

推荐模式（5 种）：
  - comprehensive: 综合推荐（多因子加权）
  - hot: 热门推荐（票房×0.6 + 评分人数×0.4）
  - high_rating: 高分推荐（纯评分降序）
  - best_value: 口碑推荐（评分² × sqrt(人数)）
  - value: 性价比推荐（评分/票价，部分模拟数据）

数据可用性（在映47部）：
  评分:    34/47 ✓
  评分人数: 23/47 ✓
  票房:    47/47 ✓
  票价:    23/47 ⚠
"""

import logging
from typing import Optional

from database.db_manager import DatabaseManager
from recommendation.scorer import (
    calc_high_rating_rank,
    calc_reputation_rank,
    calc_hot_rank,
    calc_value_rank,
    calc_comprehensive_rank,
)

logger = logging.getLogger("Recommender")


# 各模式的中文描述与数据标注
MODE_INFO = {
    "comprehensive": {
        "label": "综合推荐",
        "description": "多因子加权（评分×0.35 + 热度×0.25 + 口碑×0.25 - 票价×0.15）",
        "data_source": "真实数据",
        "supported": True,
    },
    "hot": {
        "label": "热门推荐",
        "description": "票房×0.6 + 评分人数×0.4",
        "data_source": "真实数据（票房47/47部有数据）",
        "supported": True,
    },
    "high_rating": {
        "label": "高分推荐",
        "description": "纯评分降序",
        "data_source": "真实数据（评分34/47部有数据）",
        "supported": True,
    },
    "best_value": {
        "label": "口碑推荐",
        "description": "评分² × √评分人数（仅评分也可排序）",
        "data_source": "真实数据（评分34/47部有数据）",
        "supported": True,
    },
    "value": {
        "label": "性价比推荐",
        "description": "评分 / 票价",
        "data_source": "⚠ 部分模拟数据（票价23/47部有数据，无票价影片使用均值估算）",
        "supported": True,
    },
}


class Recommender:
    """推荐引擎——所有数据来自猫眼爬取或 CSV 备份，不虚构。"""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def recommend(
        self,
        mode: str = "comprehensive",
        limit: int = 20,
        **filters,
    ) -> list[dict]:
        """按指定模式返回推荐列表。

        Args:
            mode: 推荐模式（comprehensive/hot/high_rating/best_value/value）
            limit: 返回条数上限
            **filters: 筛选参数

        Returns:
            推荐电影列表（仅限 showing + coming_soon）
        """
        total, movies = self.db.query_movies(
            limit=200, sort_by="rating", sort_order="DESC", **filters
        )

        if not movies:
            return []

        # 只展示在映电影
        movies = [
            m for m in movies
            if m.get("showing_status") == "showing"
        ]
        if not movies:
            return []

        # 按模式选择排名算法
        mode_dispatch = {
            "high_rating":     lambda ms: calc_high_rating_rank(ms),
            "best_value":      lambda ms: calc_reputation_rank(ms),
            "hot":             lambda ms: calc_hot_rank(ms),
            "value":           lambda ms: calc_value_rank(ms),
            "comprehensive":   lambda ms: calc_comprehensive_rank(ms),
        }

        rank_func = mode_dispatch.get(mode, mode_dispatch["comprehensive"])
        ranked = rank_func(movies)

        result = ranked[:limit]

        # 生成推荐理由（模式特有，让各榜单差异化）
        for rank, movie in enumerate(result, 1):
            movie["rank"] = rank
            movie["recommendation_reason"] = self._generate_reason(movie, mode)
            movie["top_comments"] = []
            movie["mode_info"] = MODE_INFO.get(mode, MODE_INFO["comprehensive"])

        return result

    def get_mode_info(self, mode: str) -> dict:
        """获取指定模式的说明信息。

        Args:
            mode: 推荐模式名称

        Returns:
            模式信息字典
        """
        return MODE_INFO.get(mode, MODE_INFO["comprehensive"])

    def _generate_reason(self, movie: dict, mode: str) -> str:
        """生成推荐理由——模式特有格式，让各榜单差异化。

        Args:
            movie: 电影数据
            mode: 推荐模式

        Returns:
            推荐理由字符串
        """
        rating = movie.get("rating") or 0
        genre = movie.get("genre", "")
        release_date = movie.get("release_date", "")
        price = movie.get("ticket_price") or 0

        # 各模式不同的理由格式
        if mode == "high_rating":
            # 高分推荐：强调评分
            if rating >= 9.0:
                return f"🏆 高分佳作 {rating:.1f}分 · {genre.replace(';', '/') if genre else ''}"
            return f"⭐ 评分 {rating:.1f} · {genre.replace(';', '/') if genre else ''}"

        elif mode == "hot":
            # 热门推荐：强调票房和关注度
            box_office = movie.get("box_office") or 0
            parts = [f"🔥 票房 {box_office:,.0f} 万"]
            rc = movie.get("rating_count") or 0
            if rc > 0:
                parts.append(f"👥 {rc:,} 人关注")
            return " · ".join(parts)

        elif mode == "best_value":
            # 口碑推荐：强调评分和人数
            rc = movie.get("rating_count") or 0
            if rc > 0:
                return f"💯 口碑佳作 {rating:.1f}分 · {rc:,} 人评价"
            return f"💯 评分 {rating:.1f} · {genre.replace(';', '/') if genre else ''}"

        elif mode == "value":
            # 性价比推荐：强调价格
            price_str = f"¥{price:.0f}" if price > 0 else "暂无票价"
            is_sim = movie.get("value_is_simulated", False)
            tag = " (估算)" if is_sim else ""
            return f"💰 参考价 {price_str}{tag} · 评分 {rating:.1f}"

        else:
            # 综合推荐：标准格式
            parts = [f"猫眼评分 {rating:.1f}"]
            if genre:
                parts.append(genre.replace(";", "/"))
            if price > 0:
                parts.append(f"¥{price:.0f}")
            if release_date:
                parts.append(release_date[:10])
            return " · ".join(parts)
