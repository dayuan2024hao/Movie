"""
四象限分析图
============
以评分均值和票房均值为分界线，将电影分为四类：
  - 叫好又叫座：高评分 + 高票房
  - 叫好不叫座：高评分 + 低票房
  - 叫座不叫好：低评分 + 高票房
  - 不叫好不叫座：低评分 + 低票房

帮助发现商业与口碑双赢的优质电影。
"""

import logging

from pyecharts.charts import Scatter
from pyecharts import options as opts
from pyecharts.globals import SymbolType

from charts.chart_engine import ChartEngine, CHART_COLORS
from database.db_manager import DatabaseManager

logger = logging.getLogger("FourQuadrant")


def create_four_quadrant_chart(db: DatabaseManager) -> str:
    """创建四象限分析图的 HTML。

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
            SELECT title, rating, box_office
            FROM movies
            WHERE rating > 0 AND box_office > 0
            ORDER BY box_office DESC
        """)
        rows = cursor.fetchall()
        raw = [dict(r) for r in rows]
    finally:
        cursor.close()

    if not raw:
        return "<div style='padding: 40px; text-align: center; color: #757575;'>暂无数据</div>"

    # 计算均分
    avg_rating = sum(r["rating"] for r in raw) / len(raw)
    avg_bo = sum(r["box_office"] for r in raw) / len(raw)

    # 分象限
    quadrants = {
        "high_high": {"name": "叫好又叫座 ⭐💰", "data": [], "color": "#E53935"},
        "high_low":  {"name": "叫好不叫座 ⭐",   "data": [], "color": "#1E88E5"},
        "low_high":  {"name": "叫座不叫好 💰",   "data": [], "color": "#FB8C00"},
        "low_low":   {"name": "双低 💤",         "data": [], "color": "#BDBDBD"},
    }

    for m in raw:
        rh = m["rating"] >= avg_rating
        bh = m["box_office"] >= avg_bo
        key = f"{'high' if rh else 'low'}_{'high' if bh else 'low'}"
        quadrants[key]["data"].append([m["rating"], round(m["box_office"], 0), m["title"]])

    scatter = Scatter(init_opts=opts.InitOpts(width="100%", height="354px", bg_color="#FFFFFF"))

    for qk, qv in quadrants.items():
        if qv["data"]:
            scatter.add_xaxis([d[0] for d in qv["data"]])
            scatter.add_yaxis(
                qv["name"],
                [d[1] for d in qv["data"]],
                symbol_size=12,
                label_opts=opts.LabelOpts(is_show=False),
                itemstyle_opts=opts.ItemStyleOpts(color=qv["color"], opacity=0.75),
            )

    # 用 markLine 画均值分割线
    scatter.set_global_opts(
        title_opts=opts.TitleOpts(
            title="四象限分析",
            subtitle=f"横轴=评分（均线{avg_rating:.1f}）  纵轴=票房（均线{avg_bo:,.0f}万）",
            pos_left="center",
            title_textstyle_opts=opts.TextStyleOpts(
                font_size=16, font_weight="bold", color="#37474F"
            ),
            subtitle_textstyle_opts=opts.TextStyleOpts(
                font_size=11, color="#757575"
            ),
        ),
        tooltip_opts=opts.TooltipOpts(
            formatter="""
                function(params) {
                    var idx = params.dataIndex;
                    // 找到实际数据项
                    for (var i = 0; i < params.seriesName.length; i++) {
                        if (params.seriesIndex == i) {
                            var data = params.data;
                            return data[2] + '<br/>评分: ' + data[0] + '<br/>票房: ' + data[1] + ' 万';
                        }
                    }
                    return '';
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
        legend_opts=opts.LegendOpts(
            orient="horizontal",
            item_gap=20,
            textstyle_opts=opts.TextStyleOpts(font_size=10),
        ),
    )
    scatter.options["grid"] = [opts.GridOpts(is_contain_label=True).opts]
    return engine.render(scatter)
