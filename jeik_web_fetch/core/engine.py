import os
import sys
import time
import json
import atexit
import base64
import asyncio
import tempfile
import shutil
import threading
import subprocess
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

import httpx
import websockets

from .models import ScrapeOptions, ScrapeResult, OutputFormat
from .dns import DNSResolverConfig
from .classifier import ContentQualityClassifier
from .cookies import CookieHelper, default_cookie_store
from .browser_mgr import browser_mgr
from .updater import updater
from ..browser import find_system_browser
from ..transformers.content import ContentTransformer
from ..storage.manager import default_storage

# CDP 就绪等待上限(秒)。必须按「墙钟」而不是「重试次数」计时：端口尚未监听时
# httpx 会立即抛 ConnectError，固定 40 次循环在负载高的机器上 4 秒就会放弃，
# 远不够 snap / 冷启动拉起一个 Chromium。
DEFAULT_BROWSER_START_TIMEOUT_SECS = 45.0


def _browser_start_timeout() -> float:
    raw = os.environ.get("JEIK_BROWSER_START_TIMEOUT")
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass
    return DEFAULT_BROWSER_START_TIMEOUT_SECS


# ---------------------------------------------------------------------------
# 临时 profile 生命周期：创建 → owner 标记 → 回收 → 遗留清扫
#
# 历史问题：每次抓取都会 mkdtemp 一个完整 Chromium profile（Windows 上约
# 131MB）。正常退出会删除，但下面两种情况会留下永不清理的目录：
#   1. 进程被强杀（工具超时 / Ctrl-C / OOM）；
#   2. Windows 上 `shutil.rmtree(ignore_errors=True)` 在 Chrome 子进程还没
#      释放文件句柄时静默失败。
# 于是 %TEMP%\jeik_engine_* 会一直累积，最终吃满磁盘。
# ---------------------------------------------------------------------------
_PROFILE_PREFIX = "jeik_engine_"
_OWNER_SUFFIX = ".owner"
_LIVE_PROFILES: Dict[str, Any] = {}
_PROFILE_LOCK = threading.Lock()
_ATEXIT_REGISTERED = False


def default_persistent_profile_dir() -> str:
    """
    常驻服务（jeik serve）使用的固定 profile 目录，跨请求、跨重启复用。

    目录会按服务端口区分：多个 `jeik serve`（不同端口）若共用同一个
    user-data-dir，Chromium 会因目录被占用而启动失败。
    """
    override = os.environ.get("JEIK_ENGINE_PROFILE_DIR")
    if override:
        return os.path.expanduser(override)
    port = os.environ.get("JEIK_SERVE_PORT", "").strip()
    suffix = f"_{port}" if port else ""
    return os.path.join(os.path.expanduser("~"), ".jeik", f"engine_profile{suffix}")


def _owner_path(profile_dir: str) -> str:
    return profile_dir + _OWNER_SUFFIX


def _write_owner(profile_dir: str, pid: int) -> None:
    try:
        with open(_owner_path(profile_dir), "w", encoding="utf-8") as handle:
            handle.write(str(pid))
    except OSError:
        pass


def _read_owner(profile_dir: str) -> Optional[int]:
    try:
        with open(_owner_path(profile_dir), "r", encoding="utf-8") as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def _process_alive(pid: int) -> bool:
    """跨平台判断 pid 是否仍存活（用于识别遗留 profile 的真正归属）。"""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            # PROCESS_QUERY_LIMITED_INFORMATION
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            try:
                code = ctypes.c_ulong()
                if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return False
                return code.value == 259  # STILL_ACTIVE
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _unlink_quietly(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _remove_tree(path: str, attempts: int = 4) -> bool:
    """带重试地删除目录：Windows 上目录句柄释放有延迟。"""
    for index in range(attempts):
        if not os.path.exists(path):
            _unlink_quietly(_owner_path(path))
            return True
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            _unlink_quietly(_owner_path(path))
            return True
        time.sleep(0.25 * (index + 1))
    return not os.path.exists(path)


def _kill_process_tree(process) -> None:
    """结束浏览器及其子进程，并回收僵尸。"""
    if process is None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                capture_output=True,
            )
        else:
            process.kill()
    except Exception:
        pass
    try:
        process.wait(timeout=5)
    except Exception:
        pass


def _snap_private_tmp_mirrors(profile_dir: str) -> List[str]:
    """
    snap 会把应用的 `/tmp` 重定向到 `<tmp>/snap-private-tmp/<snap>/tmp/`。

    实测：Chromium 通过 snap 运行时，`--user-data-dir=/tmp/jeik_engine_x` 里的
    135MB 真实数据全部落在 snap 私有目录，宿主侧 `/tmp/jeik_engine_x` 只剩一个
    4KB 空壳。只删宿主路径就是「看起来删干净了，磁盘一点没少」。
    """
    name = os.path.basename(profile_dir.rstrip("/\\"))
    root = os.path.join(tempfile.gettempdir(), "snap-private-tmp")
    mirrors: List[str] = []
    try:
        apps = os.listdir(root)
    except OSError:
        return mirrors
    for app in apps:
        candidate = os.path.join(root, app, "tmp", name)
        if os.path.isdir(candidate):
            mirrors.append(candidate)
    return mirrors


def _remove_profile(profile_dir: str) -> bool:
    """删除 profile 本体及其 snap 私有目录镜像。"""
    removed = _remove_tree(profile_dir)
    for mirror in _snap_private_tmp_mirrors(profile_dir):
        _remove_tree(mirror)
    return removed


def _profile_pids(profile_dir: str) -> List[int]:
    """返回仍在使用该 profile 的进程 PID（硬杀后的兜底回收用）。"""
    needle = f"--user-data-dir={profile_dir}"
    pids: List[int] = []

    if os.name == "nt":
        escaped = needle.replace("'", "''")
        script = (
            "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and "
            f"$_.CommandLine.Contains('{escaped}') }} | "
            "Select-Object -ExpandProperty ProcessId"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=20,
            )
        except Exception:
            return pids
        for token in result.stdout.split():
            if token.isdigit():
                pids.append(int(token))
        return pids

    encoded = needle.encode()
    try:
        entries = os.listdir("/proc")
    except OSError:
        return pids
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == os.getpid():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as handle:
                raw = handle.read()
        except OSError:
            continue
        if encoded in raw:
            pids.append(pid)
    return pids


