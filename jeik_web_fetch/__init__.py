"""
Jeik-Web-Fetch: 高性能通用网页抓取与反反爬 Markdown 提取引擎
完全吸收 Firecrawl 生产级架构思想，原生无依赖运行。
"""

from .fetcher import firecrawl_fetch, fetch, fetch_markdown
from .browser import find_system_browser
from .converter import html_to_markdown

__version__ = "1.0.0"
__all__ = [
    "firecrawl_fetch",
    "fetch",
    "fetch_markdown",
    "find_system_browser",
    "html_to_markdown",
]
