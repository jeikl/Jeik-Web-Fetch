import os
import re
import sys
import time
import json
import ssl
import asyncio
import threading
import subprocess
import urllib.error
import urllib.request
from typing import Optional, Tuple
from pathlib import Path

GITHUB_REPO = os.environ.get("JEIK_REPO", "jeikl/Jeik-Web-Fetch")
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# 不经过 API 的兜底通道：github.com 的 releases/latest 会 302 到 /releases/tag/<v>，
# 而 releases/latest/download/<asset> 始终指向最新发行包 —— 两者都不吃 API 限流。
RELEASE_LATEST_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"
RELEASE_LATEST_DOWNLOAD = f"https://github.com/{GITHUB_REPO}/releases/latest/download"

# GitHub API 超时与重试：默认 8s 在慢网络/代理环境里太短，失败一次就直接
# 报“无法连接”，让人完全看不出是 TLS、限流还是 DNS 问题。
GITHUB_API_TIMEOUT_SECS = float(os.environ.get("JEIK_UPDATE_TIMEOUT", "20"))
GITHUB_API_RETRIES = 3


def _ssl_context() -> ssl.SSLContext:
    """
    优先使用 certifi 的 CA 包。

    PyInstaller 单文件在 Windows 上常常找不到系统根证书目录，`urlopen` 会直接
    抛 CERTIFICATE_VERIFY_FAILED；而 httpx/requests 因为有 certifi 反而正常。
    """
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _api_headers() -> dict:
    """
    GitHub API 请求头。

    匿名请求只有 60 次/小时（按出口 IP 计），共享 IP/办公室网络几下就耗尽并返回
    403；带上 token 则抬到 5000 次/小时。任选 GITHUB_TOKEN 或 GH_TOKEN。
    """
    headers = {
        "User-Agent": "jeik-web-fetch-updater",
        "Accept": "application/vnd.github+json",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class AutoUpdater:
    """
    Background Autonomous Updater & Hot-Upgrader:
    - Checks GitHub Releases for updates every 10 minutes (600s).
    - Ensures non-destructive upgrades: waits until active tasks == 0 before upgrading.
    - Seamlessly replaces binary or local editable files and restarts.
    """
    def __init__(self, check_interval_sec: int = 600):
        self.check_interval_sec = check_interval_sec
        self.active_tasks: int = 0
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False

    # 最近一次版本探测的真实失败原因；None 表示成功。
    last_error: Optional[str] = None

    def enter_task(self):
        """Register that a scrape task has started."""
        with self._lock:
            self.active_tasks += 1

    def leave_task(self):
        """Register that a scrape task has ended."""
        with self._lock:
            self.active_tasks = max(0, self.active_tasks - 1)

    def is_idle(self) -> bool:
        """Check whether the engine is currently idle."""
        with self._lock:
            return self.active_tasks == 0

    @classmethod
    def get_current_version(cls) -> str:
        try:
            from . import __version__
            return __version__.lstrip("v")
        except Exception:
            return "1.0.0"

    @classmethod
    def _pick_asset(cls, assets: list, plat: str, arch: str) -> Optional[str]:
        """
        选择当前平台/架构对应的发行包下载地址。

        旧实现只判断 `"windows" in name and ".exe" in name`，在 Windows arm64
        机器上会错拿 x64 包；这里补上「架构精确匹配优先」的筛子。
        """
        exact: Optional[str] = None
        loose: Optional[str] = None
        for asset in assets:
            name = str(asset.get("name", "")).lower()
            url = asset.get("browser_download_url")
            if not name or not url:
                continue

            if plat.startswith("win"):
                if not (("windows" in name or "win" in name) and name.endswith(".exe")):
                    continue
            elif plat.startswith("linux"):
                if "linux" not in name:
                    continue
            elif plat.startswith("darwin"):
                if "darwin" not in name and "macos" not in name:
                    continue
            else:
                continue

            if arch in name:
                exact = exact or url
            else:
                loose = loose or url

        return exact or loose

    @staticmethod
    def _describe_http_error(exc: urllib.error.HTTPError) -> str:
        """把 HTTPError 翻译成一句能直接指导用户的话（限流会带上重置时间）。"""
        reason = f"HTTP {exc.code} {exc.reason}"
        headers = getattr(exc, "headers", None)
        if headers is not None:
            remaining = headers.get("x-ratelimit-remaining")
            reset = headers.get("x-ratelimit-reset")
            if remaining == "0" and reset and str(reset).isdigit():
                when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(reset)))
                reason += f" (API rate limit exhausted, resets at {when})"
            retry_after = headers.get("retry-after")
            if retry_after:
                reason += f" (retry-after {retry_after}s)"
        try:
            body = exc.read().decode("utf-8", "replace").strip()
        except Exception:
            body = ""
        if body:
            try:
                message = json.loads(body).get("message")
            except Exception:
                message = body[:200]
            if message:
                reason += f": {message}"
        return reason

    @classmethod
    def _fallback_asset_name(cls, plat: str, arch: str) -> str:
        if plat.startswith("win"):
            return f"jeik-web-fetch-windows-{arch}.exe"
        if plat.startswith("darwin"):
            return f"jeik-web-fetch-darwin-{arch}"
        return f"jeik-web-fetch-linux-{arch}"

    @classmethod
    def _check_via_release_page(cls) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        完全不经过 GitHub API 的兜底探测。

        `https://github.com/<repo>/releases/latest` 会 302 到 `/releases/tag/<v>`，
        读最终 URL 即可拿到版本号；发行包用 `releases/latest/download/<asset>` 直链，
        始终指向最新一版。这条路不受匿名 API 60 次/小时的限流影响。
        """
        import platform

        arch = "arm64" if "arm" in platform.machine().lower() or "aarch" in platform.machine().lower() else "x64"
        try:
            request = urllib.request.Request(
                RELEASE_LATEST_PAGE,
                headers={"User-Agent": "jeik-web-fetch-updater", "Accept": "text/html"},
                method="HEAD",
            )
            with urllib.request.urlopen(
                request, timeout=GITHUB_API_TIMEOUT_SECS, context=_ssl_context()
            ) as response:
                final_url = response.geturl()
        except Exception as exc:
            return None, None, f"{type(exc).__name__}: {exc}"

        match = re.search(r"/releases/tag/([^/?#]+)", final_url or "")
        if not match:
            return None, None, f"unexpected redirect target: {final_url}"

        version = match.group(1).lstrip("v")
        asset = f"{RELEASE_LATEST_DOWNLOAD}/{cls._fallback_asset_name(sys.platform, arch)}"
        return version, asset, None

    @classmethod
    def check_remote_version(cls) -> Tuple[Optional[str], Optional[str]]:
        """
        Query GitHub for the latest release version and download URL.
        Returns: (remote_version, download_url)

        先走 API；API 被限流/拦截时自动退到不依赖 API 的 releases 页面通道。
        两者都失败时，把真实原因写进 `AutoUpdater.last_error`。
        """
        cls.last_error = None
        import platform

        plat = sys.platform
        arch = "arm64" if "arm" in platform.machine().lower() or "aarch" in platform.machine().lower() else "x64"

        last_reason: Optional[str] = None
        for attempt in range(1, GITHUB_API_RETRIES + 1):
            try:
                request = urllib.request.Request(LATEST_RELEASE_API, headers=_api_headers())
                with urllib.request.urlopen(
                    request, timeout=GITHUB_API_TIMEOUT_SECS, context=_ssl_context()
                ) as response:
                    if response.status != 200:
                        last_reason = f"HTTP {response.status}"
                    else:
                        data = json.loads(response.read().decode("utf-8"))
                        tag_name = str(data.get("tag_name", "")).lstrip("v")
                        if not tag_name:
                            last_reason = "release response has no tag_name"
                            break
                        return tag_name, cls._pick_asset(data.get("assets", []), plat, arch)
            except urllib.error.HTTPError as exc:
                last_reason = cls._describe_http_error(exc)
                # 403/429 是限流或拒绝，重试没有意义
                if exc.code in (403, 404, 429):
                    break
            except Exception as exc:  # SSL / DNS / 超时 / 解析
                last_reason = f"{type(exc).__name__}: {exc}"

            if attempt < GITHUB_API_RETRIES:
                time.sleep(1.5 * attempt)

        api_reason = last_reason or "unknown error"

        # API 被限流（典型：匿名 60 次/小时耗尽 → 403）时，走不依赖 API 的页面通道
        version, asset, fallback_reason = cls._check_via_release_page()
        if version:
            cls.last_error = None
            return version, asset

        cls.last_error = f"{api_reason}; fallback: {fallback_reason or 'unknown error'}"
        return None, None

    @classmethod
    def is_newer(cls, remote: str, current: str) -> bool:
        def parse(v: str):
            return [int(x) for x in re.sub(r"[^\d.]", "", v).split(".") if x.isdigit()]
        try:
            return parse(remote) > parse(current)
        except Exception:
            return remote != current

    def perform_upgrade_and_restart(self, direct_cli: bool = False):
        """Wait until idle, execute the upgrade, and restart smoothly."""
        current_ver = self.get_current_version()
        remote_ver, asset_url = self.check_remote_version()

        if not remote_ver:
            if direct_cli:
                print("[-] Could not reach GitHub releases or release not found.", file=sys.stderr)
                if self.last_error:
                    print(f"    Reason : {self.last_error}", file=sys.stderr)
                print(f"    URL    : {LATEST_RELEASE_API}", file=sys.stderr)
                print(
                    "    Hint   : 若处于代理/受限网络，先设置 HTTPS_PROXY 再重试（Windows: "
                    "$env:HTTPS_PROXY='http://127.0.0.1:7890'；Linux/macOS: export HTTPS_PROXY=...）；"
                    "也可以直接从 Releases 页面手动下载对应平台安装包。",
                    file=sys.stderr,
                )
            return False

        if not self.is_newer(remote_ver, current_ver) and not direct_cli:
            return False

        # Wait until current scraping tasks finish
        if direct_cli:
            print(f"[*] Upgrading jeik-web-fetch: {current_ver} -> {remote_ver}...")
        while not self.is_idle():
            if direct_cli:
                print("[*] Waiting for active scraping tasks to finish before applying upgrade...")
            time.sleep(1.0)

        # Execute online installer script
        try:
            if sys.platform.startswith("win"):
                install_cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "$env:JEIK_LANG='en'; irm https://raw.githubusercontent.com/jeikl/Jeik-Web-Fetch/main/scripts/install.ps1 | iex"]
            else:
                install_cmd = ["/bin/bash", "-c", "export JEIK_LANG='en'; curl -fsSL https://raw.githubusercontent.com/jeikl/Jeik-Web-Fetch/main/scripts/install.sh | bash"]
            
            res = subprocess.run(install_cmd, capture_output=True, text=True)
            if res.returncode == 0:
                if direct_cli:
                    print(f"[✔] Upgrade complete! Successfully upgraded to v{remote_ver}.")
                return True
            else:
                if direct_cli:
                    print(f"[-] Upgrade failed (exit {res.returncode}).", file=sys.stderr)
                    detail = (res.stderr or res.stdout or "").strip()
                    if detail:
                        print(detail, file=sys.stderr)
                    if asset_url:
                        # 安装脚本依赖 raw.githubusercontent.com，它比 API 更容易被墙；
                        # 直接给出发行包地址，用户可手动下载替换。
                        print(f"[*] Fallback: download the release asset directly:\n    {asset_url}", file=sys.stderr)
                return False
        except Exception as e:
            if direct_cli:
                print(f"[-] Upgrade error: {e}", file=sys.stderr)
                if asset_url:
                    print(f"[*] Fallback: download the release asset directly:\n    {asset_url}", file=sys.stderr)
            return False

    def start_background_daemon(self):
        """Start non-blocking daemon thread to auto-check and upgrade every 10 minutes."""
        if self._running:
            return
        self._running = True

        def _loop():
            while self._running:
                try:
                    time.sleep(self.check_interval_sec)
                    if not self._running:
                        break
                    current_ver = self.get_current_version()
                    remote_ver, _ = self.check_remote_version()
                    if remote_ver and self.is_newer(remote_ver, current_ver):
                        # Upgrade in background when idle
                        self.perform_upgrade_and_restart(direct_cli=False)
                except Exception:
                    pass

        self._thread = threading.Thread(target=_loop, daemon=True, name="jeik-updater-daemon")
        self._thread.start()

updater = AutoUpdater()
