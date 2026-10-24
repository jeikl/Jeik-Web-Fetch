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

- **⚡ Zero Heavy Dependencies**: Operates directly on native Chromium/Chrome/Edge installed on the host. No bulky Playwright/Node.js runtimes or Docker containers required.
- **🎯 3 Dedicated Fetch Modes**:
  - `--fast` *(Default)*: Sub-second HTTP static probe (<200ms) with zero browser overhead; automatically escalates to headless browser if an unhydrated client skeleton is detected.
  - `--common`: Full headless Chromium execution for complex documentation, SPA rendering (React, Vue, Next.js, Nuxt), recursive folding expansion, and multi-scenario code harvesting.
  - `--complex`: Advanced anti-bot stealth emulation (Cloudflare Turnstile/5s challenge, CAPTCHAs, DataDome), extended settling timeouts, smooth scrolling, and seamless takeover of authenticated active browser tabs (`jeik open` / `jeik fetch --active-tab`).
- **📚 Full-Fidelity Tech Docs & Developer Portal Harvesting**:
  - **Sidebar Navigation Tree with Absolute URL Resolution**: Automatically maps directory hierarchies, group titles, and HTTP method badges (GET/POST/PUT/DELETE) for documentation frameworks (Docusaurus, Mintlify, VitePress, DingTalk, Ant Design Tree, Ark), resolving all relative paths to absolute URLs in structured appendices.
  - **Multi-Language & Multi-Scenario Code Preservation**: Automatically iterates and collects code snippets across scenario and language tabs (cURL, Python, Go, Node.js, Java) without overwriting.
  - **OpenAPI / Swagger Parameter Trees**: Formats API schema parameter lists into clean Markdown trees, preventing compressed single-line text collisions.
  - **Global Header & Contact Harvesting**: Extracts topbar navigation links, enterprise/technical support emails, GitHub, Discord, Twitter communities, and ICP/copyright footers.
- **🛡️ Enterprise Stealth Evasion**:
  - `navigator.webdriver` prototype cleaning and physical 1080P viewport/media query spoofing.
  - Full `window.chrome.runtime`, plugins, and permissions emulation.
- **🧩 Monaco / Code Editor In-Memory Penetration**:
  - Direct model extraction via `window.monaco.editor.getModels().getValue()` with precision filtering, eliminating virtual-scroll truncation in modern documentation (Stripe, Supabase, Cloudflare Docs).
- **🔍 Agentic Deep Exploration & Auto-Unfolding**:
  - Automated stepped smooth-scrolling across `window`, `main`, and inner `overflow-auto` containers to trigger `IntersectionObserver` lazy loaders.
  - Multi-pass recursive expansion across native `<details>`, `aria-expanded="false"` toggles, and parameter drawers.
- **🧠 Heuristic Content Quality Classifier**: Evaluates text density, tag ratios, and SPA skeleton markers. Fast SSR targets (GitHub, Wikipedia) return cleanly in under 1 second without launching a browser.
- **🚀 Collision-Free Concurrency**: Dynamic debug port allocation prevents multi-process collisions; hybrid async CDP I/O with a dedicated `ThreadPoolExecutor` handles CPU-heavy HTML parsing and Markdown transformations.
- **🌐 Encrypted & Custom DNS**: Resolves numeric IPs (`8.8.8.8`, `1.1.1.1`) and DNS-over-HTTPS (`--dns https://1.1.1.1/dns-query` / `--dns google`), supporting both intranet and public access.

---

## 🏗️ Architecture

```text
jeik_web_fetch/
├── core/                   # Domain & Engine Layer
│   ├── models.py           # Typed contracts (ScrapeOptions, ScrapeResult, FetchMode, OutputFormat)
│   ├── engine.py           # Browser pool, dynamic port allocator & CDP lifecycle controller
│   ├── classifier.py       # Heuristic text density & SPA skeleton classifier
│   ├── cookies.py          # Domain-scoped persistent Cookie store
│   └── dns.py              # Custom & DoH encrypted DNS resolvers
├── transformers/           # Content Transformation Pipeline
│   └── content.py          # Markdown/HTML/Text/Links/Sidebar/TOC/Contact transformers
├── storage/                # Artifacts & Persistence
│   └── manager.py          # Absolute path generator & safe file management
├── api/                    # Transport Layer
│   └── routes.py           # Async FastAPI endpoints (/scrape, /scrape/batch, /health)
├── cli.py                  # Unified CLI logic (fetch, open, cookie, serve, upgrade, uninstall)
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

#### The 3 Categorized Fetch Modes:
```bash
# 1. Fast Mode (Default) — Static pages, raw files, GitHub repositories
jeik fetch "https://github.com/torvalds/linux"
jeik fetch "https://raw.githubusercontent.com/user/repo/main/README.md" --fast

# 2. Common Mode — Dynamic technical docs, OpenAPI/Swagger references, SPA manuals
jeik fetch "https://api-docs.deepseek.com/zh-cn/api/create-chat-completion" --common
jeik fetch "https://mimo.mi.com/docs/zh-CN/api/guidance/rate-limit" --common

# 3. Complex Mode — Anti-bot evasion, Cloudflare challenge, or login wall takeover
jeik fetch "https://www.zhihu.com/question/123456" --complex

# Seamless interactive browser takeover (for login walls / slider CAPTCHAs):
jeik open "https://www.xiaohongshu.com"   # Opens browser with debug port for manual login
jeik fetch --active-tab                  # Instantly extracts content from the active tab!
```

*Output begins with an absolute path header, followed by clean, full Markdown:*
```markdown
> Complete scraped document persisted at: /path/to/.jeik/fetches/docs.stripe.com_api_xxx.md
> If this output is truncated by model context windows, read the absolute path above directly.

# Stripe API Reference
...
```

#### Multi-URL Concurrent Scraping:
```bash
jeik fetch "https://github.com/torvalds/linux" "https://news.ycombinator.com" -j 4 --common
```

#### Suppress Sidebar Navigation Catalog:
```bash
jeik fetch "<URL>" --common --no-sidebar
```

#### Using Encrypted DNS (DoH):
```bash
jeik fetch "https://en.wikipedia.org/wiki/Rust_(programming_language)" --dns https://1.1.1.1/dns-query
```

#### Managing Persistent Cookies:
```bash
jeik cookie set zhihu.com "z_c0=..."
jeik cookie list
```

#### Start High-Concurrency FastAPI Server:
```bash
jeik serve --port 8863
```

#### Self-Uninstall:
```bash
jeik uninstall -y
```

---

### 3. Python SDK Usage

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
  - Tags matching both `vX.Y.Z` and `X.Y.Z` (e.g. `1.2.0` or `v1.2.0`) trigger the CI/CD pipeline immediately.
  - Multi-architecture matrix builds:
    - `jeik-web-fetch-linux-x64`
    - `jeik-web-fetch-linux-arm64` (Native 4-core ARM64 binary for Raspberry Pi, Orange Pi, Kunpeng, etc.)
    - `jeik-web-fetch-darwin-arm64` (Apple Silicon M-series)
    - `jeik-web-fetch-windows-x64.exe`
    - Universal Python Wheel package

---

## 📄 License

Licensed under the [Apache-2.0 License](./LICENSE).
