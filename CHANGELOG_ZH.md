# 更新日志 (Changelog)

本项目所有重要更新与版本迭代均记录于此文档。

版本规范严格遵循 [语义化版本 2.0.0 (Semantic Versioning)](https://semver.org/lang/zh-CN/)，日志格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

---

## [1.2.0] - 2026-10-25

### 新增特性 (Added)
- **全新三档抓取模式分类 (3 Dedicated Fetch Modes)**：
  - `--fast` *(缺省 / Default)*：毫秒级极速静态探针直出（<200ms），零内存开销；若遇未水合的客户端 SPA 骨架屏自动自愈升级。
  - `--common`：无头浏览器完整深度渲染，专为复杂文档与前端 SPA（React、Vue、Next.js、Nuxt）设计，递归展开折叠节点并采集多语言代码用例。
  - `--complex`：深度反反爬对抗与浏览器接管，穿透 Cloudflare 5秒盾/Turnstile、验证码拦截与高风控风控检测，支持一键接管真实浏览器已登录标签页（`jeik open` / `jeik fetch --active-tab`）。
- **文档侧边栏树与相对路径自动绝对化**：自动识别 Docusaurus、Mintlify、VitePress、钉钉文档、Ant Design Tree、Ark 等主流文档系统的左侧目录树与接口分类，标准化 HTTP Method 标记（POST/GET/PUT/DELETE），并将所有相对链接转换为完整的绝对 HTTP/HTTPS URL，挂载为文末结构化导航附录。
- **多语言与多场景代码用例全量留存**：自动遍历并收集场景与语言选项卡（cURL、Python、Go、Node.js、Java）下的所有代码块与响应 JSON，杜绝后续 Tab 切换覆盖前序代码。
- **OpenAPI / Swagger 参数列表树形排版**：智能解析 API 结构体与参数项，分离字段名、类型、约束与描述，彻底杜绝字段挤压在一行的格式缺陷。
- **全站顶栏导航与商务/技术支持采集**：全面捕获顶栏超链接、企业支持邮箱、GitHub、Discord、Twitter 社区入口及备案版权信息。
- **Partial SSR 未水合组件智能识别与过滤**：识别带有未水合动态占位符（如 Loading...）的页面，自动升级至无头浏览器以抓取完整客户端渲染内容，并自动清除骨架屏与孤立的 Loading 占位节点。
- **无缝真实浏览器接管方案**：新增 `jeik open <URL>` 与 `jeik fetch --active-tab`，支持人工登录或完成滑块验证后 1 秒瞬间接管提取。
- **全英文 Agent Skill 规范**：将 `skill/SKILL.md` 全量重构为地道规范的纯英文版本，提升 Agent 工具生态解析度。

### 优化与修复 (Changed & Fixed)
- **高精度代码块识别过滤**：修复 Tailwind CSS 样式类（`text-[var(--color-highlight)]`）被误判为 Monaco 代码编辑器的缺陷，彻底清除虚假空代码块。
- **动态可用端口探测**：浏览器底层改为动态可用端口绑定，彻底杜绝多进程并发调用时的端口冲突。
- **自愈侧边栏根容器解析**：修复外部传入完整侧边栏片段时因查询子节点失败导致导航丢失的边界 Bug。

---

## [1.1.1] - 2026-09-27

### 修复与加固 (Fixed)
- **Windows GBK 编码与 Emoji 崩溃根治**：强制标准 I/O（`sys.stdout`、`sys.stderr`、`sys.stdin`）自动以 UTF-8 运行并注入 `SetConsoleOutputCP(65001)`，新增 `safe_print` 兜底保护，彻底杜绝 Windows GBK/cp936 管道下抓取包含 Emoji（如 `\U0001f468` 👨）及特殊多语言字符时触发的 `UnicodeEncodeError` 崩溃。
- **网络连接重置与不可达精准探测**：针对网络 reset/unreachable 错误返回明确错误原因与提示，杜绝生成空 Markdown 文件。
- **相对链接自动还原**：基于文档真实 `base_url` 自动将页面中的相对 URL 补全为规范的完整绝对 HTTP/HTTPS 链接。

### 新增特性 (Added)
- **超时与等待时间自定义参数**：CLI 暴露 `-t/--timeout` 与 `-w/--wait` 命令行参数，无缝支持高延迟弱网环境或重度 SPA 渲染需求。

### 性能优化 (Performance)
- **SPA 内容就绪动态侦听 (Dynamic Settle)**：引入轻量级 DOM 真实正文就绪探测，页面加载完成后提前进入提取，SPA 等待耗时平均缩减 50%。

### 构建与发布 (CI/CD)
- **PyInstaller 模块解析路径优化**：在 Release 工作流构建命令中追加 `--paths .`，确保各平台独立二进制打包无隐式依赖丢失。

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
