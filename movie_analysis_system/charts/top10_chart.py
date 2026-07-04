"""
票房 Top 10 横向柱状图
======================
展示票房收入最高的 10 部电影，使用横向柱状图。
前三名使用金/银/铜色区分。
"""

import logging
from typing import Optional

from pyecharts.charts import Bar
from pyecharts import options as opts

from charts.chart_engine import ChartEngine, CHART_COLORS, TOP3_COLORS
from database.db_manager import DatabaseManager

logger = logging.getLogger("Top10Chart")


def create_top10_chart(db: DatabaseManager) -> str:
    """创建票房 Top 10 横向柱状图的 HTML。

    Args:
        db: 数据库管理器实例

    Returns:
        完整的图表 HTML 字符串
    """
    engine = ChartEngine()
    data = db.get_top10_box_office()

    if not data:
        return "<div style='padding: 40px; text-align: center; color: #757575; font-size: 14px;'>暂无票房数据</div>"

    # 提取数据
    titles = [item["title"] for item in data]
    values = [round(item["box_office"], 0) for item in data]
    ratings = [item["rating"] for item in data]

    # 颜色：前三名特殊色，其余使用常规色
    colors = TOP3_COLORS + CHART_COLORS[3:]  # type: ignore[operator]
    item_colors = [colors[i] if i < len(colors) else "#1E88E5" for i in range(len(data))]

    bar = (
        Bar(init_opts=opts.InitOpts(bg_color="#FFFFFF"))
        .add_xaxis(titles[::-1])  # 反转，让最高的在上面
        .add_yaxis(
            "票房（万元）",
            values[::-1],
            label_opts=opts.LabelOpts(
                position="right",
                formatter="{c} 万",
                font_size=12,
            ),
            itemstyle_opts=opts.ItemStyleOpts(color=item_colors[::-1]),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="票房 Top 10",
                subtitle="单位：万元",
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
                formatter="{b}<br/>票房: {c} 万<br/>评分: {d}",
            ),
            xaxis_opts=opts.AxisOpts(
                axislabel_opts=opts.LabelOpts(font_size=11, color="#757575"),
                axistick_opts=opts.AxisTickOpts(is_show=False),
                splitline_opts=opts.SplitLineOpts(is_show=False),
            ),
            yaxis_opts=opts.AxisOpts(
                axislabel_opts=opts.LabelOpts(font_size=11, color="#37474F"),
                axistick_opts=opts.AxisTickOpts(is_show=False),
                splitline_opts=opts.SplitLineOpts(
                    is_show=True, linestyle_opts=opts.LineStyleOpts(color="#F0F0F0")
                ),
            ),
            legend_opts=opts.LegendOpts(is_show=False),
        )
        .set_series_opts(
            label_opts=opts.LabelOpts(
                position="right",
                formatter="{c} 万",
                font_size=11,
            ),
        )
    )

    return engine.render(bar, height="390px")
