"""
系统配置文件
============
集中管理 API Key、数据库路径等敏感/可配置项。
"""

# ─── OMDB API ───
# 从 www.omdbapi.com 注册获取
OMDB_API_KEY = "c8baa94c"

# ─── TMDB API ───
# 从 www.themoviedb.org 注册获取
TMDB_API_KEY = "689c6bb83710eee417a14d457d92e86d"

# ─── DeepSeek API ───
# 从 platform.deepseek.com/api_keys 获取
# 支持 OpenAI 兼容格式，可替换为其他兼容 API
DEEPSEEK_API_KEY = "sk-your-key-here"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
