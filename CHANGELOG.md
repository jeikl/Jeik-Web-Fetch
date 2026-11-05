# Changelog

All notable changes to **Jeik-Web-Fetch** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.2.2] - 2026-11-05

### Added
- **Browser slot pool with memory-aware sizing**: `jeik fetch` now borrows an exclusive slot (one browser + one profile) instead of queueing behind a single daemon. An empty pool creates the `anchor` slot (idle TTL 3600s); concurrent calls create `temp` slots (1200s) up to a cap derived from physical memory — ≤1.5 GB → 1, ≤2.5 GB → 2, ≤6 GB → 3, else 4 (cgroup-aware inside containers). At the cap a call immediately falls back to a private one-shot engine instead of waiting, and every slot is reclaimed by its own idle timer.
  - Registry is one JSON file per slot plus `O_CREAT|O_EXCL` leases, so concurrent processes never overwrite each other; a lease left by a killed process is stolen after `JEIK_POOL_LEASE_TTL` (default 300s).
  - A pre-existing hand-started `jeik serve` is adopted as the anchor (health-managed, PID unknown) instead of spawning a second daemon.
  - Tunables: `JEIK_POOL_MAX`, `JEIK_POOL_ANCHOR_TTL`, `JEIK_POOL_TEMP_TTL`, `JEIK_POOL_LEASE_TTL`, `JEIK_POOL_DIR`.
  - Regression tests: `tests/test_daemon_guard.py`, `tests/test_resources.py`.

### Changed
- **The daemon now binds to loopback by default**: `jeik serve --host` defaults to `127.0.0.1` instead of `0.0.0.0`. The service has no authentication, so the old default exposed an open scraping proxy — and its CDP port through `/health` — to anyone who could reach the machine. Binding to a non-loopback interface now requires an explicit `--allow-public`, both installers (`scripts/install.sh`, `scripts/install.ps1`) pass `--host 127.0.0.1`, and CORS is limited to localhost origins so a random website can no longer drive the local browser.
- **`jeik fetch` reuses an auto-spawned daemon**: instead of requiring a manually started `jeik serve`, the CLI probes `127.0.0.1:8863` and, when nothing is listening, spawns a detached daemon with `--idle-exit 3600` (it exits by itself after an hour idle). Only loopback endpoints are ever accepted; `JEIK_NO_DAEMON_REUSE=1` disables reuse and `JEIK_NO_AUTO_DAEMON=1` disables auto-spawn.

### Fixed
- **Temp Chromium profiles were never reclaimed (`%TEMP%\jeik_engine_*`, ~131 MB each)**: every headless run creates a full browser profile, but the only cleanup was `shutil.rmtree(..., ignore_errors=True)` inside `stop()`. Two paths leaked it permanently — the process being killed (tool timeout / Ctrl-C / OOM), and on Windows `rmtree` silently failing while Chromium child processes still held file handles. 130+ accumulated profiles had consumed ~18 GB.
  - Each profile now carries a `<dir>.owner` PID marker, and `sweep_stale_profiles()` reclaims any profile whose owner process is gone. A profile without a marker (created by an older build) is only removed once it is more than an hour old, so a concurrently running fetch is never touched.
  - The sweep runs on every `ensure_started`, so leftovers are reclaimed by the next fetch or daemon start.
  - `_remove_tree()` retries with backoff instead of swallowing the failure, and the whole browser tree is killed (`taskkill /T /F` on Windows) before deletion.
  - **snap private-temp mirrors are reclaimed too**: when Chromium runs from the snap package, its `/tmp` is redirected to `<tmp>/snap-private-tmp/<snap>/tmp/`, so the real ~135 MB profile lands there while the host-side `/tmp/jeik_engine_*` is a 4 KB shell. Deleting only the host path freed nothing — 142 stale mirrors had grown to 18 GB on a Linux host. `_remove_profile()` now removes both, the sweep enumerates both, and a stale profile whose owner died also takes down any browser still using it (`/proc` scan on POSIX, `Get-CimInstance` on Windows), so a SIGKILLed fetch no longer leaves a live orphan.
  - **Concurrent scrapes no longer wipe each other's cookies**: a persistent-profile engine (`jeik serve`) still sent `Network.clearBrowserCookies` for every tab, so parallel requests (e.g. `/scrape/batch` with 8 workers) erased each other's session. The global clear now runs only for exclusive one-shot engines; shared browsers rely on per-tab cookie injection.
  - An `atexit` hook reaps still-live profiles on `sys.exit` and uncaught exceptions.
  - `jeik serve` now runs in **persistent-profile mode** (`~/.jeik/engine_profile`, override with `JEIK_ENGINE_PROFILE_DIR`): the browser and its profile are reused across requests *and* restarts, so a restart no longer leaves another 131 MB temporary directory behind.
  - `jeik fetch` now **reuses the running daemon's browser** when `jeik serve` is up (discovered through `/health` → `pool_port`), so a CLI call creates no profile at all. Opt out with `JEIK_NO_DAEMON_REUSE=1`; override the endpoint with `JEIK_DAEMON_URL`. Attaching to a shared browser no longer clears its cookies.
  - One-shot runs disable the disk cache (`--disk-cache-size=1`, `--disable-application-cache`, …), cutting a run's profile from ~131 MB to ~20-30 MB. The persistent serve profile keeps its cache, where cross-request reuse actually pays off.
  - The same retry logic was applied to the legacy `BrowserPool` in `fastapi_server.py`.
  - Regression tests in `tests/test_profile_cleanup.py`.
