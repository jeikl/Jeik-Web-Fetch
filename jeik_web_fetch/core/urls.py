"""目标 URL 规范化：把用户输入的裸域名补全为可导航的绝对 URL。

`httpx` 与 CDP 的 `Page.navigate` 都只接受绝对 URL：用户输入 `www.baidu.com`
时前者抛 `UnsupportedProtocol`，后者直接返回 `Cannot navigate to invalid URL`，
浏览器停在 about:blank，最终被误报成「网络不可达 / ERR_CONNECTION_TIMED_OUT」。
"""

import ipaddress
import re
from typing import Optional
from urllib.parse import urlsplit

# 这些 scheme 的地址本身已完整，绝不能再补 `https://`
_OPAQUE_SCHEMES = (
    "about:",
    "data:",
    "blob:",
    "chrome:",
    "chrome-error:",
    "chrome-extension:",
    "edge:",
    "devtools:",
    "file:",
    "view-source:",
    "javascript:",
    "mailto:",
    "ftp:",
)

# 常见的内网/本机域名后缀：这些主机几乎只会说明文 HTTP
_PRIVATE_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp")


def _looks_like_private_host(host: str) -> bool:
    host = host.strip().strip(".").lower()
    if not host:
        return False
    if host == "localhost" or host.endswith(_PRIVATE_SUFFIXES):
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_private
    except ValueError:
        pass
    # 没有点号的主机名基本只能是内网机器名（example.com 一定带点）
    return "." not in host


def _host_of(authority: str) -> str:
    host = authority.rsplit("@", 1)[-1]
    if host.startswith("["):  # IPv6 字面量 [::1]:8080
        end = host.find("]")
        return host[: end + 1] if end != -1 else host
    return host.split(":", 1)[0]


def _port_of(authority: str) -> str:
    tail = authority.rsplit(":", 1)
    if len(tail) != 2:
        return ""
    return tail[1] if tail[1].isdigit() else ""


def _pick_scheme(host: str, port: str) -> str:
    """显式端口优先，其次按主机类型判断。"""
    if port == "80":
        return "http"
    if port == "443":
        return "https"
    return "http" if _looks_like_private_host(host) else "https"


def normalize_target_url(raw: Optional[str]) -> str:
    """补全缺失的 scheme；已是绝对 URL 的输入原样返回（幂等）。

    公网主机默认 https（现代站点几乎都 301 到 https），本机/内网与显式 :80
    默认 http（开发服务器极少配证书）。
    """
    url = (raw or "").strip()
    if not url:
        return url
    if "://" in url or url.lower().startswith(_OPAQUE_SCHEMES):
        return url
    if url.startswith("//"):  # 协议相对地址
        return f"https:{url}"

    authority = re.split(r"[/?#]", url, maxsplit=1)[0]
    scheme = _pick_scheme(_host_of(authority), _port_of(authority))
    return f"{scheme}://{url}"


def is_navigable_url(url: str) -> bool:
    """`Page.navigate` 能否接受这个地址（浏览器内部 scheme 放行）。"""
    try:
        parts = urlsplit(url or "")
    except ValueError:
        return False
    if parts.scheme in ("about", "data", "file", "view-source", "devtools", "chrome"):
        return True
    return parts.scheme in ("http", "https") and bool(parts.netloc)
