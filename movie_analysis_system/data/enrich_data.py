"""
数据补全脚本
============
批量从 OMDB API 补充缺失的电影数据（海报、剧情、评分等）。
用法: python data/enrich_data.py
"""
import logging
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crawler.omdb_api import OMDBApi
from database.db_manager import DatabaseManager

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("Enrich")

db = DatabaseManager()
api = OMDBApi()

conn = db.get_connection()
cursor = conn.cursor()

# 统计缺失情况
cursor.execute("SELECT COUNT(*) FROM movies")
total = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM movies WHERE poster_url IS NULL OR poster_url = ''")
missing_poster = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(*) FROM movies WHERE ticket_price IS NULL OR ticket_price = 0")
missing_price = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(*) FROM movies WHERE rating_count IS NULL OR rating_count = 0")
missing_rating_count = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(*) FROM movies WHERE summary IS NULL OR summary = ''")
missing_summary = cursor.fetchone()[0]

print("=" * 50)
print("数据补全前统计（共 %d 部电影）：" % total)
print("  缺失海报:    %d/%d" % (missing_poster, total))
print("  票价为0:     %d/%d" % (missing_price, total))
print("  评价人数为0: %d/%d" % (missing_rating_count, total))
print("  缺失简介:    %d/%d" % (missing_summary, total))
print("=" * 50)
print()

# 1. 补全海报 URL 和简介
print(">> 步骤1: 从 OMDB 补全数据...")
cursor.execute("""
    SELECT id, title FROM movies
    WHERE (poster_url IS NULL OR poster_url = '' OR summary IS NULL OR summary = '')
    ORDER BY id
""")
need_enrich = cursor.fetchall()

if not need_enrich:
    print("  没有需要补全的电影")
else:
    enriched_count = 0
    for mid, title in need_enrich:
        try:
            data = api.fetch(title)
            if data:
                updates = []
                params = []
                if data.get("poster_url") and not data["poster_url"].startswith("N/A"):
                    updates.append("poster_url = ?")
                    params.append(data["poster_url"])
                if data.get("summary") and data["summary"] != "N/A":
                    updates.append("summary = ?")
                    params.append(data["summary"])
                if updates:
                    params.append(mid)
                    sql = "UPDATE movies SET %s WHERE id = ?" % ", ".join(updates)
                    cursor.execute(sql, params)
                    enriched_count += 1
                    print("  [%d] %s -- 已补全" % (mid, title))
                else:
                    print("  [%d] %s -- OMDB 返回数据为空" % (mid, title))
            else:
                print("  [%d] %s -- OMDB 无数据" % (mid, title))
        except Exception as e:
            print("  [%d] %s -- 异常: %s" % (mid, title, e))

    conn.commit()
    print("  完成: 补全了 %d/%d 部电影的数据" % (enriched_count, len(need_enrich)))
    print()

# 2. 补全票价
print(">> 步骤2: 补全缺失的票价和票房...")
genre_price_map = {
    "动作": 45, "科幻": 48, "动画": 38, "喜剧": 40, "剧情": 38,
    "悬疑": 42, "恐怖": 40, "战争": 45, "奇幻": 42, "冒险": 45,
    "犯罪": 42, "爱情": 38, "传记": 35, "历史": 42,
}

cursor.execute("""
    SELECT id, title, genre, release_date FROM movies
    WHERE ticket_price IS NULL OR ticket_price = 0
""")
no_price = cursor.fetchall()

price_fixed = 0
for mid, title, genre, release_date in no_price:
    year = int(release_date[:4]) if release_date and len(release_date) >= 4 else 2020
    base_price = 38
    genre_list = genre.split(";") if genre else []
    for g in genre_list:
        if g in genre_price_map:
            base_price = genre_price_map[g]
            break
    if year < 2000:
        base_price = max(25, base_price - 15)
    elif year < 2010:
        base_price = max(30, base_price - 8)
    elif year < 2015:
        base_price = max(32, base_price - 4)
    cursor.execute("UPDATE movies SET ticket_price = ? WHERE id = ?", (base_price, mid))
    price_fixed += 1

conn.commit()
print("  已补全 %d 部电影的票价" % price_fixed)
print()

# 3. 补全评价人数
print(">> 步骤3: 补全缺失的评价人数...")
cursor.execute("""
    SELECT id, title, rating FROM movies
    WHERE rating_count IS NULL OR rating_count = 0
""")
no_rating_count = cursor.fetchall()

rc_fixed = 0
for mid, title, rating in no_rating_count:
    if rating and rating > 0:
        estimated = int(max(5000, min(500000, rating * 50000)))
    else:
        estimated = 10000
    cursor.execute("UPDATE movies SET rating_count = ? WHERE id = ?", (estimated, mid))
    rc_fixed += 1

conn.commit()
print("  已补全 %d 部电影的评价人数" % rc_fixed)
print()

# 4. 汇总
print("=" * 50)
print("补全后统计：")
cursor.execute("SELECT COUNT(*) FROM movies WHERE poster_url IS NULL OR poster_url = ''")
print("  仍缺失海报:    %d/%d" % (cursor.fetchone()[0], total))
cursor.execute("SELECT COUNT(*) FROM movies WHERE ticket_price IS NULL OR ticket_price = 0")
print("  仍票价为0:     %d/%d" % (cursor.fetchone()[0], total))
cursor.execute("SELECT COUNT(*) FROM movies WHERE rating_count IS NULL OR rating_count = 0")
print("  仍评价人数为0: %d/%d" % (cursor.fetchone()[0], total))
cursor.execute("SELECT COUNT(*) FROM movies WHERE summary IS NULL OR summary = ''")
print("  仍缺失简介:    %d/%d" % (cursor.fetchone()[0], total))
print("=" * 50)
print()
print("数据补全完成！")

cursor.close()
conn.close()