def _kill_processes(pid_list: List[int]) -> None:
    for pid in pid_list:
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(pid)],
                    capture_output=True,
                )
            else:
                os.kill(pid, 9)
        except Exception:
            pass


def _profile_mtime(profile_dir: str) -> float:
    newest = 0.0
    for candidate in [profile_dir] + _snap_private_tmp_mirrors(profile_dir):
        try:
            newest = max(newest, os.path.getmtime(candidate))
        except OSError:
            pass
    return newest


def _profile_candidates() -> List[str]:
    """列出宿主临时目录与 snap 私有临时目录里的所有 profile 目录名。"""
    root = tempfile.gettempdir()
    names = set()

    try:
        for entry in os.listdir(root):
            if entry.startswith(_PROFILE_PREFIX) and not entry.endswith(_OWNER_SUFFIX):
                if os.path.isdir(os.path.join(root, entry)):
                    names.add(entry)
    except OSError:
        pass

    snap_root = os.path.join(root, "snap-private-tmp")
    try:
        for app in os.listdir(snap_root):
            app_tmp = os.path.join(snap_root, app, "tmp")
            try:
                for entry in os.listdir(app_tmp):
                    if entry.startswith(_PROFILE_PREFIX) and os.path.isdir(
                        os.path.join(app_tmp, entry)
                    ):
                        names.add(entry)
            except OSError:
                continue
    except OSError:
        pass

    return sorted(names)


def sweep_stale_profiles(min_age_secs: float = 3600.0) -> int:
    """
    回收遗留 profile（含 snap 私有目录镜像）以及仍挂在它们上面的孤儿浏览器。

    - owner PID 已死：先杀掉仍在用它的浏览器，再删目录；
    - 没有 owner 标记（旧版本创建）：在用时绝不删，否则只有超过
      `min_age_secs` 未修改才回收。
    """
    root = tempfile.gettempdir()
    removed = 0
    now = time.time()

    for name in _profile_candidates():
        host_path = os.path.join(root, name)
        with _PROFILE_LOCK:
            if host_path in _LIVE_PROFILES:
                continue

        owner = _read_owner(host_path)
        if owner is not None:
            if _process_alive(owner):
                continue
            # 宿主进程已死，但浏览器可能还活着（被 SIGKILL / OOM 时）
            _kill_processes(_profile_pids(host_path))
        else:
            # 旧版本没有 owner 标记：只要还有进程在用就不能碰
            if _profile_pids(host_path):
                continue
            mtime = _profile_mtime(host_path)
            if not mtime:
                continue
            if now - mtime < min_age_secs:
                continue

        if _remove_profile(host_path):
            removed += 1

    return removed


def _register_live_profile(path: str, process) -> None:
    with _PROFILE_LOCK:
        _LIVE_PROFILES[path] = process


def _unregister_live_profile(path: str) -> None:
    with _PROFILE_LOCK:
        _LIVE_PROFILES.pop(path, None)


def _reap_all_live_profiles_at_exit() -> None:
    """进程退出前的最后一道保险（覆盖 sys.exit / 未捕获异常）。"""
    with _PROFILE_LOCK:
        entries = list(_LIVE_PROFILES.items())
    for path, process in entries:
        _kill_process_tree(process)
        _remove_profile(path)


def _ensure_exit_hook() -> None:
    global _ATEXIT_REGISTERED
    if _ATEXIT_REGISTERED:
        return
    _ATEXIT_REGISTERED = True
    try:
        atexit.register(_reap_all_live_profiles_at_exit)
    except Exception:
        pass


