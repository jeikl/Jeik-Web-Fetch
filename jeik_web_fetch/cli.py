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
import io
import shutil
import argparse
import asyncio
import subprocess
from pathlib import Path

def configure_utf8_io():
    """
    Force standard I/O streams (stdin, stdout, stderr) to UTF-8 encoding on all platforms.
    Prevents UnicodeEncodeError on Windows (e.g. GBK/cp936) when printing
    emojis (\U0001f468, etc.) or multi-lingual web content.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is not None:
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, io.UnsupportedOperation):
                try:
                    if hasattr(stream, "buffer"):
                        setattr(sys, stream_name, io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace", line_buffering=True))
                except Exception:
                    pass

    if hasattr(sys.stdin, "reconfigure"):
        try:
            sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# Immediately reconfigure I/O streams on module import
configure_utf8_io()

def safe_print(*args, **kwargs):
    """
    Print wrapper with fallback to replace unencodable characters
    if stdout/stderr cannot encode them (e.g. stubborn legacy pipes).
    """
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        file = kwargs.get("file") or sys.stdout
        enc = getattr(file, "encoding", None) or "utf-8"
        sep = kwargs.get("sep", " ")
        text = sep.join(str(a) for a in args)
        sanitized = text.encode(enc, errors="replace").decode(enc, errors="replace")
        kwargs_copy = dict(kwargs)
        print(sanitized, **kwargs_copy)

from .core.models import ScrapeOptions, OutputFormat
from .core.engine import default_engine
from .core.cookies import default_cookie_store
from .api.routes import app
import uvicorn

async def run_fetch(
    urls: list[str],
    dns: str = None,
    max_workers: int = 4,
    timeout: float = 30.0,
    wait_sec: float = 2.0,
    cookie: str = None,
    cookie_file: str = None,
    headers: list[str] = None,
    cdp_endpoint: str = None,
    browser_port: int = None,
    attach_tab: bool = False,
    tab: str = None
):
    parsed_headers = {}
    if headers:
        for h in headers:
            if ":" in h:
                k, v = h.split(":", 1)
                parsed_headers[k.strip()] = v.strip()

    # 如果启用了接管当前活跃标签页或指定标签且未显式指定 URL，则传入占位 URL
    if (attach_tab or tab) and not urls:
        urls = ["about:blank"]

    if not urls:
        safe_print("[-] 错误: 请提供目标网页 URL，或使用 --active-tab / --tab 附加到当前打开的浏览器标签页。", file=sys.stderr)
        sys.exit(1)

    if len(urls) == 1:
        # 单 URL 场景：最简流式输出
        options = ScrapeOptions(
            url=urls[0],
            formats=[OutputFormat.MARKDOWN],
            save_to_file=True,
            output_dir=None,
            dns=dns,
            timeout=timeout,
            waitFor=wait_sec,
            cookies=cookie,
            cookie_file=cookie_file,
            headers=parsed_headers if parsed_headers else None,
            cdp_endpoint=cdp_endpoint,
            browser_port=browser_port,
            attach_tab=attach_tab,
            tab=tab
        )
        result = await default_engine.scrape_url(options)
        await default_engine.stop()

        if not result.success:
            safe_print(f"[-] 抓取失败: {result.error}", file=sys.stderr)
            sys.exit(1)

        saved_md_path = result.saved_files.get("markdown", "")
        content = result.markdown or ""

        # Unambiguous English anchor header (critical for LLM reasoning and tools)
        header = (
            f"> Complete scraped document persisted at: {saved_md_path}\n"
            f"> If this output is truncated by model context windows, read the absolute path above directly.\n\n"
        )
        safe_print(header + content)
    else:
        # 多 URL 场景：全异步多线程并发抓取
        safe_print(f"[*] Starting concurrent scraping for {len(urls)} URLs (concurrency workers: {max_workers})...\n")
        options_list = [
            ScrapeOptions(
                url=u,
                formats=[OutputFormat.MARKDOWN],
                save_to_file=True,
                output_dir=None,
                dns=dns,
                timeout=timeout,
                waitFor=wait_sec,
                cookies=cookie,
                cookie_file=cookie_file,
                headers=parsed_headers if parsed_headers else None,
                cdp_endpoint=cdp_endpoint,
                browser_port=browser_port,
                attach_tab=attach_tab,
                tab=tab
            ) for u in urls
        ]
        results = await default_engine.scrape_urls_concurrent(options_list, max_workers=max_workers)
        await default_engine.stop()

        safe_print("=" * 60)
        safe_print("Concurrent Scraping Task Summary:")
        safe_print("=" * 60)
        for i, res in enumerate(results, 1):
            if res.success:
                saved = res.saved_files.get("markdown", "")
                safe_print(f"[{i}/{len(urls)}] ✔ Succeeded: {res.url} ({res.elapsed_seconds}s)")
                safe_print(f"      Saved: {saved}")
            else:
                safe_print(f"[{i}/{len(urls)}] ✘ Failed: {res.url} -> {res.error}")
        safe_print("\n> All documents have been persisted to the absolute paths above.")

def run_uninstall(skip_confirm: bool = False):
    """
    One-click self-uninstaller for jeik:
    - Stops and removes systemd / launchd background daemons
    - Removes /usr/local/bin/jeik and local binaries
    - Removes ~/.agents/skills/jeik-web-fetch
    - Uninstalls pip package if installed via pip
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

    print("[*] Stopping and removing background system services...")
    # 1. 停止并删除 systemd / launchd 守护进程
    try:
        subprocess.run(["systemctl", "stop", "jeik-daemon.service"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        subprocess.run(["systemctl", "disable", "jeik-daemon.service"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        for sfile in ["/etc/systemd/system/jeik-daemon.service", "/lib/systemd/system/jeik-daemon.service"]:
            if os.path.exists(sfile):
                try:
                    os.remove(sfile)
                except Exception:
                    pass
        subprocess.run(["systemctl", "daemon-reload"], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    except Exception:
        pass

    # 2. 删除通用智能体技能 ~/.agents/skills/jeik-web-fetch
    home = Path.home()
    skill_dir = home / ".agents" / "skills" / "jeik-web-fetch"
    if skill_dir.exists():
        shutil.rmtree(skill_dir, ignore_errors=True)
        print(f"[+] Removed skill directory: {skill_dir}")

    # 3. 如果是作为 Python 包安装的，调用 pip 卸载
    # 注意：在 PyInstaller 独立单文件环境中，sys.executable 是 jeik 二进制本身！不能执行 sys.executable -m pip！
    is_standalone_binary = getattr(sys, "frozen", False)
    if not is_standalone_binary:
        try:
            subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "jeik-web-fetch"], stderr=subprocess.DEVNULL)
        except Exception:
            pass

    # 4. 删除系统可执行文件自身 (/usr/local/bin/jeik 或 ~/.jeik/bin/jeik)
    print("[*] Removing CLI executables...")
    candidates = [
        "/usr/local/bin/jeik",
        "/usr/local/bin/jeik-web-fetch",
        "/usr/bin/jeik",
        str(home / ".local" / "bin" / "jeik"),
        str(home / ".jeik" / "bin" / "jeik.exe"),
        str(home / ".jeik" / "bin" / "jeik")
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                os.remove(c)
                print(f"[+] Removed: {c}")
            except Exception:
                pass

    print("\n[✔] jeik-web-fetch has been completely uninstalled from this system!")

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

def run_cookie_command(sub_args):
    """持久化域名 Cookie 维护命令"""
    action = getattr(sub_args, "cookie_action", None)
    if action == "set":
        domain = sub_args.domain
        raw_val = sub_args.value
        # 如果 raw_val 是文件路径，从文件读取
        if os.path.isfile(raw_val):
            raw_val = Path(raw_val).read_text(encoding="utf-8")
        out_path = default_cookie_store.save_for_domain(domain, raw_val)
        safe_print(f"[✔] Successfully saved persistent cookies for domain '{domain}'.")
        safe_print(f"    Saved at: {out_path}")
        safe_print(f"    Subsequent scraping for this domain will automatically carry this login session!")
    elif action == "list":
        items = default_cookie_store.list_all()
        if not items:
            safe_print("[*] No persistent domain cookies configured yet.")
            safe_print("    Use `jeik cookie set <domain> '<cookie>'` to save one.")
            return
        safe_print("=" * 60)
        safe_print("Configured Persistent Domain Cookies:")
        safe_print("=" * 60)
        for it in items:
            safe_print(f"• Domain: {it['domain']:<28} Cookies: {it['count']:<4} Updated: {it['updated_at']}")
            safe_print(f"  Path: {it['file']}")
    elif action == "delete":
        deleted = default_cookie_store.delete_for_domain(sub_args.domain)
        if deleted:
            safe_print(f"[✔] Successfully deleted persistent cookies for domain '{sub_args.domain}'.")
        else:
            safe_print(f"[-] No persistent cookies found for domain '{sub_args.domain}'.")

def run_browser_command(sub_args):
    """运行中浏览器实例管理与调试端口辅助命令"""
    action = getattr(sub_args, "browser_action", None)
    port = getattr(sub_args, "port", 9222)
    if action == "check":
        import httpx
        try:
            res = httpx.get(f"http://127.0.0.1:{port}/json/version", timeout=1.5)
            if res.status_code == 200:
                data = res.json()
                safe_print(f"[✔] Connected to active Chromium browser on port {port}!")
                safe_print(f"    Browser: {data.get('Browser', 'Unknown')}")
                safe_print(f"    Protocol: {data.get('Protocol-Version', 'Unknown')}")
                safe_print(f"    WebSocket: {data.get('webSocketDebuggerUrl', '')}")
                return
        except Exception:
            pass
        safe_print(f"[-] No active browser detected on port {port}.")
        safe_print(f"    Tip: Launch your Chrome/Edge with: `jeik browser launch --port {port}`")
    elif action == "launch":
        from .browser import find_system_browser
        bin_path = find_system_browser()
        if not bin_path:
            safe_print("[-] Could not find Chrome or Edge on your system.", file=sys.stderr)
            return
        profile_dir = Path.home() / ".jeik" / "browser_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        cmd = [
            bin_path,
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check"
        ]
        safe_print(f"[*] Launching browser with remote debugging on port {port}...")
        safe_print(f"    Profile: {profile_dir}")
        subprocess.Popen(cmd)
        safe_print(f"[✔] Browser successfully started! You can log into any target website in it,")
        safe_print(f"    and run: `jeik fetch <URL> -bp {port}` to seamlessly scrape with your full login session!")

def run_tabs_command(sub_args):
    """为非技术用户列出当前运行浏览器中打开的所有标签页"""
    from .core.browser_mgr import browser_mgr
    endpoint = getattr(sub_args, "cdp_endpoint", None) or os.environ.get("JEIK_CDP_ENDPOINT")
    if not endpoint:
        port = getattr(sub_args, "port", None) or os.environ.get("JEIK_BROWSER_PORT")
        if port:
            endpoint = f"http://127.0.0.1:{port}"
    if not endpoint:
        endpoint = browser_mgr.auto_discover_cdp_endpoint()

    if not endpoint:
        safe_print("[-] 未检测到正在运行且已开启调试通道的浏览器。")
        safe_print("\n💡 针对非技术人员的一键解决方案:")
        safe_print("   在终端运行: `jeik open <URL>` (系统将自动弹出已配置好的浏览器)")
        return

    tabs = browser_mgr.get_open_tabs(endpoint)
    if not tabs:
        safe_print(f"[*] 成功连接到浏览器 ({endpoint})，但当前没有打开的网页标签页。")
        return

    safe_print("=" * 65)
    safe_print("当前运行浏览器中已打开的标签页列表:")
    safe_print("=" * 65)
    for t in tabs:
        safe_print(f"[{t['index']}] {t['title']}")
        safe_print(f"    URL: {t['url']}")
    safe_print("-" * 65)
    safe_print("💡 极简抓取命令 (无需记忆端口和网址):")
    safe_print(f"   jeik fetch --tab 1")
    first_title_kw = re.sub(r"[^\w\u4e00-\u9fa5]", "", tabs[0]['title'])[:4] or "1"
    safe_print(f"   jeik fetch --tab \"{first_title_kw}\"")
    safe_print(f"   jeik fetch --active-tab")

def run_open_command(sub_args):
    """一键为非技术用户拉起已配置好调试端口的真实日常浏览器窗口"""
    from .core.browser_mgr import browser_mgr
    url = getattr(sub_args, "url", "https://www.google.com")
    port = getattr(sub_args, "port", 9222)
    safe_print(f"[*] 正在为您启动已配置调试通道的可视化浏览器窗口...")
    ok, msg = browser_mgr.launch_debug_browser(target_url=url, port=port)
    if ok:
        safe_print(f"[✔] 浏览器窗口已弹出！({msg})")
        safe_print(f"    您可以在窗口中正常浏览、点击或扫码登录网站。")
        safe_print(f"    登录完成后，直接在终端运行以下命令即可享受完整登录态抓取:")
        safe_print(f"    👉 jeik fetch --active-tab")
        safe_print(f"    👉 jeik fetch --tab \"关键词\"")
    else:
        safe_print(f"[-] {msg}", file=sys.stderr)

def main():
    # 强制确保所有标准 I/O 为 UTF-8 编码
    configure_utf8_io()

    # 启动后台自动更新探测器 (每10分钟自动检查一次，若有更新且当前空闲则无感平滑升级)
    from .core.updater import updater
    updater.start_background_daemon()

    parser = argparse.ArgumentParser(
        prog="jeik",
        description="Jeik CLI: High-performance, anti-bot web scraper & markdown extraction toolkit"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # 1. jeik fetch <url> ...
    fetch_parser = subparsers.add_parser("fetch", help="Scrape any URL (intranet/internet/SPA/anti-bot) into structured Markdown")
    fetch_parser.add_argument("urls", nargs="*", default=[], help="Target URL(s) to scrape (supports parallel multi-URL scraping)")
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
    fetch_parser.add_argument(
        "-t", "--timeout",
        dest="timeout",
        type=float,
        default=30.0,
        help="Overall network timeout in seconds (default: 30.0s, increase for high-latency or slow overseas pages)"
    )
    fetch_parser.add_argument(
        "-w", "--wait",
        dest="wait",
        type=float,
        default=2.0,
        help="SPA render buffering wait in seconds (default: 2.0s, increase for slow API rendering)"
    )
    fetch_parser.add_argument(
        "-c", "--cookie",
        dest="cookie",
        default=None,
        help="Raw Cookie string (e.g. 'session_id=abc; token=123')"
    )
    fetch_parser.add_argument(
        "--cookie-file",
        dest="cookie_file",
        default=None,
        help="Path to cookie file (Netscape cookies.txt or JSON format)"
    )
    fetch_parser.add_argument(
        "-H", "--header",
        dest="headers",
        action="append",
        default=[],
        help="Custom HTTP request header (e.g. -H 'Authorization: Bearer xxx', can be used multiple times)"
    )
    fetch_parser.add_argument(
        "--cdp-endpoint",
        dest="cdp_endpoint",
        default=None,
        help="Connect to an existing running Chromium/Chrome/Edge browser CDP endpoint (e.g. http://127.0.0.1:9222)"
    )
    fetch_parser.add_argument(
        "-bp", "--browser-port",
        dest="browser_port",
        type=int,
        default=None,
        help="Connect to local running browser debugging port (e.g. 9222, shorthand for --cdp-endpoint http://127.0.0.1:<port>)"
    )
    fetch_parser.add_argument(
        "--active-tab",
        dest="attach_tab",
        action="store_true",
        help="Directly attach and scrape the currently active tab in running browser without opening a new tab"
    )
    fetch_parser.add_argument(
        "--tab",
        dest="tab",
        default=None,
        help="Match an open tab by title keyword, URL or index in running browser (e.g. --tab '知乎', --tab 1)"
    )

    # 2. jeik tabs (非技术用户查看当前打开的标签页)
    tabs_parser = subparsers.add_parser("tabs", help="List all open tabs in running browser with friendly index and title")
    tabs_parser.add_argument("-p", "--port", type=int, default=None, help="Debugging port to inspect (default: auto-discover)")
    tabs_parser.add_argument("--cdp-endpoint", default=None, help="Custom CDP endpoint to inspect (default: auto-discover)")

    # 3. jeik open / jeik login (一键拉起带调试端口的浏览器供非技术用户登录)
    open_parser = subparsers.add_parser("open", help="Launch a real browser with auto-configured debugging port for user to log in")
    open_parser.add_argument("url", nargs="?", default="https://www.bing.com", help="Initial webpage URL to open")
    open_parser.add_argument("-p", "--port", type=int, default=9222, help="Debugging port (default: 9222)")

    login_parser = subparsers.add_parser("login", help="Launch browser for interactive login, session is saved automatically")
    login_parser.add_argument("url", help="Target website URL to log into")
    login_parser.add_argument("-p", "--port", type=int, default=9222, help="Debugging port (default: 9222)")

    # 4. jeik cookie {set, list, delete}
    cookie_parser = subparsers.add_parser("cookie", help="Manage persistent domain login cookies")
    cookie_sub = cookie_parser.add_subparsers(dest="cookie_action", help="Cookie actions")
    
    cookie_set = cookie_sub.add_parser("set", help="Save/update login cookies for a domain")
    cookie_set.add_argument("domain", help="Target domain (e.g. github.com, zhihu.com)")
    cookie_set.add_argument("value", help="Cookie string (e.g. 'uid=1; token=abc') or path to cookies.txt/json")
    
    cookie_sub.add_parser("list", help="List all saved domain cookies")
    
    cookie_del = cookie_sub.add_parser("delete", help="Delete saved cookies for a domain")
    cookie_del.add_argument("domain", help="Target domain to delete")

    # 3. jeik browser {check, launch}
    browser_parser = subparsers.add_parser("browser", help="Manage or connect to running browser instances")
    browser_sub = browser_parser.add_subparsers(dest="browser_action", help="Browser actions")
    
    b_check = browser_sub.add_parser("check", help="Check if an existing browser is running on debugging port")
    b_check.add_argument("-p", "--port", type=int, default=9222, help="Debugging port to check (default: 9222)")
    
    b_launch = browser_sub.add_parser("launch", help="Launch a browser instance with remote debugging enabled")
    b_launch.add_argument("-p", "--port", type=int, default=9222, help="Debugging port to bind (default: 9222)")

    # 4. jeik serve [--port 8863]
    serve_parser = subparsers.add_parser("serve", help="Start high-concurrency FastAPI HTTP server")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Host address to bind (default: 0.0.0.0)")
    serve_parser.add_argument("-p", "--port", type=int, default=8863, help="Listening port (default: 8863)")

    # 5. jeik upgrade
    subparsers.add_parser("upgrade", help="Check and upgrade jeik to the latest release version, then restart")

    # 6. jeik uninstall [-y]
    uninstall_parser = subparsers.add_parser("uninstall", help="One-click uninstall jeik-web-fetch from system")
    uninstall_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")

    # Shorthand: `jeik https://...` -> auto route to `fetch`
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-") and sys.argv[1] not in ["fetch", "tabs", "open", "login", "serve", "upgrade", "uninstall", "cookie", "browser", "help"]:
        sys.argv.insert(1, "fetch")

    args = parser.parse_args()

    if args.command == "fetch":
        asyncio.run(run_fetch(
            args.urls,
            dns=args.dns,
            max_workers=args.max_workers,
            timeout=args.timeout,
            wait_sec=args.wait,
            cookie=args.cookie,
            cookie_file=args.cookie_file,
            headers=args.headers,
            cdp_endpoint=args.cdp_endpoint,
            browser_port=args.browser_port,
            attach_tab=args.attach_tab,
            tab=args.tab
        ))
    elif args.command == "tabs":
        run_tabs_command(args)
    elif args.command in ("open", "login"):
        run_open_command(args)
    elif args.command == "cookie":
        run_cookie_command(args)
    elif args.command == "browser":
        run_browser_command(args)
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
