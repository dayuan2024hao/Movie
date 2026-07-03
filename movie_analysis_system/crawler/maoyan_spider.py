"""
猫眼爬虫
========
从猫眼电影爬取**当前正在热映**和**即将上映**的电影数据。

访问链接：
  正在热映列表：https://www.maoyan.com/films?showType=1&offset=0
  即将上映列表：https://www.maoyan.com/films?showType=2&offset=0

翻页策略：
  - offset 从 0 开始，步长 20
  - 当某页返回结果 < 20 时停止
  - 目标：≥15 部热映电影

猫眼页面真实结构：
  <dd>
    <div class="movie-item film-channel">
      <div class="movie-poster">
        <img data-src="https://...真实海报.jpg?imageView2/1/w/320/h/440"/>
      </div>
      <div class="movie-item-hover">
        <a href="/films/1522535">
        <div class="movie-hover-title">
          <span class="name">电影名</span>
          <span class="score"><i class="integer">9.</i><i class="fraction">6</i></span>
        </div>
        <div class="movie-hover-title">
          <span class="hover-tag">类型:</span>喜剧 / 志怪
        </div>
        ...
      </div>
    </div>
  </dd>
"""

import logging
import random
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("MaoyanSpider")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
]

REQUEST_TIMEOUT = 10
MIN_DELAY = 3.0
MAX_DELAY = 8.0
MAX_RETRIES = 3
PAGE_SIZE = 20          # 每页 20 部


