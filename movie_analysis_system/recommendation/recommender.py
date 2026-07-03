"""
推荐逻辑
========
基于电影真实数据提供推荐，不虚构任何评论或数据。

推荐模式（5 种）：
  - comprehensive: 综合推荐（多因子加权）
  - hot: 热门推荐（热度×票房）
  - high_rating: 高分推荐（纯评分）
  - best_value: 口碑推荐（评分² × 人数）
  - value: 性价比推荐（评分×上座率/票价）

配置区 RANK_WEIGHTS — 所有排名核心参数，方便后期调整。
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


# ═══════════════ 配置区 ═══════════════════════════════════
RANK_WEIGHTS = {
    # 综合推荐 — 5 因子权重（总和 ≈ 1.0）
    "comprehensive": {
        "rating": 0.35,          # 评分因子
        "popularity": 0.25,      # 热度因子
        "reputation": 0.25,      # 口碑因子
        "price": -0.15,          # 票价因子（负值）
    },
    # 热门推荐 — 热度指标权重
    "hot": {
        "rating_count": 0.60,    # 评分人数
        "box_office": 0.40,      # 票房
    },
    # 口碑推荐 — 评分/人数放大参数
    "reputation": {
        "rating_power": 2.0,     # 评分指数（>1 放大高分差异）
        "count_damp": 0.5,       # 人数对数压缩（<1 压缩大数）
    },
    # 性价比推荐 — 分子权重
    "value": {
        "rating_w": 0.50,        # 评分权重
        "seat_rate_w": 0.50,     # 上座率权重
    },
}
# ═════════════════════════════════════════════════════════


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
            mode: 推荐模式
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

        # 只展示在映电影（不包含即将上映）
        movies = [
            m for m in movies
            if m.get("showing_status") == "showing"
        ]
        if not movies:
            return []

        # 按模式选择排名算法
        mode_dispatch = {
            "high_rating": lambda ms: calc_high_rating_rank(ms),
            "best_value":  lambda ms: calc_reputation_rank(ms),
            "hot":         lambda ms: calc_hot_rank(ms),
            "value":       lambda ms: calc_value_rank(ms),
            "comprehensive": lambda ms: calc_comprehensive_rank(ms),
        }

        rank_func = mode_dispatch.get(mode, mode_dispatch["comprehensive"])
        ranked = rank_func(movies)

        result = ranked[:limit]

        # 生成推荐理由（只基于真实数据）
        for rank, movie in enumerate(result, 1):
            movie["rank"] = rank
            movie["recommendation_reason"] = self._generate_reason(movie, mode)
            movie["top_comments"] = []  # 不虚构评论

        return result

    def _generate_reason(self, movie: dict, mode: str) -> str:
        """生成推荐理由——只使用猫眼真实字段，不虚构。

        格式：评分 · 类型 · 主演 · 上映日期
        """
        showing = movie.get("showing_status") == "showing"
        rating = movie.get("rating") or 0
        genre = movie.get("genre", "")
        actors = movie.get("actors", "")
        release_date = movie.get("release_date", "")
        price = movie.get("ticket_price") or 0

        parts = []

        # 评分
        if showing and rating > 0:
            parts.append(f"猫眼评分 {rating:.1f}")
        elif showing:
            parts.append("暂无评分")
        elif rating > 0:
            parts.append(f"评分 {rating:.1f}")
        else:
            parts.append("即将上映")

        # 类型
        if genre:
            genre_short = genre.replace(";", "/")
            parts.append(genre_short)

        # 主演（取前2）
        if actors:
            actor_list = actors.split(";")[:2]
            parts.append(" / ".join(actor_list) + " 主演")

        # 上映日期
        if release_date:
            parts.append(release_date[:10])

        # 票价（性价比模式特别显示）
        if mode == "value" and price > 0:
            parts.append(f"¥{price:.0f} 起")

        return " · ".join(parts)
