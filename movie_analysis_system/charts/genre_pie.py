"""
类型占比饼图
============
展示各电影类型的数量和比例，支持年份筛选。
"""

import logging
from typing import Optional

from pyecharts.charts import Pie
from pyecharts import options as opts

from charts.chart_engine import ChartEngine, CHART_COLORS
from database.db_manager import DatabaseManager

logger = logging.getLogger("GenrePie")


def create_genre_pie(db: DatabaseManager,
                     year_start: Optional[int] = None,
                     year_end: Optional[int] = None) -> str:
    """创建类型占比饼图的 HTML。

    Args:
        db: 数据库管理器
        year_start: 起始年份（含），None 不限
        year_end: 结束年份（含），None 不限

    Returns:
        图表 HTML 字符串
    """
    engine = ChartEngine()

    conn = db.get_connection()
    cursor = conn.cursor()
    try:
        where = "WHERE 1=1"
        params = []
        if year_start:
            where += " AND CAST(SUBSTR(release_date,1,4) AS INTEGER) >= ?"
            params.append(year_start)
        if year_end:
            where += " AND CAST(SUBSTR(release_date,1,4) AS INTEGER) <= ?"
            params.append(year_end)

        cursor.execute(f"""
            SELECT TRIM(value) AS genre, COUNT(*) AS count, ROUND(AVG(rating),2) AS avg_rating
            FROM movies, json_each('["' || REPLACE(genre, ',', '","') || '"]')
            {where}
            GROUP BY TRIM(value) ORDER BY count DESC
        """, params)
        data = [dict(row) for row in cursor.fetchall()]
    finally:
        cursor.close()

    if not data:
        return "<div style='padding: 40px; text-align: center; color: #757575; font-size: 14px;'>暂无类型数据</div>"

    major = data[:8]
    others_count = sum(item["count"] for item in data[8:])
    pie_data = [(item["genre"], item["count"]) for item in major]
    if others_count > 0:
        pie_data.append(("其他", others_count))

    pie = (
        Pie(init_opts=opts.InitOpts(width="100%", height="314px", bg_color="#FFFFFF"))
        .add(
            series_name="电影类型", data_pair=pie_data,
            radius=["30%", "60%"], center=["50%", "55%"],
            label_opts=opts.LabelOpts(formatter="{b}: {c} ({d}%)", font_size=11),
        )
        .set_global_opts(
            tooltip_opts=opts.TooltipOpts(
                trigger="item", formatter="{b}: {c} 部 ({d}%)",
            ),
            legend_opts=opts.LegendOpts(
                orient="vertical", pos_left="left",
                textstyle_opts=opts.TextStyleOpts(font_size=12, color="#616161"),
            ),
        )
        .set_series_opts(label_opts=opts.LabelOpts(is_show=True))
    )
    return engine.render(pie)
