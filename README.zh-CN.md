<p align="center">
  <h1 align="center">Jeik-Web-Fetch 🚀</h1>
  <p align="center">
    <strong>工业级、高性能通用动态网页抓取、多格式转换与工件存储引擎。</strong>
  </p>
  <p align="center">
    <a href="./README.zh-CN.md">简体中文</a> | <a href="./README.md">English</a> | <a href="./CHANGELOG_ZH.md">更新日志</a>
  </p>
</p>

---

## 🌟 核心亮点

- **⚡ 零重型外部依赖**：直接调用宿主机已安装的原生 Chromium / Chrome / Edge。无需安装笨重的 Playwright/Node.js 运行时或 Docker 容器。
- **🛡️ 生产级反反爬探针绕过 (Stealth)**：
  - `navigator.webdriver` 原型链清洗
  - 1080P 物理视口与媒体查询伪装（轻松穿透知乎专栏、Cloudflare 等对小窗口无头爬虫的 403 封锁）
  - 完整补齐 `window.chrome.runtime`、插件列表与权限模拟
- **🧩 现代前端代码框内存穿透**：
  - 通过 `window.monaco.editor.getModels().getValue()` 直接提取内存模型
  - 彻底解决现代长文档（如钉钉开放平台 OpenAPI）中 Monaco Editor 虚拟滚动导致的下半部分长代码丢失、截断问题
- **🔍 Agentic 深度自愈探索**：
  - 自动化步进平滑滚屏：自适应触发 `IntersectionObserver` 视口监听，激活页面深层懒加载与异步询价接口（如阿里云 `queryPrice`，彻底消灭“询价中…”）。
  - 隐式抽屉与弹窗自动采集器：智能识别“活动规则/细则/FAQ/须知”点击触发器，自动展开提取多达数万字的深层风控条款，并在文档底部作为附录全量挂载。
  - 动态 Tab 选项卡遍历：自动识别并循环派发点击未激活的选项卡，合并多分支条件渲染内容。
- **🧠 本质内容质量分类器 (`ContentQualityClassifier`)**：完全抛弃生硬脆弱的域名黑白名单，基于文本密度、标签比例与 SPA 挂载点骨架特征进行本质判别。普通静态页面（如 GitHub、维基百科）1 秒内秒级直出，完全免开浏览器。
- **🚀 混合并发架构**：融合异步 CDP I/O 与专用的 `ThreadPoolExecutor` 线程池，处理繁重的 HTML 解析与 Markdown 正则转换，主事件循环毫秒不卡，支持多 URL 并行并发抓取。
- **🌐 加密 DNS (DoH) 与自定义 DNS**：支持指定数字 IP（`8.8.8.8`）与标准 DoH 加密 DNS（`--dns https://1.1.1.1/dns-query` 或 `--dns aliyun`），彻底放行所有内网与公网请求。

---

## 🏗️ 架构分层设计 (Clean Architecture)

```text
jeik_web_fetch/
├── core/                   # 核心领域与引擎层 (Domain & Engine)
│   ├── models.py           # 强类型数据契约 (ScrapeOptions, ScrapeResult, OutputFormat)
│   ├── engine.py           # 常驻浏览器连接池与 CDP 会话驱动引擎 (ScrapeEngine)
│   ├── classifier.py       # 本质内容质量与 SPA 骨架特征分类器
│   └── dns.py              # 自定义与 DoH 加密 DNS 解析配置
├── transformers/           # 转换器分治层 (Content Processing)
│   └── content.py          # 多格式流水线 (Markdown/HTML/Text/Links/Metadata)
├── storage/                # 存储管理层 (Artifacts & Persistence)
│   └── manager.py          # 绝对路径生成器与文件安全落盘管理
├── api/                    # 外部服务接口层 (Transport)
│   └── routes.py           # 高并发异步 FastAPI 路由 (/scrape, /scrape/batch, /health)
├── cli.py                  # 统一 CLI 命令行交互逻辑
└── browser.py              # 跨平台宿主适配层 (Windows/macOS/Linux/ARM64 浏览器自动探测)
```

---

## ⚡ 快速开始

### 1. 一键纯二进制在线安装（推荐，完全无需安装 Python）

#### Linux (Ubuntu/Debian/CentOS/Arch, x64 & ARM64) 与 macOS:
```bash
curl -fsSL https://raw.githubusercontent.com/jeikl/Jeik-Web-Fetch/main/scripts/install.sh | bash
```

#### Windows (PowerShell):
```powershell
irm https://raw.githubusercontent.com/jeikl/Jeik-Web-Fetch/main/scripts/install.ps1 | iex
```

---

### 2. Jeik CLI 命令行使用

#### 单页面抓取：
```bash
jeik fetch "https://zhuanlan.zhihu.com/p/25964484"
```
*终端首行输出保存的绝对路径，随后输出完整无截断 Markdown：*
```markdown
> 当前摘取的完整文档已存到: E:\code\jeikcode\.jeik\fetches\zhuanlan.zhihu.com_xxx.md
> 如果后续输出被终端或模型窗口截断，可直接使用读取工具读取上述绝对路径获取完整内容。

# 标题
...
```

#### 多 URL 高并发并行抓取：
```bash
jeik fetch "https://url1" "https://url2" "https://url3" -j 4
```

#### 使用加密 DNS (DoH)：
```bash
jeik fetch "https://open.dingtalk.com/..." --dns https://1.1.1.1/dns-query
```

#### 启动 FastAPI 高并发后台服务：
```bash
jeik serve --port 8000
```

#### 一键自卸载：
```bash
jeik uninstall -y
```

---

### 3. Python SDK 调用

```python
import asyncio
from jeik_web_fetch import default_engine, ScrapeOptions, OutputFormat

async def main():
    options = ScrapeOptions(
        url="https://open.dingtalk.com/document/development/overview-of-event-subscription",
        formats=[OutputFormat.MARKDOWN, OutputFormat.LINKS],
        save_to_file=True
    )
    result = await default_engine.scrape_url(options)
    print(f"抓取状态: {result.success}, 耗时: {result.elapsed_seconds}s")
    print(result.markdown[:500])

asyncio.run(main())
```

---

## 🚀 分支规范与自动化发版流水线

严格对齐 **JeikCode 官方发版纪律**：
- **`main`**：生产发布基准主干。所有正式发版制品均严格以此分支为准。
- **`beta`**：功能特性预发布与阶段研发分支。
- **打 Tag 自动化触发发版流水线**：
  - 监听所有形如 `[0-9]+.[0-9]+.[0-9]+*` 以及 `v*` 的标签（例如直接打 `1.1.0` 或 `v1.1.0` 均可直接触发！）；
  - 全并发矩阵构建 6 套发布产物：
    - `jeik-web-fetch-linux-x64`
    - `jeik-web-fetch-linux-arm64` (通过 QEMU 自动化构建)
    - `jeik-web-fetch-darwin-arm64` (Apple Silicon M 系列芯片)
    - `jeik-web-fetch-darwin-x64` (Intel Mac)
    - `jeik-web-fetch-windows-x64.exe`
    - 通用 Python Wheel 安装包
  - 自动创建 GitHub Release 并挂载发布制品供在线安装器抓取。

---

## 📄 开源许可证

本项目基于 [Apache-2.0 许可证](./LICENSE) 开源。
