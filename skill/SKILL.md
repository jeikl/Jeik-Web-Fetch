---
name: jeik-web-fetch
description: "High-performance web extraction tool. Scrapes any URL (SPA, dynamic JS, anti-bot, intranet, or internet) and outputs clean structured Markdown."
---

# Jeik Web Fetch

Run the `jeik fetch` command directly in terminal or bash:

```bash
jeik fetch "<URL>"
```

### Options (Threads & Custom DNS)

```bash
# Custom numeric DNS or encrypted DNS (DoH), and multi-worker concurrency
jeik fetch "<URL>" --dns "https://1.1.1.1/dns-query" -j 4
```

> Output begins with an absolute path anchor header where the full Markdown has been persisted safely to `.jeik/fetches/`.
