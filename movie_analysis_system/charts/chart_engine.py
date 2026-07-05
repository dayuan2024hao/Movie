"""
图表引擎
========
封装 PyECharts 图表的创建和渲染过程，提供统一的 HTML 生成接口。

⚠️ 核心约束：
  每个图表模块必须在 InitOpts 中显式设置 width="100%" + 正确 height，
  禁止依赖 pyecharts 默认尺寸（900×500px），否则容器与图表尺寸不匹配
  会导致内部滚动条或内容裁剪。
"""

import logging

from pyecharts.charts import Bar, Pie, Scatter, Line
from pyecharts import options as opts
from pyecharts.globals import CurrentConfig, ThemeType

logger = logging.getLogger("ChartEngine")

# 图表主题配色
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
        CurrentConfig.ONLINE_HOST = "https://cdn.jsdelivr.net/npm/echarts@5/dist/"
        logger.debug("图表引擎初始化完成")

    def render(self, chart) -> str:
        """将 PyECharts 图表对象渲染为完整 HTML。
        图表尺寸由 chart 的 InitOpts(width/height) 控制。
        容器使用 overflow:hidden 防止 Chromium 产生额外滚动条。

        Args:
            chart: PyECharts 图表对象（Bar / Pie / Scatter 等）

        Returns:
            可直接在 QWebEngineView 中加载的 HTML 字符串
        """
        html = chart.render_embed()
        full_html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html, body {
            width: 100%; height: 100%;
            overflow: visible;
            background: #FFFFFF;
        }
    </style>
</head>
<body>
    """ + html + """
</body>
</html>"""
        return full_html

    @staticmethod
    def base_opts(title: str = "", subtitle: str = "") -> dict:
        """返回图表通用配置选项。"""
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
