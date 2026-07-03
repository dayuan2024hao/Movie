"""
图表引擎
========
封装 PyECharts 图表的创建和渲染过程，提供统一的 HTML 生成接口。

用法：
    engine = ChartEngine()
    chart = Top10Chart(db)
    html = engine.render(chart.get_option())
    webview.setHtml(html)
"""

import logging
from typing import Optional

from pyecharts.charts import Bar, Pie, Scatter, Line
from pyecharts import options as opts
from pyecharts.globals import CurrentConfig, ThemeType

logger = logging.getLogger("ChartEngine")

# 图表主题配色（对应 UI 设计规范 2.3 图表色板）
CHART_COLORS = [
    "#1E88E5", "#43A047", "#FB8C00", "#E53935",
    "#8E24AA", "#00ACC1", "#FF7043", "#FDD835",
    "#26A69A", "#5C6BC0",
]

# Top 3 特殊配色
TOP3_COLORS = ["#E53935", "#FB8C00", "#FDD835"]


class ChartEngine:
    """图表引擎，统一管理图表的创建、主题和 HTML 渲染。"""

    def __init__(self) -> None:
        """初始化图表引擎。"""
        CurrentConfig.ONLINE_HOST = "https://cdn.jsdelivr.net/npm/echarts@5/dist/"
        logger.debug("图表引擎初始化完成")

    def render(self, chart, width: str = "100%", height: str = "400px") -> str:
        """将 PyECharts 图表对象渲染为完整的 HTML 字符串。

        Args:
            chart: PyECharts 图表对象（Bar / Pie / Scatter 等）
            width: 图表宽度 CSS 值
            height: 图表高度 CSS 值

        Returns:
            可直接在 QWebEngineView 中加载的 HTML 字符串
        """
        html = chart.render_embed()
        # 包裹完整 HTML 结构，确保自适应
        full_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        html, body {{ width: 100%; height: 100%; background: #FFFFFF; }}
        .chart-container {{ width: {width}; height: {height}; }}
    </style>
</head>
<body>
    <div class="chart-container">
        {html}
    </div>
</body>
</html>"""
        return full_html

    @staticmethod
    def base_opts(title: str = "", subtitle: str = "") -> dict:
        """返回图表通用配置选项。

        Args:
            title: 图表标题
            subtitle: 图表副标题

        Returns:
            配置选项字典
        """
        return {
            "title": {
                "text": title,
                "subtext": subtitle,
                "left": "center",
                "textStyle": {"fontSize": 16, "fontWeight": "bold", "color": "#37474F"},
                "subtextStyle": {"fontSize": 12, "color": "#757575"},
            },
            "color": CHART_COLORS,
            "backgroundColor": "#FFFFFF",
            "tooltip": {"trigger": "axis", "axisPointer": {"type": "shadow"}},
        }
