"""
Jeik-Web-Fetch: 工业级高性能通用网页抓取、多格式转换与工件存储引擎
完全基于原生无头架构与反爬探针绕过思想设计。
"""

from .core.models import OutputFormat, ScrapeOptions, ScrapeResult
from .core.engine import ScrapeEngine, default_engine
from .browser import find_system_browser
from .transformers.content import ContentTransformer
from .storage.manager import StorageManager, default_storage
from .api.routes import app
from .fetcher import jeik_fetch, fetch, fetch_markdown

__version__ = "1.1.1"
__all__ = [
    "OutputFormat",
    "ScrapeOptions",
    "ScrapeResult",
    "ScrapeEngine",
    "default_engine",
    "find_system_browser",
    "ContentTransformer",
    "StorageManager",
    "default_storage",
    "app",
    "jeik_fetch",
    "fetch",
    "fetch_markdown",
]