- **`jeik upgrade` failed with "Could not reach GitHub releases" on Windows**: two independent defects.
  - **GitHub API rate limiting (403)**: `check_remote_version()` swallowed every failure in a bare `except Exception`, so an exhausted anonymous quota (60 req/h per egress IP), a TLS error, a DNS failure and a captive proxy all produced the same message. The probe now records the real cause in `AutoUpdater.last_error` (including the quota reset time) and prints it with the endpoint and a proxy hint. When the API is rate limited it **falls back to `github.com/<repo>/releases/latest`**, whose redirect reveals the version without touching the API, so `jeik upgrade` keeps working. `GITHUB_TOKEN`/`GH_TOKEN` are honoured to raise the quota to 5000/h.
  - **Self-replace of the running `jeik.exe` (Windows file lock)**: `scripts/install.ps1` streamed the download straight onto `$TargetExe`, which Windows refuses with *"The process cannot access the file ... because it is being used by another process"*. It now stages to `jeik.exe.new`, stops only the `serve` daemon (never the CLI performing the upgrade), then swaps by renaming the locked binary and moves the new one into place.
  - TLS now verifies against the bundled `certifi` CA store: PyInstaller one-file builds on Windows often cannot locate the system roots and fail with `CERTIFICATE_VERIFY_FAILED`, while `httpx` (which bundles certifi) keeps working.
  - Timeout raised from 8s to 20s (`JEIK_UPDATE_TIMEOUT`) with up to 3 attempts; `403/404/429` are terminal and not retried.
  - Release asset selection now prefers the matching CPU architecture, so a Windows arm64 host no longer silently picks the x64 build.
  - When the shell installer fails, the direct release asset URL is printed as a fallback.
  - Regression tests in `tests/test_updater_connectivity.py`.

---

## [1.2.1] - 2026-10-31

### Fixed
- **Headless browser leak when the pool prewarm times out**: `ScrapeEngine.ensure_started()` polled the CDP endpoint with a fixed 40-attempt loop and, on timeout, raised `TimeoutError` **without killing the Chromium it had just spawned**. The ASGI lifespan never reached `stop()` (startup failed before `yield`), so the browser was reparented to PID 1 and stayed resident: one full headless Chromium (~389 MB PSS, 10 processes) leaked per failed start. Combined with `Restart=always` that turned into a leak every few seconds until the host ran out of memory.
  - Readiness polling now uses a **wall-clock deadline** (`JEIK_BROWSER_START_TIMEOUT`, default 45s) instead of an attempt count. A refused connection returns instantly, so 40 attempts gave up after ~4s on loaded machines — long before snap / a cold-start Chromium could open the debugging port.
  - Added `_reap_browser()`: kill + `wait()` (no zombies) + remove the temporary profile, invoked from **every** failure path and from `stop()`.
  - The FastAPI lifespan now reaps the pool when prewarm fails, and always stops it through `try/finally`.
  - The legacy `BrowserPool` in `fastapi_server.py` carried the same defect and received the same fix.
  - Regression tests in `tests/test_browser_leak.py` reproduce the failure path with a fake browser that never opens the CDP port.

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
