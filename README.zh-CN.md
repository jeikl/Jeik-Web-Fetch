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
- **🎯 专设三档抓取模式分类**：
  - `--fast` *(缺省 / Default)*：毫秒级极速静态探针直出（<200ms），零内存开销；若遇未水合的客户端 SPA 骨架屏自动自愈升级。
  - `--common`：无头浏览器完整深度渲染，专为复杂文档与前端 SPA（React、Vue、Next.js、Nuxt）设计，递归展开折叠节点并采集多语言代码用例。
  - `--complex`：深度反反爬对抗与浏览器接管，穿透 Cloudflare 5秒盾/Turnstile、验证码拦截与高风控风控检测，支持一键接管真实浏览器已登录标签页（`jeik open` / `jeik fetch --active-tab`）。
- **📚 高保真技术文档与开发者门户全量采集**：
  - **文档侧边栏树与相对路径自动绝对化**：自动识别 Docusaurus、Mintlify、VitePress、钉钉文档、Ant Design Tree、Ark 等主流文档系统的左侧目录树与接口分类，标准化 HTTP Method 标记（POST/GET/PUT/DELETE），并将所有相对链接转换为完整的绝对 HTTP/HTTPS URL，挂载为文末结构化导航附录。
  - **多语言与多场景代码用例全量留存**：自动遍历并收集场景与语言选项卡（cURL、Python、Go、Node.js、Java）下的所有代码块与响应 JSON，杜绝后续 Tab 切换覆盖前序代码。
  - **OpenAPI / Swagger 参数列表树形排版**：智能解析 API 结构体与参数项，分离字段名、类型、约束与描述，彻底杜绝字段挤压在一行的格式缺陷。
  - **全站顶栏导航与商务/技术支持采集**：全面捕获顶栏超链接、企业支持邮箱、GitHub、Discord、Twitter 社区入口及备案版权信息。
- **🛡️ 生产级反反爬探针绕过 (Stealth)**：
  - `navigator.webdriver` 原型链清洗
  - 1080P 物理视口与媒体查询伪装（轻松穿透 Cloudflare Turnstile、DataDome 等针对小窗口无头爬虫的 403 封锁）
  - 完整补齐 `window.chrome.runtime`、插件列表与权限模拟
- **🧩 现代前端代码框内存穿透**：
  - 通过 `window.monaco.editor.getModels().getValue()` 直接提取内存模型并结合高精度样式过滤，彻底清除虚假空代码块，解决长文档（Stripe、Supabase、Cloudflare Docs 等）中 Monaco 虚拟滚动截断问题。
- **🔍 Agentic 深度自愈探索与递归展开**：
  - 自动化步进平滑滚屏：遍历 `window`、`main` 及内部 `overflow-auto` 容器，自适应触发 `IntersectionObserver` 视口监听，激活页面深层懒加载。
  - 递归多轮深度穿透展开：自动展开原生 `<details>`、`aria-expanded="false"` 按钮及参数抽屉。
- **🧠 本质内容质量分类器 (`ContentQualityClassifier`)**：完全抛弃生硬脆弱的域名黑白名单，基于文本密度、标签比例与 SPA 挂载点骨架特征进行本质判别。普通静态页面（如 GitHub、维基百科）秒级直出，免开浏览器。
- **🚀 零冲突并发架构**：动态 CDP 调试端口分配，杜绝多进程并行时的端口冲突；融合异步 CDP I/O 与专用的 `ThreadPoolExecutor` 线程池，处理繁重的 HTML 解析与 Markdown 正则转换。
- **🌐 加密 DNS (DoH) 与自定义 DNS**：支持指定数字 IP（`8.8.8.8`，`1.1.1.1`）与标准 DoH 加密 DNS（`--dns https://1.1.1.1/dns-query` 或 `--dns google`），彻底放行所有内网与公网请求。

---

## 🏗️ 架构拓扑

