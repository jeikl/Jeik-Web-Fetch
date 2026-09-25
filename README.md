<p align="center">
  <h1 align="center">Jeik-Web-Fetch 🚀</h1>
  <p align="center">
    <strong>Industrial-grade, high-performance web extraction, multi-format transformation, and anti-bot scraper engine.</strong>
  </p>
  <p align="center">
    <a href="./README.zh-CN.md">简体中文</a> | <a href="./README.md">English</a> | <a href="./CHANGELOG.md">Changelog</a>
  </p>
</p>

---

## 🌟 Highlights

- **⚡ Zero Heavy Dependencies**: Operates on native Chromium/Chrome/Edge already installed on the host. No bulky Playwright/Node.js runtimes or Docker containers required.
- **🛡️ Enterprise Stealth Evasion**:
  - `navigator.webdriver` prototype removal
  - 1080P physical viewport & media query spoofing (bypasses anti-bot 403 walls on Zhihu, Cloudflare, etc.)
  - Complete `window.chrome.runtime`, plugins, and permissions emulation
- **🧩 Monaco / Code Editor In-Memory Penetration**:
  - Directly extracts models via `window.monaco.editor.getModels().getValue()`
  - Eliminates virtual scroll code truncation in modern API documentation (e.g., DingTalk OpenAPI)
- **🔍 Agentic Deep Exploration**:
  - Automated stepped smooth-scrolling to trigger `IntersectionObserver` and asynchronous API pricing callbacks (e.g., Aliyun `queryPrice`).
  - Automated drawer/modal scanner to extract hidden terms, FAQ details, and activity rules into a dedicated appendix.
  - Automated tab traversal across unselected options (`[role="tab"]`).
- **🧠 Heuristic Content Quality Classifier**: Evaluates text density, tag ratios, and SPA skeleton markers. Fast SSR targets (GitHub, Wikipedia) return cleanly in under 1 second without launching a browser.
- **🚀 Hybrid Concurrency**: Blends asynchronous CDP I/O with a dedicated `ThreadPoolExecutor` for CPU-heavy HTML parsing and Markdown conversion. Supports parallel multi-URL scraping.
- **🌐 Encrypted & Custom DNS**: Resolves numeric IPs (`8.8.8.8`) and DNS-over-HTTPS (`--dns https://1.1.1.1/dns-query` / `--dns aliyun`), with complete intranet and public access.

---

## 🏗️ Architecture

```text
jeik_web_fetch/
├── core/                   # Domain & Engine Layer
│   ├── models.py           # Typed contracts (ScrapeOptions, ScrapeResult, OutputFormat)
│   ├── engine.py           # Warm browser pool & CDP lifecycle controller
│   ├── classifier.py       # Heuristic text density & SPA classifier
│   └── dns.py              # Custom & DoH encrypted DNS resolvers
├── transformers/           # Content Transformation Pipeline
│   └── content.py          # Markdown/HTML/Text/Links/Metadata transformers
├── storage/                # Artifacts & Persistence
│   └── manager.py          # Absolute path generator & safe file management
├── api/                    # Transport Layer
│   └── routes.py           # Async FastAPI endpoints (/scrape, /scrape/batch, /health)
├── cli.py                  # Unified CLI logic
└── browser.py              # Multi-platform browser discovery
```

---

## ⚡ Quick Start

### 1. One-Command Binary Installation (Recommended, Zero Python Required)

#### Linux (Ubuntu/Debian/CentOS/Arch, x64 & ARM64) & macOS:
```bash
curl -fsSL https://raw.githubusercontent.com/jeikl/Jeik-Web-Fetch/main/scripts/install.sh | bash
```

#### Windows (PowerShell):
```powershell
irm https://raw.githubusercontent.com/jeikl/Jeik-Web-Fetch/main/scripts/install.ps1 | iex
```

---

### 2. Jeik CLI Usage

#### Single URL Scraping:
```bash
jeik fetch "https://zhuanlan.zhihu.com/p/25964484"
```
*Output begins with an absolute path header, followed by clean, full Markdown:*
```markdown
> 当前摘取的完整文档已存到: /path/to/.jeik/fetches/zhuanlan.zhihu.com_xxx.md
> 如果后续输出被终端或模型窗口截断，可直接使用读取工具读取上述绝对路径获取完整内容。

# Document Title
...
```

#### Multi-URL Concurrent Scraping:
```bash
jeik fetch "https://url1" "https://url2" "https://url3" -j 4
```

#### Using Encrypted DNS (DoH):
```bash
jeik fetch "https://open.dingtalk.com/..." --dns https://1.1.1.1/dns-query
```

#### Start High-Concurrency FastAPI Server:
```bash
jeik serve --port 8000
```

#### Self-Uninstall:
```bash
jeik uninstall -y
```

---

### 3. Python SDK Usage

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
    print(f"Success: {result.success}, elapsed: {result.elapsed_seconds}s")
    print(result.markdown[:500])

asyncio.run(main())
```

---

## 🚀 Branching & Release Pipeline

Following the official **JeikCode release discipline**:
- **`main`**: Production-ready branch. Official release artifacts are built strictly from this branch.
- **`beta`**: Feature-staging branch for upcoming releases and community integration.
- **Tag-Triggered Automated Release**:
  - Tags matching both `vX.Y.Z` and `X.Y.Z` (e.g. `1.1.0` or `v1.1.0`) trigger the CI/CD pipeline immediately.
  - Multi-architecture matrix builds:
    - `jeik-web-fetch-linux-x64`
    - `jeik-web-fetch-darwin-arm64` (Apple Silicon M-series)
    - `jeik-web-fetch-windows-x64.exe`
    - Universal Python Wheel package (works natively on Linux ARM64, macOS, Windows)

---

## 📄 License

Licensed under the [Apache-2.0 License](./LICENSE).
