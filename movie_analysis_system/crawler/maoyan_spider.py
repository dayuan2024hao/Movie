"""
猫眼爬虫
========
从猫眼桌面站 HTML 实时爬取当前热映和即将上映电影。

已验证：
  - 热映列表：https://www.maoyan.com/films?showType=1 → HTTP 200 ✅
  - 即将上映：https://www.maoyan.com/films?showType=2 → HTTP 200 ✅
  - 详情页：https://www.maoyan.com/films/{id} → HTTP 200 ✅

数据提取方式：正则解析（已验证可行，无需额外依赖）
"""

import logging
import re
import time
from typing import Optional

import requests

logger = logging.getLogger("MaoyanSpider")

TIMEOUT = 10


class MaoyanSpider:
    """猫眼桌面站爬虫——实时获取热映电影列表。"""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.maoyan.com/",
        })

    def get_showing_list(self, limit: int = 30) -> list[dict]:
        """爬取正在热映电影列表。

        Args:
            limit: 最多返回条数

        Returns:
            [{title, maoyan_id, rating, genre, actors, release_date, poster_url}, ...]
        """
        return self._crawl("https://www.maoyan.com/films", {"showType": "1"}, limit)

    def get_coming_list(self, limit: int = 20) -> list[dict]:
        """爬取即将上映电影列表。

        Args:
            limit: 最多返回条数

        Returns:
            同上
        """
        return self._crawl("https://www.maoyan.com/films", {"showType": "2"}, limit)

    def _crawl(self, url: str, params: dict, limit: int) -> list[dict]:
        """爬取猫眼电影列表。

        Args:
            url: 请求地址
            params: 查询参数
            limit: 最大条数

        Returns:
            电影列表
        """
        try:
            resp = self._session.get(url, params=params, timeout=TIMEOUT)
            if resp.status_code != 200:
                logger.warning("[MAOYAN] 列表请求失败: HTTP %d", resp.status_code)
                return []

            movies = self._parse_list(resp.text)
            logger.info("[MAOYAN] 获取 %d 部电影 (HTTP %d)", len(movies), resp.status_code)
            return movies[:limit] if movies else []

        except requests.RequestException as e:
            logger.warning("[MAOYAN] 请求异常: %s", e)
            return []

    def _parse_list(self, html: str) -> list[dict]:
        """解析热映列表 HTML。

        Args:
            html: 页面 HTML

        Returns:
            电影列表
        """
        movies = []
        # 每个 movie-item 块包含一部电影
        items = html.split('<div class="movie-item film-channel">')[1:]

        for block in items:
            movie = {}

            # maoyan_id
            m = re.search(r'/films/(\d+)', block)
            if m:
                movie["maoyan_id"] = m.group(1)

            # 标题
            m = re.search(r'<span class="name[^"]*">(.*?)</span>', block)
            if m:
                title = m.group(1).strip()
                # 去除可能的评分前缀（如"评分 9.6"）
                title = re.sub(r'^评分\s*[\d.]+\s*', '', title).strip()
                movie["title"] = title

            # 评分
            m = re.search(r'<span class="score">([^<]+)<', block)
            if m:
                try:
                    movie["rating"] = float(m.group(1).strip())
                except ValueError:
                    pass

            # 类型
            m = re.search(r'类型:</span>\s*([^<]+)<', block)
            if m:
                movie["genre"] = m.group(1).strip().replace('，', ';').replace('/', ';')

            # 主演
            m = re.search(r'主演:</span>\s*([^<]+)<', block)
            if m:
                movie["actors"] = m.group(1).strip().replace('，', ';').replace('/', ';')[:80]

            # 上映日期
            m = re.search(r'上映时间:</span>\s*([^<]+)<', block)
            if m:
                movie["release_date"] = m.group(1).strip()[:10]

            # 海报
            m = re.search(r'data-src="([^"]+)"', block)
            if m:
                poster = m.group(1)
                if poster.startswith("//"):
                    poster = "https:" + poster
                movie["poster_url"] = poster

            if movie.get("title") and movie.get("maoyan_id"):
                movies.append(movie)

        return movies

    def _mock_list(self) -> list[dict]:
        """爬取失败时返回模拟数据（确保 app 有内容可展示）。

        Returns:
            预置的热映电影列表
        """
        logger.info("[MAOYAN] 使用模拟数据")
        return [
            {"title": "流浪地球3", "maoyan_id": "1490532", "rating": 8.6,
             "genre": "科幻;冒险;灾难", "actors": "吴京;刘德华;李雪健",
             "release_date": "2026-02-10", "poster_url": ""},
            {"title": "哪吒3", "maoyan_id": "1522535", "rating": 8.4,
             "genre": "动画;奇幻", "actors": "吕艳婷;囧森瑟夫;陈浩",
             "release_date": "2026-07-18", "poster_url": ""},
            {"title": "盗梦空间2", "maoyan_id": "1528803", "rating": 8.9,
             "genre": "科幻;悬疑;动作", "actors": "莱昂纳多;赞达亚;汤姆·哈迪",
             "release_date": "2026-06-12", "poster_url": ""},
        ]

    def get_detail(self, maoyan_id: str) -> Optional[dict]:
        """爬取猫眼电影详情页。

        Args:
            maoyan_id: 猫眼电影 ID

        Returns:
            {summary, ...} 或 None
        """
        try:
            url = f"https://www.maoyan.com/films/{maoyan_id}"
            resp = self._session.get(url, timeout=TIMEOUT)
            if resp.status_code != 200:
                return None

            html = resp.text
            detail = {}

            # 简介
            m = re.search(r'class="summary">(.*?)<', html, re.DOTALL)
            if m:
                detail["summary"] = m.group(1).strip()

            return detail if detail else None

        except requests.RequestException:
            return None

    def close(self) -> None:
        self._session.close()
