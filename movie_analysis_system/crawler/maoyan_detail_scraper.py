"""
猫眼详情页爬虫（Selenium Edge 无头浏览器）
========================================
从猫眼电影详情页提取 JS 渲染后的完整数据。

策略：
  - 长延迟（6~12 秒）避免触发反爬
  - 随机 User-Agent + 窗口尺寸
  - 每页停留 3~5 秒等待 JS 渲染
  - 失败时降级返回空数据（不阻塞主流程）
"""

import logging
import os
import re
import time
import random
from typing import Optional

from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.common.exceptions import TimeoutException, WebDriverException

logger = logging.getLogger("DetailScraper")

EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
CHROME_PATH = os.environ.get("CHROME_PATH", EDGE_PATH)
MAX_CONCURRENT = 2  # 并发数（实际串行，避免触发风控）
REQUEST_DELAY = (6, 12)  # 请求间隔（秒）

# 窗口尺寸池（模拟不同设备）
VIEWPORTS = [
    (1920, 1080), (1366, 768), (1440, 900), (1536, 864),
]


def check_pyppeteer_available() -> bool:
    """检测浏览器是否可用于详情页实时数据获取。"""
    paths = [
        CHROME_PATH,
        EDGE_PATH,
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    for p in paths:
        if os.path.exists(p):
            logger.info("浏览器可用: %s", p)
            return True
    logger.warning("未找到可用浏览器，详情页将使用离线数据")
    return False


def _create_driver() -> webdriver.Edge:
    """创建 Edge 无头浏览器实例。"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
    )
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.binary_location = EDGE_PATH
    return webdriver.Edge(options=options)


def scrape_single(maoyan_id: str) -> Optional[dict]:
    """爬取单个电影的详情页数据。

    Args:
        maoyan_id: 猫眼电影 ID

    Returns:
        {"maoyan_id": str, "rating_count": int, "box_office": float,
         "price_min": float, "price_max": float, "rating": float,
         "summary": str}
    """
    driver = None
    try:
        driver = _create_driver()
        w, h = random.choice(VIEWPORTS)
        driver.set_window_size(w, h)

        url = f"https://www.maoyan.com/films/{maoyan_id}"
        driver.get(url)

        # 等待 JS 渲染（3~5 秒）
        time.sleep(random.uniform(3, 5))

        text = driver.execute_script("return document.body.innerText")

        # 检查是否被 CAPTCHA 拦截
        if any(kw in text for kw in ["安全验证", "请依次点击", "验证失败"]):
            logger.warning("[DETAIL] %s: 触发反爬验证，跳过", maoyan_id)
            return None

        # ─── 从文本中提取数据 ───

        result: dict = {"maoyan_id": maoyan_id}

        # 票房：首周票房(万) 和 累计票房(万)
        box_match = re.search(r"累计票房\(万\)\s*(\d+)", text)
        result["box_office"] = float(box_match.group(1)) if box_match else 0

        first_match = re.search(r"首周票房\(万\)\s*(\d+)", text)
        if first_match and not result["box_office"]:
            result["box_office"] = float(first_match.group(1))

        # 评分人数：找 "X人评分"
        rc_match = re.search(r"(\d+)\s*人评分", text)
        result["rating_count"] = int(rc_match.group(1)) if rc_match else 0

        # 评分：找 .stonefont 旁边的数字，或 "猫眼评分 X.X"
        score_match = re.search(r"猫眼评分[：:]?\s*([\d.]+)", text)
        result["rating"] = float(score_match.group(1)) if score_match else 0

        # 如果上面没找到评分，尝试从 HTML 的 data 属性提取
        if not result["rating"]:
            try:
                html_score = driver.execute_script(
                    "return document.querySelector('.score-num')?.textContent || ''"
                )
                # iconfont 编码 → 尝试从 HTML attribute 找真实数字
                if html_score and not any(c.isdigit() for c in html_score):
                    # iconfont 编码，从相邻 DOM 属性获取
                    real_score = driver.execute_script("""
                        var el = document.querySelector('[class*=\"score\"]');
                        if (!el) return '';
                        var text = el.textContent || '';
                        var digits = text.match(/\\d+\\.\\d+/);
                        return digits ? digits[0] : '';
                    """)
                    result["rating"] = float(real_score) if real_score else 0
            except Exception:
                pass

        # 票价：找 "¥X-Y"、"¥X起"、"X-Y元"
        price_min = price_max = 0
        price_match = re.search(r"[¥￥]\s*(\d+)\s*[~-]\s*(\d+)", text)
        if price_match:
            price_min = float(price_match.group(1))
            price_max = float(price_match.group(2))
        else:
            price_single = re.search(r"[¥￥]\s*(\d+)\s*起", text)
            if price_single:
                price_min = price_max = float(price_single.group(1))
        result["price_min"] = price_min
        result["price_max"] = price_max

        # 剧情简介
        summary_match = re.search(
            r"剧情简介[：:\s]*\n?\s*([^\\n]+(?:\\n[^\\n]+){0,5})",
            text,
        )
        result["summary"] = summary_match.group(1).strip() if summary_match else ""

        logger.info(
            "[DETAIL] %s: %s人评 | 票房%s万 | ¥%s-%s",
            maoyan_id,
            result["rating_count"] or "?",
            result["box_office"] or "?",
            result["price_min"] or "?",
            result["price_max"] or "?",
        )
        return result

    except (TimeoutException, WebDriverException) as e:
        logger.warning("[DETAIL] %s 浏览器异常: %s", maoyan_id, e)
        return None
    except Exception as e:
        logger.warning("[DETAIL] %s 爬取失败: %s", maoyan_id, e)
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def scrape_movie_details_sync(maoyan_ids: list[str]) -> list[dict]:
    """同步批量爬取（串行执行，避免风控）。

    Args:
        maoyan_ids: 猫眼电影 ID 列表

    Returns:
        包含完整数据的字典列表
    """
    if not maoyan_ids:
        return []

    logger.info("[DETAIL] 开始爬取 %d 部电影详情...", len(maoyan_ids))

    results: list[dict] = []
    for i, mid in enumerate(maoyan_ids):
        delay = random.uniform(*REQUEST_DELAY)
        if i > 0:
            logger.info("[DETAIL] 等待 %.1f 秒后爬取下一部...", delay)
            time.sleep(delay)

        data = scrape_single(mid)
        if data:
            results.append(data)

    logger.info("[DETAIL] 详情爬取完成: 成功 %d/%d", len(results), len(maoyan_ids))
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = scrape_movie_details_sync(["1522535"])
    for r in result:
        print(r)
