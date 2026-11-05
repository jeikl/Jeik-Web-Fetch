"""本地浏览器槽位池（Engine Slot Pool）。

`jeik fetch` 每次都是独立进程，无法在进程内复用浏览器。原来只靠一个 8863
守护进程，冷启动竞态时后来的进程要等最前面的启动（最长 25s）。现在改为
**一组槽位**：

    anchor 槽：长 TTL（默认 3600s），常驻主力
    temp   槽：短 TTL（默认 1200s），并发突发时临时扩容

- 并发调用各取一个**独占槽**（一个浏览器 + 一个 profile），互不等待；
- 空闲到 TTL 由守护进程自己收浏览器退出；
- 上限按设备物理内存自动定（见 `resources.default_pool_max`）；
- 抢不到槽 `MAX` 时立刻退回「私有临时实例」，绝不排队。

环境变量：
  - `JEIK_POOL_ANCHOR_TTL`（默认 3600）
  - `JEIK_POOL_TEMP_TTL`（默认 1200）
  - `JEIK_POOL_MAX`（默认按内存自动：2G→2 / 4G→3 / 8G+→4）
  - `JEIK_POOL_LEASE_TTL`（默认 300，进程被强杀后租约过期时间）
  - `JEIK_POOL_DIR`（默认 ~/.jeik/pool）
  - `JEIK_NO_DAEMON_REUSE=1`：完全不用池（每次自建浏览器）
  - `JEIK_NO_AUTO_DAEMON=1`：只复用，不新建槽
"""

import os
import sys
import json
import time
import atexit
import socket
import asyncio
import subprocess
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse

import httpx

from .resources import default_pool_max, process_alive

DEFAULT_DAEMON_PORT = int(os.environ.get("JEIK_DAEMON_PORT", "8863"))
ANCHOR_TTL_SECS = int(
    os.environ.get("JEIK_POOL_ANCHOR_TTL")
    or os.environ.get("JEIK_DAEMON_IDLE_EXIT")
    or "3600"
)
TEMP_TTL_SECS = int(os.environ.get("JEIK_POOL_TEMP_TTL") or "1200")
POOL_MAX = int(os.environ.get("JEIK_POOL_MAX") or default_pool_max())
LEASE_TTL_SECS = int(os.environ.get("JEIK_POOL_LEASE_TTL") or "300")
SPAWN_WAIT_SECS = float(os.environ.get("JEIK_DAEMON_SPAWN_WAIT") or "20")

# 兼容旧名字（测试与外部调用仍在用）
AUTO_IDLE_EXIT_SECS = ANCHOR_TTL_SECS

POOL_DIR = os.path.expanduser(os.environ.get("JEIK_POOL_DIR") or "~/.jeik/pool")
SLOT_DIR = os.path.join(POOL_DIR, "slots")
LEASE_DIR = os.path.join(POOL_DIR, "leases")
PORT_DIR = os.path.join(POOL_DIR, "ports")

# 守护进程只允许回环地址：它没有鉴权，一旦绑到 0.0.0.0 就是公网开放代理。
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

_BORROWED_ENDPOINT: Optional[str] = None
_BORROWED_SLOT_PORT: Optional[int] = None
_ATEXIT_REGISTERED = False


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


def _spawn_daemon(port: int, idle_exit: int) -> Optional[int]:
    """拉起一个分离的守护进程，返回它的 PID（失败返回 None）。"""
    command = _spawn_command(port, idle_exit)
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            **kwargs,
        )
        return process.pid
    except Exception:
        return None


async def _probe(client: httpx.AsyncClient, base: str) -> Optional[str]:
    """探测 base 上是否有可用的 jeik 守护进程，返回它的 CDP 端点。"""
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


# ---------------------------------------------------------------------------
# 槽位注册表（一槽一文件 + 原子替换，避免多进程写同一个 JSON 互相覆盖）
# ---------------------------------------------------------------------------

def _ensure_dirs() -> None:
    for path in (SLOT_DIR, LEASE_DIR, PORT_DIR):
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            pass


def _slot_path(port: int) -> str:
    return os.path.join(SLOT_DIR, f"{port}.json")


def _lease_path(port: int) -> str:
    return os.path.join(LEASE_DIR, f"{port}.lease")


def _port_lock_path(port: int) -> str:
    return os.path.join(PORT_DIR, f"{port}.lock")


