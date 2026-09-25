---
name: jeik-web-fetch
description: "使用 Jeik-Web-Fetch 引擎抓取任何复杂的动态 JS、单页应用 (SPA)、知乎、钉钉文档以及带有反爬机制的网页，并直接提取干净结构化的 Markdown。当用户需要抓取、提取网页文档、分析网页正文，且普通静态抓取失败时使用此技能。"
---

# Jeik-Web-Fetch 技能指南

本技能调用本地或远程的 `Jeik-Web-Fetch` 引擎，支持：
- 动态 JS 单页渲染（React / Vue / VitePress 等）
- Monaco Editor / CodeMirror 代码框穿透
- 自动绕过知乎、阿里云等站点的无头反爬探针
- 高保真输出带对齐线的表格、标题与代码围栏

## 调用方式

### 方式 1：CLI 命令行直接调用 (推荐)
直接在终端或通过 Bash 执行：
```bash
python ../Jeik-Web-Fetch/bin/jeik-web-fetch "https://open.dingtalk.com/document/development/overview-of-event-subscription"
```
或者指定保存路径：
```bash
python ../Jeik-Web-Fetch/bin/jeik-web-fetch "https://zhuanlan.zhihu.com/p/25964484" -o zhihu.md
```

### 方式 2：启动并调用本地 HTTP 服务
在后台启动服务：
```bash
python ../Jeik-Web-Fetch/bin/jeik-web-fetch serve --port 8000
```
然后随时通过标准 HTTP POST 请求调用（兼容 Firecrawl 接口规范）：
```bash
curl -s -X POST http://localhost:8000/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://docs.volcengine.com/docs"}'
```

### 方式 3：Python 代码直接调用
```python
import sys
sys.path.insert(0, "../Jeik-Web-Fetch")
from jeik_web_fetch import firecrawl_fetch

markdown = firecrawl_fetch("https://open.dingtalk.com/document/development/overview-of-event-subscription")
print(markdown)
```
