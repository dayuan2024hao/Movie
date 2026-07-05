"""
报告生成器
==========
支持将看板状态导出为 PDF/图片，并生成结构化数据分析报告。

功能：
  1. export_pdf(db, filepath) — 看板内容导出为 PDF
  2. export_image(widget, filepath) — 任意 QWidget 导出为图片
  3. generate_report(db, filepath) — 结构化分析报告（HTML）
"""

import logging
import os
import json
from datetime import datetime
from typing import Optional

from PyQt5.QtWidgets import QWidget
from PyQt5.QtCore import QUrl
from PyQt5.QtWebEngineWidgets import QWebEngineView

from database.db_manager import DatabaseManager

logger = logging.getLogger("ReportGenerator")


def _gather_stats(db: DatabaseManager) -> dict:
    """收集所有统计数据用于报告。"""
    stats = db.get_statistics() or {}
    conn = db.get_connection()
    cursor = conn.cursor()

    # 各状态电影数
    cursor.execute("SELECT showing_status, COUNT(*) as cnt FROM movies GROUP BY showing_status")
    status_counts = {row["showing_status"]: row["cnt"] for row in cursor.fetchall()}

    # 各类型分布
    cursor.execute("""
        SELECT TRIM(value) AS genre, COUNT(*) AS cnt
        FROM movies, json_each('["' || REPLACE(genre, ',', '","') || '"]')
        GROUP BY TRIM(value) ORDER BY cnt DESC
    """)
    genre_dist = [dict(r) for r in cursor.fetchall()]

    # 评分区间分布
    cursor.execute("""
        SELECT
            CASE
                WHEN rating >= 9 THEN '9-10'
                WHEN rating >= 8 THEN '8-9'
                WHEN rating >= 7 THEN '7-8'
                WHEN rating >= 6 THEN '6-7'
                ELSE '0-6'
            END AS bucket,
            COUNT(*) AS cnt
        FROM movies WHERE rating > 0
        GROUP BY bucket ORDER BY bucket DESC
    """)
    rating_dist = [dict(r) for r in cursor.fetchall()]

    # 票房区间分布
    cursor.execute("""
        SELECT
            CASE
                WHEN box_office >= 100000 THEN '10亿+'
                WHEN box_office >= 50000 THEN '5-10亿'
                WHEN box_office >= 10000 THEN '1-5亿'
                WHEN box_office >= 1000 THEN '千万级'
                ELSE '千万以下'
            END AS bucket,
            COUNT(*) AS cnt
        FROM movies WHERE box_office > 0
        GROUP BY bucket ORDER BY MIN(box_office)
    """)
    box_office_dist = [dict(r) for r in cursor.fetchall()]

    # 最新爬取记录
    cursor.execute(
        "SELECT status, records_count, message, created_at FROM crawl_record ORDER BY id DESC LIMIT 5"
    )
    crawl_logs = [dict(r) for r in cursor.fetchall()]

    cursor.close()

    return {
        "stats": stats,
        "status_counts": status_counts,
        "genre_dist": genre_dist,
        "rating_dist": rating_dist,
        "box_office_dist": box_office_dist,
        "crawl_logs": crawl_logs,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_movies": stats.get("total_movies", 0),
        "showing": status_counts.get("showing", 0),
        "coming_soon": status_counts.get("coming_soon", 0),
        "released": status_counts.get("released", 0),
    }


def export_image(widget: QWidget, filepath: str) -> bool:
    """将任意 QWidget 导出为 PNG 图片。

    Args:
        widget: 要导出的组件（如 dashboard 的 scroll area）
        filepath: 输出路径（建议 .png）

    Returns:
        是否成功
    """
    try:
        pixmap = widget.grab()
        pixmap.save(filepath, "PNG")
        logger.info("图片已导出: %s (%dx%d)", filepath, pixmap.width(), pixmap.height())
        return True
    except Exception as e:
        logger.error("图片导出失败: %s", e)
        return False


def export_pdf_from_webview(webview: QWebEngineView, filepath: str) -> bool:
    """将 QWebEngineView 内容导出为 PDF。"""
    try:
        webview.page().printToPdf(filepath)
        logger.info("PDF 已导出: %s", filepath)
        return True
    except Exception as e:
        logger.error("PDF 导出失败: %s", e)
        return False


