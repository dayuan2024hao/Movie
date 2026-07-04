"""
票房区间分布图
==============
统计各票房区间的电影数量，快速了解票房分布格局。
区间划分：
  <1千万     → 低票房
  1千万~1亿  → 中低票房
  1亿~5亿    → 中等票房
  5亿~10亿   → 中高票房
  10亿~30亿  → 高票房
  30亿+      → 爆款
"""

import logging

from pyecharts.charts import Bar
from pyecharts import options as opts
from pyecharts.globals import ThemeType

from charts.chart_engine import ChartEngine, CHART_COLORS
from database.db_manager import DatabaseManager

logger = logging.getLogger("BoxOfficeRange")

# 票房区间定义：（显示标签, 最小值, 最大值, 单位:万元）
RANGES = [
    ("<1千万",     0,       1000),
    ("1千万~1亿",  1000,    10000),
    ("1亿~5亿",    10000,   50000),
    ("5亿~10亿",   50000,   100000),
    ("10亿~30亿",  100000,  300000),
    ("30亿+",      300000,  1e12),
]

RANGE_COLORS = ["#B0BEC5", "#90A4AE", "#64B5F6", "#42A5F5", "#1E88E5", "#0D47A1"]


def create_box_office_range_chart(db: DatabaseManager) -> str:
    """创建票房区间分布柱状图的 HTML。

    Args:
        db: 数据库管理器实例

    Returns:
        完整的图表 HTML 字符串
    """
    engine = ChartEngine()

    conn = db.get_connection()
    cursor = conn.cursor()
    try:
        counts = []
        for label, lo, hi in RANGES:
            cursor.execute(
                "SELECT COUNT(*) AS cnt FROM movies "
                "WHERE box_office > 0 AND box_office >= ? AND box_office < ?",
                (lo, hi),
            )
            cnt = cursor.fetchone()["cnt"]
            counts.append(cnt)
    finally:
        cursor.close()

    if sum(counts) == 0:
        return "<div style='padding: 40px; text-align: center; color: #757575;'>暂无票房数据</div>"

    labels = [r[0] for r in RANGES]

    bar = (
        Bar(init_opts=opts.InitOpts(bg_color="#FFFFFF"))
        .add_xaxis(labels)
        .add_yaxis(
            "电影数量",
            counts,
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
                title="票房区间分布",
                subtitle="各票房区间电影数量分布",
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
                formatter="{b}<br/>电影数量: {c} 部",
            ),
            xaxis_opts=opts.AxisOpts(
                axislabel_opts=opts.LabelOpts(font_size=10, color="#37474F", rotate=15),
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

    return engine.render(bar, height="250px")
