# 更新日志 (Changelog)

本项目所有重要更新与版本迭代均记录于此文档。

版本规范严格遵循 [语义化版本 2.0.0 (Semantic Versioning)](https://semver.org/lang/zh-CN/)，日志格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

---

## [1.1.0] - 2026-09-26

### 新增 (Added)
- **全新 Jeik CLI (`jeik`)**：推出统一极简的现代化终端命令行工具，支持开箱即用零配置抓取（`jeik fetch <url>`）。
- **绝对路径首行锚定机制**：抓取输出首部强制输出保存工件的绝对路径，彻底根治大模型 Agent 在终端截断后无法捞回全文或相对路径找不到文件的顽疾。
- **Agentic 深度自愈探索模式 (Deep Interactive Exploration)**：
  - 自动化步进平滑滚屏：自适应触发 `IntersectionObserver` 视口监听，激活页面深层懒加载与异步询价接口（彻底消灭“询价中…”）。
  - 隐式抽屉与弹窗自动采集器：智能识别“活动规则/细则/FAQ/须知”点击触发器，自动展开提取多达数万字的深层风控条款，并在文档底部作为附录全量挂载。
  - 动态 Tab 选项卡遍历：自动识别并循环派发点击未激活的选项卡，合并多分支条件渲染内容。
- **本质内容质量与特征分类器 (`ContentQualityClassifier`)**：彻底剔除生硬的域名黑白名单，基于文本密度（Text-to-Tag Ratio）与 SPA 挂载点骨架特征进行本质判别，静态高价值页面（如 GitHub、维基百科）1 秒内秒级直出，完全免开浏览器。
- **混合多线程/多协程并发引擎**：引入 `ThreadPoolExecutor` 专用计算线程池结合 `asyncio.Semaphore`，解决 Python GIL 下大页面 HTML 解析与正则提取卡死主事件循环的痛点，支持 `jeik fetch url1 url2 ... -j 4` 高并发并行抓取。
- **加密 DNS (DoH) 与自定义数字 DNS 支持**：支持 `--dns 8.8.8.8` 以及 `--dns https://1.1.1.1/dns-query`，且彻底解除任何内网（localhost / 127.0.0.1 / 192.168.x.x）的请求门禁。
- **一键自卸载命令**：集成 `jeik uninstall [-y]`，支持从当前系统中一键完整自清理。
- **跨平台纯二进制一键在线安装器**：新增 `scripts/install.sh` 与 `scripts/install.ps1`，纯净新机器一行命令自动装完。

### 优化与重构 (Changed)
- 全面自主品牌收敛：将所有核心函数与接口由 `firecrawl_fetch` 统一重命名为原生的 `jeik_fetch` 与 `fetch`。
- 清晰分层架构重构：严格划分为核心引擎层 `core/`、数据转换层 `transformers/`、存储管理层 `storage/` 以及服务传输层 `api/`。
- PyInstaller 全平台打包强化：自动收集 FastAPI、Uvicorn、Httpx 与 WebSockets 全量依赖，构建真正零 Python 环境依赖的独立单文件可执行文件。

---

## [1.0.0] - 2026-09-26

### 新增 (Added)
- Jeik-Web-Fetch 初始版本正式发布。
- 原生无头 Chromium CDP 会话控制引擎，解决单页应用（SPA / React / Vue）客户端异步渲染难题。
- 原生穿透提取 Monaco Editor 内存数据模型，攻克长代码框虚拟滚动导致的截断痛点。
- 生产级多维反爬探针绕过：抹除 `navigator.webdriver` 自动化标识、伪装 1920x1080 真实桌面视口、补齐 Chrome 插件与硬件语言结构。
- GFM 标准表格对齐线自动补全与语义化 Markdown 结构提取。
- 基于预热浏览器池的 FastAPI 异步高并发 HTTP 服务。
- 覆盖 Linux (x64, arm64)、macOS (Intel, Apple Silicon) 与 Windows (x64) 的多架构 GitHub Actions 自动化 CI/CD 发版流水线。
