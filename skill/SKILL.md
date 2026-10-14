---
name: jeik-web-fetch
description: "High-performance web extraction tool. Scrapes any URL (SPA, dynamic JS, anti-bot, intranet, or internet) and outputs clean structured Markdown."
---

# Jeik Web Fetch

Run the `jeik fetch` command directly in terminal or bash:

```bash
jeik fetch "<URL>"
```

### Options (Threads, Cookies & Authenticated Sessions)

```bash
# 1. Custom numeric DNS or encrypted DNS (DoH), and multi-worker concurrency
jeik fetch "<URL>" --dns "https://1.1.1.1/dns-query" -j 4

# 2. Scrape with login cookies directly (string or cookies.txt file)
jeik fetch "<URL>" --cookie "session_id=abc; token=123"
jeik fetch "<URL>" --cookie-file "./cookies.txt"

# 3. Save domain cookies permanently (zero-config authenticated scraping for future tasks)
jeik cookie set zhihu.com "z_c0=..."
jeik cookie list
jeik fetch "https://www.zhihu.com/question/123"  # Automatically uses saved login session!

# 4. Zero-barrier: Attach to user's currently open browser tab (No port needed!)
jeik tabs                       # Lists all open tabs with numbers and titles
jeik fetch --active-tab          # Directly scrape the currently active browser tab
jeik fetch --tab "TitleKeyword"  # Fuzzy match tab by title (e.g. --tab "阿里云", --tab 1)

# 5. Non-technical 1-click browser launcher (Auto-configured debugging channel)
jeik open "<URL>"               # Pops up browser for user to log in/scan QR code, then scrape with --active-tab
```

> Output begins with an absolute path anchor header where the full Markdown has been persisted safely to `.jeik/fetches/`.