def generate_report(db: DatabaseManager, filepath: str) -> bool:
    """生成结构化数据分析报告（HTML 格式）。

    Report includes:
      - 数据概览（电影总数、票房、评分等）
      - 类型分布
      - 评分分布
      - 票房分布
      - 推荐结论摘要
      - 数据来源说明

    Args:
        db: 数据库管理器
        filepath: 输出 HTML 文件路径

    Returns:
        是否成功
    """
    try:
        data = _gather_stats(db)
        stats = data["stats"]
        s = stats  # alias

        # 构建 HTML 报告
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>电影票分析系统 · 数据报告</title>
<style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ font-family: 'Microsoft YaHei', 'PingFang SC', sans-serif; background:#f5f7fa; color:#333; padding:40px; }}
    .container {{ max-width:900px; margin:0 auto; background:white; border-radius:12px; padding:40px; box-shadow:0 2px 12px rgba(0,0,0,0.08); }}
    h1 {{ font-size:24px; color:#1E88E5; margin-bottom:4px; }}
    .subtitle {{ color:#999; font-size:13px; margin-bottom:24px; }}
    h2 {{ font-size:18px; color:#37474F; margin:28px 0 12px; padding-bottom:8px; border-bottom:2px solid #1E88E5; }}
    .card-row {{ display:flex; gap:12px; flex-wrap:wrap; margin:12px 0; }}
    .card {{ flex:1; min-width:120px; background:#f8f9fa; border-radius:8px; padding:16px; text-align:center; }}
    .card .num {{ font-size:28px; font-weight:bold; color:#1E88E5; }}
    .card .label {{ font-size:12px; color:#666; margin-top:4px; }}
    table {{ width:100%; border-collapse:collapse; margin:12px 0; }}
    th, td {{ padding:8px 12px; text-align:left; border-bottom:1px solid #eee; font-size:13px; }}
    th {{ background:#f0f4f8; font-weight:bold; color:#555; }}
    tr:hover td {{ background:#f8faff; }}
    .insight {{ background:#e3f2fd; border-left:4px solid #1E88E5; padding:16px; border-radius:4px; margin:16px 0; }}
    .insight p {{ margin:4px 0; font-size:13px; color:#444; }}
    .footer {{ margin-top:32px; padding-top:16px; border-top:1px solid #eee; font-size:11px; color:#999; text-align:center; }}
</style>
</head>
<body>
<div class="container">
    <h1>🎬 电影票分析系统 · 数据分析报告</h1>
    <p class="subtitle">生成时间: {data['generated_at']}</p>

    <h2>📊 数据概览</h2>
    <div class="card-row">
        <div class="card"><div class="num">{s.get('total_movies', 0)}</div><div class="label">电影总数</div></div>
        <div class="card"><div class="num">{s.get('total_box_office', 0):,.0f}</div><div class="label">总票房(万)</div></div>
        <div class="card"><div class="num">{s.get('avg_rating', 0):.1f}</div><div class="label">平均评分</div></div>
        <div class="card"><div class="num">{s.get('avg_ticket_price', 0):.0f}</div><div class="label">平均票价(元)</div></div>
    </div>
    <div class="card-row">
        <div class="card"><div class="num" style="color:#43A047;">{data.get('showing', 0)}</div><div class="label">热映中</div></div>
        <div class="card"><div class="num" style="color:#FB8C00;">{data.get('coming_soon', 0)}</div><div class="label">即将上映</div></div>
        <div class="card"><div class="num" style="color:#757575;">{data.get('released', 0)}</div><div class="label">已下映</div></div>
    </div>

    <h2>🎭 类型分布</h2>
    <table>
        <tr><th>类型</th><th>数量</th><th>占比</th></tr>
"""
        total = max(data["total_movies"], 1)
        for item in data["genre_dist"]:
            pct = item["cnt"] / total * 100
            html += f"        <tr><td>{item['genre']}</td><td>{item['cnt']}</td><td>{pct:.1f}%</td></tr>\n"

        html += """    </table>

    <h2>⭐ 评分分布</h2>
    <table>
        <tr><th>评分区间</th><th>电影数量</th></tr>
"""
        for item in data["rating_dist"]:
            html += f"        <tr><td>{item['bucket']}</td><td>{item['cnt']}</td></tr>\n"

        html += """    </table>

    <h2>💰 票房分布</h2>
    <table>
        <tr><th>区间</th><th>电影数量</th></tr>
"""
        for item in data["box_office_dist"]:
            html += f"        <tr><td>{item['bucket']}</td><td>{item['cnt']}</td></tr>\n"

        # 数据洞察摘要
        avg_r = s.get('avg_rating', 0)
        tag = "优秀" if avg_r >= 8.0 else "良好" if avg_r >= 7.0 else "一般"
        html += f"""    </table>

    <h2>💡 关键结论摘要</h2>
    <div class="insight">
        <p>📌 系统共收录 <strong>{s.get('total_movies', 0)}</strong> 部电影数据</p>
        <p>⭐ 平均评分 <strong>{avg_r:.1f}</strong>，整体质量{tag}</p>
        <p>💰 累计总票房 <strong>{s.get('total_box_office', 0):,.0f} 万</strong></p>
        <p>🎫 平均票价 <strong>{s.get('avg_ticket_price', 0):.0f} 元</strong></p>
        <p>🏆 最高评分电影: <strong>{s.get('highest_rated', '—')}</strong> ({s.get('highest_rated_score', 0):.1f})</p>
        <p>🥇 最高票房电影: <strong>{s.get('highest_box_office', '—')}</strong> ({s.get('highest_box_office_value', 0):,.0f} 万)</p>
"""
        if data["showing"] > 0:
            html += f"        <p>🎬 当前热映 <strong>{data['showing']}</strong> 部，可供实时推荐</p>\n"
        html += """    </div>

    <h2>🔍 数据来源</h2>
"""
        if data["crawl_logs"]:
            html += """    <table>
        <tr><th>来源</th><th>状态</th><th>记录数</th><th>时间</th></tr>
"""
            for log in data["crawl_logs"]:
                html += f"        <tr><td>{log.get('source', '—')}</td><td>{log.get('status', '—')}</td><td>{log.get('records_count', 0)}</td><td>{log.get('created_at', '—')}</td></tr>\n"
            html += "    </table>\n"
        else:
            html += "    <p style='color:#999; font-size:13px;'>暂无爬取记录</p>\n"

        html += f"""
    <div class="footer">
        电影票分析系统 · 自动生成 · {data['generated_at']}
    </div>
</div>
</body>
</html>"""

        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)

        logger.info("分析报告已生成: %s", filepath)
        return True

    except Exception as e:
        logger.error("报告生成失败: %s", e)
        import traceback
        traceback.print_exc()
        return False
