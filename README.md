# Jeik-Web-Fetch 🚀

工业级、高性能通用动态网页抓取、多格式转换与工件存储引擎。

完全吸收 **Firecrawl 生产级无头渲染架构** 与 **Puppeteer-Stealth 反爬绕过精髓**，以极简、高内聚、易维护的模块化分层架构实现。

---

## 🏗️ 架构分层设计 (Clean Architecture)

```text
jeik_web_fetch/
├── core/                   # 核心领域层 (Domain & Engine)
│   ├── models.py           # 强类型数据模型 (ScrapeOptions, ScrapeResult, OutputFormat)
│   └── engine.py           # 常驻浏览器连接池与 CDP 会话驱动引擎 (ScrapeEngine)
├── transformers/           # 转换器分治层 (Content Processing)
│   └── content.py          # 多格式流水线 (Markdown/HTML/RawHTML/Text/Links/Metadata)
├── storage/                # 存储管理层 (Artifacts & Persistence)
│   └── manager.py          # 临时文件与持久化工件管理 (自动规整安全文件名、按需落盘)
├── api/                    # 外部服务接口层 (Transport)
│   └── routes.py           # 高并发异步 FastAPI 路由 (/scrape, /scrape/batch, /docs)
└── browser.py              # 跨平台环境适配层 (Windows/macOS/Linux/ARM64 浏览器探测)
```

---

## 🌟 核心特性

- ⚡ **常驻浏览器池 (Warm Browser Pool)**：毫秒级派发隔离 Tab，极大降低进程启动冷开销，支持高并发批量抓取。
- 📦 **多目标格式按需输出**：
  - `markdown`：高保真带表格对齐与 Monaco 代码框提纯
  - `html` / `rawHtml`：清洗或原始 DOM 镜像
  - `text`：纯文本结构
  - `links`：提取结构化超链接列表
  - `metadata`：提取 SEO 标题、描述与关键词
- 💾 **临时文件与工件持久化 (Artifacts)**：
  - 支持 `save_to_file=True`，自动将抓取大文本、HTML 或 Markdown 隔离落盘到系统临时目录或用户指定目录，防止打爆上下文；
  - 自动生成合规、友好的安全文件名。
- 🛡️ **生产级反爬探针绕过 (Stealth)**：
  - `navigator.webdriver` 原型链清洗
  - 真实物理 1080P 分辨率模拟
  - 补齐 Chrome 插件与硬件语言特征，稳健穿透知乎、钉钉、阿里云等站点

---

## 📦 使用指南

### 1. Python 模块调用

```python
import asyncio
from jeik_web_fetch import default_engine, ScrapeOptions, OutputFormat

async def main():
    options = ScrapeOptions(
        url="https://open.dingtalk.com/document/development/overview-of-event-subscription",
        formats=[OutputFormat.MARKDOWN, OutputFormat.LINKS],
        save_to_file=True,     # 自动保存到临时文件
        output_dir="./dist"    # 可选：指定保存目录
    )
    result = await default_engine.scrape_url(options)
    print(f"抓取状态: {result.success}")
    print(f"生成的 Markdown:\n{result.markdown[:500]}")
    print(f"保存的文件: {result.saved_files}")

asyncio.run(main())
```

### 2. 启动 FastAPI 高并发服务

```bash
uvicorn jeik_web_fetch.api.routes:app --host 0.0.0.0 --port 8000
```
或直接通过内置 CLI：
```bash
python bin/jeik-web-fetch serve --port 8000
```
启动后访问 `http://localhost:8000/docs` 即可查看 Swagger 交互式文档。

---

## 🚀 跨平台 CI/CD 自动化发版

项目配置了完整的 GitHub Actions 流水线（`.github/workflows/release.yml`）：
- 每次推送形如 `v1.0.0` 的 Git Tag，并发交叉构建：
  - `jeik-web-fetch-windows-x64.exe`
  - `jeik-web-fetch-darwin-arm64` (Apple Silicon)
  - `jeik-web-fetch-darwin-x64` (Intel Mac)
  - `jeik-web-fetch-linux-x64`
  - `jeik-web-fetch-linux-arm64` (ARM64 架构)
  - 通用 Python Wheel 包
