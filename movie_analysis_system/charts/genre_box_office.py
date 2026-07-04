"""
各类型平均票房柱状图
====================
展示每种电影类型的平均票房和最高票房，辅助选片决策。
多类型电影分别计入各类型。
"""

import logging

from pyecharts.charts import Bar
from pyecharts import options as opts

from charts.chart_engine import ChartEngine, CHART_COLORS
from database.db_manager import DatabaseManager

logger = logging.getLogger("GenreBoxOffice")


def create_genre_box_office_chart(db: DatabaseManager) -> str:
    """创建各类型平均票房柱状图的 HTML。

    Args:
        db: 数据库管理器实例

    Returns:
        完整的图表 HTML 字符串
    """
    engine = ChartEngine()

    conn = db.get_connection()
    cursor = conn.cursor()
    try:
        # 用 JSON 拆分多类型，计算每类型的平均票房和最高票房
        cursor.execute("""
            SELECT
                TRIM(value) AS genre,
                ROUND(AVG(box_office), 0) AS avg_box_office,
                ROUND(MAX(box_office), 0) AS max_box_office,
                COUNT(*) AS count
            FROM movies, json_each('["' || REPLACE(genre, ',', '","') || '"]')
            WHERE box_office > 0 AND rating > 0
            GROUP BY TRIM(value)
            ORDER BY avg_box_office DESC
        """)
        rows = cursor.fetchall()
        data = [dict(row) for row in rows]
    finally:
        cursor.close()

    if not data:
        return "<div style='padding: 40px; text-align: center; color: #757575;'>暂无类型票房数据</div>"

    # 取前 10 个类型
    major = data[:10]

    labels = [item["genre"] for item in major]
    avg_values = [item["avg_box_office"] for item in major]
    max_values = [item["max_box_office"] for item in major]

    bar = (
        Bar(init_opts=opts.InitOpts(bg_color="#FFFFFF"))
        .add_xaxis(labels)
        .add_yaxis(
            "平均票房(万)",
            avg_values,
            label_opts=opts.LabelOpts(
                position="top",
                formatter="{c}",
                font_size=10,
            ),
            itemstyle_opts=opts.ItemStyleOpts(color="#42A5F5"),
        )
        .add_yaxis(
            "最高票房(万)",
            max_values,
            label_opts=opts.LabelOpts(
                position="top",
                formatter="{c}",
                font_size=10,
            ),
            itemstyle_opts=opts.ItemStyleOpts(color="#FF7043"),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="各类型平均票房",
                subtitle="蓝色=平均票房，橙色=最高票房",
                pos_left="center",
                title_textstyle_opts=opts.TextStyleOpts(
                    font_size=16, font_weight="bold", color="#37474F"
                ),
                subtitle_textstyle_opts=opts.TextStyleOpts(
                    font_size=12, color="#757575"
                ),
            ),
            tooltip_opts=opts.TooltipOpts(
                trigger="axis",
                formatter="{b}<br/>{a}: {c} 万<br/>{a0}: {c0} 万",
            ),
            xaxis_opts=opts.AxisOpts(
                axislabel_opts=opts.LabelOpts(font_size=10, color="#37474F", rotate=20),
            ),
            yaxis_opts=opts.AxisOpts(
                name="票房（万元）",
                axislabel_opts=opts.LabelOpts(font_size=11, color="#757575"),
                splitline_opts=opts.SplitLineOpts(
                    is_show=True, linestyle_opts=opts.LineStyleOpts(color="#F0F0F0")
                ),
            ),
            legend_opts=opts.LegendOpts(
                pos_top="30",
                textstyle_opts=opts.TextStyleOpts(font_size=11),
            ),
        )
    )

    return engine.render(bar, height="310px")
