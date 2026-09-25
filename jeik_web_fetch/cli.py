#!/usr/bin/env python3
"""
Jeik CLI 核心入口模块
命令格式:
    jeik fetch <url> [--dns <dns>]
    jeik serve [--host <host>] [--port <port>]
    jeik uninstall [-y]
    jeik <url> (快捷方式)
"""

import os
import sys
import argparse
import asyncio
import subprocess
from pathlib import Path

from .core.models import ScrapeOptions, OutputFormat
from .core.engine import default_engine
from .api.routes import app
import uvicorn

async def run_fetch(urls: list[str], dns: str = None, max_workers: int = 4):
    if len(urls) == 1:
        # 单 URL 场景：最简流式输出
        options = ScrapeOptions(
            url=urls[0],
            formats=[OutputFormat.MARKDOWN],
            save_to_file=True,
            output_dir=None,
            dns=dns,
            waitFor=4.0
        )
        result = await default_engine.scrape_url(options)
        await default_engine.stop()

        if not result.success:
            print(f"[-] 抓取失败: {result.error}", file=sys.stderr)
            sys.exit(1)

        saved_md_path = result.saved_files.get("markdown", "")
        content = result.markdown or ""

        header = (
            f"> 当前摘取的完整文档已存到: {saved_md_path}\n"
            f"> 如果后续输出被终端或模型窗口截断，可直接使用读取工具读取上述绝对路径获取完整内容。\n\n"
        )
        print(header + content)
    else:
        # 多 URL 场景：全异步多线程并发抓取
        print(f"[*] Starting concurrent scraping for {len(urls)} URLs (concurrency workers: {max_workers})...\n")
        options_list = [
            ScrapeOptions(
                url=u,
                formats=[OutputFormat.MARKDOWN],
                save_to_file=True,
                output_dir=None,
                dns=dns,
                waitFor=4.0
            ) for u in urls
        ]
        results = await default_engine.scrape_urls_concurrent(options_list, max_workers=max_workers)
        await default_engine.stop()

        print("=" * 60)
        print("Concurrent Scraping Task Summary:")
        print("=" * 60)
        for i, res in enumerate(results, 1):
            if res.success:
                saved = res.saved_files.get("markdown", "")
                print(f"[{i}/{len(urls)}] ✔ Succeeded: {res.url} ({res.elapsed_seconds}s)")
                print(f"      Saved: {saved}")
            else:
                print(f"[{i}/{len(urls)}] ✘ Failed: {res.url} -> {res.error}")
        print("\n> All documents have been persisted to the absolute paths above.")

def run_uninstall(skip_confirm: bool = False):
    """
    One-click uninstaller for jeik-web-fetch.
    """
    print("=" * 50)
    print("Jeik CLI Uninstallation Wizard")
    print("=" * 50)

    if not skip_confirm:
        try:
            choice = input("Are you sure you want to completely uninstall jeik-web-fetch? [y/N]: ").strip().lower()
            if choice not in ("y", "yes"):
                print("[-] Uninstallation cancelled.")
                return
        except (KeyboardInterrupt, EOFError):
            print("\n[-] Operation cancelled.")
            return

    print("[*] Uninstalling package...")
    cmd = [sys.executable, "-m", "pip", "uninstall", "-y", "jeik-web-fetch"]
    res = subprocess.run(cmd)

    if res.returncode == 0:
        print("\n[✔] jeik-web-fetch successfully removed from system.")
    else:
        print(f"\n[-] Uninstallation encountered error with exit code {res.returncode}", file=sys.stderr)
        sys.exit(res.returncode)

def run_upgrade():
    """
    One-click upgrade command for jeik-web-fetch:
    Checks latest GitHub release, waits for idle, applies update, and restarts.
    """
    from .core.updater import updater
    print("=" * 50)
    print("Jeik CLI Self-Upgrade Program")
    print("=" * 50)
    success = updater.perform_upgrade_and_restart(direct_cli=True)
    if not success:
        sys.exit(1)

def main():
    # 启动后台自动更新探测器 (每10分钟自动检查一次，若有更新且当前空闲则无感平滑升级)
    from .core.updater import updater
    updater.start_background_daemon()

    parser = argparse.ArgumentParser(
        prog="jeik",
        description="Jeik CLI: High-performance, anti-bot web scraper & markdown extraction toolkit"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # 1. jeik fetch <url> [<url> ...] [-j / --threads <N>] [--dns <dns>]
    fetch_parser = subparsers.add_parser("fetch", help="Scrape any URL (intranet/internet/SPA/anti-bot) into structured Markdown")
    fetch_parser.add_argument("urls", nargs="+", help="Target URL(s) to scrape (supports parallel multi-URL scraping)")
    fetch_parser.add_argument(
        "-j", "--threads",
        dest="max_workers",
        type=int,
        default=4,
        help="Concurrency worker pool size (default: 4)"
    )
    fetch_parser.add_argument(
        "--dns",
        default=None,
        help="Custom DNS resolver (numeric IP e.g. 8.8.8.8, or DoH encrypted e.g. https://1.1.1.1/dns-query, default: system)"
    )

    # 2. jeik serve [--port 8000]
    serve_parser = subparsers.add_parser("serve", help="Start high-concurrency FastAPI HTTP server")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Host address to bind (default: 0.0.0.0)")
    serve_parser.add_argument("-p", "--port", type=int, default=8000, help="Listening port (default: 8000)")

    # 3. jeik upgrade
    subparsers.add_parser("upgrade", help="Check and upgrade jeik to the latest release version, then restart")

    # 4. jeik uninstall [-y]
    uninstall_parser = subparsers.add_parser("uninstall", help="One-click uninstall jeik-web-fetch from system")
    uninstall_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")

    # Shorthand: `jeik https://...` -> auto route to `fetch`
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-") and sys.argv[1] not in ["fetch", "serve", "upgrade", "uninstall", "help"]:
        sys.argv.insert(1, "fetch")

    args = parser.parse_args()

    if args.command == "fetch":
        asyncio.run(run_fetch(args.urls, dns=args.dns, max_workers=args.max_workers))
    elif args.command == "serve":
        uvicorn.run(app, host=args.host, port=args.port, log_level="info", access_log=False)
    elif args.command == "upgrade":
        run_upgrade()
    elif args.command == "uninstall":
        run_uninstall(skip_confirm=args.yes)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
