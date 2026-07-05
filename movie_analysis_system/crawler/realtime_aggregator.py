"""
实时数据聚合器
==============
多源搜索 + 电影详情 + 实时票价，LRU缓存(TTL=30min)

数据流：
  搜索：  并发请求猫眼H5 + 豆瓣 → 去重合并
  详情：  猫眼H5接口 → LRU缓存 → 降级到 movie_data_fallback

日志要求：
  每次请求打印 [REALTIME] {method} {url} {status_code} {耗时:.2f}s
  降级时打印 [FALLBACK] H5 failed for {id}, using offline data
"""

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from crawler.movie_data_fallback import (
    get_summary_from_maoyan,
    get_reviews_from_maoyan,
)

logger = logging.getLogger("RealtimeAggregator")

MOBILE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    ),
    "Referer": "https://m.maoyan.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "X-Requested-With": "XMLHttpRequest",
}

DOUBAN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

TIMEOUT = 8
CACHE_TTL = 1800  # 30分钟
CACHE_MAXSIZE = 256


# ═══════════════════════════════════════════════
#  TTL 缓存
# ═══════════════════════════════════════════════

class TTLCache:
    """内存缓存，TTL 过期自动失效。"""

    def __init__(self, maxsize: int = CACHE_MAXSIZE, ttl: int = CACHE_TTL) -> None:
        self.maxsize = maxsize
        self.ttl = ttl
        self._data: dict[str, tuple[float, object]] = {}

    def get(self, key: str):
        if key in self._data:
            ts, value = self._data[key]
            if time.time() - ts < self.ttl:
                return value
            del self._data[key]
        return None

    def set(self, key: str, value: object) -> None:
        if len(self._data) >= self.maxsize:
            oldest = min(self._data, key=lambda k: self._data[k][0])
            del self._data[oldest]
        self._data[key] = (time.time(), value)

    def clear(self) -> None:
        self._data.clear()


# ═══════════════════════════════════════════════
#  实时聚合器
# ═══════════════════════════════════════════════

