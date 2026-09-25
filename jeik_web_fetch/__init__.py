"""
Jeik-Web-Fetch: 工业级高性能通用网页抓取、多格式转换与工件存储引擎
完全吸收 Firecrawl 生产级无头架构与反爬探针绕过思想。
"""

from .core.models import OutputFormat, ScrapeOptions, ScrapeResult
from .core.engine import ScrapeEngine, default_engine
from .browser import find_system_browser
from .transformers.content import ContentTransformer
from .storage.manager import StorageManager, default_storage
from .api.routes import app
from .fetcher import firecrawl_fetch, fetch, fetch_markdown

__version__ = "1.1.0"
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
    "firecrawl_fetch",
    "fetch",
    "fetch_markdown",
]
