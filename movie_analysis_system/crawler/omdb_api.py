"""
OMDB API 集成模块
==================
通过 OMDB API (IMDb 数据源) 获取电影简介、评分、类型、海报等。

数据流：
  1. 根据英文片名映射 → 查询 OMDB
  2. 缓存结果到数据库（imdb_id + omdb_data）
  3. 下次直接从缓存读取

OMDB API Key: 用户提供
"""

import json
import logging
import os
import re
import sqlite3
from typing import Optional

import requests

logger = logging.getLogger("OMDB")

# OMDB API Key（从 config.py 读取，空字符串则跳过 OMDB）
import sys, os
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
try:
    from config import OMDB_API_KEY
except ImportError:
    OMDB_API_KEY = ""
OMDB_BASE = "http://www.omdbapi.com/"

# 英文片名映射（中文→英文）
# OMDB 不识别中文，必须用英文片名搜索
# 部分新片/国产片 OMDB 可能没有收录
EN_TITLE_MAP = {
    # === 国际大片/续集 ===
    "阿凡达4": "Avatar 4",
    "盗梦空间2": "Inception 2",
    "沙丘3": "Dune 3",
    "侏罗纪世界4": "Jurassic World 4",
    "头脑特工队2": "Inside Out 2",
    "疯狂动物城2": "Zootopia 2",
    "玩具总动员5": "Toy Story 5",
    "奥本海默": "Oppenheimer",
    "疾速追杀5": "John Wick 5",
    "碟中谍8": "Mission: Impossible 8",
    "毒液3": "Venom 3",
    "变形金刚7": "Transformers 7",
    "超级少女": "Supergirl",
    "功夫熊猫4": "Kung Fu Panda 4",
    "战狼2": "Wolf Warrior 2",

    # === 国产片（不保证 OMDB 有） ===
    "流浪地球3": "The Wandering Earth 3",
    "哪吒3": "Ne Zha 3",
    "封神第二部": "Creation of the Gods II",
    "志愿军2": "The Volunteers 2",
    "蛟龙行动": "Operation Seadragon",
    "神探大战2": "Detective vs. Sleuths 2",
    "猎罪图鉴": "The Hunt for the Guilty",
    "大鱼海棠2": "Big Fish and Begonia 2",
    "末路狂花钱": "The Last Frenzy",
    "诺曼底72小时": "72 Hours in Normandy",

    # === 经典片 ===
    "俄罗斯方块": "Tetris",
    "消失的她": "Lost in the Stars",
    "抓特务": "Catch the Spy",

    # === 补充映射（搜索常用） ===
    "功夫熊猫": "Kung Fu Panda",
    "功夫熊猫4": "Kung Fu Panda 4",
    "功夫熊猫3": "Kung Fu Panda 3",
    "功夫熊猫2": "Kung Fu Panda 2",
    "流浪地球": "The Wandering Earth",
    "流浪地球2": "The Wandering Earth 2",
    "流浪地球3": "The Wandering Earth 3",
    "流浪地球3(上)": "The Wandering Earth 3",
    "流浪地球3(下)": "The Wandering Earth 3",
    "战狼": "Wolf Warrior",
    "战狼2": "Wolf Warrior 2",
    "哪吒": "Ne Zha",
    "哪吒之魔童降世": "Ne Zha",
    "封神": "Creation of the Gods",
    "封神第一部": "Creation of the Gods",
    "大鱼海棠": "Big Fish and Begonia",
    "你好李焕英": "Hi Mom",
    "唐人街探案": "Detective Chinatown",
    "长津湖": "The Battle at Lake Changjin",
    "我不是药神": "Dying to Survive",
    "我和我的祖国": "My People My Country",
}


