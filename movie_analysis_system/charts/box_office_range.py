"""
票房区间分布图
==============
统计各票房区间的电影数量，支持年份筛选。
"""

import logging
from typing import Optional

from pyecharts.charts import Bar
from pyecharts import options as opts

from charts.chart_engine import ChartEngine
from database.db_manager import DatabaseManager

logger = logging.getLogger("BoxOfficeRange")

RANGES = [
    ("<1千万",     0,       1000),
    ("1千万~1亿",  1000,    10000),
    ("1亿~5亿",    10000,   50000),
    ("5亿~10亿",   50000,   100000),
    ("10亿~30亿",  100000,  300000),
    ("30亿+",      300000,  1e12),
]


def create_box_office_range_chart(db: DatabaseManager,
                                  year_start: Optional[int] = None,
                                  year_end: Optional[int] = None) -> str:
    """创建票房区间分布柱状图的 HTML。

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

        counts = []
        for label, lo, hi in RANGES:
            cursor.execute(
                "SELECT COUNT(*) AS cnt FROM movies "
                "WHERE box_office > 0 AND box_office >= ? AND box_office < ?" + yf,
                (lo, hi) + tuple(params),
            )
            cnt = cursor.fetchone()["cnt"]
            counts.append(cnt)
    finally:
        cursor.close()

    if sum(counts) == 0:
        return "<div style='padding: 40px; text-align: center; color: #757575;'>暂无票房数据</div>"

    labels = [r[0] for r in RANGES]

    bar = (
        Bar(init_opts=opts.InitOpts(width="100%", height="314px", bg_color="#FFFFFF"))
        .add_xaxis(labels)
        .add_yaxis(
            "电影数量", counts,
            label_opts=opts.LabelOpts(position="top", font_size=14),
            itemstyle_opts=opts.ItemStyleOpts(
                color={"type": "linear", "x": 0, "y": 0, "x2": 0, "y2": 1,
                       "colorStops": [
                           {"offset": 0, "color": "#64B5F6"},
                           {"offset": 1, "color": "#1E88E5"},
                       ]}
            ),
        )
        .set_global_opts(
            tooltip_opts=opts.TooltipOpts(trigger="axis", formatter="{b}<br/>电影数量: {c} 部"),
            xaxis_opts=opts.AxisOpts(axislabel_opts=opts.LabelOpts(font_size=15, color="#37474F", rotate=15)),
            yaxis_opts=opts.AxisOpts(
                name="电影数量",
                axislabel_opts=opts.LabelOpts(font_size=15, color="#757575"),
                splitline_opts=opts.SplitLineOpts(is_show=True, linestyle_opts=opts.LineStyleOpts(color="#F0F0F0")),
            ),
            legend_opts=opts.LegendOpts(is_show=False),
        )
    )
    bar.options["grid"] = [opts.GridOpts(is_contain_label=True, pos_right="40").opts]
    return engine.render(bar)
