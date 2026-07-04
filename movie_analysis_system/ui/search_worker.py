"""
搜索异步工作者
==============
QObject + QThread 跨线程搜索封装。

搜索策略：
  1. 并发查询豆瓣搜索页 + OMDB API
  2. 按标题去重合并
  3. 结果通过 Qt 信号安全返回主线程

用法：
    worker = SearchWorker()
    thread = QThread()
    worker.moveToThread(thread)
    thread.start()
    worker.search("电影名")  # 跨线程安全
"""

import logging
import threading
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot, Qt

from crawler.omdb_api import OMDBApi

logger = logging.getLogger("SearchWorker")


def _search_douban(keyword: str) -> list[dict]:
    """通过豆瓣 suggest API 搜索电影。

    Args:
        keyword: 搜索关键词

    Returns:
        [{title, douban_id, rating, year, poster_url, source:"豆瓣"}, ...]
    """
    import requests
    try:
        # 使用 suggest API (返回JSON，不需要JS渲染)
        url = (
            "https://movie.douban.com/j/subject_suggest?"
            f"q={requests.utils.quote(keyword)}"
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Referer": "https://movie.douban.com/",
        }
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code != 200:
            return []

        data = resp.json()
        results = []
        for item in data[:10]:
            title = item.get("title", "")
            if not title:
                continue
            results.append({
                "title": title.strip(),
                "douban_id": str(item.get("id", "")),
                "imdb_id": item.get("imdb_id", ""),
                "rating": item.get("rating", 0) or 0,
                "poster_url": item.get("img", ""),
                "year": str(item.get("year", "")),
                "sub_title": item.get("sub_title", ""),
                "source": "豆瓣",
            })
        return results

    except Exception as e:
        logger.debug("[SEARCH] 豆瓣搜索异常: %s", e)
        return []


def _search_omdb(keyword: str) -> list[dict]:
    """搜索 OMDB API。

    Args:
        keyword: 搜索关键词

    Returns:
        [{title, year, imdb_id, poster_url, source:"OMDB"}, ...]
    """
    try:
        api = OMDBApi()
        results = api.search(keyword)
        return results
    except Exception as e:
        logger.debug("[SEARCH] OMDB搜索异常: %s", e)
        return []


class SearchWorker(QObject):
    """异步搜索工作者（跨线程安全）。"""

    finished = pyqtSignal(list)
    error_happened = pyqtSignal(str)
    progress = pyqtSignal(str)

    _search_requested = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._search_requested.connect(self._do_search, Qt.QueuedConnection)

    def search(self, keyword: str) -> None:
        """启动搜索（跨线程安全）。

        Args:
            keyword: 搜索关键词
        """
        kw = keyword.strip()
        if not kw:
            self.finished.emit([])
            return
        self._search_requested.emit(kw)

    @pyqtSlot(str)
    def _do_search(self, keyword: str) -> None:
        """在工作者线程执行搜索。"""
        print(f"[SEARCH] 搜索: {keyword}")

        try:
            self.progress.emit(f"正在搜索「{keyword}」...")

            # 并发搜索豆瓣 + OMDB
            results_map: dict[str, dict] = {}

            douban_future = threading.Thread(
                target=lambda: self._merge_results(
                    _search_douban(keyword), results_map
                ),
                daemon=True,
            )
            omdb_future = threading.Thread(
                target=lambda: self._merge_results(
                    _search_omdb(keyword), results_map
                ),
                daemon=True,
            )
            douban_future.start()
            omdb_future.start()
            douban_future.join(timeout=10)
            omdb_future.join(timeout=10)

            results = list(results_map.values())
            print(f"[SEARCH] 结果: {len(results)} 条 (豆瓣+OMDB合并)")

            self.progress.emit(f"找到 {len(results)} 条结果")
            self.finished.emit(results)

        except Exception as e:
            import traceback
            print(f"[SEARCH] 异常: {e}")
            traceback.print_exc()
            self.error_happened.emit(str(e))
            self.finished.emit([])

    @staticmethod
    def _merge_results(new_items: list[dict], results_map: dict[str, dict]) -> None:
        """将搜索结果合并到总表中（按标题/ID双重去重）。

        Args:
            new_items: 新搜索结果
            results_map: 总结果字典（副作用修改）
        """
        for item in new_items:
            # 先用标题做 key
            title_key = item.get("title", "").strip().lower()
            if not title_key:
                continue

            # 尝试按 ID 匹配（中英文片名不一样时用 imdb_id 或 douban_id 关联）
            matched_key = None
            for existing_key, existing in results_map.items():
                # 检查 imdb_id
                if item.get("imdb_id") and existing.get("imdb_id") == item["imdb_id"]:
                    matched_key = existing_key
                    break
                # 检查 douban_id
                if item.get("douban_id") and existing.get("douban_id") == item["douban_id"]:
                    matched_key = existing_key
                    break

            if matched_key:
                existing = results_map[matched_key]
                # 合并字段
                for field in ["douban_id", "imdb_id", "maoyan_id", "rating", "poster_url", "year"]:
                    if item.get(field) and not existing.get(field):
                        existing[field] = item[field]
                    elif item.get(field) and field == "rating" and item[field] > (existing.get(field) or 0):
                        existing[field] = item[field]
                # 补充来源
                src = existing.get("source", "")
                item_src = item.get("source", "")
                if "豆瓣" in item_src and "OMDB" in src:
                    existing["source"] = "豆瓣+OMDB"
                elif "OMDB" in item_src and "豆瓣" in src:
                    existing["source"] = "豆瓣+OMDB"
                # 保留英文标题（OMDB 查详情时需要）
                if item.get("title") and title_key != matched_key:
                    existing.setdefault("en_title", item["title"])
            elif title_key in results_map:
                existing = results_map[title_key]
                for field in ["douban_id", "imdb_id", "maoyan_id", "rating", "poster_url"]:
                    if item.get(field) and not existing.get(field):
                        existing[field] = item[field]
                    elif item.get(field) and field == "rating" and item[field] > (existing.get(field) or 0):
                        existing[field] = item[field]
                src = existing.get("source", "")
                item_src = item.get("source", "")
                if "豆瓣" in item_src and "OMDB" in src:
                    existing["source"] = "豆瓣+OMDB"
                elif "OMDB" in item_src and "豆瓣" in src:
                    existing["source"] = "豆瓣+OMDB"
            else:
                results_map[title_key] = item