def _atomic_write_json(path: str, payload: Dict[str, Any]) -> None:
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.replace(tmp, path)


def read_slots() -> List[Dict[str, Any]]:
    _ensure_dirs()
    slots: List[Dict[str, Any]] = []
    try:
        names = os.listdir(SLOT_DIR)
    except OSError:
        return slots
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(SLOT_DIR, name), "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("port"):
            slots.append(data)
    slots.sort(key=lambda item: int(item["port"]))
    return slots


def _write_slot(port: int, pid: int, role: str, idle_exit: int) -> None:
    _ensure_dirs()
    now = time.time()
    _atomic_write_json(
        _slot_path(port),
        {
            "port": port,
            "pid": pid,
            "role": role,
            "idle_exit": idle_exit,
            "started_at": now,
            "last_used": now,
        },
    )


def _touch_slot(port: int) -> None:
    path = _slot_path(port)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return
    data["last_used"] = time.time()
    try:
        _atomic_write_json(path, data)
    except OSError:
        pass


def _drop_slot(port: int) -> None:
    for path in (_slot_path(port), _lease_path(port)):
        try:
            os.unlink(path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 租约：O_CREAT|O_EXCL 抢占，进程被强杀后按过期时间回收
# ---------------------------------------------------------------------------

def _lease_alive(port: int) -> bool:
    try:
        with open(_lease_path(port), "r", encoding="utf-8") as handle:
            parts = handle.read().split()
    except OSError:
        return False
    if len(parts) < 2:
        return False
    try:
        pid = int(parts[0])
        expires = float(parts[1])
    except ValueError:
        return False
    return time.time() < expires and process_alive(pid)


def _try_lease(port: int, holder_pid: int) -> bool:
    _ensure_dirs()
    path = _lease_path(port)
    payload = f"{holder_pid} {time.time() + LEASE_TTL_SECS}"

    for attempt in (1, 2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if _lease_alive(port):
                return False
            try:
                os.unlink(path)
            except OSError:
                pass
            continue
        except OSError:
            return False
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
        except OSError:
            pass
        return True
    return False


def _release_lease(port: int) -> None:
    try:
        os.unlink(_lease_path(port))
    except OSError:
        pass


def release(endpoint: Optional[str] = None) -> None:
    """归还本次借出的槽位（幂等）。

    注意：租约是按**守护进程端口**（8863…）记账的，而调用方手上是 CDP 端点
    （9527…），所以以借出时记录的槽位端口为准，不能拿 endpoint 反推。
    """
    global _BORROWED_SLOT_PORT, _BORROWED_ENDPOINT
    port = _BORROWED_SLOT_PORT
    if port is None and endpoint:
        port = _port_from_endpoint(endpoint)
    if port:
        _release_lease(port)
    _BORROWED_SLOT_PORT = None
    _BORROWED_ENDPOINT = None


def _port_from_endpoint(endpoint: Optional[str]) -> Optional[int]:
    if not endpoint:
        return None
    try:
        parsed = urlparse(endpoint)
        return int(parsed.port) if parsed.port else None
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# 端口选择
# ---------------------------------------------------------------------------

def _claim_port_lock(port: int) -> bool:
    """抢占「我负责拉起这个端口」的所有权，避免两个进程同时 spawn。"""
    _ensure_dirs()
    path = _port_lock_path(port)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        return True
    except FileExistsError:
        # 30 秒仍未释放，视为失败进程留下的锁
        try:
            if time.time() - os.path.getmtime(path) > 30:
                os.unlink(path)
                return _claim_port_lock(port)
        except OSError:
            pass
        return False
    except OSError:
        return False


def _drop_port_lock(port: int) -> None:
    try:
        os.unlink(_port_lock_path(port))
    except OSError:
        pass


def _pick_port(slots: List[Dict[str, Any]]) -> Optional[int]:
    used = {int(item["port"]) for item in slots}
    for offset in range(max(POOL_MAX, 1) + 2):
        port = DEFAULT_DAEMON_PORT + offset
        if port in used:
            continue
        if not _port_is_free(port):
            continue
        if _claim_port_lock(port):
            return port
    return None


# ---------------------------------------------------------------------------
# 清理：死槽、过期租约
# ---------------------------------------------------------------------------

def _janitor() -> None:
    for slot in read_slots():
        try:
            port = int(slot["port"])
        except (KeyError, TypeError, ValueError):
            continue
        pid = int(slot.get("pid") or 0)
        # pid<=0 = 健康托管槽（兼容手工启动的 serve，我们不知道它的 PID）
        if pid > 0 and not process_alive(pid):
            _drop_slot(port)
    _ensure_dirs()
    try:
        for name in os.listdir(LEASE_DIR):
            if not name.endswith(".lease"):
                continue
            try:
                port = int(name.split(".")[0])
            except ValueError:
                continue
            if not _lease_alive(port):
                _release_lease(port)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 取用 / 归还
# ---------------------------------------------------------------------------

async def _create_slot(
    client: httpx.AsyncClient, holder_pid: int
) -> Optional[tuple]:
    slots = read_slots()
    # anchor 只有不存在时才会被创建；其余并发都建 temp
    role = "anchor" if not any(item.get("role") == "anchor" for item in slots) else "temp"
    ttl = ANCHOR_TTL_SECS if role == "anchor" else TEMP_TTL_SECS

    if len(slots) >= max(POOL_MAX, 1):
        return None

    port = _pick_port(slots)
    if port is None:
        return None

    pid = _spawn_daemon(port, ttl)
    if not pid:
        _drop_port_lock(port)
        return None

    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + SPAWN_WAIT_SECS
    while time.monotonic() < deadline:
        endpoint = await _probe(client, base)
        if endpoint:
            _write_slot(port, pid, role, ttl)
            _drop_port_lock(port)
            _try_lease(port, holder_pid)
            return endpoint, port
        await asyncio.sleep(0.2)

    _drop_port_lock(port)
    return None


async def borrow() -> Optional[str]:
    """取一个空闲槽；没有就按角色新建；到上限返回 None（调用方走私有实例）。"""
    global _BORROWED_SLOT_PORT
    if os.environ.get("JEIK_NO_DAEMON_REUSE") == "1":
        return None

    # 安全防线：守护进程没有鉴权，绝不连接非回环地址
    if not is_loopback_url(_base()):
        return None

    _janitor()
    holder_pid = os.getpid()

    async with httpx.AsyncClient() as client:
        slots = read_slots()

        # 兼容：已有手工 `jeik serve` 但注册表为空时，先探测默认端口并收编
        if not any(int(item.get("port") or 0) == DEFAULT_DAEMON_PORT for item in slots):
            adopted = await _probe(client, _base())
            if adopted:
                _write_slot(DEFAULT_DAEMON_PORT, 0, "anchor", ANCHOR_TTL_SECS)
                slots = read_slots()

        for slot in slots:
            try:
                port = int(slot["port"])
            except (KeyError, TypeError, ValueError):
                continue
            pid = int(slot.get("pid") or 0)
            if pid > 0 and not process_alive(pid):
                _drop_slot(port)
                continue
            if not _try_lease(port, holder_pid):
                continue
            endpoint = await _probe(client, f"http://127.0.0.1:{port}")
            if endpoint:
                _touch_slot(port)
                _BORROWED_SLOT_PORT = port
                return endpoint
            _release_lease(port)
            _drop_slot(port)

        if os.environ.get("JEIK_NO_AUTO_DAEMON") == "1":
            return None

        created = await _create_slot(client, holder_pid)
        if created:
            endpoint, port = created
            _BORROWED_SLOT_PORT = port
            return endpoint
        return None


def _release_on_exit() -> None:
    release()


async def resolve_endpoint() -> Optional[str]:
    """进程级缓存：一次 CLI 调用只借一个槽，退出时归还。"""
    global _BORROWED_ENDPOINT, _ATEXIT_REGISTERED

    if _BORROWED_ENDPOINT:
        return _BORROWED_ENDPOINT

    endpoint = await borrow()
    if endpoint:
        _BORROWED_ENDPOINT = endpoint
        if not _ATEXIT_REGISTERED:
            _ATEXIT_REGISTERED = True
            try:
                atexit.register(_release_on_exit)
            except Exception:
                pass
    return endpoint


def reset_for_tests() -> None:
    global _BORROWED_ENDPOINT, _BORROWED_SLOT_PORT, _ATEXIT_REGISTERED
    _BORROWED_ENDPOINT = None
    _BORROWED_SLOT_PORT = None
    _ATEXIT_REGISTERED = False