class RealtimeAggregator:
    """实时电影数据聚合器。"""

    def __init__(self) -> None:
        self.cache = TTLCache()

        # 猫眼移动端 session（H5 API）
        self._maoyan_session = requests.Session()
        self._maoyan_session.headers.update(MOBILE_HEADERS)
        self._maoyan_session.cookies.set("X-CSRF-TOKEN", "")
        self._maoyan_session.cookies.set("_lxsdk_cuid", "")
        # 增大连接池避免并发阻塞
        adapter = HTTPAdapter(
            pool_connections=20, pool_maxsize=20,
            max_retries=Retry(total=1, backoff_factor=0.5),
        )
        self._maoyan_session.mount("https://", adapter)

        # 猫眼桌面站 session（网页解析兜底）
        self._desktop_session = requests.Session()
        self._desktop_session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.maoyan.com/",
        })
        desktop_adapter = HTTPAdapter(
            pool_connections=10, pool_maxsize=10,
            max_retries=Retry(total=1, backoff_factor=0.5),
        )
        self._desktop_session.mount("https://", desktop_adapter)

        self._douban_session = requests.Session()
        self._douban_session.headers.update(DOUBAN_HEADERS)

        self._executor = ThreadPoolExecutor(max_workers=8)

    # ──────────── 猫眼 H5 搜索 ────────────

    def search_maoyan(self, keyword: str) -> list[dict]:
        """猫眼H5搜索。

        Returns:
            [{title, maoyan_id, rating, poster_url, year, source:"猫眼"}, ...]
        """
        if not keyword or not keyword.strip():
            return []
        try:
            url = f"https://m.maoyan.com/ajax/search?keyword={requests.utils.quote(keyword.strip())}"
            t0 = time.time()
            resp = self._maoyan_session.get(url, timeout=TIMEOUT)
            elapsed = time.time() - t0
            logger.info("[REALTIME] search_maoyan → %s status=%d (%.2fs)",
                        keyword.strip(), resp.status_code, elapsed)

            if resp.status_code != 200:
                logger.warning("[REALTIME] 猫眼搜索 HTTP %d", resp.status_code)
                return self._fallback_search(keyword)

            data = resp.json()
            movies_list = data.get("movies", data.get("list", []))
            if not movies_list:
                logger.info("[REALTIME] 猫眼搜索无结果: %s", keyword)
                return self._fallback_search(keyword)

            results = []
            for item in movies_list[:10]:
                # 猫眼搜索结果可能嵌套在 movieList 或直接返回
                m = item.get("movie", item)
                maoyan_id = str(m.get("id", ""))
                if not maoyan_id or not maoyan_id.isdigit():
                    continue

                poster = m.get("img", m.get("poster", ""))
                if poster and poster.startswith("//"):
                    poster = "https:" + poster

                year = m.get("year", "")
                if isinstance(year, int):
                    year = str(year)

                results.append({
                    "title": m.get("title", "").strip(),
                    "maoyan_id": maoyan_id,
                    "rating": m.get("score", m.get("rating", 0)) or 0,
                    "poster_url": poster,
                    "year": year,
                    "source": "猫眼",
                })

            logger.info("[REALTIME] 猫眼搜索: %s → %d 条", keyword, len(results))
            return results

        except requests.RequestException as e:
            logger.warning("[REALTIME] 猫眼搜索异常: %s (%s)", keyword, e)
            return self._fallback_search(keyword)

    def _fallback_search(self, keyword: str) -> list[dict]:
        """搜索降级：从本地数据库模糊匹配（不要求 maoyan_id）。"""
        logger.info("[FALLBACK] 搜索降级: 本地模糊匹配 '%s'", keyword)
        try:
            from database.db_manager import DatabaseManager
            db = DatabaseManager()
            total, movies = db.query_movies(
                keyword=keyword, limit=20,
                sort_by="rating", sort_order="DESC",
            )
            results = []
            for m in movies:
                maoyan_id = str(m.get("maoyan_id", "") or "")
                douban_id = str(m.get("douban_id", "") or "")
                has_maoyan = maoyan_id.isdigit() and len(maoyan_id) >= 5
                has_douban = douban_id.isdigit() and len(douban_id) >= 5
                source = "猫眼" if has_maoyan else ("豆瓣" if has_douban else "本地数据")

                results.append({
                    "title": m.get("title", ""),
                    "maoyan_id": maoyan_id if has_maoyan else "",
                    "douban_id": douban_id if has_douban else "",
                    "rating": m.get("rating") or 0,
                    "poster_url": m.get("poster_url", ""),
                    "year": (m.get("release_date") or "")[:4],
                    "source": source,
                })
            logger.info("[FALLBACK] 本地搜索结果: %d 条 (总匹配 %d)", len(results), total)
            return results
        except Exception as e:
            logger.warning("[FALLBACK] 本地搜索失败: %s", e)
            return []

    # ──────────── 豆瓣搜索 ────────────

    def search_douban(self, keyword: str) -> list[dict]:
        """豆瓣搜索（静态页面解析）。

        Returns:
            [{title, douban_id, rating, poster_url, year, source:"豆瓣"}, ...]
        """
        if not keyword or not keyword.strip():
            return []
        try:
            url = ("https://search.douban.com/movie/subject_search?"
                   f"search_text={requests.utils.quote(keyword.strip())}")
            t0 = time.time()
            resp = self._douban_session.get(url, timeout=TIMEOUT)
            elapsed = time.time() - t0
            logger.info("[REALTIME] search_douban → %s status=%d (%.2fs)",
                        keyword.strip(), resp.status_code, elapsed)

            if resp.status_code != 200:
                return []

            results = []
            # 解析搜索结果卡片
            for item in re.finditer(
                r'<div class="item-root[^"]*"\s*.*?'
                r'<a[^>]*href="https?://movie\.douban\.com/subject/(\d+)/[^"]*"[^>]*>'
                r'\s*<img[^>]*src="([^"]*)"[^>]*title="([^"]*)"',
                resp.text, re.DOTALL,
            ):
                douban_id = item.group(1)
                poster = item.group(2)
                title = item.group(3)

                # 从上下文中提取评分
                rating_match = re.search(
                    rf'<span class="rating_nums">([\d.]+)</span>',
                    resp.text[item.start():item.end() + 500],
                )
                rating = float(rating_match.group(1)) if rating_match else 0

                # 提取年份
                year_match = re.search(
                    rf'<span class="date">(\d{{4}})</span>',
                    resp.text[item.start():item.end() + 200],
                )
                year = year_match.group(1) if year_match else ""

                results.append({
                    "title": title.strip(),
                    "douban_id": douban_id,
                    "rating": rating,
                    "poster_url": poster,
                    "year": year,
                    "source": "豆瓣",
                })

                if len(results) >= 5:
                    break

            logger.info("[REALTIME] 豆瓣搜索: %s → %d 条", keyword, len(results))
            return results

        except requests.RequestException as e:
            logger.warning("[REALTIME] 豆瓣搜索异常: %s", e)
            return []
        except Exception as e:
            logger.debug("[REALTIME] 豆瓣搜索解析失败: %s", e)
            return []

    # ──────────── 多源合并搜索 ────────────

    def search_all(self, keyword: str) -> list[dict]:
        """并发搜索猫眼 + 豆瓣，去重合并。

        去重规则：
          - 标题 + 年份 双重校验（同标题不同年份 → 不同电影）
          - 合并优先级：猫眼 > 豆瓣

        Returns:
            [{title, maoyan_id?, douban_id?, rating, poster_url,
              year, source:"猫眼"|"豆瓣"|"猫眼+豆瓣"}, ...]
        """
        if not keyword or not keyword.strip():
            return []

        keyword = keyword.strip()
        cache_key = f"search:{keyword}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.info("[REALTIME] search_all: 缓存命中 '%s' (%d 条)", keyword, len(cached))
            return cached

        t0 = time.time()

        # 并发请求
        maoyan_future = self._executor.submit(self.search_maoyan, keyword)
        douban_future = self._executor.submit(self.search_douban, keyword)

        maoyan_results = []
        douban_results = []
        try:
            maoyan_results = maoyan_future.result(timeout=15) or []
        except Exception as e:
            logger.warning("[REALTIME] 猫眼搜索超时: %s", e)
        try:
            douban_results = douban_future.result(timeout=15) or []
        except Exception as e:
            logger.warning("[REALTIME] 豆瓣搜索超时: %s", e)

        # 去重合并（按 标题+年份 分组，猫眼优先）
        merged: dict[str, dict] = {}

        def merge_key(item: dict) -> str:
            return f"{item['title']}|{item.get('year', '')}"

        # 先处理猫眼（优先级高）
        for item in maoyan_results:
            key = merge_key(item)
            if key not in merged:
                item["maoyan_id"] = item.get("maoyan_id", "")
                item["douban_id"] = ""
                merged[key] = item

        # 再处理豆瓣（补充猫眼没有的字段）
        for item in douban_results:
            key = merge_key(item)
            if key in merged:
                # 补充豆瓣ID
                merged[key]["douban_id"] = item.get("douban_id", "")
                merged[key]["source"] = "猫眼+豆瓣"
                if not merged[key].get("rating"):
                    merged[key]["rating"] = item.get("rating", 0)
            else:
                item["maoyan_id"] = ""
                item["douban_id"] = item.get("douban_id", "")
                merged[key] = item

        results = list(merged.values())
        elapsed = time.time() - t0
        logger.info(
            "[REALTIME] search_all: 并发搜索 '%s' 完成 (猫眼:%d 豆瓣:%d 合并:%d) [%.2fs]",
            keyword, len(maoyan_results), len(douban_results), len(results), elapsed,
        )

        self.cache.set(cache_key, results)
        return results

    # ──────────── 电影详情 ────────────

    def _fetch_h5(self, maoyan_id: str) -> Optional[dict]:
        """从猫眼H5获取电影详情JSON。"""
        cache_key = f"detail:{maoyan_id}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            url = f"https://m.maoyan.com/ajax/movie?movieId={maoyan_id}"
            t0 = time.time()
            resp = self._maoyan_session.get(url, timeout=TIMEOUT)
            elapsed = time.time() - t0
            logger.info("[REALTIME] GET %s status=%d (%.2fs)",
                        url, resp.status_code, elapsed)

            if resp.status_code != 200:
                logger.warning("[REALTIME] 详情H5 HTTP %d for %s", resp.status_code, maoyan_id)
                return None

            data = resp.json()
            if not data or data.get("data", {}).get("movie", {}).get("id") is None:
                logger.warning("[REALTIME] 详情H5 空JSON for %s", maoyan_id)
                logger.info("[FALLBACK] H5 failed for %s, using offline data", maoyan_id)
                return None

            self.cache.set(cache_key, data)
            return data

        except requests.RequestException as e:
            logger.warning("[REALTIME] 详情H5 异常 %s: %s", maoyan_id, e)
            logger.info("[FALLBACK] H5 failed for %s, using offline data", maoyan_id)
            return None

    def get_ticket_price(self, maoyan_id: str,
                         movie_title: str = "") -> Optional[float]:
        """获取实时最低票价。

        多级策略：
          1) 直接 H5 API 尝试（桌面站 ID 可能不兼容）
          2) 搜索电影标题获取 H5 兼容 ID，再用 H5 API 获取票价
          3) 桌面站 HTML 正则尝试
          4) 基于类型估算默认票价（兜底）

        Log:
            [PRICE] movie=name price=XX source=h5/search-h5/html/estimated
        """
        if not maoyan_id:
            return self._estimate_price_by_title(movie_title)

        movie_name = movie_title or f"id:{maoyan_id}"
        price = None
        source = ""

        # 1) H5 API 直接尝试（可能因桌面站 ID 不兼容而 404）
        data = self._fetch_h5(maoyan_id)
        if data is not None:
            price, source = self._parse_price_from_h5(data, "h5")

        # 2) 搜索标题 → 获取 H5 兼容 ID → 获取票价
        if price is None and movie_title:
            logger.info("[PRICE] %s: H5直连失败, 尝试搜索标题获取H5 ID", movie_name)
            h5_id = self._find_h5_id_by_title(movie_title)
            if h5_id and h5_id != maoyan_id:
                logger.info("[PRICE] %s: 找到H5 ID=%s, 重新获取票价", movie_name, h5_id)
                data = self._fetch_h5(h5_id)
                if data is not None:
                    price, source = self._parse_price_from_h5(data, "search-h5")

        # 3) 桌面站 HTML 兜底
        if price is None:
            try:
                url = f"https://www.maoyan.com/films/{maoyan_id}"
                resp = self._desktop_session.get(url, timeout=8)
                if resp.status_code == 200:
                    patterns = [
                        r'<span[^>]*class=["\']price["\'][^>]*>(\d+)</span>',
                        r'[¥￥]\s*(\d+)\s*起',
                        r'最低[价票].*?(\d+)',
                    ]
                    for pat in patterns:
                        m = re.search(pat, resp.text[:10000])
                        if m:
                            price = float(m.group(1))
                            source = "html"
                            break
            except Exception as e:
                logger.debug("[PRICE] 桌面站失败: %s", e)

        # 4) 基于类型估算
        if price is None and movie_title:
            price = self._estimate_price_by_title(movie_title)
            source = "estimated"

        if price and price > 0:
            logger.info("[PRICE] %s price=%.0f source=%s", movie_name, price, source)
            return price

        logger.info("[PRICE] %s: 所有数据源均不可获取票价", movie_name)
        return None

    def _find_h5_id_by_title(self, title: str) -> Optional[str]:
        """通过搜索获取电影在 H5 API 中的正确 ID。"""
        if not title:
            return None
        try:
            results = self.search_maoyan(title)
            if not results:
                return None
            # 精确匹配或按相关性取第一个
            for r in results:
                if r.get("title", "").strip() == title.strip():
                    return r.get("maoyan_id")
            # 返回第一个有效结果
            for r in results:
                mid = r.get("maoyan_id", "")
                if mid:
                    return mid
            return None
        except Exception as e:
            logger.debug("[PRICE] 搜索标题获取H5 ID失败: %s", e)
            return None

    @staticmethod
    def _parse_price_from_h5(data: dict, source_label: str) -> tuple:
        """从 H5 API 返回数据中解析票价。返回 (price, source) 或 (None, '')."""
        try:
            movie_data = data.get("data", {}).get("movie", {})
            show_info = movie_data.get("showInfo", {})
            if show_info:
                pt = show_info.get("price", "")
                if pt:
                    digits = re.findall(r'[\d.]+', str(pt))
                    if digits:
                        return float(digits[0]), source_label

            for key in ("lowestPrice", "minPrice"):
                val = movie_data.get(key, 0)
                if val:
                    return float(val), source_label

            cinemas = data.get("data", {}).get("cinemas", [])
            if cinemas:
                prices = [float(c.get("price", 0)) for c in cinemas
                          if c.get("price", 0)]
                if prices:
                    return min(prices), source_label
        except Exception as e:
            logger.debug("[PRICE] H5解析失败: %s", e)
        return None, ""

    def _estimate_price_by_title(self, title: str) -> Optional[float]:
        """基于电影类型估算默认票价（兜底策略）。"""
        if not title:
            return None
        try:
            # 从本地数据库获取同类型电影的平均票价
            from database.db_manager import DatabaseManager
            db = DatabaseManager()
            conn = db.get_connection()
            cursor = conn.cursor()

            # 先找这部电影的类型
            cursor.execute(
                "SELECT genre FROM movies WHERE title LIKE ? LIMIT 1",
                (f"%{title[:6]}%",),
            )
            row = cursor.fetchone()
            if not row:
                cursor.close()
                return None

            genre = row["genre"]
            if not genre:
                cursor.close()
                return None

            # 获取该类型电影的平均票价
            first_genre = genre.split(";")[0].split(",")[0].strip()
            cursor.execute(
                "SELECT AVG(ticket_price) FROM movies "
                "WHERE genre LIKE ? AND ticket_price > 0",
                (f"%{first_genre}%",),
            )
            avg = cursor.fetchone()[0]
            cursor.close()

            if avg and avg > 0:
                logger.info("[PRICE] 基于类型 '%s' 估算票价: %.0f", first_genre, avg)
                return round(avg, 0)

        except Exception as e:
            logger.debug("[PRICE] 估算票价失败: %s", e)
        return None

    def _scrape_price_from_desktop(self, maoyan_id: str) -> Optional[float]:
        """从猫眼桌面站 HTML 提取最低票价。"""
        try:
            url = f"https://www.maoyan.com/films/{maoyan_id}"
            t0 = time.time()
            resp = self._desktop_session.get(url, timeout=10)
            elapsed = time.time() - t0
            logger.info("[REALTIME] desktop_price %s status=%d (%.2fs)",
                        maoyan_id, resp.status_code, elapsed)

            if resp.status_code != 200:
                return None

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "lxml")

            # 尝试多个选择器
            selectors = [
                ".price", ".buy-ticket-price", ".price-min",
                ".stonefont", ".show-info .price",
            ]
            for sel in selectors:
                el = soup.select_one(sel)
                if el:
                    text = el.get_text(strip=True)
                    digits = re.findall(r'[\d.]+', text)
                    if digits:
                        return float(digits[0])

            # 正则备选
            patterns = [
                r'[¥￥]\s*(\d+)\s*起',
                r'[¥￥]\s*(\d+)\s*[~-]',
                r'最低[价票]\s*[¥￥]?\s*(\d+)',
            ]
            for pat in patterns:
                match = re.search(pat, resp.text)
                if match:
                    return float(match.group(1))

            return None

        except Exception as e:
            logger.debug("[REALTIME] 请求/解析失败 %s: %s", maoyan_id, e)
            return None

    def get_summary(self, maoyan_id: str) -> Optional[str]:
        """获取剧情简介（H5 → 降级）。"""
        # 先尝试H5
        data = self._fetch_h5(maoyan_id)
        if data:
            try:
                summary = data.get("data", {}).get("movie", {}).get("summary", "")
                if summary and summary.strip():
                    logger.info("[REALTIME] get_summary: %s summary_len=%d (接口返回)",
                                maoyan_id, len(summary.strip()))
                    return summary.strip()
            except Exception:
                pass

        # 降级到 movie_data_fallback
        logger.info("[FALLBACK] get_summary: %s H5无数据，使用离线数据", maoyan_id)
        return get_summary_from_maoyan(maoyan_id)

    def get_reviews(self, maoyan_id: str, limit: int = 3) -> list[dict]:
        """获取短评（H5 → 降级）。"""
        data = self._fetch_h5(maoyan_id)
        if data:
            try:
                comments = data.get("data", {}).get("comments", {}).get("list", [])
                if comments:
                    reviews = []
                    for c in comments[:limit]:
                        nick = c.get("nick", "匿名")
                        score_raw = c.get("score", 0)
                        rating = score_raw // 2 if score_raw else 0
                        content = c.get("content", "").strip()
                        if content:
                            reviews.append({
                                "author": nick,
                                "rating": min(rating, 5),
                                "content": content,
                            })
                    if reviews:
                        logger.info("[REALTIME] get_reviews: %s count=%d (接口返回)",
                                    maoyan_id, len(reviews))
                        return reviews
            except Exception:
                pass

        # 降级
        logger.info("[FALLBACK] get_reviews: %s H5无数据，使用离线数据", maoyan_id)
        return get_reviews_from_maoyan(maoyan_id, limit)

    def close(self) -> None:
        """释放资源。"""
        self._maoyan_session.close()
        self._desktop_session.close()
        self._douban_session.close()
        self._executor.shutdown(wait=False)
