"""按需复用后台 `jeik serve` 实例（用户无需手动启动）。

`jeik fetch` 每次都是独立进程，无法在进程内复用浏览器。与其每次都冷启动
Chromium 并写一份 ~131MB 的 profile，不如：

1. 先探测本机是否已有 `jeik serve` 在跑；
2. 没有就以**分离进程**拉起一个（POSIX `start_new_session` / Windows
   `DETACHED_PROCESS`），不阻塞当前终端，也不随 CLI 退出而死；
3. 该守护进程空闲 `JEIK_DAEMON_IDLE_EXIT`（默认 3600s，即 1 小时）后自行退出，
   不会长期占用内存。

可通过环境变量关闭：
  - `JEIK_NO_DAEMON_REUSE=1`：完全不复用（每次自建浏览器）
  - `JEIK_NO_AUTO_DAEMON=1`：只复用，不自动拉起

相关环境变量：
  - `JEIK_DAEMON_URL`（默认 http://127.0.0.1:8863）
  - `JEIK_DAEMON_PORT`（默认 8863，自动拉起时用）
  - `JEIK_DAEMON_IDLE_EXIT`（默认 3600 秒，即 1 小时）
  - `JEIK_DAEMON_SPAWN_WAIT`（默认 25 秒，等待守护进程就绪的上限）
"""

import os
import sys
import time
import socket
import asyncio
import subprocess
from typing import Optional
from urllib.parse import urlparse

import httpx

DEFAULT_DAEMON_PORT = int(os.environ.get("JEIK_DAEMON_PORT", "8863"))
AUTO_IDLE_EXIT_SECS = int(os.environ.get("JEIK_DAEMON_IDLE_EXIT", "3600"))
SPAWN_WAIT_SECS = float(os.environ.get("JEIK_DAEMON_SPAWN_WAIT", "25"))

# 守护进程只允许回环地址：它没有鉴权，一旦绑到 0.0.0.0 就是公网开放代理。
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def is_loopback_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").strip("[]").lower()
    except Exception:
        return False
    return host in LOOPBACK_HOSTS


def _base() -> str:
    return os.environ.get(
        "JEIK_DAEMON_URL", f"http://127.0.0.1:{DEFAULT_DAEMON_PORT}"
    ).rstrip("/")


def _is_local_base(base: str) -> bool:
    return is_loopback_url(base)


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _spawn_command(port: int, idle_exit: int) -> list:
    args = [
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--idle-exit",
        str(idle_exit),
    ]
    if getattr(sys, "frozen", False):
        # PyInstaller 单文件：sys.executable 就是 jeik 自己
        return [sys.executable, *args]
    return [sys.executable, "-m", "jeik_web_fetch.cli", *args]


def _spawn_daemon(port: int, idle_exit: int) -> bool:
    command = _spawn_command(port, idle_exit)
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            **kwargs,
        )
        return True
    except Exception:
        return False


async def _probe(client: httpx.AsyncClient, base: str) -> Optional[str]:
    """探测 base 上是否已有可用的 jeik 守护进程，返回它的 CDP 端点。"""
    try:
        health = await client.get(f"{base}/health", timeout=0.8)
        if health.status_code != 200:
            return None
        pool_port = health.json().get("pool_port")
        if not pool_port:
            return None
        endpoint = f"http://127.0.0.1:{int(pool_port)}"
        version = await client.get(f"{endpoint}/json/version", timeout=0.8)
        return endpoint if version.status_code == 200 else None
    except Exception:
        return None


async def resolve_endpoint() -> Optional[str]:
    """返回可复用的 CDP 端点；必要时自动拉起一个后台守护进程。"""
    if os.environ.get("JEIK_NO_DAEMON_REUSE") == "1":
        return None

    base = _base()

    # 安全防线：守护进程没有鉴权，绝不允许连接到非回环地址（也就绝不会
    # 把浏览器能力暴露给公网，或反过来把公网地址当成内网守护）。
    if not is_loopback_url(base):
        return None

    async with httpx.AsyncClient() as client:
        existing = await _probe(client, base)
        if existing:
            return existing

        # 只对本机默认地址自动拉起；远端/自定义地址只做探测
        if not _is_local_base(base):
            return None
        if os.environ.get("JEIK_NO_AUTO_DAEMON") == "1":
            return None
        if not _port_is_free(DEFAULT_DAEMON_PORT):
            # 端口被别的程序占着，交给调用方退回「自建浏览器」
            return None
        if not _spawn_daemon(DEFAULT_DAEMON_PORT, AUTO_IDLE_EXIT_SECS):
            return None

        deadline = time.monotonic() + SPAWN_WAIT_SECS
        while time.monotonic() < deadline:
            endpoint = await _probe(client, base)
            if endpoint:
                return endpoint
            await asyncio.sleep(0.25)

    return None
