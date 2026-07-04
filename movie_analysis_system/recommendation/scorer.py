"""
综合评分模型
============
基于猫眼真实数据，对电影进行多维度排名。

排名算法（独立函数，各有独立权重依据）：
  高分推荐   calc_high_rating_rank()  — 纯评分降序
  口碑推荐   calc_reputation_rank()   — 评分² × sqrt(评分人数)
  热门推荐   calc_hot_rank()          — 票房×0.6 + 评分人数×0.4
  性价比推荐  calc_value_rank()        — 评分 / 票价（数据不全时标记模拟数据）
  综合推荐   calc_comprehensive_rank() — 多因子加权

数据可用性说明（在映47部）：
  - rating:    34/47 (72%)  ✓
  - rating_count: 23/47 (49%)  ✓
  - box_office: 47/47 (100%) ✓
  - ticket_price: 23/47 (49%)  ⚠ 性价比模式用模拟数据
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
HOT_RATING_COUNT = 0.40       # 评分人数权重
HOT_BOX_OFFICE = 0.60         # 票房权重（在映全有票房，提权）

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
    """高分推荐：纯评分降序。

    算法：评分降序，无评分排在末尾。
    数据源：rating 字段（34/47 在映有数据）
    """
    print(f"[DEBUG_STEP_3] calc_high_rating_rank input: {len(movies)} movies")
    scored = [dict(m) for m in movies if m.get("rating", 0) > 0]
    print(f"[DEBUG_STEP_3]   after filter (rating>0): {len(scored)} movies")
    if scored:
        print(f"[DEBUG_STEP_3]   before sort - first 5: {[(m.get('title','?')[:8], m.get('rating')) for m in scored[:5]]}")
        print(f"[DEBUG_STEP_3]   before sort - last 5: {[(m.get('title','?')[:8], m.get('rating')) for m in scored[-5:]]}")
    scored.sort(key=lambda m: m["rating"], reverse=True)
    if scored:
        print(f"[DEBUG_STEP_3]   after sort - first 5: {[(m.get('title','?')[:8], m.get('rating')) for m in scored[:5]]}")
    return scored


# ──────────────────── 口碑推荐 ────────────────────

def calc_reputation_rank(movies: list[dict]) -> list[dict]:
    """口碑推荐：评分² × sqrt(评分人数)。

    算法：
      - 评分²：高分口碑放大
      - sqrt(人数)：对数压缩
      - 无评分人数时降级为评分×票房系数

    数据源：rating + rating_count（23/47 在映有评分人数）
    """
    def _score(m: dict) -> float:
        r = m.get("rating") or 0
        c = m.get("rating_count") or 0
        bo = m.get("box_office") or 0
        if r <= 0:
            return 0
        if c > 0:
            return (r / MAX_RATING) ** REP_RATING_POWER * (c ** REP_COUNT_DAMP + 1)
        # 无评分人数时用票房缩放作为替代热度指标
        return (r / MAX_RATING) ** REP_RATING_POWER * (min(bo, 500000) / 500000 * 100 + 1)

    scored = [dict(m) for m in movies if m.get("rating", 0) > 0]
    scored.sort(key=_score, reverse=True)
    return scored


# ──────────────────── 热门推荐 ────────────────────

def calc_hot_rank(movies: list[dict]) -> list[dict]:
    """热门推荐：票房×0.6 + 评分人数×0.4。

    算法：
      - 票房：反映市场热度（在映全有数据）
      - 评分人数：反映关注热度
      - 无评分人数时纯用票房

    数据源：box_office（47/47）+ rating_count（23/47）
    """
    max_box = max((m.get("box_office") or 0) for m in movies) or 1
    max_count = max((m.get("rating_count") or 0) for m in movies) or 1

    def _score(m: dict) -> float:
        bo = (m.get("box_office") or 0) / max_box
        nc = (m.get("rating_count") or 0) / max_count
        if m.get("rating_count", 0) > 0:
            return bo * HOT_BOX_OFFICE + nc * HOT_RATING_COUNT
        return bo  # 无评分人数时纯票房

    scored = list(movies)  # 所有在映电影都有票房
    scored.sort(key=_score, reverse=True)
    return scored


# ──────────────────── 性价比推荐 ────────────────────

def calc_value_rank(movies: list[dict]) -> list[dict]:
    """性价比推荐：(评分得分 / 票价系数)。

    算法：
      value_score = (rating/MAX_RATING) / (price_norm + 0.01)
      price_norm = ticket_price / max_price

    数据源：rating（34/47）+ ticket_price（23/47）
    注意：约半数在映电影无票价数据，无票价电影降级使用
    同评分均值票价估算（标记为模拟数据）。
    """
    # 计算有票价电影的平均票价用于估算
    priced_movies = [m for m in movies if m.get("ticket_price", 0) > 0]
    avg_price = (
        sum(m.get("ticket_price", 0) for m in priced_movies) / len(priced_movies)
        if priced_movies else 45.0
    )

    max_price = max((m.get("ticket_price") or avg_price) for m in movies) or avg_price

    results = []
    for m in movies:
        movie = dict(m)
        r = movie.get("rating") or 0
        p = movie.get("ticket_price") or 0

        if r <= 0:
            movie["value_score"] = 0
            movie["value_is_simulated"] = False
            results.append(movie)
            continue

        price_norm = (p / max_price) if p > 0 else (avg_price / max_price)
        value = (r / MAX_RATING) / (price_norm + 0.01)

        movie["value_score"] = round(value, 4)
        movie["value_is_simulated"] = (p <= 0)
        results.append(movie)

    scored = [m for m in results if m.get("value_score", 0) > 0]
    scored.sort(key=lambda m: m["value_score"], reverse=True)
    return scored


# ──────────────────── 综合推荐 ────────────────────

def calc_comprehensive_rank(movies: list[dict]) -> list[dict]:
    """综合推荐：多因子加权。

    公式：
      comprehensive = rating_norm × 0.35
                    + popularity_norm × 0.25
                    + reputation_norm × 0.25
                    - price_norm × 0.15

    数据源：rating + rating_count + box_office + ticket_price
    """
    if not movies:
        return []

    max_count = max((m.get("rating_count") or 0) for m in movies) or 1

    results = []
    for m in movies:
        movie = dict(m)
        r = m.get("rating") or 0
        c = m.get("rating_count") or 0
        p = m.get("ticket_price") or 0

        rating_norm = r / MAX_RATING
        popularity_norm = min(c, MAX_RATING_COUNT) / MAX_RATING_COUNT

        # 口碑因子
        raw_rep = (r / MAX_RATING) ** REP_RATING_POWER * (c ** REP_COUNT_DAMP + 1)
        max_raw = (1.0) ** REP_RATING_POWER * (max_count ** REP_COUNT_DAMP + 1) or 1
        reputation_norm = raw_rep / max_raw

        price_norm = min(p, MAX_PRICE) / MAX_PRICE if p > 0 else 0

        if r > 0:
            if p > 0:
                comprehensive = (
                    rating_norm * WEIGHT_RATING
                    + popularity_norm * WEIGHT_POPULARITY
                    + reputation_norm * WEIGHT_REPUTATION
                    + price_norm * WEIGHT_PRICE
                )
            else:
                # 无票价：权重重新分配
                adj = WEIGHT_RATING + WEIGHT_POPULARITY + WEIGHT_REPUTATION + abs(WEIGHT_PRICE)
                comprehensive = (
                    rating_norm * (WEIGHT_RATING + abs(WEIGHT_PRICE) * 0.5) / adj
                    + popularity_norm * WEIGHT_POPULARITY / adj
                    + reputation_norm * WEIGHT_REPUTATION / adj
                )
        else:
            comprehensive = 0

        movie["comprehensive_score"] = round(comprehensive * 10, 1)
        results.append(movie)

    results.sort(key=lambda m: m.get("comprehensive_score") or 0, reverse=True)
    return results


# ──────────────────── 兼容：ComprehensiveScorer 类 ────────────────────

class ComprehensiveScorer:
    """综合评分计算器（旧接口，保持向后兼容）。"""

    def __init__(self, movies: list[dict]) -> None:
        self.movies = movies

    def calc_scores(self) -> list[dict]:
        return calc_comprehensive_rank(self.movies)
