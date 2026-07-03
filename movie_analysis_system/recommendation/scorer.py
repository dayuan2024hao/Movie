"""
综合评分模型
============
基于猫眼真实数据，对电影进行多维度排名。

排名算法（独立函数，各有独立权重依据）：
  高分推荐   calc_high_rating_rank()  — 纯评分降序，≥9.0优先
  口碑推荐   calc_reputation_rank()   — 评分² × sqrt(评分人数)
  热门推荐   calc_hot_rank()          — 热度×0.6 + 票房×0.4
  性价比推荐  calc_value_rank()        — (评分×上座率) / 票价
  综合推荐   calc_comprehensive_rank() — 多因子加权
"""

import logging
from typing import Optional

logger = logging.getLogger("Scorer")


# ═══════════════ 配置区 ═══════════════
# 综合推荐权重（5 因子）
WEIGHT_RATING = 0.35          # 评分
WEIGHT_POPULARITY = 0.25      # 热度（评分人数）
WEIGHT_REPUTATION = 0.25      # 口碑（评分² × 人数）
WEIGHT_PRICE = -0.15          # 票价成本（负值=加分）

# 热门推荐权重
HOT_RATING_COUNT = 0.60       # 评分人数权重
HOT_BOX_OFFICE = 0.40         # 票房权重

# 性价比推荐参数
VALUE_RATING_W = 0.50         # 评分在性价比中的权重
VALUE_SEAT_RATE_W = 0.50      # 上座率在性价比中的权重

# 口碑推荐参数
REP_RATING_POWER = 2.0        # 评分指数放大
REP_COUNT_DAMP = 0.5          # 评分人数对数压缩系数

# 归一化常数
MAX_RATING = 10.0
MAX_RATING_COUNT = 500000
MAX_PRICE = 80.0
# ═════════════════════════════════════


# ──────────────────── 高分推荐 ────────────────────

def calc_high_rating_rank(movies: list[dict]) -> list[dict]:
    """高分推荐：纯评分降序，≥9.0 优先展示。

    权重依据：
      - 只考虑评分质量，不引入热度/票价等干扰
      - ≥9.0 的电影视为"高分佳作"，排在 9.0 以下之前
    """
    scored = [
        dict(m) for m in movies
        if m.get("rating", 0) > 0
    ]
    # 优先：≥9.0 → 按评分降序
    scored.sort(
        key=lambda m: (1 if m["rating"] >= 9.0 else 0, m["rating"]),
        reverse=True,
    )
    return scored


# ──────────────────── 口碑推荐 ────────────────────

def calc_reputation_rank(movies: list[dict]) -> list[dict]:
    """口碑推荐：评分² × sqrt(评分人数)。

    权重依据：
      - 评分²：高分口碑放大（9.5²=90.25 >> 8.0²=64.0）
      - sqrt(人数)：对数压缩，万人评与百万评差异缩小
      - 乘积：同时考察"分高"和"人多"，避免高分冷门片
      - 限 showing：未上映无法检验口碑
    """
    def _score(m: dict) -> float:
        r = m.get("rating") or 0
        c = m.get("rating_count") or 0
        return (r / MAX_RATING) ** REP_RATING_POWER * (c ** REP_COUNT_DAMP + 1)

    showing = [
        dict(m) for m in movies
        if m.get("showing_status") == "showing" and m.get("rating", 0) > 0
    ]
    showing.sort(key=_score, reverse=True)
    return showing


# ──────────────────── 热门推荐 ────────────────────

def calc_hot_rank(movies: list[dict]) -> list[dict]:
    """热门推荐：评分人数×0.6 + 票房×0.4。

    权重依据：
      - 评分人数：反映关注热度/想看人群
      - 票房：真金白银的市场热度
      - 限 showing：未上映无票房数据，coming_soon 降级为仅用评分人数
    """
    max_count = max((m.get("rating_count") or 0) for m in movies) or 1
    max_box = max((m.get("box_office") or 0) for m in movies) or 1

    def _score(m: dict) -> float:
        nc = (m.get("rating_count") or 0) / max_count
        bo = (m.get("box_office") or 0) / max_box
        if m.get("box_office", 0) > 0:
            return nc * HOT_RATING_COUNT + bo * HOT_BOX_OFFICE
        return nc  # 无票房数据时纯用评分人数

    showing = [
        dict(m) for m in movies
        if m.get("showing_status") == "showing"
    ]
    showing.sort(key=_score, reverse=True)
    return showing


# ──────────────────── 性价比推荐 ────────────────────

