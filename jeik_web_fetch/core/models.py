from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class OutputFormat(str, Enum):
    MARKDOWN = "markdown"
    HTML = "html"
    RAW_HTML = "rawHtml"
    TEXT = "text"
    LINKS = "links"
    JSON = "json"

class ScrapeOptions(BaseModel):
    url: str = Field(..., description="目标网页绝对 URL")
    formats: List[OutputFormat] = Field(default=[OutputFormat.MARKDOWN], description="输出格式列表")
    waitFor: float = Field(default=3.5, description="页面渲染与异步 API 缓冲等待时间 (秒)")
    timeout: float = Field(default=25.0, description="请求超时时间 (秒)")
    save_to_file: bool = Field(default=False, description="是否自动持久化到本地/临时文件")
    output_dir: Optional[str] = Field(default=None, description="自定义存储目录")
    only_main_content: bool = Field(default=True, description="是否仅保留主体内容（清洗导航/页脚）")

class ScrapeResult(BaseModel):
    success: bool
    url: str
    markdown: Optional[str] = None
    html: Optional[str] = None
    rawHtml: Optional[str] = None
    text: Optional[str] = None
    links: Optional[List[Dict[str, str]]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    saved_files: Dict[str, str] = Field(default_factory=dict, description="已保存的本地/临时文件路径映射")
    error: Optional[str] = None
    elapsed_seconds: float = 0.0
