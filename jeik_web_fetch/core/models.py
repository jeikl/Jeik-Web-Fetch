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
    dns: Optional[str] = Field(default=None, description="自定义 DNS (支持数字 IP 如 8.8.8.8，或 DoH 加密 DNS 如 https://1.1.1.1/dns-query，默认系统 DNS)")
    deep_explore: bool = Field(default=True, description="开启深度交互探索 (自动平滑滚动触发异步价格接口、自动遍历所有Tab、自动点击提取弹窗抽屉细则)")
    max_workers: int = Field(default=4, description="多线程并发工作池容量")

class ScrapeResult(BaseModel):
    success: bool
    url: str
    markdown: Optional[str] = None
    html: Optional[str] = None
    rawHtml: Optional[str] = None
    text: Optional[str] = None
    links: Optional[List[Dict[str, str]]] = None
    drawers: Optional[str] = Field(default=None, description="已提取的弹窗/抽屉/活动规则完整细则")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    saved_files: Dict[str, str] = Field(default_factory=dict, description="已保存的本地/临时文件路径映射")
    error: Optional[str] = None
    elapsed_seconds: float = 0.0
