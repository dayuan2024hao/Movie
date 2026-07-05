"""
档期专题分析图
==============
按电影档期（春节/暑期/国庆/贺岁/其他）分组，
统计各档期电影数量、总票房、平均评分。

档期划分规则（基于公历日期）：
  - 春节档：1月20日 ~ 2月15日（含前后15天）
  - 暑期档：6月1日 ~ 8月31日
  - 国庆档：9月28日 ~ 10月7日
  - 贺岁档：12月1日 ~ 1月5日
  - 其他：其余日期
"""

import logging
from datetime import datetime
from typing import Optional

from pyecharts.charts import Bar
from pyecharts import options as opts

from charts.chart_engine import ChartEngine
from database.db_manager import DatabaseManager

logger = logging.getLogger("SeasonChart")

SEASONS = [
    ("春节档", "#E53935"),
    ("暑期档", "#1E88E5"),
    ("国庆档", "#FB8C00"),
    ("贺岁档", "#8E24AA"),
    ("其他",   "#BDBDBD"),
]


def _get_season(release_date: str) -> str:
    """根据上映日期判断所属档期。"""
    if not release_date or len(release_date) < 10:
        return "其他"
    try:
        dt = datetime.strptime(release_date[:10], "%Y-%m-%d")
        m, d = dt.month, dt.day

        # 春节档：1月20日~2月15日
        if (m == 1 and d >= 20) or (m == 2 and d <= 15):
            return "春节档"
        # 暑期档：6~8月
        if 6 <= m <= 8:
            return "暑期档"
        # 国庆档：9月28日~10月7日
        if (m == 9 and d >= 28) or (m == 10 and d <= 7):
            return "国庆档"
        # 贺岁档：12月1日~1月5日
        if (m == 12) or (m == 1 and d <= 5):
            return "贺岁档"
        return "其他"
    except (ValueError, TypeError):
        return "其他"


def create_season_chart(db: DatabaseManager,
                        year_start: Optional[int] = None,
                        year_end: Optional[int] = None) -> str:
    """创建档期专题分析图的 HTML。

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
            SELECT title, release_date, box_office, rating, genre
            FROM movies
            WHERE release_date IS NOT NULL AND release_date != '' {yf}
            ORDER BY release_date
        """, params)
        movies = [dict(r) for r in cursor.fetchall()]
    finally:
        cursor.close()

    if not movies:
        return "<div style='padding:40px;text-align:center;color:#757575;'>暂无数据</div>"

    # 按档期汇总
    season_data = {s[0]: {"count": 0, "box_office": 0.0, "rating_sum": 0.0,
                          "rating_count": 0, "titles": []}
                   for s in SEASONS}

    for m in movies:
        s = _get_season(m.get("release_date", ""))
        if s not in season_data:
            s = "其他"
        season_data[s]["count"] += 1
        bo = m.get("box_office") or 0
        if bo > 0:
            season_data[s]["box_office"] += bo
        r = m.get("rating") or 0
        if r > 0:
            season_data[s]["rating_sum"] += r
            season_data[s]["rating_count"] += 1
        season_data[s]["titles"].append(m["title"])

    # 构建图表数据
    season_order = [s[0] for s in SEASONS]
    colors = [s[1] for s in SEASONS]
    counts = [season_data[s]["count"] for s in season_order]
    box_offices = [round(season_data[s]["box_office"]) for s in season_order]
    avg_ratings = [
        round(season_data[s]["rating_sum"] / season_data[s]["rating_count"], 1)
        if season_data[s]["rating_count"] > 0 else 0
        for s in season_order
    ]

    bar = (
        Bar(init_opts=opts.InitOpts(width="100%", height="364px", bg_color="#FFFFFF"))
        .add_xaxis(season_order)
        .add_yaxis("电影数量", counts,
                   label_opts=opts.LabelOpts(position="top", font_size=14),
                   itemstyle_opts=opts.ItemStyleOpts(color=colors),
                   yaxis_index=0)
        .add_yaxis("总票房(万)", box_offices,
                   label_opts=opts.LabelOpts(position="top", formatter="{c}", font_size=14),
                   itemstyle_opts=opts.ItemStyleOpts(color=[c + "80" for c in colors]),
                   yaxis_index=1)
        .set_global_opts(
            tooltip_opts=opts.TooltipOpts(trigger="axis",
                formatter="{b}<br/>{a}: {c} 部<br/>{a0}: {c0} 万<br/>均分: ..."),
            xaxis_opts=opts.AxisOpts(axislabel_opts=opts.LabelOpts(font_size=15, color="#37474F")),
            yaxis_opts=opts.AxisOpts(name="电影数量",
                axislabel_opts=opts.LabelOpts(font_size=15, color="#757575"),
                splitline_opts=opts.SplitLineOpts(is_show=True, linestyle_opts=opts.LineStyleOpts(color="#F0F0F0"))),
            legend_opts=opts.LegendOpts(orient="horizontal", item_gap=20, textstyle_opts=opts.TextStyleOpts(font_size=14)),
        )
    )
    bar.options["grid"] = [opts.GridOpts(is_contain_label=True, pos_right="80", pos_left="60").opts]
    # 添加右轴
    bar.extend_axis(yaxis=opts.AxisOpts(name="总票房(万)", type_="value",
        axislabel_opts=opts.LabelOpts(font_size=15, color="#FF7043"),
        splitline_opts=opts.SplitLineOpts(is_show=False)))

    return engine.render(bar)
