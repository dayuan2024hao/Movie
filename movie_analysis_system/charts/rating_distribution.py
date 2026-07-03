"""
评分分布直方图
==============
统计各评分区间的电影数量，展示评分整体分布情况。
"""

import logging
from typing import Optional

from pyecharts.charts import Bar
from pyecharts import options as opts

from charts.chart_engine import ChartEngine, CHART_COLORS
from database.db_manager import DatabaseManager

logger = logging.getLogger("RatingDistribution")


def create_rating_distribution(db: DatabaseManager) -> str:
    """创建评分分布直方图的 HTML。

    Args:
        db: 数据库管理器实例

    Returns:
        完整的图表 HTML 字符串
    """
    engine = ChartEngine()

    # 从数据库查各评分区间数量
    conn = db.get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT
                CAST(ROUND(rating) AS INTEGER) AS rating_group,
                COUNT(*) AS count
            FROM movies
            WHERE rating > 0
            GROUP BY rating_group
            ORDER BY rating_group
        """)
        rows = cursor.fetchall()
        data = [dict(row) for row in rows]
    finally:
        cursor.close()

    if not data:
        return "<div style='padding: 40px; text-align: center; color: #757575; font-size: 14px;'>暂无评分数据</div>"

    # 补全缺失的评分区间（1-10）
    rating_map = {r["rating_group"]: r["count"] for r in data}
    all_ratings = list(range(1, 11))
    all_counts = [rating_map.get(r, 0) for r in all_ratings]
    labels = [f"{r}分" for r in all_ratings]

    bar = (
        Bar(init_opts=opts.InitOpts(bg_color="#FFFFFF"))
        .add_xaxis(labels)
        .add_yaxis(
            "电影数量",
            all_counts,
            label_opts=opts.LabelOpts(position="top", font_size=11),
            itemstyle_opts=opts.ItemStyleOpts(
                color={
                    "type": "linear",
                    "x": 0, "y": 0, "x2": 0, "y2": 1,
                    "colorStops": [
                        {"offset": 0, "color": "#64B5F6"},
                        {"offset": 1, "color": "#1E88E5"},
                    ],
                }
            ),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="评分分布",
                subtitle="各评分区间电影数量",
                pos_left="center",
                title_textstyle_opts=opts.TextStyleOpts(
                    font_size=16, font_weight="bold", color="#37474F"
                ),
                subtitle_textstyle_opts=opts.TextStyleOpts(
                    font_size=12, color="#757575"
                ),
            ),
            tooltip_opts=opts.TooltipOpts(trigger="axis"),
            xaxis_opts=opts.AxisOpts(
                axislabel_opts=opts.LabelOpts(font_size=11, color="#37474F"),
            ),
            yaxis_opts=opts.AxisOpts(
                name="电影数量",
                axislabel_opts=opts.LabelOpts(font_size=11, color="#757575"),
                splitline_opts=opts.SplitLineOpts(
                    is_show=True, linestyle_opts=opts.LineStyleOpts(color="#F0F0F0")
                ),
            ),
            legend_opts=opts.LegendOpts(is_show=False),
        )
    )

    return engine.render(bar, height="300px")
