"""
票价分布直方图
==============
统计各票价区间的电影数量，直观展示票价结构。
区间划分：
  20元以下   → 低价票
  20~30元    → 经济票
  30~40元    → 标准票
  40~50元    → 中等票
  50~80元    → 高价票
  80元+      → 豪华票
"""

import logging

from pyecharts.charts import Bar
from pyecharts import options as opts

from charts.chart_engine import ChartEngine, CHART_COLORS
from database.db_manager import DatabaseManager

logger = logging.getLogger("PriceDistribution")

# 票价区间：（显示标签, 最小值, 最大值）
PRICE_RANGES = [
    ("<20元",   0,   20),
    ("20~30元", 20,  30),
    ("30~40元", 30,  40),
    ("40~50元", 40,  50),
    ("50~80元", 50,  80),
    ("80元+",   80,  1e6),
]


def create_price_distribution_chart(db: DatabaseManager) -> str:
    """创建票价分布直方图的 HTML。

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
        for label, lo, hi in PRICE_RANGES:
            cursor.execute(
                "SELECT COUNT(*) AS cnt FROM movies "
                "WHERE ticket_price > 0 AND ticket_price >= ? AND ticket_price < ?",
                (lo, hi),
            )
            cnt = cursor.fetchone()["cnt"]
            counts.append(cnt)
    finally:
        cursor.close()

    if sum(counts) == 0:
        return "<div style='padding: 40px; text-align: center; color: #757575;'>暂无票价数据</div>"

    labels = [r[0] for r in PRICE_RANGES]

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
                        {"offset": 0, "color": "#FF8A65"},
                        {"offset": 1, "color": "#E64A19"},
                    ],
                }
            ),
        )
        .set_global_opts(
            title_opts=opts.TitleOpts(
                title="票价区间分布",
                subtitle="各票价区间电影数量",
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
                axislabel_opts=opts.LabelOpts(font_size=10, color="#37474F"),
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