class ScrapeEngine:
    """
    Jeik-Web-Fetch 核心渲染引擎 (异步 I/O + CPU 密集型多线程混合架构)：
    - 常驻 Chromium 连接池管理多 Tab 隔离会话
    - 内置专用 ThreadPoolExecutor 线程池，解决 Python GIL 下巨型 HTML/DOM 转换阻塞事件循环的性能痛点
    - 结合 ContentTransformer 进行多线程并行提取
    - 结合 StorageManager 自动保存到本地临时文件或指定工程目录
    """
    def __init__(
        self,
        port: int = 9527,
        thread_workers: Optional[int] = None,
        profile_dir: Optional[str] = None,
    ):
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self.tmp_dir: Optional[str] = None
        # None = 一次性实例：每次 mkdtemp 一个临时 profile，关停时删除（CLI / 技能调用）
        # 非 None = 常驻实例：复用同一个目录，不删、不重建（jeik serve）
        self.profile_dir: Optional[str] = os.path.expanduser(profile_dir) if profile_dir else None
        self.bin_path: str = ""
        self._lock = asyncio.Lock()
        # 针对 CPU 密集的 HTML/DOM/正则/Markdown 转换分配专用多线程池
        self.executor = ThreadPoolExecutor(max_workers=thread_workers or min(32, (os.cpu_count() or 4) * 2))

    def use_persistent_profile(self, path: Optional[str] = None) -> None:
        """
        切换到「常驻复用」模式：

        - profile 固定落在 `~/.jeik/engine_profile`（可用 JEIK_ENGINE_PROFILE_DIR 覆盖）；
        - 跨请求、跨重启复用同一份，不再每重启一次就留下一份 131MB 临时目录；
        - 保留磁盘缓存，因为常驻浏览器会反复访问同类站点，缓存确实有收益。

        一次性调用（`jeik fetch`）不要用这个：临时 profile 用完即删才干净。
        """
        self.profile_dir = os.path.expanduser(path) if path else default_persistent_profile_dir()

    def _cache_flags(self) -> List[str]:
        """
        一次性实例关掉磁盘缓存：profile 用完即删，缓存不会被下一次复用，
        却会让单次落盘从 ~131MB 降到 ~20-30MB。常驻实例保留缓存（跨请求有收益）。
        """
        if self.profile_dir:
            return []
        return [
            "--disk-cache-size=1",
            "--disable-application-cache",
            "--disable-gpu-shader-disk-cache",
            "--disable-component-update",
            "--no-pings",
        ]

    async def ensure_started(self, dns: Optional[str] = None):
        async with self._lock:
            if self.process and self.process.poll() is None:
                return

            # 上一轮若启动失败，可能残留未回收的进程与临时 profile，先清理干净。
            self._reap_browser()

            self.bin_path = find_system_browser()
            if not self.bin_path:
                raise RuntimeError("未检测到本地 Chrome / Edge / Chromium，无法启动渲染引擎。")

            # 动态检测并分配可用端口，彻底避免多进程并发调用时端口冲突
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", self.port))
                except OSError:
                    s.bind(("127.0.0.1", 0))
                    self.port = s.getsockname()[1]

            # 常驻实例复用固定 profile；一次性实例用临时目录并在关停时删除。
            if self.profile_dir:
                os.makedirs(self.profile_dir, exist_ok=True)
                user_data_dir = self.profile_dir
                self.tmp_dir = None
            else:
                user_data_dir = tempfile.mkdtemp(prefix=_PROFILE_PREFIX)
                self.tmp_dir = user_data_dir
                _write_owner(self.tmp_dir, os.getpid())
            _ensure_exit_hook()

            # 顺手回收历史遗留 profile（被强杀的进程 / Windows 句柄未释放）
            try:
                sweep_stale_profiles()
            except Exception:
                pass
            dns_args = DNSResolverConfig.build_chrome_args(dns)
            cmd = [
                self.bin_path,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--window-size=1920,1080",
                "--disable-blink-features=AutomationControlled",
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "--disable-background-networking",
                "--disable-sync",
                "--disable-default-apps",
                "--disable-extensions",
                "--mute-audio",
                "--no-first-run",
                "--no-default-browser-check",
                f"--remote-debugging-port={self.port}",
                f"--user-data-dir={user_data_dir}",
            ] + self._cache_flags() + dns_args + ["about:blank"]
            self.process = subprocess.Popen(cmd, stderr=subprocess.DEVNULL)
            if self.tmp_dir:
                _register_live_profile(self.tmp_dir, self.process)

            started = False
            try:
                deadline = time.monotonic() + _browser_start_timeout()
                async with httpx.AsyncClient() as client:
                    while time.monotonic() < deadline:
                        try:
                            res = await client.get(f"http://127.0.0.1:{self.port}/json/version", timeout=0.5)
                            if res.status_code == 200:
                                started = True
                                return
                        except Exception:
                            pass
                        await asyncio.sleep(0.1)
            finally:
                # 关键修复：启动失败时浏览器是我们唯一 owner。此处不回收，进程就会
                # 变成孤儿常驻(每次失败泄漏一个完整 Chromium，数百 MB)，而且外层
                # supervisor 往往只能杀到本进程的 cgroup / 进程组，够不着它。
                if not started:
                    self._reap_browser()
            raise TimeoutError("Browser pool initialization timed out.")

    def _reap_browser(self) -> None:
        """
        回收本引擎拉起的浏览器进程并删除其临时 profile。

        必须在**所有**失败路径调用：`ensure_started` 抛出前、`stop()` 关闭时。
        只 kill 不 wait 会留下僵尸进程，因此这里显式 reap。
        """
        process = self.process
        self.process = None
        _kill_process_tree(process)
        if self.tmp_dir:
            profile = self.tmp_dir
            self.tmp_dir = None
            _unregister_live_profile(profile)
            # Windows 上 Chrome 子进程可能还要几毫秒才释放句柄；_remove_tree 内置重试，
            # 并且要连 snap 私有临时目录里的镜像一起删。
            _remove_profile(profile)

    async def stop(self):
        async with self._lock:
            self._reap_browser()

    def _resolve_cdp_endpoint(self, options: ScrapeOptions) -> Optional[str]:
        """
        解析外部 CDP 浏览器端点：
        - 优先级 1: options.cdp_endpoint (形如 http://127.0.0.1:9222 或 127.0.0.1:9222)
        - 优先级 2: options.browser_port (形如 9222)
        - 优先级 3: 环境变量 JEIK_CDP_ENDPOINT / JEIK_BROWSER_PORT
        - 优先级 4: 当用户指定了 options.attach_tab 或 options.tab，或未指定端口时，全自动智能探测本地运行中的浏览器！
        若未提供且未探测到，则返回 None (表示使用内置的无头 Chromium 常驻池)
        """
        endpoint = options.cdp_endpoint or os.environ.get("JEIK_CDP_ENDPOINT")
        if not endpoint:
            port = options.browser_port or os.environ.get("JEIK_BROWSER_PORT")
            if port:
                endpoint = f"http://127.0.0.1:{port}"

        # 若用户启用了 attach_tab 或指定了 tab，尝试全自动探测本地运行中的浏览器实例
        if not endpoint and (options.attach_tab or options.tab):
            discovered = browser_mgr.auto_discover_cdp_endpoint()
            if discovered:
                endpoint = discovered

        if endpoint:
            endpoint = str(endpoint).strip()
            if not endpoint.startswith("http://") and not endpoint.startswith("https://"):
                endpoint = f"http://{endpoint}"
            return endpoint.rstrip("/")
        return None

    async def _resolve_daemon_endpoint(self) -> Optional[str]:
        """
        复用（必要时自动拉起）后台 `jeik serve` 的常驻浏览器。

        CLI 每次调用都是独立进程，进程内无法复用；但守护进程本来就长期持有一个
        Chromium。接到它的 CDP 端点上，新 tab 用完即关，就完全不需要再创建一份
        131MB 的临时 profile —— 既不会累积，也省掉每次的写盘+删除。

        没有在跑的守护进程时，`daemon_client` 会自动以分离进程拉起一个（空闲
        自动退出），所以用户不需要手动 `jeik serve`。
        """
        from .daemon_client import resolve_endpoint

        try:
            return await resolve_endpoint()
        except Exception:
            return None

    def _resolve_cookies_and_headers(
        self, options: ScrapeOptions
    ) -> tuple[List[Dict[str, Any]], Dict[str, str]]:
        """
        解析并合并显式 Cookie、文件 Cookie、持久化 Cookie 与自定义 Header
        返回: (normalized_cookies, extra_headers)
        """
        raw_cookies_list = []

        # 1. 从 cookie_file 读取
        if options.cookie_file:
            try:
                raw_cookies_list.extend(CookieHelper.load_from_file(options.cookie_file))
            except Exception:
                pass

        # 2. 从 options.cookies 解析
        if options.cookies:
            raw_cookies_list.extend(CookieHelper.normalize_cookies(options.cookies, target_url=options.url))

        # 3. 若未显式传入任何 Cookie，自动检索对应域名的全局持久化登录态
        if not raw_cookies_list:
            saved_cookies = default_cookie_store.get_for_url_or_domain(options.url)
            if saved_cookies:
                raw_cookies_list.extend(saved_cookies)

        normalized_cookies = CookieHelper.normalize_cookies(raw_cookies_list, target_url=options.url)

        # 4. 解析并合并 headers
        headers = dict(options.headers or {})
        if normalized_cookies:
            cookie_header_val = CookieHelper.to_cookie_header(normalized_cookies)
            if cookie_header_val and "cookie" not in [k.lower() for k in headers]:
                headers["Cookie"] = cookie_header_val

        return normalized_cookies, headers

    async def _try_fast_fetch(
        self, options: ScrapeOptions, extra_headers: Optional[Dict[str, str]] = None
    ) -> Optional[ScrapeResult]:
        """
        本质性内容质量裁决器（零域名白名单）：
        - 对任何未知 URL 先以毫秒级 HTTP 探针试探（包含登录态 Cookie 与 Headers）；
        - 根据“文本密度、语义结构、反爬/SPA 骨架特征”由 ContentQualityClassifier 进行本质裁决；
        - 只有真实内容充沛且非骨架屏的页面才会直接输出，绝无误判；
        - 一旦属于 SPA 空壳或风控拦截，毫秒级无感降级至无头浏览器！
        """
        t0 = time.time()
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            }
            if extra_headers:
                headers.update(extra_headers)

            async with httpx.AsyncClient(follow_redirects=True, timeout=6.0, verify=False) as client:
                res = await client.get(options.url, headers=headers)
                
                # 本质特征裁决
                is_valid, reason = ContentQualityClassifier.evaluate_html(res.text, res.status_code)
                if not is_valid:
                    return None

                raw_html = res.text

                # 快速并行转换
                loop = asyncio.get_running_loop()
                transformed = await loop.run_in_executor(
                    self.executor,
                    ContentTransformer.transform,
                    raw_html,
                    options.formats,
                    options.only_main_content,
                    None,
                    options.url,
                    options.include_sidebar,
                    None
                )

                md = transformed.get("markdown", "")
                if len(md.strip()) < 200:
                    return None

                saved = {}
                if options.save_to_file:
                    if "markdown" in transformed:
                        saved["markdown"] = default_storage.save_content(options.url, transformed["markdown"], "md", options.output_dir)
                    if "html" in transformed:
                        saved["html"] = default_storage.save_content(options.url, transformed["html"], "html", options.output_dir)
                    if "rawHtml" in transformed:
                        saved["rawHtml"] = default_storage.save_content(options.url, transformed["rawHtml"], "raw.html", options.output_dir)
                    if "text" in transformed:
                        saved["text"] = default_storage.save_content(options.url, transformed["text"], "txt", options.output_dir)

                return ScrapeResult(
                    success=True,
                    url=options.url,
                    markdown=transformed.get("markdown"),
                    html=transformed.get("html"),
                    rawHtml=transformed.get("rawHtml"),
                    text=transformed.get("text"),
                    links=transformed.get("links"),
                    metadata=transformed.get("metadata", {}),
                    saved_files=saved,
                    elapsed_seconds=round(time.time() - t0, 2)
                )
        except Exception:
            return None

    def _is_shared_browser(self, external_cdp: Optional[str]) -> bool:
        """
        当前浏览器是否被“共享”使用。

        共享意味着可能同时有多个抓取并发跑：
          - 复用了外部/守护进程的浏览器（external_cdp 非空）；
          - 常驻实例（profile_dir 非空，`jeik serve`）。
        共享时绝不能清空整站 Cookie，否则会把并发中其它抓取的登录态一并抹掉。
        """
        return external_cdp is not None or self.profile_dir is not None

    async def scrape_url(self, options: ScrapeOptions) -> ScrapeResult:
        updater.enter_task()
        target_id = None
        cdp_base = None
        should_close_tab = False
        shared_engine = False
        t0 = time.time()
        try:
            # 模式策略自适配 (--fast / --common / --complex)
            from .models import FetchMode
            if options.mode == FetchMode.COMMON:
                options.headless = True
            elif options.mode == FetchMode.COMPLEX:
                options.headless = True
                options.deep_explore = True
                if options.waitFor < 3.5:
                    options.waitFor = 3.5

            # 解析外部现有浏览器端点（若指定，则直接接入该运行中的浏览器实例）
            external_cdp = self._resolve_cdp_endpoint(options)
            cdp_base = external_cdp or f"http://127.0.0.1:{self.port}"

            # 解析并收集 Cookies 与自定义 Headers (含自动全局持久化登录态匹配)
            cookies, extra_headers = self._resolve_cookies_and_headers(options)

            # 若指定了接管标签页但未找到任何运行中的浏览器实例，给出针对非技术用户的极简指引
            if (options.attach_tab or options.tab) and not external_cdp:
                return ScrapeResult(
                    success=False,
                    url=options.url,
                    error=(
                        "未检测到正在运行且已开启调试通道的浏览器。\n\n"
                        "💡 针对非技术人员的 1 秒极简解决方案:\n"
                        "  1. 在终端运行: `jeik open <网址>` (系统会自动弹出已配置好的 Chrome/Edge 浏览器窗口)；\n"
                        "  2. 在弹出的浏览器中正常查看网页或扫码登录；\n"
                        "  3. 再次运行: `jeik fetch --active-tab` 或 `jeik fetch --tab \"关键词\"` 即可瞬间自动提取！"
                    ),
                    elapsed_seconds=round(time.time() - t0, 2)
                )

            # 若未指定外部浏览器且未开启 attach_tab/tab/headless，优先尝试 Tier 1 极速探针
            if not external_cdp and not options.attach_tab and not options.tab and not options.headless:
                fast_res = await self._try_fast_fetch(options, extra_headers=extra_headers)
                if fast_res:
                    return fast_res

            # Tier 2: 降级自愈升级至无头浏览器 / 连接现有运行中的浏览器实例
            if not external_cdp:
                # CLI（非常驻实例）优先复用正在运行的 jeik serve 浏览器：
                # 不新建 profile，也就没有写盘/删除的拖抖与累积。
                if not self.profile_dir and not options.attach_tab and not options.tab:
                    external_cdp = await self._resolve_daemon_endpoint()
                if external_cdp:
                    cdp_base = external_cdp
                else:
                    await self.ensure_started(dns=options.dns)
                    cdp_base = f"http://127.0.0.1:{self.port}"

            # 共享浏览器（守护进程 / 常驻 profile）里可能同时有多个抓取：
            # 此时清空整站 Cookie 会互相干扰，所以只在独占的临时实例里做。
            shared_engine = self._is_shared_browser(external_cdp)

            async with httpx.AsyncClient() as client:
                # 连通性校验
                try:
                    ver_res = await client.get(f"{cdp_base}/json/version", timeout=3.0)
                    if ver_res.status_code != 200:
                        raise ConnectionError(f"HTTP {ver_res.status_code}")
                except Exception as conn_err:
                    err_msg = (
                        f"无法连接到正在运行的浏览器实例 ({cdp_base}): {conn_err}。\n"
                        f"提示: 请运行 `jeik open` 一键启动已配置好调试通道的浏览器。"
                    )
                    return ScrapeResult(
                        success=False,
                        url=options.url,
                        error=err_msg,
                        elapsed_seconds=round(time.time() - t0, 2)
                    )

                if (options.attach_tab or options.tab) and external_cdp:
                    # 接管外部浏览器当前活跃或指定的标签页 (不新建也不关闭 Tab)
                    tabs = browser_mgr.get_open_tabs(cdp_base, timeout=3.0)
                    if not tabs:
                        return ScrapeResult(
                            success=False,
                            url=options.url,
                            error="在正在运行的浏览器实例中未找到任何打开的网页标签页 (Page Tab)。",
                            elapsed_seconds=round(time.time() - t0, 2)
                        )
                    matched = None
                    if options.tab:
                        matched = browser_mgr.match_tab_by_query(tabs, options.tab)
                        if not matched:
                            tabs_summary = "\n".join([f"  [{t['index']}] {t['title']} ({t['url']})" for t in tabs[:10]])
                            return ScrapeResult(
                                success=False,
                                url=options.url,
                                error=(
                                    f"未在运行的浏览器中找到匹配 '{options.tab}' 的标签页。\n"
                                    f"当前打开的标签页列表:\n{tabs_summary}\n\n"
                                    f"提示: 您可以直接使用标签序号或标题关键词，例如: `jeik fetch --tab 1` 或 `jeik fetch --tab \"{tabs[0]['title'][:6]}\"`"
                                ),
                                elapsed_seconds=round(time.time() - t0, 2)
                            )
                    else:
                        # 优先匹配当前正在访问 options.url 的标签页，否则直接接管最顶层活跃标签页
                        matched = next((t for t in tabs if options.url and options.url in t.get("url", "")), tabs[0])

                    target_id = matched["id"]
                    ws_url = matched["webSocketDebuggerUrl"]
                    should_close_tab = False
                    # 动态反向同步实际标签页 URL
                    if matched.get("url") and (not options.url or options.url == "about:blank"):
                        options.url = matched["url"]
                else:
                    # 在浏览器中预先创建干净空白页，以便在页面导航前完整注入反爬脚本与登录态 Cookie
                    new_tab = await client.put(f"{cdp_base}/json/new?about:blank", timeout=10)
                    tab_info = new_tab.json()
                    target_id = tab_info["id"]
                    ws_url = tab_info["webSocketDebuggerUrl"]
                    should_close_tab = True

            async with websockets.connect(ws_url, max_size=50 * 1024 * 1024) as ws:
                # 1. 开启 Network 与 Page 域
                await ws.send(json.dumps({"id": 101, "method": "Network.enable"}))
                await ws.send(json.dumps({"id": 102, "method": "Page.enable"}))

                # 若是新建的独立临时 Tab，清理上一轮可能残留的临时 Cookie，确保请求与请求之间的会话天然隔离
                # 只用我们自己的浏览器时才清空整站 Cookie；复用守护进程的常驻
                # 浏览器时不能清它的会话。
                if should_close_tab and not shared_engine:
                    await ws.send(json.dumps({"id": 100, "method": "Network.clearBrowserCookies"}))

                # 2. 注入反爬特征 (页面导航前注册生命周期脚本 + 当前运行时求值)
                stealth_js = """
                (() => {
                    try {
                        if (navigator.webdriver) {
                            delete Object.getPrototypeOf(navigator).webdriver;
                        }
                        if (!navigator.plugins || navigator.plugins.length === 0) {
                            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                        }
                        Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en-US', 'en'] });
                        if (!window.chrome) {
                            window.chrome = {
                                app: { isInstalled: false },
                                runtime: { PlatformOs: { WIN: 'win' } }
                            };
                        }
                    } catch (e) {}
                })()
                """
                await ws.send(json.dumps({"id": 103, "method": "Page.addScriptToEvaluateOnNewDocument", "params": {"source": stealth_js}}))
                await ws.send(json.dumps({"id": 104, "method": "Runtime.evaluate", "params": {"expression": stealth_js}}))

                # 3. 注入登录态 Cookies
                cdp_cookies = CookieHelper.to_cdp_cookies(cookies, options.url)
                if cdp_cookies:
                    await ws.send(json.dumps({
                        "id": 105,
                        "method": "Network.setCookies",
                        "params": {"cookies": cdp_cookies}
                    }))

                # 4. 注入额外 HTTP 请求头 (如 Authorization 等)
                if extra_headers:
                    await ws.send(json.dumps({
                        "id": 106,
                        "method": "Network.setExtraHTTPHeaders",
                        "params": {"headers": extra_headers}
                    }))

                # 5. 导航到目标网页 (如果是接管已打开的活跃页面且未强制跳转，则跳过 navigate)
                if not options.attach_tab or (options.url and options.url != "about:blank"):
                    await ws.send(json.dumps({
                        "id": 107,
                        "method": "Page.navigate",
                        "params": {"url": options.url}
                    }))

                # 6. 动态智能内容就绪侦听 (Dynamic Content Settle)
                # 替代固定的 sleep 傻等，只要页面出现实质文字且脱离 Loading 状态，立即提前进入提取！
                poll_js = r"""
                (() => {
                    const text = document.body ? document.body.innerText : "";
                    const hasSubstance = text.length > 500 && !text.includes("Loading...");
                    return hasSubstance;
                })()
                """
                settled = False
                max_polls = int(options.waitFor * 10)
                for _ in range(max_polls):
                    await asyncio.sleep(0.1)
                    await ws.send(json.dumps({
                        "id": 888,
                        "method": "Runtime.evaluate",
                        "params": {"expression": poll_js, "returnByValue": True}
                    }))
                    try:
                        # 兼容过滤其他异步事件广播，精确寻找 id=888 的响应
                        for _ in range(4):
                            msg_str = await asyncio.wait_for(ws.recv(), timeout=0.5)
                            msg_obj = json.loads(msg_str)
                            if msg_obj.get("id") == 888:
                                if msg_obj.get("result", {}).get("result", {}).get("value") is True:
                                    settled = True
                                break
                    except (asyncio.TimeoutError, Exception):
                        pass
                    if settled:
                        break

                # 4. 深度交互探索 (若开启 deep_explore)
                dom_extract_js = r"""
                (async () => {
                    const extractedDrawers = [];

                    // 1. 全容器平滑步进滚动（同时覆盖 window、main 以及所有内部滚动容器，彻底触发异步请求与懒加载）
                    const scrollables = [
                        window,
                        ...Array.from(document.querySelectorAll("main, [class*='content'], [class*='container'], [class*='scroll'], .mdxContent"))
                            .filter(el => el && el.scrollHeight > el.clientHeight + 100)
                    ];
                    for (const sc of scrollables) {
                        const isWin = sc === window;
                        const maxH = isWin ? document.body.scrollHeight : sc.scrollHeight;
                        for (let y = 0; y < Math.min(maxH, 25000); y += 1200) {
                            if (isWin) window.scrollTo(0, y);
                            else sc.scrollTop = y;
                            await new Promise(r => setTimeout(r, 40));
                        }
                        if (isWin) window.scrollTo(0, 0);
                        else sc.scrollTop = 0;
                    }
                    await new Promise(r => setTimeout(r, 400));

                    // 2. 递归多轮深度折叠展开 (Recursive Multi-pass Unfolding)
                    // 彻底展开：原生 details、展开子属性、Body参数、响应参数、aria-expanded="false" 按钮
                    for (let pass = 0; pass < 3; pass++) {
                        document.querySelectorAll("details:not([open])").forEach(d => d.setAttribute("open", "true"));
                        document.querySelectorAll("[aria-expanded='false']").forEach(btn => {
                            try { btn.click(); } catch(e) {}
                        });
                        const toggles = Array.from(document.querySelectorAll("button, [role='button'], span, div, a")).filter(el => {
                            const txt = (el.innerText || "").trim();
                            return /^(展开|展开子属性|显示全部|更多|View more|Expand|Show more)$/i.test(txt) && el.children.length <= 1;
                        });
                        if (toggles.length === 0) break;
                        for (const btn of toggles.slice(0, 50)) {
                            try {
                                btn.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
                            } catch(e) {}
                        }
                        await new Promise(r => setTimeout(r, 200));
                    }

                    // 3. 侧边栏折叠目录全量展开 (Sidebar Accordion Unfolding - Mintlify / Docusaurus / VitePress)
                    const sidebarContainers = Array.from(document.querySelectorAll("aside, nav[class*='sticky'], [class*='sidebar'], [class*='docSidebar'], nav[aria-label*='sidebar' i]"));
                    for (const sb of sidebarContainers) {
                        const expandBtns = Array.from(sb.querySelectorAll("button, [role='button'], [aria-expanded='false']"));
                        for (const b of expandBtns.slice(0, 30)) {
                            try { b.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })); } catch(e) {}
                        }
                    }
                    await new Promise(r => setTimeout(r, 200));

                    // 4. 扫描并提取通用活动细则/规则抽屉 (抽屉探针)
                    const ruleLinks = Array.from(document.querySelectorAll("a, button, span")).filter(
                        e => e.innerText && /活动规则|详细细则|规则说明|使用须知/i.test(e.innerText.trim()) && e.innerText.trim().length <= 10
                    );
                    for (let i = 0; i < Math.min(ruleLinks.length, 10); i++) {
                        const btn = ruleLinks[i];
                        try {
                            btn.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
                            await new Promise(r => setTimeout(r, 350));
                            const drawer = document.querySelector(".next-drawer, [role=\"dialog\"], .next-dialog, .ant-modal, .ant-drawer");
                            if (drawer && drawer.innerText) {
                                const txt = drawer.innerText.trim();
                                if (txt && !extractedDrawers.includes(txt)) {
                                    extractedDrawers.push(txt);
                                }
                            }
                            const close = document.querySelector(".next-drawer-close, .next-dialog-close, [aria-label=\"Close\"], .ant-modal-close");
                            if (close) {
                                close.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
                                await new Promise(r => setTimeout(r, 100));
                            }
                        } catch(e) {}
                    }

                    // 4. 场景与用例选项卡全量捕获 (基础调用, 流式响应, 函数调用, 联网搜索, 图像输入, 深度思考, 结构化输出...)
                    const scenarioNames = [
                        "基础调用", "流式响应", "函数调用", "联网搜索", "图像输入", "音频输入", "视频输入",
                        "深度思考", "结构化输出", "基础文本对话", "流式输出", "图片理解", "Function Calling"
                    ];
                    const scenarioTabs = Array.from(document.querySelectorAll("button, [role='tab'], span, div")).filter(el => {
                        const txt = (el.innerText || "").trim();
                        return scenarioNames.includes(txt) && el.children.length === 0;
                    });
                    const uniqueScenarios = [];
                    const seenScenarioNames = new Set();
                    for (const st of scenarioTabs) {
                        const txt = st.innerText.trim();
                        if (!seenScenarioNames.has(txt)) {
                            seenScenarioNames.add(txt);
                            uniqueScenarios.push({ name: txt, el: st });
                        }
                    }

                    const harvestedScenarios = [];
                    if (uniqueScenarios.length > 0) {
                        for (const sc of uniqueScenarios.slice(0, 8)) {
                            try {
                                sc.el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
                                await new Promise(r => setTimeout(r, 200));
                            } catch(e) {}
                            const pres = Array.from(document.querySelectorAll("pre")).map(p => p.innerText.trim()).filter(s => s.length > 10);
                            const reqCode = pres.find(c => c.includes("curl ") || c.includes("curl\n") || c.includes("--location") || c.includes("--header") || c.includes("requests.") || c.includes("axios.") || c.includes("http.Client") || c.includes("OkHttpClient")) ||
                                            pres.find(c => c.split("\n").length >= 3 && (c.includes("POST") || c.includes("GET"))) ||
                                            pres[0] || "";
                            const resJson = pres.find(c => c !== reqCode && (c.startsWith("{") || c.startsWith("[") || c.includes("\"id\":") || c.includes("\"choices\":"))) || (pres.length > 1 ? pres[1] : "");
                            harvestedScenarios.push({
                                scenario: sc.name,
                                requestCode: reqCode,
                                responseJson: resJson
                            });
                        }
                        // 重置回首个场景
                        try {
                            uniqueScenarios[0].el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
                            await new Promise(r => setTimeout(r, 100));
                        } catch(e) {}
                    }

                    // 5. 多语言代码 Tab 遍历与全量采集 (cURL, Python, Go, Node.js, Java 等)
                    const langCodeSamples = [];
                    const codeTabs = Array.from(document.querySelectorAll("[role='tab'], .openapi-tabs__tab, .tabs__item, button")).filter(t => {
                        const txt = (t.innerText || "").trim().toUpperCase();
                        return ["CURL", "PYTHON", "GO", "NODEJS", "JAVA", "PHP", "RUBY", "C#", "JAVASCRIPT", "TYPESCRIPT", "RUST", "BASH", "SHELL"].includes(txt);
                    });
                    const seenLangs = new Set();
                    for (const t of codeTabs) {
                        const lang = t.innerText.trim();
                        if (seenLangs.has(lang)) continue;
                        seenLangs.add(lang);
                        try {
                            t.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
                            await new Promise(r => setTimeout(r, 200));
                            const rightPanel = document.querySelector(".openapi-right-panel__container, [class*='right-panel'], [class*='code-panel']") || document.body;
                            const pres = Array.from(rightPanel.querySelectorAll("pre"));
                            const activePre = pres[pres.length - 1];
                            if (activePre && activePre.innerText.trim().length > 10) {
                                langCodeSamples.push({
                                    language: lang,
                                    code: activePre.innerText.trim()
                                });
                            }
                        } catch(e) {}
                    }
                    if (codeTabs.length > 0) {
                        try {
                            codeTabs[0].dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
                            await new Promise(r => setTimeout(r, 100));
                        } catch(e) {}
                    }

                    // 6. 遍历对象分支与变体 Tab (OneOf / AnyOf: 如 Developer message, System message, User message...)
                    const variantTabs = Array.from(document.querySelectorAll("button, [role='tab'], span")).filter(el => {
                        const txt = (el.innerText || "").trim();
                        return /^(Developer message|System message|User message|Assistant message|Tool message|Text content|Array of content parts)/i.test(txt) && el.children.length === 0;
                    });
                    for (const vt of variantTabs.slice(0, 10)) {
                        try {
                            vt.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
                            await new Promise(r => setTimeout(r, 150));
                        } catch(e) {}
                    }

                    // 7. Monaco Editor 内存模型还原 (杜绝长代码截断)
                    if (window.monaco && window.monaco.editor) {
                        const models = window.monaco.editor.getModels();
                        const editors = document.querySelectorAll(".monaco-editor");
                        editors.forEach((ed, idx) => {
                            const model = models[idx] || (models.length === 1 ? models[0] : null);
                            if (model) {
                                const pre = document.createElement("pre");
                                const code = document.createElement("code");
                                code.textContent = model.getValue();
                                pre.appendChild(code);
                                ed.replaceWith(pre);
                            }
                        });
                    }

                    // 8. CodeMirror 还原
                    document.querySelectorAll(".CodeMirror").forEach(cm => {
                        if (cm.CodeMirror) {
                            const pre = document.createElement("pre");
                            const code = document.createElement("code");
                            code.textContent = cm.CodeMirror.getValue();
                            pre.appendChild(code);
                            cm.replaceWith(pre);
                        }
                    });

                    // 8.5 支持 Ant Design Tree / 钉钉及阿里系文档树结构 (DingTalk, Alibaba, etc.)
                    const antTree = document.querySelector(".ant-tree, [class*='treeMenu'], [class*='layout-sider']");
                    if (antTree) {
                        const treeNodes = Array.from(antTree.querySelectorAll(".ant-tree-treenode"));
                        if (treeNodes.length >= 3) {
                            treeNodes.forEach(node => {
                                if (node.querySelectorAll("a").length === 0) {
                                    const spanWithId = node.querySelector("[id]");
                                    const titleSpan = node.querySelector(".ant-tree-title") || node;
                                    const text = titleSpan.innerText.trim();
                                    if (spanWithId && spanWithId.id && text) {
                                        const slug = spanWithId.id;
                                        const a = document.createElement("a");
                                        const isDingTalk = location.hostname.includes("dingtalk.com");
                                        a.href = isDingTalk ? ("/document/development/" + slug) : slug;
                                        a.innerText = text;
                                        node.appendChild(a);
                                    }
                                }
                            });
                        }
                    }

                    // 9. 通用侧边栏精确定位 (包含 Mintlify, Docusaurus, Ark, MiMo, VitePress, DingTalk 几何/类名双模探测)
                    let asideEl = null;
                    const asideCandidates = Array.from(document.querySelectorAll("aside, [class*='layout-sider'], [class*='treeMenu'], .ant-tree, nav[class*='sticky'], [class*='sidebar'], [class*='docSidebar'], nav[aria-label*='sidebar' i], nav[class*='menu']"));
                    asideEl = asideCandidates.find(el => el.querySelectorAll("a").length >= 2);
                    if (!asideEl) {
                        const leftNavs = Array.from(document.querySelectorAll("div, nav, section")).filter(el => {
                            const rect = el.getBoundingClientRect();
                            return rect.left < 80 && rect.top < 300 && rect.width > 120 && rect.width < 420 && el.querySelectorAll("a").length >= 3 && el.querySelectorAll("a").length < 300;
                        });
                        if (leftNavs.length > 0) {
                            asideEl = leftNavs.sort((a, b) => b.querySelectorAll("a").length - a.querySelectorAll("a").length)[0];
                        }
                    }

                    // 10. 捕获底部分页导航 (Previous / Next)
                    const paginationEl = document.querySelector(".pagination-nav, nav[aria-label*='pagination' i], nav[aria-label*='Pages' i], [class*='pagination']");

                    // 11. 全站联系方式与社区支持探测 (Contacts & Community Support)
                    const contactsData = [];
                    const seenContactHrefs = new Set();
                    const contactKeywords = /联系|contact|support|email|mail|discord|github|twitter|wechat|微信|telegram|反馈|feedback/i;
                    Array.from(document.querySelectorAll("a")).forEach(a => {
                        const text = (a.innerText || "").trim();
                        const href = a.getAttribute("href") || "";
                        if (!href || href === "#" || href.startsWith("javascript:")) return;
                        const lowerH = href.toLowerCase();
                        const isContact = contactKeywords.test(text) || lowerH.startsWith("mailto:") || lowerH.includes("contact") || lowerH.includes("discord.gg") || lowerH.includes("twitter.com") || lowerH.includes("github.com");
                        if (isContact && !seenContactHrefs.has(href)) {
                            seenContactHrefs.add(href);
                            contactsData.push({ text: text || (lowerH.startsWith("mailto:") ? href.substring(7) : href), href });
                        }
                    });
                    const footerEl = document.querySelector("footer, [class*='footer']");
                    const footerText = footerEl ? footerEl.innerText.trim() : "";

                    // 12. 顶栏菜单与全局导航 (Header Navigation - 包含顶栏下拉与二级Sub-nav)
                    const headerLinks = [];
                    const seenNavHrefs = new Set();
                    Array.from(document.querySelectorAll("header a, nav a, [class*='navbar'] a, [class*='nav-tab'] a, [class*='header'] a, a")).forEach(a => {
                        const text = (a.innerText || "").trim();
                        const href = a.getAttribute("href");
                        if (!text || !href || href === "#" || href.startsWith("javascript:")) return;
                        const rect = a.getBoundingClientRect();
                        if (rect.top < 120 && rect.height > 0 && !seenNavHrefs.has(href)) {
                            seenNavHrefs.add(href);
                            headerLinks.push({ text, href });
                        }
                    });

                    return {
                        html: document.querySelector("main") ? document.querySelector("main").outerHTML : document.body.outerHTML,
                        drawers: extractedDrawers.join("\n\n"),
                        sidebar: asideEl ? asideEl.outerHTML : "",
                        pagination: paginationEl ? paginationEl.outerHTML : "",
                        code_samples: langCodeSamples,
                        scenarios: harvestedScenarios,
                        contacts: contactsData,
                        footer_text: footerText,
                        header_links: headerLinks
                    };
                })()
                """
                await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": dom_extract_js, "awaitPromise": True, "returnByValue": True}}))

                # 接收完整响应
                raw_html = ""
                drawers_text = ""
                sidebar_html = ""
                pagination_html = ""
                code_samples = []
                scenarios = []
                contacts_data = []
                footer_text = ""
                header_links = []
                while True:
                    msg_str = await asyncio.wait_for(ws.recv(), timeout=options.timeout)
                    msg = json.loads(msg_str)
                    if msg.get("id") == 1:
                        val = msg.get("result", {}).get("result", {}).get("value", {})
                        if isinstance(val, dict):
                            raw_html = val.get("html", "")
                            drawers_text = val.get("drawers", "")
                            sidebar_html = val.get("sidebar", "")
                            pagination_html = val.get("pagination", "")
                            code_samples = val.get("code_samples", [])
                            scenarios = val.get("scenarios", [])
                            contacts_data = val.get("contacts", [])
                            footer_text = val.get("footer_text", "")
                            header_links = val.get("header_links", [])
                        else:
                            raw_html = str(val)
                        break

            # 多格式转换 (移交给 CPU 密集型多线程池并行处理，完全释放主事件循环)
            loop = asyncio.get_running_loop()
            transformed = await loop.run_in_executor(
                self.executor,
                ContentTransformer.transform,
                raw_html,
                options.formats,
                options.only_main_content,
                drawers_text,
                options.url,
                options.include_sidebar,
                sidebar_html,
                code_samples,
                pagination_html,
                scenarios,
                contacts_data,
                footer_text,
                header_links
            )

            # 严格错误校验：如果提取出的 Markdown 与纯文本全为空，且 HTML 包含网络阻断错误
            markdown_content = transformed.get("markdown", "")
            if not markdown_content.strip():
                # 检查浏览器是否遇到了网络连接重置或超时错误 (如 GFW 阻断、DNS 不可达)
                error_match = None
                if "net::ERR_" in raw_html:
                    import re
                    m = re.search(r'net::ERR_[A-Z_]+', raw_html)
                    if m:
                        error_match = m.group(0)
                
                err_msg = (
                    f"Navigation failed or connection was reset ({error_match or 'net::ERR_CONNECTION_TIMED_OUT'}). "
                    f"Target host is unreachable from your network environment."
                )
                return ScrapeResult(
                    success=False,
                    url=options.url,
                    error=err_msg,
                    elapsed_seconds=round(time.time() - t0, 2)
                )

            # 持久化到临时/本地文件（如果指定）
            saved = {}
            if options.save_to_file:
                if "markdown" in transformed:
                    p = default_storage.save_content(options.url, transformed["markdown"], "md", options.output_dir)
                    saved["markdown"] = p
                if "html" in transformed:
                    p = default_storage.save_content(options.url, transformed["html"], "html", options.output_dir)
                    saved["html"] = p
                if "rawHtml" in transformed:
                    p = default_storage.save_content(options.url, transformed["rawHtml"], "raw.html", options.output_dir)
                    saved["rawHtml"] = p
                if "text" in transformed:
                    p = default_storage.save_content(options.url, transformed["text"], "txt", options.output_dir)
                    saved["text"] = p

            return ScrapeResult(
                success=True,
                url=options.url,
                markdown=transformed.get("markdown"),
                html=transformed.get("html"),
                rawHtml=transformed.get("rawHtml"),
                text=transformed.get("text"),
                links=transformed.get("links"),
                drawers=drawers_text if drawers_text else None,
                metadata=transformed.get("metadata", {}),
                saved_files=saved,
                elapsed_seconds=round(time.time() - t0, 2)
            )

        except Exception as e:
            return ScrapeResult(
                success=False,
                url=options.url,
                error=str(e),
                elapsed_seconds=round(time.time() - t0, 2)
            )

        finally:
            updater.leave_task()
            if should_close_tab and target_id and cdp_base:
                try:
                    async with httpx.AsyncClient() as client:
                        await client.get(f"{cdp_base}/json/close/{target_id}", timeout=2)
                except Exception:
                    pass

    async def scrape_urls_concurrent(
        self,
        options_list: List[ScrapeOptions],
        max_workers: int = 4
    ) -> List[ScrapeResult]:
        """
        高并发多线程/多协程并行遍历：
        - 结合 asyncio.Semaphore 限制最大并行 Tab 数量，防止内存与连接过载
        - 在常驻 Chromium 池中并发开辟多个隔离 Target 标签页同时执行
        """
        await self.ensure_started()
        sem = asyncio.Semaphore(max_workers)

        async def worker(opt: ScrapeOptions) -> ScrapeResult:
            async with sem:
                return await self.scrape_url(opt)

        tasks = [worker(opt) for opt in options_list]
        return await asyncio.gather(*tasks)

# 全局默认引擎实例
default_engine = ScrapeEngine()
