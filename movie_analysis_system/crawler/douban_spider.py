"""
豆瓣爬虫
========
按电影名称搜索豆瓣获取评分信息，以及爬取电影详情页的完整数据。

访问链接：
  搜索：https://movie.douban.com/subject_search?search_text={电影名}
  详情：https://movie.douban.com/subject/{douban_id}/

反爬策略：
  - 随机 User-Agent（10 个浏览器 UA 池）
  - 请求间隔 1.0~3.0 秒
  - 超时 10 秒
  - 失败重试最多 3 次（间隔递增 2/4/8 秒）
"""

import logging
import random
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger("DoubanSpider")

# User-Agent 池
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/604.1",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Edge/120.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
    "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/118.0.0.0 Safari/537.36",
]

# 请求配置
REQUEST_TIMEOUT = 10
MIN_DELAY = 1.0
MAX_DELAY = 3.0
MAX_RETRIES = 3


class DoubanSpider:
    """豆瓣爬虫，支持按名称搜索和详情页爬取。"""

    def __init__(self) -> None:
        self.session = requests.Session()

    def search_movie(self, keyword: str) -> Optional[dict]:
        """按电影名称搜索豆瓣，返回第一条匹配结果。

        Args:
            keyword: 电影名称关键词

        Returns:
            匹配到的电影概要信息字典，或 None
        """
        url = "https://movie.douban.com/subject_search"
        params = {"search_text": keyword}
        html = self._request(url, params=params)
        if html is None:
            return None

        soup = BeautifulSoup(html, "lxml")
        # 搜索结果列表
        items = soup.select(".item")
        if not items:
            logger.warning("豆瓣搜索无结果: %s", keyword)
            return None

        for item in items[:3]:  # 只看前 3 条
            try:
                # 标题
                title_tag = item.select_one(".title a")
                if not title_tag:
                    continue
                title = title_tag.text.strip()

                # douban_id 从 URL 提取
                href = title_tag.get("href", "")
                match = re.search(r"/subject/(\d+)/", href)
                if not match:
                    continue
                douban_id = match.group(1)

                # 评分
                rating_tag = item.select_one(".rating_num")
                rating = float(rating_tag.text.strip()) if rating_tag else 0.0

                # 评分人数
                rating_count = 0
                pl_tag = item.select_one(".pl")
                if pl_tag:
                    count_match = re.search(r"(\d+)", pl_tag.text)
                    if count_match:
                        rating_count = int(count_match.group(1))

                # 简介信息（导演/演员/年份/地区/类型）
                abstract = ""
                bd_tag = item.select_one(".bd p")
                if bd_tag:
                    abstract = bd_tag.text.strip()

                logger.info("豆瓣搜索匹配: %s (id=%s, 评分=%.1f)", title, douban_id, rating)
                return {
                    "title": title,
                    "douban_id": douban_id,
                    "rating": rating,
                    "rating_count": rating_count,
                    "abstract": abstract,
                }
            except (AttributeError, ValueError) as e:
                logger.debug("解析搜索结果项失败: %s", e)
                continue

        return None

    def get_movie_detail(self, douban_id: str) -> Optional[dict]:
        """爬取豆瓣电影详情页的完整数据。

        Args:
            douban_id: 豆瓣电影 ID

        Returns:
            电影完整信息字典，或 None
        """
        url = f"https://movie.douban.com/subject/{douban_id}/"
        html = self._request(url)
        if html is None:
            return None

        soup = BeautifulSoup(html, "lxml")
        result: dict = {"douban_id": douban_id}

        try:
            # 标题
            title_tag = soup.select_one("h1 span[property='v:itemreviewed']")
            if title_tag:
                result["title"] = title_tag.text.strip()
            else:
                title_tag = soup.select_one("h1")
                if title_tag:
                    result["title"] = title_tag.text.strip()

            # 评分
            rating_tag = soup.select_one(".rating_num")
            if rating_tag:
                try:
                    result["rating"] = float(rating_tag.text.strip())
                except ValueError:
                    pass

            # 评分人数
            rating_count = 0
            rating_people = soup.select_one(".rating_people span")
            if rating_people:
                try:
                    rating_count = int(rating_people.text.strip())
                except ValueError:
                    pass
            result["rating_count"] = rating_count

            # 基本信息区 #info
            info_text = ""
            info_div = soup.select_one("#info")
            if info_div:
                info_text = info_div.get_text(" ", strip=True)

                # 导演
                director_tag = info_div.select_one("a[rel='v:directedBy']")
                if director_tag:
                    result["director"] = director_tag.text.strip()

                # 主演（取前 5）
                actor_tags = info_div.select("span.actor a")
                actors = [a.text.strip() for a in actor_tags if a.text.strip()]
                # 或者通过 "主演" 标签找
                if not actors:
                    for span in info_div.find_all("span", class_="pl"):
                        if "主演" in span.text:
                            actor_links = span.parent.find_all("a") if span.parent else []
                            actors = [a.text.strip() for a in actor_links][:5]
                            break
                if actors:
                    result["actors"] = ";".join(actors[:5])

                # 从 info 文本中提取其他字段
                # 类型
                genre_tags = info_div.select("span[property='v:genre']")
                if genre_tags:
                    result["genre"] = ";".join(g.text.strip() for g in genre_tags)

                # 日期和片长
                date_tag = info_div.select_one("span[property='v:initialReleaseDate']")
                if date_tag:
                    result["release_date"] = date_tag.text.strip()[:10]

                runtime_tag = info_div.select_one("span[property='v:runtime']")
                if runtime_tag:
                    try:
                        result["runtime"] = int(re.search(r"\d+", runtime_tag.text).group())
                    except (AttributeError, ValueError):
                        pass

                # 地区、语言等（从 info 文本正则提取）
                info_all = info_div.get_text(" ", strip=True)
                region_match = re.search(r"制片国家/地区:\s*([^\n]+)", info_all)
                if region_match:
                    result["region"] = region_match.group(1).strip()

                lang_match = re.search(r"语言:\s*([^\n]+)", info_all)
                if lang_match:
                    result["language"] = lang_match.group(1).strip()

            # 剧情简介
            summary_tag = soup.select_one(".related-info .all")
            if summary_tag:
                result["summary"] = summary_tag.text.strip()
            else:
                summary_tag = soup.select_one("#link-report-intra .all")
                if summary_tag:
                    result["summary"] = summary_tag.text.strip()
                else:
                    summary_tag = soup.select_one("span[property='v:summary']")
                    if summary_tag:
                        result["summary"] = summary_tag.text.strip()

            if "title" not in result:
                logger.warning("豆瓣详情页解析失败: id=%s", douban_id)
                return None

            logger.info("豆瓣详情爬取成功: %s (id=%s)", result.get("title"), douban_id)
            return result

        except Exception as e:
            logger.error("解析豆瓣详情页失败 id=%s: %s", douban_id, e)
            return None

    def _request(self, url: str, params: Optional[dict] = None) -> Optional[str]:
        """发送 HTTP 请求，含反爬策略。

        Args:
            url: 请求 URL
            params: URL 查询参数

        Returns:
            响应文本，或 None
        """
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
                resp = self.session.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
                resp.raise_for_status()
                resp.encoding = "utf-8"
                return resp.text
            except requests.RequestException as e:
                logger.warning("请求失败 (尝试 %d/%d): %s", attempt, MAX_RETRIES, e)
                if attempt < MAX_RETRIES:
                    wait = 2 ** attempt  # 2, 4, 8 秒递增
                    time.sleep(wait)
        return None

    def close(self) -> None:
        """关闭 HTTP 会话。"""
        self.session.close()
