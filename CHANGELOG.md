# Changelog

All notable changes to **Jeik-Web-Fetch** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.2.0] - 2026-10-25

### Added
- **3 Dedicated Fetch Modes**:
  - `--fast` *(Default)*: Sub-second static probe (<200ms) with zero browser overhead; automatically escalates to headless browser if an unhydrated client skeleton is detected.
  - `--common`: Full headless Chromium execution for complex documentation, SPA rendering (React, Vue, Next.js, Nuxt), recursive folding expansion, and multi-scenario code harvesting.
  - `--complex`: Advanced anti-bot stealth emulation (Cloudflare Turnstile/5s challenge, CAPTCHAs, DataDome), extended settling timeouts, smooth scrolling, and seamless takeover of authenticated active browser tabs (`jeik open` / `jeik fetch --active-tab`).
- **Sidebar Navigation Tree with Absolute URL Resolution**: Automatically discovers documentation sidebar catalogs, groups, and HTTP methods (POST/GET/PUT/DELETE) for Docusaurus, Mintlify, VitePress, DingTalk, Ant Design Tree, and Ark, converting all relative paths to absolute URLs in structured appendices.
- **Multi-Language & Multi-Scenario Code Preservation**: Automatically iterates and collects code snippets across scenario and language tabs (cURL, Python, Go, Node.js, Java) without overwriting.
- **OpenAPI & Swagger Parameter Trees**: Formats API schema parameter lists into clean Markdown trees, preventing compressed single-line text collisions.
- **Global Header & Contact Harvesting**: Extracts topbar navigation links, enterprise/technical support emails, GitHub, Discord, Twitter communities, and ICP/copyright footers.
- **Partial SSR Unhydrated Component Quality Classifier**: Detects unhydrated client component fallbacks and automatically upgrades to headless browser, while stripping skeleton containers and orphan Loading... placeholder tags.
- **Interactive Browser Takeover**: Added `jeik open <URL>` and `jeik fetch --active-tab` for effortless manual login and CAPTCHA resolution.
- **Pure English Agent Skill Specification**: Converted `skill/SKILL.md` completely into pure English for agent tool discovery and execution.

### Changed
- **Precision Code Block Filtering**: Fixed Tailwind CSS color utility classes (`text-[var(--color-highlight)]`) being misidentified as Monaco code editors, eliminating pseudo-fenced blocks.
- **Dynamic CDP Port Allocation**: Allocate dynamic debug ports to eliminate multi-process port collisions during concurrent runs.
- **Self-Healing Sidebar Root Parsing**: Fixed boundary regression where pre-isolated sidebar root containers were discarded during child lookup.

---

## [1.1.1] - 2026-09-27

### Fixed
- **Windows GBK Encoding & Emoji Safety**: Enforced UTF-8 stream reconfigure (`sys.stdout`, `sys.stderr`, `sys.stdin`) and added `safe_print` fallback to completely eliminate `UnicodeEncodeError` when printing emojis (e.g. `\U0001f468`) and multi-lingual web content under Windows GBK/cp936 pipes.
- **Network Reset & Unreachable Error Detection**: Surface clear network failure messages instead of empty persisted files on connection resets.
- **Relative URL Resolution**: Automatically resolve relative URLs to absolute HTTP/HTTPS links using `base_url` during Markdown conversion.

### Added
- **Configurable Network Timeout & Wait**: Added `-t/--timeout` and `-w/--wait` CLI flags to support slow and high-latency networks seamlessly.

### Performance
- **Dynamic Content Settle Detection**: Added dynamic DOM substance polling to cut SPA wait time by up to 50%.

### CI/CD
- **PyInstaller Path Resolution**: Added `--paths .` to PyInstaller packaging in GitHub Actions release workflow.

---

## [1.1.0] - 2026-09-26

### Added
- **Jeik CLI (`jeik`)**: Introduced the unified command-line tool with zero-configuration scraping (`jeik fetch <url>`).
- **Absolute Path Anchoring**: Output begins with an unambiguous absolute path header, preventing LLM context cut-offs and relative path directory confusion.
- **Deep Interactive Exploration (Agentic Crawler)**:
  - Automated stepped smooth-scrolling to trigger `IntersectionObserver` and asynchronous API pricing callbacks (e.g. Aliyun `queryPrice`).
  - Automated drawer/modal scanner to extract hidden terms, FAQ details, and activity rules into a dedicated appendix.
  - Automated tab traversal across unselected options (`[role="tab"]`, `.next-tabs-tab`).
- **Content Quality Classifier**: Replaced rigid domain-based routing with heuristic text density and skeleton detection. Static SSR pages (GitHub, Wikipedia) return in under 1 second without launching a browser.
- **Multi-Worker Concurrency**: Added `scrape_urls_concurrent` with `asyncio.Semaphore` and `ThreadPoolExecutor` to handle concurrent scraping and heavy CPU transformations.
- **Encrypted DNS Support**: Added custom DNS resolution supporting numeric IPs (e.g. `8.8.8.8`) and DNS-over-HTTPS (`--dns https://1.1.1.1/dns-query` / `--dns aliyun`).
- **Self-Uninstall Command**: Added `jeik uninstall [-y]` for clean, one-command removal.
- **Cross-Platform Online Installers**: Added `scripts/install.sh` (Linux/macOS) and `scripts/install.ps1` (Windows) for zero-dependency binary distribution.

### Changed
- Rebranded core engine and API functions from `firecrawl_fetch` to `jeik_fetch` / `fetch`.
- Restructured code into modular domain layers: `core/`, `transformers/`, `storage/`, `api/`.
- Updated PyInstaller multi-platform workflow to bundle FastAPI, Uvicorn, Httpx, and WebSockets.

---

## [1.0.0] - 2026-09-26

### Added
- Initial release of Jeik-Web-Fetch engine.
- Headless Chromium CDP active-session controller for JavaScript single-page applications (SPA).
- Native Monaco Editor (`window.monaco.editor.getModels()`) memory-model extraction to prevent virtual-scroll code truncations.
- Automated anti-bot evasion: `navigator.webdriver` prototype cleaning, 1920x1080 viewport emulation, and runtime structure mocking.
- GFM table and code block structured Markdown converter.
- FastAPI asynchronous HTTP service with warm browser connection pooling.
- Multi-architecture GitHub Actions CI/CD release workflow for Linux (x64, arm64), macOS (Intel, Apple Silicon), and Windows (x64).
