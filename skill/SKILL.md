---
name: jeik-web-fetch
description: "抓取任何网页，并转化为 Markdown 文档。当任务执行到中途发现需要抓取网页内容综合分析、或用户需要抓取网页时，使用此技能。"
---

# Jeik-Web-Fetch 技能指南

### 方式 1：CLI 命令行直接调用 (推荐)
直接在终端或通过 Bash 执行：
```bash
python ../Jeik-Web-Fetch/bin/jeik fetch "https://open.dingtalk.com/document/development/overview-of-event-subscription"
```

### 方式 2：启动并调用本地 HTTP 服务
在后台启动服务：
```bash
python ../Jeik-Web-Fetch/bin/jeik serve --port 8000
```
 POST 调用：
```bash
curl -s -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.volcengine.com/docs"}'
```

### 方式 3：Python 调用
```python
import sys
sys.path.insert(0, "../Jeik-Web-Fetch")
from jeik_web_fetch import fetch

markdown = fetch("https://open.dingtalk.com/document/development/overview-of-event-subscription")
print(markdown)
```
