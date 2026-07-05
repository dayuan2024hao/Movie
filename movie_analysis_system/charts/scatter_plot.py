"""
评分 vs 票房散点图
==================
展示评分与票房之间的关系，帮助发现高评分高票房的优质电影。
悬停显示电影名称。
"""

import logging
from typing import Optional

from pyecharts.charts import Scatter
from pyecharts import options as opts

from charts.chart_engine import ChartEngine, CHART_COLORS
from database.db_manager import DatabaseManager

logger = logging.getLogger("ScatterPlot")


def create_scatter_plot(db: DatabaseManager) -> str:
    """创建评分 vs 票房散点图的 HTML。

    Args:
        db: 数据库管理器实例

    Returns:
        完整的图表 HTML 字符串
    """
    engine = ChartEngine()

    # 查询评分和票房数据
    conn = db.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT title, rating, box_office
            FROM movies
            WHERE rating > 0 AND box_office > 0
            ORDER BY box_office DESC
        """)
        rows = cursor.fetchall()
        data = [dict(row) for row in rows]
    finally:
        cursor.close()

    if not data:
        return "<div style='padding: 40px; text-align: center; color: #757575; font-size: 14px;'>暂无数据</div>"

    # 准备散点数据
    scatter_data = [
        [item["rating"], round(item["box_office"], 0), item["title"]]
        for item in data
    ]
    ratings = [d[0] for d in scatter_data]
    box_offices = [d[1] for d in scatter_data]

    scatter = (
        Scatter(init_opts=opts.InitOpts(width="100%", height="334px", bg_color="#FFFFFF"))
        .add_xaxis([round(r, 1) for r in ratings])
        .add_yaxis(
            "电影",
            box_offices,
            symbol_size=10,
            label_opts=opts.LabelOpts(is_show=False),
            itemstyle_opts=opts.ItemStyleOpts(
                color=CHART_COLORS[0],
                opacity=0.7,
            ),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="评分 vs 票房",
                subtitle="每部电影的评分与票房关系",
                pos_left="center",
                title_textstyle_opts=opts.TextStyleOpts(
                    font_size=16, font_weight="bold", color="#37474F"
                ),
                subtitle_textstyle_opts=opts.TextStyleOpts(
                    font_size=12, color="#757575"
                ),
            ),
            tooltip_opts=opts.TooltipOpts(
                formatter="""
                    function(params) {
                        var idx = params.dataIndex;
                        var data = params.data;
                        return data[2] + '<br/>评分: ' + data[0] + '<br/>票房: ' + data[1] + ' 万';
                    }
                """,
            ),
            xaxis_opts=opts.AxisOpts(
                name="评分",
                min_=0,
                max_=10,
                axislabel_opts=opts.LabelOpts(font_size=11, color="#757575"),
                splitline_opts=opts.SplitLineOpts(
                    is_show=True, linestyle_opts=opts.LineStyleOpts(color="#F0F0F0")
                ),
            ),
            yaxis_opts=opts.AxisOpts(
                name="票房（万元）",
                axislabel_opts=opts.LabelOpts(font_size=11, color="#757575"),
                splitline_opts=opts.SplitLineOpts(
                    is_show=True, linestyle_opts=opts.LineStyleOpts(color="#F0F0F0")
                ),
            ),
            legend_opts=opts.LegendOpts(is_show=False),
        )
    )

    return engine.render(scatter)
