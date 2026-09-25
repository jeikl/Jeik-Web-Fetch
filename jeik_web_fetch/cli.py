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

async def run_fetch(url: str, dns: str = None):
    options = ScrapeOptions(
        url=url,
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

def run_uninstall(skip_confirm: bool = False):
    """
    一键卸载 jeik-web-fetch
    """
    print("=" * 50)
    print("Jeik CLI 一键自卸载程序")
    print("=" * 50)

    if not skip_confirm:
        try:
            choice = input("确定要从当前 Python 环境中完全卸载 jeik-web-fetch 吗？ [y/N]: ").strip().lower()
            if choice not in ("y", "yes"):
                print("[-] 已取消卸载。")
                return
        except (KeyboardInterrupt, EOFError):
            print("\n[-] 已取消操作。")
            return

    print("[*] 正在执行卸载流程...")
    cmd = [sys.executable, "-m", "pip", "uninstall", "-y", "jeik-web-fetch"]
    res = subprocess.run(cmd)

    if res.returncode == 0:
        print("\n[✔] jeik-web-fetch 已成功从系统中卸载！感谢您的使用。")
    else:
        print(f"\n[-] 卸载遇到异常，返回码: {res.returncode}", file=sys.stderr)
        sys.exit(res.returncode)

def main():
    parser = argparse.ArgumentParser(
        prog="jeik",
        description="Jeik CLI: 新一代全能极速智能终端套件 (包含抓取、高并发服务、一键卸载)"
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # 1. jeik fetch <url> [--dns <dns>]
    fetch_parser = subparsers.add_parser("fetch", help="高保真抓取任何网页 (内网/公网/SPA/反爬)，并完整输出为 Markdown")
    fetch_parser.add_argument("url", help="目标网页绝对 URL (支持内网 IP、域名及公网)")
    fetch_parser.add_argument(
        "--dns",
        default=None,
        help="指定 DNS 服务器 (支持数字 IP 如 8.8.8.8, 114.114.114.114，或 DoH 加密 DNS 如 https://1.1.1.1/dns-query，默认系统 DNS)"
    )

    # 2. jeik serve [--port 8000]
    serve_parser = subparsers.add_parser("serve", help="启动 FastAPI 高并发 HTTP 服务")
    serve_parser.add_argument("--host", default="0.0.0.0", help="监听地址 (默认: 0.0.0.0)")
    serve_parser.add_argument("-p", "--port", type=int, default=8000, help="监听端口 (默认: 8000)")

    # 3. jeik uninstall [-y]
    uninstall_parser = subparsers.add_parser("uninstall", help="从系统中一键卸载 jeik-web-fetch")
    uninstall_parser.add_argument("-y", "--yes", action="store_true", help="跳过确认提示直接卸载")

    # 极简模式：直接输入 `jeik https://...` 自动进入 fetch
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-") and sys.argv[1] not in ["fetch", "serve", "uninstall", "help"]:
        sys.argv.insert(1, "fetch")

    args = parser.parse_args()

    if args.command == "fetch":
        asyncio.run(run_fetch(args.url, dns=args.dns))
    elif args.command == "serve":
        uvicorn.run(app, host=args.host, port=args.port, log_level="info", access_log=False)
    elif args.command == "uninstall":
        run_uninstall(skip_confirm=args.yes)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
