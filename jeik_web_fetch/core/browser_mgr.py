import os
import re
import sys
import json
import time
import subprocess
import urllib.request
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path

from ..browser import find_system_browser

COMMON_DEBUG_PORTS = [9222, 9223, 9224, 9527, 9876, 5003]

class BrowserManager:
    """
    智能运行中浏览器实例发现与标签页语义匹配器：
    - 专为非技术用户设计：用户无需知道什么是 CDP、端口号是多少；
    - 自动探针扫描本地常见调试端口，或从系统正在运行的进程参数中反查端口；
    - 支持按网页标题（Title）、关键词或序号（Index）模糊匹配标签页；
    - 支持一键拉起带有调试端口的日常可视化浏览器供用户扫码/登录。
    """

    @staticmethod
    def probe_port(port: int, timeout: float = 0.5) -> Optional[Dict[str, Any]]:
        """探针检测指定端口是否为合法的 Chromium CDP 服务"""
        url = f"http://127.0.0.1:{port}/json/version"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "JeikBrowserProbe/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    return data
        except Exception:
            pass
        return None

    @classmethod
    def find_port_from_processes(cls) -> Optional[int]:
        """从操作系统当前运行进程的命令行参数中反查 --remote-debugging-port"""
        try:
            if sys.platform == "win32":
                # 使用 wmic 或 PowerShell 查询命令行
                cmd = ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process -Filter \"Name like '%chrome%' or Name like '%edge%' or Name like '%brave%'\" | Select-Object -ExpandProperty CommandLine"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
                if res.returncode == 0:
                    matches = re.findall(r"--remote-debugging-port=(\d+)", res.stdout)
                    for m in matches:
                        p = int(m)
                        if p > 0 and cls.probe_port(p):
                            return p
            else:
                # Linux / macOS 使用 ps aux
                cmd = ["ps", "aux"]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
                if res.returncode == 0:
                    matches = re.findall(r"--remote-debugging-port=(\d+)", res.stdout)
                    for m in matches:
                        p = int(m)
                        if p > 0 and cls.probe_port(p):
                            return p
        except Exception:
            pass
        return None

    @classmethod
    def auto_discover_cdp_endpoint(cls) -> Optional[str]:
        """
        全自动发现正在运行的浏览器 CDP 端点：
        1. 先探针扫描常见端口 (9222, 9223 等)；
        2. 若未命中，则扫描系统进程命令行；
        3. 找到即返回例如 'http://127.0.0.1:9222'，完全免除用户输入端口的负担！
        """
        for port in COMMON_DEBUG_PORTS:
            if cls.probe_port(port):
                return f"http://127.0.0.1:{port}"

        proc_port = cls.find_port_from_processes()
        if proc_port:
            return f"http://127.0.0.1:{proc_port}"

        return None

    @classmethod
    def get_open_tabs(cls, cdp_base: str, timeout: float = 2.0) -> List[Dict[str, Any]]:
        """获取当前浏览器中所有打开的真实网页标签页 (包含友好的 1-based 序号、标题与 URL)"""
        url = f"{cdp_base.rstrip('/')}/json/list"
        tabs = []
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "JeikBrowserProbe/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw_list = json.loads(resp.read().decode("utf-8"))
                idx = 1
                for t in raw_list:
                    # 过滤后台页面和插件后台，只保留普通网页
                    if t.get("type") == "page":
                        tabs.append({
                            "index": idx,
                            "id": t.get("id"),
                            "title": t.get("title", "").strip() or "Untitled",
                            "url": t.get("url", ""),
                            "webSocketDebuggerUrl": t.get("webSocketDebuggerUrl")
                        })
                        idx += 1
        except Exception:
            pass
        return tabs

    @classmethod
    def match_tab_by_query(cls, tabs: List[Dict[str, Any]], query: str) -> Optional[Dict[str, Any]]:
        """
        根据用户输入的直观信息模糊匹配标签页：
        - 支持按序号: 如 '1', '2'
        - 支持按标题关键词: 如 '知乎', '阿里云', '双十一'
        - 支持按 URL 关键词: 如 'zhihu', 'github.com/myrepo'
        """
        if not tabs or not query:
            return None

        q = query.strip()

        # 1. 尝试按 1-based 序号精确匹配
        if q.isdigit():
            target_idx = int(q)
            for t in tabs:
                if t.get("index") == target_idx:
                    return t

        q_lower = q.lower()

        # 2. 尝试按页面标题 Title 模糊包含匹配
        for t in tabs:
            if q_lower in t.get("title", "").lower():
                return t

        # 3. 尝试按页面 URL 模糊包含匹配
        for t in tabs:
            if q_lower in t.get("url", "").lower():
                return t

        return None

    @classmethod
    def launch_debug_browser(
        cls,
        target_url: Optional[str] = None,
        port: int = 9222
    ) -> Tuple[bool, str]:
        """
        一键拉起带有远程调试端口的可视化浏览器窗口：
        - 专为普通用户登录、扫码与查看页面设计；
        - 使用独立的专属用户配置目录，不污染用户日常数据，但支持长期保留登录状态！
        """
        bin_path = find_system_browser()
        if not bin_path:
            return False, "未在系统中检测到 Google Chrome 或 Microsoft Edge 浏览器。"

        profile_dir = Path.home() / ".jeik" / "browser_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            bin_path,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={str(profile_dir)}",
            "--no-first-run",
            "--no-default-browser-check"
        ]
        if target_url:
            cmd.append(target_url)

        try:
            subprocess.Popen(cmd)
            # 等待片刻直至 CDP 端口就绪
            t0 = time.time()
            while time.time() - t0 < 4.0:
                if cls.probe_port(port):
                    return True, f"浏览器已就绪 (端口: {port})"
                time.sleep(0.2)
            return True, f"浏览器已启动，正在初始化配置..."
        except Exception as e:
            return False, f"启动浏览器失败: {e}"

# 全局默认浏览器管理器
browser_mgr = BrowserManager()
