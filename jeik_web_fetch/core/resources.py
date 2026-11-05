"""设备资源探测：自动决定浏览器槽位上限。

槽位上限直接决定峰值内存（每个浏览器约 150–390MB PSS），因此按设备物理内存
分档，而不是写死一个值：

    物理内存        槽位上限
    <= 1.5 GB       1
    <= 2.5 GB       2
    <= 6 GB         3
    其余            4

注意：Linux 容器里 `/proc/meminfo` 反映的是**宿主机**内存，必须再和 cgroup
限额取较小值，否则在 512MB 的容器里会误判成 32GB。
"""

import os
import sys
import ctypes
import subprocess
from typing import Optional

_MEMORY_CACHE: Optional[float] = None


def _linux_cgroup_limit_bytes() -> Optional[int]:
    # cgroup v2
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                raw = handle.read().strip()
        except OSError:
            continue
        if not raw or raw == "max":
            continue
        try:
            value = int(raw)
        except ValueError:
            continue
        # 未设限时内核会给一个极大的哨兵值
        if 0 < value < (1 << 60):
            return value
    return None


def _linux_meminfo_bytes() -> Optional[int]:
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    return int(parts[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _windows_total_bytes() -> Optional[int]:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    try:
        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return int(status.ullTotalPhys)
    except Exception:
        return None


def _macos_total_bytes() -> Optional[int]:
    try:
        result = subprocess.run(
            ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5
        )
        return int(result.stdout.strip())
    except Exception:
        return None


def total_memory_gb() -> float:
    """设备可用物理内存（GB）。容器内取 cgroup 限额与物理内存的较小值。"""
    global _MEMORY_CACHE
    if _MEMORY_CACHE is not None:
        return _MEMORY_CACHE

    total: Optional[int] = None
    if sys.platform.startswith("win"):
        total = _windows_total_bytes()
    elif sys.platform == "darwin":
        total = _macos_total_bytes()
    else:
        physical = _linux_meminfo_bytes()
        limit = _linux_cgroup_limit_bytes()
        candidates = [value for value in (physical, limit) if value]
        total = min(candidates) if candidates else None

    if not total:
        _MEMORY_CACHE = 0.0
    else:
        _MEMORY_CACHE = round(total / (1024 ** 3), 2)
    return _MEMORY_CACHE


def default_pool_max() -> int:
    """按物理内存推荐槽位上限。"""
    size = total_memory_gb()
    if size <= 0:
        return 2  # 探测失败时保守取值
    if size <= 1.5:
        return 1
    if size <= 2.5:
        return 2
    if size <= 6.0:
        return 3
    return 4


def process_alive(pid: int) -> bool:
    """跨平台判断 pid 是否仍存活。"""
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        try:
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


def _reset_cache_for_tests() -> None:
    global _MEMORY_CACHE
    _MEMORY_CACHE = None
