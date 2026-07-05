"""
评分分布直方图
==============
统计各评分区间的电影数量，支持年份筛选。
"""

import logging
from typing import Optional

from pyecharts.charts import Bar
from pyecharts import options as opts

from charts.chart_engine import ChartEngine
from database.db_manager import DatabaseManager

logger = logging.getLogger("RatingDistribution")


def create_rating_distribution(db: DatabaseManager,
                               year_start: Optional[int] = None,
                               year_end: Optional[int] = None) -> str:
    """创建评分分布直方图的 HTML。

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
        where = "WHERE rating > 0"
        params = []
        if year_start:
            where += " AND CAST(SUBSTR(release_date,1,4) AS INTEGER) >= ?"
            params.append(year_start)
        if year_end:
            where += " AND CAST(SUBSTR(release_date,1,4) AS INTEGER) <= ?"
            params.append(year_end)

        cursor.execute(f"""
            SELECT CAST(ROUND(rating) AS INTEGER) AS rating_group, COUNT(*) AS count
            FROM movies {where}
            GROUP BY rating_group ORDER BY rating_group
        """, params)
        rows = cursor.fetchall()
        data = [dict(row) for row in rows]
    finally:
        cursor.close()

    if not data:
        return "<div style='padding: 40px; text-align: center; color: #757575; font-size: 14px;'>暂无评分数据</div>"

    rating_map = {r["rating_group"]: r["count"] for r in data}
    all_ratings = list(range(1, 11))
    all_counts = [rating_map.get(r, 0) for r in all_ratings]
    labels = [f"{r}分" for r in all_ratings]

    bar = (
        Bar(init_opts=opts.InitOpts(width="100%", height="314px", bg_color="#FFFFFF"))
        .add_xaxis(labels)
        .add_yaxis(
            "电影数量", all_counts,
            label_opts=opts.LabelOpts(position="top", font_size=14),
            itemstyle_opts=opts.ItemStyleOpts(
                color={"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1,
                       "colorStops": [
                           {"offset": 0, "color": "#64B5F6"},
                           {"offset": 1, "color": "#1E88E5"},
                       ]}
            ),
        )
        .set_global_opts(
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
            xaxis_opts=opts.AxisOpts(
                axislabel_opts=opts.LabelOpts(font_size=15, color="#37474F"),
            ),
            yaxis_opts=opts.AxisOpts(
                name="电影数量",
                axislabel_opts=opts.LabelOpts(font_size=15, color="#757575"),
                splitline_opts=opts.SplitLineOpts(
                    is_show=True, linestyle_opts=opts.LineStyleOpts(color="#F0F0F0")
                ),
            ),
            legend_opts=opts.LegendOpts(is_show=False),
        )
    )
    bar.options["grid"] = [opts.GridOpts(is_contain_label=True, pos_right="40").opts]
    return engine.render(bar)
