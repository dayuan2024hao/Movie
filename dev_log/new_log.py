"""
开发日志生成工具
用法：python new_log.py
功能：在 dev_log 文件夹中创建今天的日志文件（如果不存在）
"""

import os
from datetime import date

today = date.today()
date_str = today.strftime("%Y-%m-%d")
filename = f"{date_str}.md"
filepath = os.path.join(os.path.dirname(__file__), filename)

if os.path.exists(filepath):
    print(f"[存在] 今天的日志已存在: {filename}")
else:
    content = f"""# 开发日志 — {date_str}

## 📋 今日完成事项

- [ ]

## 🔧 遇到的问题 & 解决方案

| 问题 | 原因 | 解决方案 |
|------|------|---------|
|      |      |         |

## 📝 代码变更摘要

```
变更文件：
-
```

## ✅ 明日待办

- [ ]

## 💭 备注

---
"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[创建] 已创建今日日志: {filename}")