class MaoyanSpider:
    """猫眼爬虫，支持翻页。"""

    def __init__(self) -> None:
        self.session = requests.Session()

    def get_showing_list(self, limit: int = 30) -> list[dict]:
        """爬取猫眼正在热映电影列表（翻页）。"""
        return self._crawl_list(
            "https://www.maoyan.com/films", {"showType": "1"}, "showing", limit
        )

    def get_coming_list(self, limit: int = 20) -> list[dict]:
        """爬取猫眼即将上映电影列表（翻页）。"""
        return self._crawl_list(
            "https://www.maoyan.com/films", {"showType": "2"}, "coming_soon", limit
        )

    def _crawl_list(self, url: str, params: dict, status: str, limit: int) -> list[dict]:
        """翻页爬取猫眼电影列表。"""
        all_movies: list[dict] = []

        for offset in range(0, limit, PAGE_SIZE):
            params_with_offset = {**params, "offset": str(offset)}
            html = self._request(url, params=params_with_offset)
            if html is None:
                logger.warning("请求失败（offset=%d），停止翻页", offset)
                break

            page_movies = self._parse_movies(html, status)
            if not page_movies:
                logger.info("offset=%d 无更多电影，停止翻页", offset)
                break

            all_movies.extend(page_movies)
            logger.info(
                "[CRAWL] %s offset=%d: 本页 %d 部，累计 %d 部",
                status, offset, len(page_movies), len(all_movies),
            )

            if len(page_movies) < PAGE_SIZE:
                break  # 最后一项

            # 页间延迟（3~6 秒）
            if offset + PAGE_SIZE < limit:
                time.sleep(random.uniform(3, 6))

        logger.info("[CRAWL] 已获取%s电影 %d 部（目标≥%d）", status, len(all_movies), limit)
        return all_movies[:limit]

    def _parse_movies(self, html: str, status: str) -> list[dict]:
        """解析 HTML，提取电影列表。"""
        soup = BeautifulSoup(html, "lxml")
        movies: list[dict] = []

        for dd in soup.select("dd"):
            try:
                hover = dd.select_one(".movie-item-hover")
                if not hover:
                    continue

                movie: dict = {"showing_status": status, "genre": "剧情"}

                # ── 标题 ──
                name_div = hover.select_one(".movie-hover-title .name")
                if not name_div:
                    continue
                movie["title"] = name_div.text.strip()

                # ── maoyan_id ──
                film_link = hover.select_one('a[href*="/films/"]')
                if film_link:
                    match = re.search(r"/films/(\d+)", film_link.get("href", ""))
                    if match:
                        movie["maoyan_id"] = match.group(1)

                # ── 评分（整数 + 小数） ──
                score_int = hover.select_one(".score .integer")
                score_frac = hover.select_one(".score .fraction")
                if score_int and score_frac:
                    try:
                        movie["rating"] = float(
                            score_int.text.strip() + score_frac.text.strip()
                        )
                    except ValueError:
                        pass

                # ── 类型 ──
                for ht in hover.select(".movie-hover-title"):
                    tag = ht.select_one(".hover-tag")
                    if tag and "类型" in tag.text:
                        raw = ht.text.replace(tag.text, "").strip()
                        movie["genre"] = raw.replace(" / ", ";") if raw else "剧情"
                        break

                # ── 主演 ──
                for ht in hover.select(".movie-hover-title"):
                    tag = ht.select_one(".hover-tag")
                    if tag and "主演" in tag.text:
                        raw = ht.text.replace(tag.text, "").strip()
                        movie["actors"] = raw.replace(" / ", ";")[:80]
                        break

                # ── 上映日期 ──
                brief = hover.select_one(".movie-hover-brief")
                if brief:
                    tag = brief.select_one(".hover-tag")
                    if tag:
                        movie["release_date"] = brief.text.replace(tag.text, "").strip()[:10]

                # ── 海报（保留完整 URL，包括 CDN 必需的 query 参数） ──
                img = dd.select_one(".movie-poster img[data-src]")
                if img:
                    src = img["data-src"].strip()
                    if src.startswith("http"):
                        movie["poster_url"] = src  # 保留完整 URL
                    elif src.startswith("//"):
                        movie["poster_url"] = "https:" + src  # 保留完整 URL

                movies.append(movie)

            except (AttributeError, ValueError) as e:
                logger.debug("解析电影项失败: %s", e)
                continue

        return movies

    def _request(self, url: str, params: Optional[dict] = None) -> Optional[str]:
        """发送 HTTP 请求（支持重试 + 反爬）。"""
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.maoyan.com/",
        }

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
                resp = self.session.get(
                    url, params=params, headers=headers, timeout=REQUEST_TIMEOUT
                )
                if resp.status_code != 200:
                    logger.warning("HTTP %d (尝试 %d/%d)", resp.status_code, attempt, MAX_RETRIES)
                    if attempt < MAX_RETRIES:
                        time.sleep(2 ** attempt)
                    continue
                resp.encoding = "utf-8"
                return resp.text
            except requests.RequestException as e:
                logger.warning("请求失败 (尝试 %d/%d): %s", attempt, MAX_RETRIES, e)
                if attempt < MAX_RETRIES:
                    time.sleep(2 ** attempt)

        return None

    def _mock_data(self, status: str) -> list[dict]:
        """当爬虫不可用时返回模拟数据。"""
        logger.info("使用模拟 %s 数据", status)
        if status == "coming_soon":
            return []
        return [
            {"title": "默杀", "genre": "悬疑;犯罪", "rating": 9.5, "actors": "王传君;张钧甯",
             "showing_status": "showing"},
            {"title": "神偷奶爸4", "genre": "动画;喜剧", "rating": 9.4, "actors": "史蒂夫·卡瑞尔",
             "showing_status": "showing"},
            {"title": "头脑特工队2", "genre": "动画;冒险", "rating": 9.3, "actors": "艾米·波勒",
             "showing_status": "showing"},
        ]

    def get_ticket_price(self, maoyan_id: str) -> Optional[dict]:
        """爬取猫眼电影详情页，提取票价区间（静态 HTML 方式，有限数据）。"""
        url = f"https://www.maoyan.com/films/{maoyan_id}"
        html = self._request(url)
        if html is None:
            return None

        soup = BeautifulSoup(html, "lxml")
        result: dict = {}

        try:
            price_el = soup.select_one(".price")
            if price_el:
                text = price_el.text.strip()
                nums = re.findall(r"[\d.]+", text)
                if len(nums) >= 2:
                    result["price_min"] = float(nums[0])
                    result["price_max"] = float(nums[1])
                elif len(nums) == 1:
                    result["price_min"] = result["price_max"] = float(nums[0])
                return result

            price_el = soup.select_one(".buy-ticket-price, .price-min")
            if price_el:
                nums = re.findall(r"[\d.]+", price_el.text)
                if nums:
                    result["price_min"] = float(nums[0])
                    return result
        except Exception as e:
            logger.warning("解析票价失败 (%s): %s", maoyan_id, e)

        return None

    def close(self) -> None:
        self.session.close()
