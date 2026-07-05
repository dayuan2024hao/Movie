"""
各类型平均票房柱状图
====================
展示每种电影类型的平均票房和最高票房，支持年份筛选。
"""

import logging
from typing import Optional

from pyecharts.charts import Bar
from pyecharts import options as opts

from charts.chart_engine import ChartEngine
from database.db_manager import DatabaseManager

logger = logging.getLogger("GenreBoxOffice")


def create_genre_box_office_chart(db: DatabaseManager,
                                  year_start: Optional[int] = None,
                                  year_end: Optional[int] = None) -> str:
    """创建各类型平均票房柱状图的 HTML。

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
            SELECT TRIM(value) AS genre,
                   ROUND(AVG(box_office),0) AS avg_box_office,
                   ROUND(MAX(box_office),0) AS max_box_office,
                   COUNT(*) AS count
            FROM movies, json_each('["' || REPLACE(genre, ',', '","') || '"]')
            WHERE box_office > 0 AND rating > 0 {yf}
            GROUP BY TRIM(value) ORDER BY avg_box_office DESC
        """, params)
        data = [dict(row) for row in cursor.fetchall()]
    finally:
        cursor.close()

    if not data:
        return "<div style='padding: 40px; text-align: center; color: #757575;'>暂无类型票房数据</div>"

    major = data[:10]
    labels = [item["genre"] for item in major]
    avg_values = [item["avg_box_office"] for item in major]
    max_values = [item["max_box_office"] for item in major]

    bar = (
        Bar(init_opts=opts.InitOpts(width="100%", height="364px", bg_color="#FFFFFF"))
        .add_xaxis(labels)
        .add_yaxis("平均票房", avg_values,
                   label_opts=opts.LabelOpts(position="top", formatter="{c}", font_size=14),
                   itemstyle_opts=opts.ItemStyleOpts(color="#42A5F5"))
        .add_yaxis("最高票房", max_values,
                   label_opts=opts.LabelOpts(position="top", formatter="{c}", font_size=14),
                   itemstyle_opts=opts.ItemStyleOpts(color="#FF7043"))
        .set_global_opts(
            tooltip_opts=opts.TooltipOpts(trigger="axis", formatter="{b}<br/>{a}: {c} 万<br/>{a0}: {c0} 万"),
            xaxis_opts=opts.AxisOpts(
                axislabel_opts=opts.LabelOpts(font_size=13, color="#37474F", rotate=45),
                axisline_opts=opts.AxisLineOpts(is_show=False),
            ),
            yaxis_opts=opts.AxisOpts(
                name="票房（万元）",
                axislabel_opts=opts.LabelOpts(font_size=14, color="#757575"),
                splitline_opts=opts.SplitLineOpts(is_show=True, linestyle_opts=opts.LineStyleOpts(color="#F0F0F0")),
            ),
            legend_opts=opts.LegendOpts(orient="horizontal", item_gap=30, textstyle_opts=opts.TextStyleOpts(font_size=14)),
        )
    )
    bar.options["grid"] = [opts.GridOpts(is_contain_label=True, pos_right="80").opts]
    return engine.render(bar)
