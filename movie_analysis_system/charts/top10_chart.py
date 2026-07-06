"""
票房 Top 10 横向柱状图
======================
展示票房收入最高的 10 部电影，支持年份筛选。
"""

import logging
from typing import Optional

from pyecharts.charts import Bar
from pyecharts import options as opts

from charts.chart_engine import ChartEngine, CHART_COLORS, TOP3_COLORS
from database.db_manager import DatabaseManager

logger = logging.getLogger("Top10Chart")


def create_top10_chart(db: DatabaseManager,
                       year_start: Optional[int] = None,
                       year_end: Optional[int] = None) -> str:
    """创建票房 Top 10 横向柱状图的 HTML。

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

    where = "WHERE box_office > 0"
    params = []
    if year_start:
        where += " AND CAST(SUBSTR(release_date,1,4) AS INTEGER) >= ?"
        params.append(year_start)
    if year_end:
        where += " AND CAST(SUBSTR(release_date,1,4) AS INTEGER) <= ?"
        params.append(year_end)

    try:
        cursor.execute(f"""
            SELECT id, title, box_office, rating, genre
            FROM movies {where}
            ORDER BY box_office DESC LIMIT 10
        """, params)
        data = [dict(row) for row in cursor.fetchall()]
    finally:
        cursor.close()

    if not data:
        return "<div style='padding: 40px; text-align: center; color: #757575; font-size: 14px;'>暂无票房数据</div>"

    titles = [item["title"] for item in data]
    values = [round(item["box_office"], 0) for item in data]

    colors = TOP3_COLORS + CHART_COLORS[3:]
    item_colors = [colors[i] if i < len(colors) else "#1E88E5" for i in range(len(data))]

    bar = (
        Bar(init_opts=opts.InitOpts(width="100%", height="384px", bg_color="#FFFFFF"))
        .add_xaxis(titles)
        .add_yaxis(
            "票房（万元）",
            values,
            label_opts=opts.LabelOpts(
                position="top", formatter="{c} 万",
                font_size=12, font_weight="bold",
            ),
            itemstyle_opts=opts.ItemStyleOpts(color=item_colors),
        )
        .set_global_opts(
            tooltip_opts=opts.TooltipOpts(
                trigger="axis",
                formatter="{b}<br/>票房: {c} 万<br/>",
            ),
            xaxis_opts=opts.AxisOpts(
                axislabel_opts=opts.LabelOpts(
                    font_size=12, color="#757575",
                    rotate=20, interval=0,
                ),
                axistick_opts=opts.AxisTickOpts(is_show=False),
                splitline_opts=opts.SplitLineOpts(is_show=False),
            ),
            yaxis_opts=opts.AxisOpts(
                axislabel_opts=opts.LabelOpts(font_size=13, color="#37474F"),
                axistick_opts=opts.AxisTickOpts(is_show=False),
                splitline_opts=opts.SplitLineOpts(
                    is_show=True, linestyle_opts=opts.LineStyleOpts(color="#F0F0F0")
                ),
            ),
            legend_opts=opts.LegendOpts(is_show=False),
        )
    )
    return engine.render(bar)
