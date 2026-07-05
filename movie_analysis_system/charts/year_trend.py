"""
年份趋势折线图
==============
展示历年上映电影数量、平均评分的变化趋势，支持年份筛选。
"""

import logging
from typing import Optional

from pyecharts.charts import Line
from pyecharts import options as opts

from charts.chart_engine import ChartEngine
from database.db_manager import DatabaseManager

logger = logging.getLogger("YearTrend")


def create_year_trend_chart(db: DatabaseManager,
                            year_start: Optional[int] = None,
                            year_end: Optional[int] = None) -> str:
    """创建年份趋势折线图的 HTML。

    Args:
        db: 数据库管理器
        year_start: 起始年份，None 不限
        year_end: 结束年份，None 不限

    Returns:
        图表 HTML 字符串
    """
    engine = ChartEngine()

    conn = db.get_connection()
    cursor = conn.cursor()
    try:
        yf = ""
        params = []
        if year_start:
            yf += " AND CAST(SUBSTR(release_date,1,4) AS INTEGER) >= ?"
            params.append(year_start)
        if year_end:
            yf += " AND CAST(SUBSTR(release_date,1,4) AS INTEGER) <= ?"
            params.append(year_end)

        cursor.execute(f"""
            SELECT CAST(SUBSTR(release_date,1,4) AS INTEGER) AS year,
                   COUNT(*) AS movie_count,
                   ROUND(AVG(rating),2) AS avg_rating
            FROM movies
            WHERE release_date IS NOT NULL AND release_date != '' {yf}
            GROUP BY year ORDER BY year
        """, params)
        data = [dict(r) for r in cursor.fetchall()]
    finally:
        cursor.close()

    if not data:
        return "<div style='padding: 40px; text-align: center; color: #757575;'>暂无年份数据</div>"

    years = [str(r["year"]) for r in data]
    counts = [r["movie_count"] for r in data]
    avg_ratings = [r["avg_rating"] if r["avg_rating"] else 0 for r in data]

    line = (
        Line(init_opts=opts.InitOpts(width="100%", height="364px", bg_color="#FFFFFF"))
        .add_xaxis(years)
        .add_yaxis("上映数量", counts, yaxis_index=0,
                   label_opts=opts.LabelOpts(is_show=True, position="top", font_size=13),
                   linestyle_opts=opts.LineStyleOpts(width=3, color="#1E88E5"),
                   itemstyle_opts=opts.ItemStyleOpts(color="#1E88E5"),
                   symbol="circle", symbol_size=8)
        .add_yaxis("平均评分", avg_ratings, yaxis_index=1,
                   label_opts=opts.LabelOpts(is_show=True, position="top", font_size=13),
                   linestyle_opts=opts.LineStyleOpts(width=3, color="#FF7043", type_="dashed"),
                   itemstyle_opts=opts.ItemStyleOpts(color="#FF7043"),
                   symbol="diamond", symbol_size=8)
        .set_global_opts(
            tooltip_opts=opts.TooltipOpts(trigger="axis", formatter="{b}<br/>{a}: {c}<br/>{a0}: {c0}"),
            xaxis_opts=opts.AxisOpts(name="年份",
                axislabel_opts=opts.LabelOpts(font_size=14, color="#37474F", rotate=30),
                splitline_opts=opts.SplitLineOpts(is_show=True, linestyle_opts=opts.LineStyleOpts(color="#F0F0F0"))),
            yaxis_opts=opts.AxisOpts(name="上映数量", type_="value",
                axislabel_opts=opts.LabelOpts(font_size=14, color="#757575"),
                splitline_opts=opts.SplitLineOpts(is_show=True, linestyle_opts=opts.LineStyleOpts(color="#F0F0F0"))),
            legend_opts=opts.LegendOpts(orient="horizontal", item_gap=30, textstyle_opts=opts.TextStyleOpts(font_size=14)),
        )
    )
    line.options["grid"] = [opts.GridOpts(is_contain_label=True, pos_right="60").opts]
    line.extend_axis(yaxis=opts.AxisOpts(name="平均评分", type_="value", min_=0, max_=10,
        axislabel_opts=opts.LabelOpts(font_size=14, color="#FF7043"),
        splitline_opts=opts.SplitLineOpts(is_show=False)))
    return engine.render(line)
