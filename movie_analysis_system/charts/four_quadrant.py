"""
四象限分析图
============
以评分均值和票房均值为分界线将电影分四类，支持年份筛选。
自动标注「黑马」（低分高票房）和「扑街」（高分低票房）影片。
"""

import logging
from typing import Optional

from pyecharts.charts import Scatter
from pyecharts import options as opts

from charts.chart_engine import ChartEngine
from database.db_manager import DatabaseManager

logger = logging.getLogger("FourQuadrant")


def create_four_quadrant_chart(db: DatabaseManager,
                               year_start: Optional[int] = None,
                               year_end: Optional[int] = None) -> str:
    """创建四象限分析图的 HTML。

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

        cursor.execute(f"""
            SELECT title, rating, box_office
            FROM movies WHERE rating > 0 AND box_office > 0 {yf}
            ORDER BY box_office DESC
        """, params)
        rows = cursor.fetchall()
        raw = [dict(r) for r in rows]
    finally:
        cursor.close()

    if not raw:
        return "<div style='padding: 40px; text-align: center; color: #757575;'>暂无数据</div>"

    avg_rating = sum(r["rating"] for r in raw) / len(raw)
    avg_bo = sum(r["box_office"] for r in raw) / len(raw)

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
            scatter.add_yaxis(qv["name"], [d[1] for d in qv["data"]],
                              symbol_size=12, label_opts=opts.LabelOpts(is_show=False),
                              itemstyle_opts=opts.ItemStyleOpts(color=qv["color"], opacity=0.75))

    # 异常检测标注：黑马（低分高票房 Top2）和 扑街（高分低票房 Top2）
    dark_horses = sorted(quadrants["low_high"]["data"],
                         key=lambda x: x[1], reverse=True)[:2]
    flops = sorted(quadrants["high_low"]["data"],
                   key=lambda x: x[0], reverse=True)[:2]

    anomaly_data = []
    anomaly_labels = []
    for dh in dark_horses:
        anomaly_data.append(dh)
        anomaly_labels.append({"name": f"🐎 {dh[2][:6]}", "label": {"show": True,
            "formatter": f"🐎 黑马\n{dh[2]}", "font_size": 10, "color": "#E65100"}})
    for fl in flops:
        anomaly_data.append(fl)
        anomaly_labels.append({"name": f"💀 {fl[2][:6]}", "label": {"show": True,
            "formatter": f"💀 扑街\n{fl[2]}", "font_size": 10, "color": "#1A237E"}})

    # 找到异常点在各自系列中的索引，然后加 markPoint，但更简单：
    # 将这些异常点作为独立系列添加，设置较大的 symbol 和 label
    if anomaly_data:
        for ad in anomaly_data:
            # 为每个异常点生成单独的 markPoint 格式
            pass

        # 用独立系列 + 标签显示
        label_texts = []
        for i, ad in enumerate(anomaly_data):
            is_horse = any(dh[2] == ad[2] for dh in dark_horses)
            prefix = "🐎 " if is_horse else "💀 "
            label_texts.append(prefix + ad[2][:8])

        scatter.add_xaxis([d[0] for d in anomaly_data])
        scatter.add_yaxis("异常标注",
            [d[1] for d in anomaly_data],
            symbol="diamond", symbol_size=22,
            label_opts=opts.LabelOpts(
                is_show=True, position="right",
                formatter="""function(params) {
                    var labels = """ + str(label_texts) + """;
                    return labels[params.dataIndex];
                }""",
                font_size=10, color="#333",
                background_color="rgba(255,255,255,0.8)",
                border_color="#1E88E5", border_width=1,
                padding=[2, 4],
            ),
            itemstyle_opts=opts.ItemStyleOpts(
                color="transparent",
                border_color="transparent",
            ),
            tooltip_opts=opts.TooltipOpts(
                formatter="""function(params) {
                    var data = params.data;
                    return data[2] + '<br/>评分: ' + data[0] + '<br/>票房: ' + data[1] + ' 万';
                }""",
            ),
        )

    scatter.set_global_opts(
        title_opts=opts.TitleOpts(
            subtitle=f"评分均线{avg_rating:.1f} · 票房均线{avg_bo:,.0f}万 · 🐎黑马 💀扑街",
            pos_left="center", pos_top="5",
            subtitle_textstyle_opts=opts.TextStyleOpts(font_size=12, color="#757575"),
        ),
        tooltip_opts=opts.TooltipOpts(
            formatter="""function(params) {
                var data = params.data;
                return data ? (data[2] + '<br/>评分: ' + data[0] +
                       '<br/>票房: ' + data[1] + ' 万') : '';
            }""",
        ),
        xaxis_opts=opts.AxisOpts(name="评分", min_=0, max_=10,
            axislabel_opts=opts.LabelOpts(font_size=15, color="#757575"),
            splitline_opts=opts.SplitLineOpts(is_show=True, linestyle_opts=opts.LineStyleOpts(color="#F0F0F0"))),
        yaxis_opts=opts.AxisOpts(name="票房（万元）",
            axislabel_opts=opts.LabelOpts(font_size=15, color="#757575"),
            splitline_opts=opts.SplitLineOpts(is_show=True, linestyle_opts=opts.LineStyleOpts(color="#F0F0F0"))),
        legend_opts=opts.LegendOpts(orient="horizontal", item_gap=16,
            textstyle_opts=opts.TextStyleOpts(font_size=14),
            selected_mode="multiple"),
    )
    scatter.options["grid"] = [opts.GridOpts(
        is_contain_label=True, pos_top="40", pos_bottom="40"
    ).opts]
    return engine.render(scatter)