```text
jeik_web_fetch/
├── core/                   # 核心领域与引擎层
│   ├── models.py           # 类型契约 (ScrapeOptions, ScrapeResult, FetchMode, OutputFormat)
│   ├── engine.py           # 浏览器池、动态端口分配与 CDP 生命周期调度
│   ├── classifier.py       # 本质文本密度与 SPA 骨架质量分类器
│   ├── cookies.py          # 域名级持久化 Cookie 存储器
│   └── dns.py              # 自定义与 DoH 加密 DNS 解析器
├── transformers/           # 内容转换管道
│   └── content.py          # Markdown/HTML/Text/Links/Sidebar/TOC/Contact 转换器
├── storage/                # 工件持久化
│   └── manager.py          # 绝对路径锚定与安全存储管理
├── api/                    # 传输协议层
│   └── routes.py           # 异步 FastAPI 端点 (/scrape, /scrape/batch, /health)
├── cli.py                  # 统一 CLI 命令行交互 (fetch, open, cookie, serve, upgrade, uninstall)
└── browser.py              # 跨平台浏览器探针与发现
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

#### 专设三档抓取模式：
```bash
# 1. Fast 模式 (缺省) — 静态网页、Raw 文件、GitHub 仓库秒级直出
jeik fetch "https://github.com/torvalds/linux"
jeik fetch "https://raw.githubusercontent.com/user/repo/main/README.md" --fast

# 2. Common 模式 — 复杂动态 JS 技术文档、OpenAPI/Swagger 接口手册、SPA 页面
jeik fetch "https://api-docs.deepseek.com/zh-cn/api/create-chat-completion" --common
jeik fetch "https://mimo.mi.com/docs/zh-CN/api/guidance/rate-limit" --common

# 3. Complex 模式 — 高风控对抗、Cloudflare 盾或登录墙接管
jeik fetch "https://www.zhihu.com/question/123456" --complex

# 无缝真实浏览器接管方案（应对滑块验证码或登录墙）：
jeik open "https://www.xiaohongshu.com"   # 启动带独立调试端口的浏览器，供用户正常扫码或交互
jeik fetch --active-tab                  # 瞬间直接接管并提取当前已登录的标签页！
```

*终端首行输出保存的绝对路径，随后输出完整无截断 Markdown：*
```markdown
> Complete scraped document persisted at: /path/to/.jeik/fetches/docs.stripe.com_api_xxx.md
> If this output is truncated by model context windows, read the absolute path above directly.

# Stripe API Reference
...
```

#### 多 URL 高并发并行抓取：
```bash
jeik fetch "https://github.com/torvalds/linux" "https://news.ycombinator.com" -j 4 --common
```

#### 关闭侧边栏导航目录挂载：
```bash
jeik fetch "<URL>" --common --no-sidebar
```

#### 使用加密 DNS (DoH)：
```bash
jeik fetch "https://en.wikipedia.org/wiki/Rust_(programming_language)" --dns https://1.1.1.1/dns-query
```

#### 管理持久化 Cookie 登录态：
```bash
jeik cookie set zhihu.com "z_c0=..."
jeik cookie list
```

#### 启动 FastAPI 高并发后台服务：
```bash
jeik serve --port 8863
```

#### 一键自卸载：
```bash
jeik uninstall -y
```

---

### 3. Python SDK 调用

```python
import asyncio
from jeik_web_fetch import default_engine, ScrapeOptions, FetchMode, OutputFormat

async def main():
    options = ScrapeOptions(
        url="https://api-docs.deepseek.com/zh-cn/api/create-chat-completion",
        mode=FetchMode.COMMON,
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
  - 监听所有形如 `[0-9]+.[0-9]+.[0-9]+*` 以及 `v*` 的标签（例如直接打 `1.2.0` 或 `v1.2.0` 均可直接触发！）；
  - 全并发矩阵构建 6 套发布产物：
    - `jeik-web-fetch-linux-x64`
    - `jeik-web-fetch-linux-arm64` (面向树莓派、香橙派、各种电视盒子及鲲鹏的原生 ARM64 单文件二进制)
    - `jeik-web-fetch-darwin-arm64` (Apple Silicon M 系列芯片)
    - `jeik-web-fetch-windows-x64.exe`
    - 通用 Python Wheel 安装包
  - 自动创建 GitHub Release 并挂载发布制品供在线安装器抓取。

---

## 📄 许可证

本项目采用 [Apache-2.0 License](./LICENSE) 开源许可证。
