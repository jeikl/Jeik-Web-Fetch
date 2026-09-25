# Changelog

All notable changes to **Jeik-Web-Fetch** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
