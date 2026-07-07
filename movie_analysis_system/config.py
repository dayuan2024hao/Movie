"""
系统配置文件
============
集中管理 API Key、数据库路径等敏感/可配置项。
"""

# ─── OMDB API ───
# 从 www.omdbapi.com 注册获取，替换为空字符串即可跳过 OMDB 数据源
OMDB_API_KEY = ""

# ─── TMDB API ───
# 从 www.themoviedb.org 注册获取，替换为空字符串即可跳过 TMDB 数据源
TMDB_API_KEY = ""

# ─── DeepSeek API ───
# 从 platform.deepseek.com/api_keys 获取，配置后启用 AI 智能推荐功能
# 支持 OpenAI 兼容格式，可替换为其他兼容 API
DEEPSEEK_API_KEY = ""
DEEPSEEK_BASE_URL = ""
