"""
电影数据降级获取模块
==================
多源数据获取，按优先级降级：
  1. 豆瓣公开页面（需 douban_id）
  2. 猫眼 H5 移动端接口（需 maoyan_id，反爬弱）

用法：
    from crawler.movie_data_fallback import DoubanAPI, get_summary_from_maoyan, get_reviews_from_maoyan
    summary = get_summary_from_maoyan("1522535")
    reviews = get_reviews_from_maoyan("1522535", limit=3)
"""

import logging
import re
from typing import Optional

import requests

logger = logging.getLogger("MovieDataFallback")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
    "KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)
TIMEOUT = 8


# ═══════════════════════════════════════════════════════════
# 豆瓣 API（静态页面爬取，需 douban_id）
# ═══════════════════════════════════════════════════════════

class DoubanAPI:
    """豆瓣电影数据接口（从公开页面抓取）。"""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://movie.douban.com/",
        })

    def get_summary(self, douban_id: str) -> Optional[str]:
        """获取电影剧情简介（从豆瓣公开页面）。"""
        if not douban_id:
            return None

        try:
            url = f"https://movie.douban.com/subject/{douban_id}/"
            resp = self.session.get(url, timeout=TIMEOUT)
            if resp.status_code != 200:
                logger.warning("[DOUBAN] 页面请求失败: HTTP %d", resp.status_code)
                return None

            match = re.search(
                r'<span\s+property="v:summary"[^>]*>(.*?)</span>',
                resp.text, re.DOTALL,
            )
            if match:
                text = re.sub(r'<[^>]+>', '', match.group(1))
                text = re.sub(r'\s+', ' ', text).strip()
                return text if text else None
            return None

        except Exception as e:
            logger.debug("[DOUBAN] 获取摘要失败: %s", e)
            return None

    def get_reviews(self, douban_id: str, limit: int = 3) -> list[dict]:
        """获取豆瓣电影热门短评（前 N 条）。"""
        if not douban_id:
            return []

        try:
            url = f"https://movie.douban.com/subject/{douban_id}/comments?status=P"
            resp = self.session.get(url, timeout=TIMEOUT)
            if resp.status_code != 200:
                return []

            reviews: list[dict] = []
            for item in re.finditer(
                r'<span class="comment-info">(.*?)</span>\s*'
                r'<span class="short">(.*?)</span>',
                resp.text, re.DOTALL,
            ):
                if len(reviews) >= limit:
                    break
                author_match = re.search(r'alt="([^"]+)"', item.group(1))
                rating_match = re.search(r'allstar(\d+)', item.group(1))
                author = author_match.group(1) if author_match else "匿名"
                rating = int(rating_match.group(1)) // 10 if rating_match else 0
                content = re.sub(r'<[^>]+>', '', item.group(2)).strip()
                reviews.append({"author": author, "rating": rating, "content": content})

            logger.info("[DOUBAN] 获取短评 %d 条 (douban_id=%s)", len(reviews), douban_id)
            return reviews

        except Exception as e:
            logger.debug("[DOUBAN] 获取短评失败: %s", e)
            return []

    def close(self) -> None:
        self.session.close()


# ═══════════════════════════════════════════════════════════
# 猫眼 H5 移动端接口（反爬弱，需 maoyan_id）
# ═══════════════════════════════════════════════════════════

def get_summary_from_maoyan(maoyan_id: str) -> Optional[str]:
    """从猫眼 H5 接口获取剧情简介。

    Args:
        maoyan_id: 猫眼电影 ID

    Returns:
        剧情简介文本，失败返回 None
    """
    if not maoyan_id:
        return None

    try:
        url = f"https://m.maoyan.com/ajax/movie?movieId={maoyan_id}"
        headers = {
            "User-Agent": MOBILE_UA,
            "Referer": "https://m.maoyan.com/",
            "Accept": "application/json",
        }
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
        if resp.status_code != 200:
            logger.warning("[MAOYAN_H5] 接口请求失败: HTTP %d", resp.status_code)
            return None

        data = resp.json()
        summary = data.get("data", {}).get("movie", {}).get("summary", "")
        summary = summary.strip() if summary else ""

        if summary:
            logger.info("[MAOYAN_H5] 获取简介成功 (maoyan_id=%s, 长度=%d)", maoyan_id, len(summary))
            return summary
        return None

    except Exception as e:
        logger.debug("[MAOYAN_H5] 获取简介失败: %s", e)
        return None


def get_reviews_from_maoyan(maoyan_id: str, limit: int = 3) -> list[dict]:
    """从猫眼 H5 接口获取短评。

    Args:
        maoyan_id: 猫眼电影 ID
        limit: 返回条数

    Returns:
        [{"author": str, "rating": int (1-5), "content": str}, ...]
    """
    if not maoyan_id:
        return []

    try:
        url = f"https://m.maoyan.com/ajax/movie?movieId={maoyan_id}"
        headers = {
            "User-Agent": MOBILE_UA,
            "Referer": "https://m.maoyan.com/",
            "Accept": "application/json",
        }
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
        if resp.status_code != 200:
            logger.warning("[MAOYAN_H5] 短评请求失败: HTTP %d", resp.status_code)
            return []

        data = resp.json()
        comments = data.get("data", {}).get("comments", {}).get("list", [])
        if not comments:
            # fallback: 尝试独立短评接口
            try:
                url2 = f"https://m.maoyan.com/mmdb/comments/v1/movie/{maoyan_id}.json?limit={limit}&offset=0"
                resp2 = requests.get(url2, headers=headers, timeout=TIMEOUT)
                if resp2.status_code == 200:
                    data2 = resp2.json()
                    comments = data2.get("data", {}).get("comments", []) or \
                              data2.get("data", {}).get("list", []) or []
            except Exception:
                pass

        reviews = []
        for c in comments[:limit]:
            nick = c.get("nick") or c.get("nickName", "匿名")
            score_raw = c.get("score", 0)
            rating = score_raw // 2 if score_raw else 0  # 猫眼2-10分 → 1-5星
            content = c.get("content", "")

            if content.strip():
                reviews.append({
                    "author": nick,
                    "rating": min(rating, 5),
                    "content": content.strip(),
                })

        logger.info("[MAOYAN_H5] 获取短评 %d 条 (maoyan_id=%s)", len(reviews), maoyan_id)
        return reviews

    except Exception as e:
        logger.debug("[MAOYAN_H5] 获取短评失败: %s", e)
        return []
