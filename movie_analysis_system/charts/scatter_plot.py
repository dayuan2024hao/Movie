"""
评分 vs 评价人数散点图
=====================
展示评分与评价人数之间的关系，支持年份筛选。
"""

import logging
from typing import Optional

from pyecharts.charts import Scatter
from pyecharts import options as opts

from charts.chart_engine import ChartEngine, CHART_COLORS
from database.db_manager import DatabaseManager

logger = logging.getLogger("ScatterPlot")


def create_scatter_plot(db: DatabaseManager,
                        year_start: Optional[int] = None,
                        year_end: Optional[int] = None) -> str:
    """创建评分 vs 评价人数散点图的 HTML。

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
            SELECT title, rating, rating_count
            FROM movies WHERE rating > 0 AND rating_count > 0 {yf}
            ORDER BY rating_count DESC
        """, params)
        data = [dict(row) for row in cursor.fetchall()]
    finally:
        cursor.close()

    if not data:
        return "<div style='padding: 40px; text-align: center; color: #757575; font-size: 14px;'>暂无数据</div>"

    scatter_data = [[item["rating"], item["rating_count"], item["title"]] for item in data]

    scatter = (
        Scatter(init_opts=opts.InitOpts(width="100%", height="354px", bg_color="#FFFFFF"))
        .add_xaxis([round(d[0], 1) for d in scatter_data])
        .add_yaxis("电影", [d[1] for d in scatter_data],
                   symbol_size=10, label_opts=opts.LabelOpts(is_show=False),
                   itemstyle_opts=opts.ItemStyleOpts(color=CHART_COLORS[2], opacity=0.7))
        .set_global_opts(
            title_opts=opts.TitleOpts(
                subtitle="口碑热度双高（右上）vs 小众佳作（左上）",
                pos_left="center", subtitle_textstyle_opts=opts.TextStyleOpts(font_size=13, color="#757575"),
            ),
            tooltip_opts=opts.TooltipOpts(
                formatter="""function(params) {
                    var data = params.data;
                    return data[2] + '<br/>评分: ' + data[0] + '<br/>评价人数: ' + data[1];
                }""",
            ),
            xaxis_opts=opts.AxisOpts(name="评分", min_=0, max_=10,
                axislabel_opts=opts.LabelOpts(font_size=11, color="#757575"),
                splitline_opts=opts.SplitLineOpts(is_show=True, linestyle_opts=opts.LineStyleOpts(color="#F0F0F0"))),
            yaxis_opts=opts.AxisOpts(name="评价人数",
                axislabel_opts=opts.LabelOpts(font_size=11, color="#757575"),
                splitline_opts=opts.SplitLineOpts(is_show=True, linestyle_opts=opts.LineStyleOpts(color="#F0F0F0"))),
            legend_opts=opts.LegendOpts(is_show=False),
        )
    )
    scatter.options["grid"] = [opts.GridOpts(is_contain_label=True, pos_right="60").opts]
    return engine.render(scatter)
