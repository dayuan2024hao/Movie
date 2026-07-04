"""
类型占比饼图
============
展示各电影类型的数量和比例，支持交互式点击高亮。
多类型电影（如"动作,科幻"）会分别计入各类型。
"""

import logging
from typing import Optional

from pyecharts.charts import Pie
from pyecharts import options as opts

from charts.chart_engine import ChartEngine, CHART_COLORS
from database.db_manager import DatabaseManager

logger = logging.getLogger("GenrePie")


def create_genre_pie(db: DatabaseManager) -> str:
    """创建类型占比饼图的 HTML。

    Args:
        db: 数据库管理器实例

    Returns:
        完整的图表 HTML 字符串
    """
    engine = ChartEngine()
    data = db.get_genre_stats()

    if not data:
        return "<div style='padding: 40px; text-align: center; color: #757575; font-size: 14px;'>暂无类型数据</div>"

    # 取前 8 个主要类型，其余归入"其他"
    major = data[:8]
    others_count = sum(item["count"] for item in data[8:])

    pie_data = [(item["genre"], item["count"]) for item in major]
    if others_count > 0:
        pie_data.append(("其他", others_count))

    pie = (
        Pie(init_opts=opts.InitOpts(bg_color="#FFFFFF"))
        .add(
            series_name="电影类型",
            data_pair=pie_data,
            radius=["30%", "60%"],
            center=["50%", "55%"],
            label_opts=opts.LabelOpts(
                formatter="{b}: {c} ({d}%)",
                font_size=11,
            ),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="电影类型占比",
                pos_left="center",
                title_textstyle_opts=opts.TextStyleOpts(
                    font_size=16, font_weight="bold", color="#37474F"
                ),
            ),
            tooltip_opts=opts.TooltipOpts(
                trigger="item",
                formatter="{b}: {c} 部 ({d}%)",
            ),
            legend_opts=opts.LegendOpts(
                orient="vertical",
                pos_left="left",
                textstyle_opts=opts.TextStyleOpts(font_size=11, color="#616161"),
            ),
        )
        .set_series_opts(
            label_opts=opts.LabelOpts(is_show=True),
        )
    )

    return engine.render(pie, height="270px")
