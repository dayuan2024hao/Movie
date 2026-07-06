"""
DeepSeek API 客户端
==================
使用 requests 调用 DeepSeek OpenAI 兼容接口。
无需额外依赖。
"""

import json
import logging
from typing import Optional

import requests

from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL

logger = logging.getLogger("LLMClient")

# 默认模型名
MODEL = "deepseek-chat"
TIMEOUT = 30


def chat(messages: list[dict]) -> str:
    """发送对话到 DeepSeek API，返回回复文本。

    Args:
        messages: OpenAI 格式的消息列表
            [{"role": "system", "content": "..."},
             {"role": "user", "content": "..."},
             {"role": "assistant", "content": "..."}]

    Returns:
        AI 回复文本，失败时返回错误提示
    """
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY.startswith("sk-your"):
        return "⚠️ 系统提示：DeepSeek API Key 未配置，请在 config.py 中设置 DEEPSEEK_API_KEY。"

    url = f"{DEEPSEEK_BASE_URL.rstrip('/')}/v1/chat/completions"

    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.8,
        "max_tokens": 2048,
        "stream": False,
    }

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    logger.info("发送 LLM 请求: %d 条消息, 模型=%s", len(messages), MODEL)

    try:
        resp = requests.post(
            url,
            headers=headers,
            data=json.dumps(payload),
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        content = data["choices"][0]["message"]["content"].strip()
        logger.info("LLM 响应成功: %d tokens", data.get("usage", {}).get("total_tokens", 0))
        return content

    except requests.exceptions.Timeout:
        logger.error("DeepSeek API 超时")
        return "⏱️ 请求超时，请检查网络连接或稍后重试。"
    except requests.exceptions.ConnectionError as e:
        logger.error("DeepSeek API 连接失败: %s", e)
        return "🔌 无法连接到 DeepSeek API，请检查网络或 API Base URL 配置。"
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else "?"
        body = e.response.text[:200] if e.response is not None else ""
        logger.error("DeepSeek API HTTP %s: %s", status, body)

        if status == 401:
            return "🔑 API Key 认证失败，请检查 config.py 中的 DEEPSEEK_API_KEY。"
        if status == 429:
            return "⏳ 请求过于频繁，请稍后重试。"
        return f"❌ API 请求失败 (HTTP {status})，请稍后重试。"
    except (KeyError, json.JSONDecodeError) as e:
        logger.error("DeepSeek API 响应解析失败: %s", e)
        return "❌ API 响应格式异常，请稍后重试。"
    except Exception as e:
        logger.error("LLM 调用异常: %s", e)
        return f"❌ 请求异常: {e}"
