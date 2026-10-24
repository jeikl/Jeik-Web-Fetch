---
name: jeik-web-fetch
description: "High-performance web extraction tool. Scrapes any URL (SPA, dynamic JS, anti-bot, intranet, or internet) and outputs clean structured Markdown with 3 categorized modes: --fast (default), --common, and --complex."
---

# Jeik Web Fetch

Run the `jeik fetch` command directly in terminal or bash. `jeik fetch` provides 3 dedicated extraction modes tailored for different types of web pages:

```bash
jeik fetch "<URL>" [mode-flag] [options]
```

---

## 🎯 3 Categorized Fetch Modes

| Mode Flag | Target Webpages & Scenarios | Underlying Mechanism & Key Advantages | Example Command |
| :--- | :--- | :--- | :--- |
| **`--fast`**<br>*(Default)* | **Static Pages & Plain Text**<br>• GitHub repos, issues, code files<br>• Plain HTML blogs, Wikipedia<br>• Raw CSS, JS, Markdown, JSON files | **Sub-second HTTP Probe**<br>Direct fetch without launching a browser, zero memory overhead, returns structured Markdown in under 200ms. Automatically escalates to headless browser if an unhydrated skeleton is detected. | `jeik fetch "https://github.com/..."`<br>`jeik fetch "https://example.com" --fast` |
| **`--common`** | **Dynamic Technical Docs & JS Pages**<br>• Modern JS documentation (DeepSeek, MiMo, Docusaurus, Mintlify)<br>• Client-side SPA (React, Vue, Next.js, Nuxt)<br>• Complex manuals with Monaco / CodeMirror editors, lazy loading, and expandable drawers | **Full Headless Browser Rendering**<br>Bypasses static probe, launches Chromium with JavaScript execution, waits for hydration, recursively expands folding sections, and extracts content along with sidebar navigation trees. | `jeik fetch "https://mimo.mi.com/docs/..." --common`<br>`jeik fetch "https://api-docs.deepseek.com/..." --common` |
| **`--complex`** | **High Anti-Bot Risk & Interactive Sites**<br>• Heavily restricted sites (Zhihu, Xiaohongshu, WeChat, Taobao)<br>• Cloudflare Turnstile/5s challenge, CAPTCHAs, login walls, or complex fingerprinting | **Deep Anti-Bot Stealth & Browser Takeover**<br>Enables advanced stealth spoofing, extended settling timeouts, and smooth micro-scrolling. Supports one-click browser debugging via `jeik open` for manual login and seamless tab takeover. | `jeik fetch "https://www.zhihu.com/..." --complex`<br>`jeik open "<URL>"` -> Login -> `jeik fetch --active-tab` |

---

## 🚀 Usage Examples

### 1. Fast Mode (Default) — Instant Static Page Scraping
```bash
# Scrape GitHub repositories, documentation, or static blogs (default is --fast)
jeik fetch "https://github.com/torvalds/linux"
jeik fetch "https://raw.githubusercontent.com/user/repo/main/README.md" --fast
```

### 2. Common Mode — Complete Dynamic JS & Tech Docs Extraction
```bash
# Scrape nested technical documentation, Swagger/OpenAPI docs, API references with sidebar links and multi-language code snippets
jeik fetch "https://mimo.mi.com/docs/zh-CN/api/guidance/rate-limit" --common
jeik fetch "https://api-docs.deepseek.com/zh-cn/api/create-chat-completion" --common
```

### 3. Complex Mode — Anti-Bot Evasion & Interactive Takeover
```bash
# Scrape sites with strict anti-bot policies
jeik fetch "https://www.zhihu.com/question/123456" --complex

# If encountering a login wall or slider CAPTCHA (1-second seamless takeover):
jeik open "https://www.xiaohongshu.com"   # Opens a browser with debugging port for manual browsing/login
jeik fetch --active-tab                  # Immediately attaches to and extracts the active authenticated tab!
```

---

## ⚙️ Advanced Options

```bash
# 1. High-concurrency multi-threaded batch scraping (-j / --threads)
jeik fetch "url1" "url2" "url3" -j 4 --common

# 2. Custom DNS resolution (--dns, supports numeric IPs or DNS-over-HTTPS)
jeik fetch "<URL>" --dns "https://1.1.1.1/dns-query"

# 3. Persistent authenticated cookies (--cookie / --cookie-file)
jeik fetch "<URL>" --cookie "session_id=abc; token=123" --complex
jeik cookie set zhihu.com "z_c0=..."     # Persist domain cookies across sessions

# 4. Suppress sidebar navigation catalog (--no-sidebar)
jeik fetch "<URL>" --common --no-sidebar  # Extract body content only, suppressing the trailing sidebar links appendix
```

> Output begins with an absolute path anchor header where the full Markdown has been persisted safely to `.jeik/fetches/`.