class OMDBApi:
    """OMDB API 封装，自动缓存到数据库。"""

    def __init__(self, db_path: str = "data/movie_analysis.db") -> None:
        self._db_path = db_path
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "MovieAnalysisSystem/1.0",
        })
        self._init_cache_table()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_cache_table(self) -> None:
        """创建 OMDB 缓存表（如果不存在）。"""
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS omdb_cache (
                cn_title TEXT PRIMARY KEY,
                imdb_id TEXT,
                data TEXT,
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.commit()
        c.close()
        conn.close()

    def get_en_title(self, cn_title: str) -> str:
        """获取中文片名对应的英文片名。

        Args:
            cn_title: 中文片名

        Returns:
            英文片名（找不到则返回中文原文）
        """
        return EN_TITLE_MAP.get(cn_title.strip(), cn_title)

    def fetch(self, cn_title: str) -> Optional[dict]:
        """获取电影数据（中文片名 → OMDB 查询）。

        流程：缓存检查 → OMDB API → 标题校验 → 缓存写入 → 返回

        Args:
            cn_title: 中文片名

        Returns:
            OMDB 返回的字典，失败返回 None
        """
        title = cn_title.strip()
        if not title:
            return None

        # 1) 检查缓存
        cached = self._get_cache(title)
        if cached:
            logger.info("[OMDB] 缓存命中: %s", title)
            return json.loads(cached)

        # 2) 查询 OMDB
        en_title = self.get_en_title(title)
        if en_title == title:
            logger.info("[OMDB] 无英文映射, 使用中文原文: %s", title)

        try:
            resp = self._session.get(
                OMDB_BASE,
                params={"apikey": OMDB_API_KEY, "t": en_title, "plot": "full"},
                timeout=8,
            )
            if resp.status_code != 200:
                logger.warning("[OMDB] HTTP %d for %s", resp.status_code, title)
                return None

            data = resp.json()
            if data.get("Response") != "True":
                logger.info("[OMDB] %s: %s", title, data.get("Error", "未找到"))
                return None

            # 3) 标题校验：OMDB 返回的英文标题与中文标题无直接关系，
            # 但至少确保不是完全不相关的电影
            omdb_title = data.get("Title", "").lower()
            en_title_lower = en_title.lower()
            # 检查英文标题是否包含搜索词（忽略大小写）
            if en_title != title:  # 只有用了英文映射才校验
                en_words = en_title_lower.split()
                omdb_words = omdb_title.split()
                # 至少有一个单词匹配
                word_match = any(w in omdb_words for w in en_words if len(w) > 2)
                if not word_match:
                    logger.warning("[OMDB] 标题不匹配: 搜索=%s, 返回=%s, 丢弃", en_title, omdb_title)
                    return None

            # 4) 写入缓存
            self._set_cache(title, data.get("imdbID", ""), json.dumps(data, ensure_ascii=False))
            logger.info("[OMDB] 成功获取: %s → %s (%s)", title, data.get("Title"), data.get("Year"))
            return data

        except requests.RequestException as e:
            logger.warning("[OMDB] 请求失败: %s", e)
            return None

    def search(self, keyword: str) -> list[dict]:
        """按关键词搜索电影。

        Args:
            keyword: 搜索关键词（中文会尝试映射为英文）

        Returns:
            搜索结果列表 [{title, year, imdb_id, poster, type, source:"OMDB"}]
        """
        if not keyword:
            return []

        # 先用英文映射搜索
        en_title = self.get_en_title(keyword)
        queries = [en_title, keyword] if en_title != keyword else [keyword]

        seen_ids = set()
        results = []
        for q in queries:
            try:
                resp = self._session.get(
                    OMDB_BASE,
                    params={"apikey": OMDB_API_KEY, "s": q, "type": "movie"},
                    timeout=8,
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if data.get("Response") != "True":
                    continue
                for item in data.get("Search", []):
                    imdb_id = item.get("imdbID", "")
                    if imdb_id in seen_ids:
                        continue
                    seen_ids.add(imdb_id)
                    results.append({
                        "title": item.get("Title", ""),
                        "year": item.get("Year", ""),
                        "imdb_id": imdb_id,
                        "poster_url": item.get("Poster", ""),
                        "type": item.get("Type", ""),
                        "source": "OMDB",
                        "rating": 0,
                    })
            except requests.RequestException:
                continue
            if results:
                break  # 找到结果就不再试

        return results

    def to_app_format(self, omdb_data: dict) -> dict:
        """将 OMDB 数据转为 app 内部格式。

        Args:
            omdb_data: OMDB API 返回的数据

        Returns:
            app 内部格式字典
        """
        if not omdb_data:
            return {}
        return {
            "title": omdb_data.get("Title", ""),
            "genre": self.extract_genre(omdb_data),
            "rating": self.extract_rating(omdb_data),
            "actors": self.extract_actors(omdb_data),
            "poster_url": self.extract_poster(omdb_data),
            "runtime": self.extract_runtime(omdb_data),
            "plot": self.extract_plot(omdb_data),
            "source": "OMDB",
            "imdb_id": omdb_data.get("imdbID", ""),
            "year": omdb_data.get("Year", ""),
            "release_date": omdb_data.get("Released", ""),
            "director": omdb_data.get("Director", ""),
            "language": omdb_data.get("Language", ""),
            "country": omdb_data.get("Country", ""),
            "metascore": omdb_data.get("Metascore", ""),
            "imdb_rating": omdb_data.get("imdbRating", ""),
            "box_office": omdb_data.get("BoxOffice", ""),
        }

    def fetch_by_imdb_id(self, imdb_id: str) -> Optional[dict]:
        """通过 IMDb ID 获取电影数据。

        Args:
            imdb_id: IMDb ID（如 tt1234567）

        Returns:
            OMDB 数据字典
        """
        if not imdb_id:
            return None
        try:
            resp = self._session.get(
                OMDB_BASE,
                params={"apikey": OMDB_API_KEY, "i": imdb_id, "plot": "full"},
                timeout=8,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("Response") == "True":
                    return data
            return None
        except requests.RequestException:
            return None

    # ──────────── 字段提取 ────────────

    @staticmethod
    def extract_plot(data: Optional[dict]) -> str:
        """提取剧情简介。

        Args:
            data: OMDB 数据

        Returns:
            简介文本
        """
        if not data:
            return ""
        plot = data.get("Plot", "") or ""
        return plot.strip()

    @staticmethod
    def extract_genre(data: Optional[dict]) -> str:
        """提取类型标签（分号分隔）。

        Args:
            data: OMDB 数据

        Returns:
            类型字符串，如 "剧情;科幻;冒险"
        """
        if not data:
            return ""
        genre = data.get("Genre", "") or ""
        # Genre 格式: "Action, Sci-Fi, Adventure" → "动作;科幻;冒险"
        # 保持英文格式，或者不翻译
        return genre.replace(", ", ";")

    @staticmethod
    def extract_rating(data: Optional[dict]) -> float:
        """提取 IMDb 评分。

        Args:
            data: OMDB 数据

        Returns:
            IMDb 评分（0-10）
        """
        if not data:
            return 0
        imdb = data.get("imdbRating", "") or ""
        try:
            return float(imdb)
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def extract_poster(data: Optional[dict]) -> str:
        """提取高清海报 URL。

        Args:
            data: OMDB 数据

        Returns:
            海报 URL
        """
        if not data:
            return ""
        poster = data.get("Poster", "") or ""
        # IMDB 海报通常较大，直接使用
        return poster

    @staticmethod
    def extract_actors(data: Optional[dict]) -> str:
        """提取演员列表（分号分隔）。

        Args:
            data: OMDB 数据

        Returns:
            演员字符串
        """
        if not data:
            return ""
        actors = data.get("Actors", "") or ""
        return actors.replace(", ", ";")

    @staticmethod
    def extract_runtime(data: Optional[dict]) -> int:
        """提取片长（分钟）。

        Args:
            data: OMDB 数据

        Returns:
            分钟数
        """
        if not data:
            return 0
        runtime = data.get("Runtime", "") or ""
        match = re.search(r"(\d+)", runtime)
        return int(match.group(1)) if match else 0

    # ──────────── 缓存管理 ────────────

    def _get_cache(self, cn_title: str) -> Optional[str]:
        """从缓存读取 OMDB 数据。"""
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("SELECT data FROM omdb_cache WHERE cn_title = ?", (cn_title,))
            row = c.fetchone()
            c.close()
            conn.close()
            return row["data"] if row else None
        except Exception:
            return None

    def _set_cache(self, cn_title: str, imdb_id: str, data: str) -> None:
        """写入 OMDB 缓存。"""
        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("""
                INSERT OR REPLACE INTO omdb_cache (cn_title, imdb_id, data)
                VALUES (?, ?, ?)
            """, (cn_title, imdb_id, data))
            conn.commit()
            c.close()
            conn.close()
        except Exception as e:
            logger.warning("[OMDB] 缓存写入失败: %s", e)

    def close(self) -> None:
        self._session.close()