def calc_value_rank(movies: list[dict]) -> list[dict]:
    """性价比推荐：(评分得分 × 上座率系数) / 票价系数。

    公式：
      value_score = (rating/10 × seat_rate) / (price_norm + 0.01)
      seat_rate = rating_count / max_rating_count  （评分人数近似上座率）
      price_norm = ticket_price / max_price

    权重依据：
      - 评分高 + 上座高 + 票价低 = 高性价比
      - 防止除以零：price_norm + 0.01
      - 无票价时降级为 (rating/10) × 0.5（纯看评分）
    """
    max_count = max((m.get("rating_count") or 0) for m in movies) or 1
    max_price = max((m.get("ticket_price") or 0) for m in movies) or 1

    results = []
    for m in movies:
        movie = dict(m)
        r = movie.get("rating") or 0
        c = movie.get("rating_count") or 0
        p = movie.get("ticket_price") or 0

        seat_rate = c / max_count
        price_norm = p / max_price if p > 0 else 0.01

        if r > 0 and p > 0:
            # 完整公式：(评分×上座率) / 票价
            value = (r / MAX_RATING * VALUE_RATING_W + seat_rate * VALUE_SEAT_RATE_W) / price_norm
        elif r > 0:
            # 无票价：降级为评分×上座率
            value = (r / MAX_RATING) * VALUE_RATING_W + seat_rate * VALUE_SEAT_RATE_W * 0.5
        else:
            value = 0

        movie["value_score"] = round(value, 4)
        results.append(movie)

    scored = [m for m in results if m.get("value_score", 0) > 0]
    scored.sort(key=lambda m: m["value_score"], reverse=True)
    return scored


# ──────────────────── 综合推荐 ────────────────────

def calc_comprehensive_rank(movies: list[dict]) -> list[dict]:
    """综合推荐：5 因子加权。

    公式：
      comprehensive = rating_norm × 0.35
                    + popularity_norm × 0.25
                    + reputation_norm × 0.25
                    - price_norm × 0.15

      rating_norm      = rating / MAX_RATING
      popularity_norm  = min(rating_count, MAX_RATING_COUNT) / MAX_RATING_COUNT
      reputation_norm  = (rating/MAX_RATING)² × sqrt(rating_count) 归一化
      price_norm       = min(ticket_price, MAX_PRICE) / MAX_PRICE
    """
    if not movies:
        return []

    # 找各指标最大值用于归一化
    max_count = max((m.get("rating_count") or 0) for m in movies) or 1

    results = []
    for m in movies:
        movie = dict(m)
        r = m.get("rating") or 0
        c = m.get("rating_count") or 0
        p = m.get("ticket_price") or 0

        # 评分因子 (0~1)
        rating_norm = r / MAX_RATING

        # 热度因子 (0~1)
        popularity_norm = min(c, MAX_RATING_COUNT) / MAX_RATING_COUNT

        # 口碑因子 (0~1)：评分² × 人数归一化
        raw_rep = (r / MAX_RATING) ** REP_RATING_POWER * (c ** REP_COUNT_DAMP + 1)
        max_raw = (1.0) ** REP_RATING_POWER * (max_count ** REP_COUNT_DAMP + 1) or 1
        reputation_norm = raw_rep / max_raw

        # 票价因子 (0~1)
        price_norm = min(p, MAX_PRICE) / MAX_PRICE if p > 0 else 0

        if p > 0:
            comprehensive = (
                rating_norm * WEIGHT_RATING
                + popularity_norm * WEIGHT_POPULARITY
                + reputation_norm * WEIGHT_REPUTATION
                + price_norm * WEIGHT_PRICE
            )
        else:
            # 无票价：权重重新分配
            adj = WEIGHT_RATING + WEIGHT_POPULARITY + WEIGHT_REPUTATION
            comprehensive = (
                rating_norm * (WEIGHT_RATING + WEIGHT_PRICE * 0.3) / adj
                + popularity_norm * WEIGHT_POPULARITY / adj
                + reputation_norm * WEIGHT_REPUTATION / adj
            )

        movie["comprehensive_score"] = round(comprehensive * 10, 1)  # 映射到 0~10 便于展示
        results.append(movie)

    results.sort(key=lambda m: m.get("comprehensive_score") or 0, reverse=True)
    return results


# ──────────────────── 兼容：ComprehensiveScorer 类 ────────────────────

class ComprehensiveScorer:
    """综合评分计算器（旧接口，保持向后兼容）。"""

    def __init__(self, movies: list[dict]) -> None:
        self.movies = movies

    def calc_scores(self) -> list[dict]:
        """计算所有电影的综合评分。"""
        return calc_comprehensive_rank(self.movies)
