"""
评分 vs 评价人数散点图
=====================
展示评分与评价人数之间的关系，帮助发现「口碑好且关注度高」的电影。
与四象限分析（评分×票房）互补，从不同维度评估电影表现。
"""

import logging

from pyecharts.charts import Scatter
from pyecharts import options as opts

from charts.chart_engine import ChartEngine, CHART_COLORS
from database.db_manager import DatabaseManager

logger = logging.getLogger("ScatterPlot")


def create_scatter_plot(db: DatabaseManager) -> str:
    """创建评分 vs 评价人数散点图的 HTML。

    Args:
        db: 数据库管理器实例

    Returns:
        完整的图表 HTML 字符串
    """
    engine = ChartEngine()

    conn = db.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT title, rating, rating_count
            FROM movies
            WHERE rating > 0 AND rating_count > 0
            ORDER BY rating_count DESC
        """)
        rows = cursor.fetchall()
        data = [dict(row) for row in rows]
    finally:
        cursor.close()

    if not data:
        return "<div style='padding: 40px; text-align: center; color: #757575; font-size: 14px;'>暂无数据</div>"

    scatter_data = [
        [item["rating"], item["rating_count"], item["title"]]
        for item in data
    ]
    ratings = [d[0] for d in scatter_data]
    counts = [d[1] for d in scatter_data]

    scatter = (
        Scatter(init_opts=opts.InitOpts(width="100%", height="334px", bg_color="#FFFFFF"))
        .add_xaxis([round(r, 1) for r in ratings])
        .add_yaxis(
            "电影",
            counts,
            symbol_size=10,
            label_opts=opts.LabelOpts(is_show=False),
            itemstyle_opts=opts.ItemStyleOpts(
                color=CHART_COLORS[2],
                opacity=0.7,
            ),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="评分 vs 评价人数",
                subtitle="口碑热度双高（右上）vs 小众佳作（左上）",
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
                        return data[2] + '<br/>评分: ' + data[0] + '<br/>评价人数: ' + data[1];
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
                name="评价人数",
                axislabel_opts=opts.LabelOpts(font_size=11, color="#757575"),
                splitline_opts=opts.SplitLineOpts(
                    is_show=True, linestyle_opts=opts.LineStyleOpts(color="#F0F0F0")
                ),
            ),
            legend_opts=opts.LegendOpts(is_show=False),
        )
    )
    scatter.options["grid"] = [opts.GridOpts(is_contain_label=True, pos_right="60").opts]
    return engine.render(scatter)
