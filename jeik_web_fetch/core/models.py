from enum import Enum
from typing import Optional, List, Dict, Any, Union
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
    waitFor: float = Field(default=2.0, description="页面渲染初始缓冲时间 (秒)")
    timeout: float = Field(default=25.0, description="请求超时时间 (秒)")
    save_to_file: bool = Field(default=False, description="是否自动持久化到本地/临时文件")
    output_dir: Optional[str] = Field(default=None, description="自定义存储目录")
    only_main_content: bool = Field(default=True, description="是否仅保留主体内容（清洗导航/页脚）")
    dns: Optional[str] = Field(default=None, description="自定义 DNS (支持数字 IP 如 8.8.8.8，或 DoH 加密 DNS 如 https://1.1.1.1/dns-query，默认系统 DNS)")
    deep_explore: bool = Field(default=True, description="开启深度交互探索 (自动平滑滚动触发异步价格接口、自动遍历所有Tab、自动点击提取弹窗抽屉细则)")
    max_workers: int = Field(default=4, description="多线程并发工作池容量")
    cookies: Optional[Union[str, Dict[str, str], List[Dict[str, Any]]]] = Field(
        default=None,
        description="网页登录态 Cookies，支持 'k1=v1; k2=v2' 字符串、字典或列表"
    )
    cookie_file: Optional[str] = Field(
        default=None,
        description="包含 Cookies 的本地文件路径 (支持 Netscape 格式 cookies.txt 或 JSON 文件)"
    )
    headers: Optional[Dict[str, str]] = Field(
        default=None,
        description="自定义 HTTP 请求头 (如 Authorization, User-Agent 等)"
    )
    cdp_endpoint: Optional[str] = Field(
        default=None,
        description="连接到现有正在运行的 Chromium 浏览器 CDP 端点 (例如 http://127.0.0.1:9222)"
    )
    browser_port: Optional[int] = Field(
        default=None,
        description="连接到本地正在运行的浏览器调试端口 (例如 9222)，等同于 cdp_endpoint=http://127.0.0.1:<port>"
    )
    attach_tab: bool = Field(
        default=False,
        description="若为 True，则直接附加到外部浏览器中已打开的活跃标签页进行提取，不新建也不关闭标签页"
    )
    tab: Optional[str] = Field(
        default=None,
        description="按标签页标题关键词、网址或序号模糊匹配运行中浏览器打开的页面 (例如: '知乎', '1', '双11')"
    )
    headless: bool = Field(
        default=False,
        description="强制使用无头浏览器完整渲染，跳过快速 HTTP 探针（适用于包含客户端动态代码块或懒加载组件的页面）"
    )

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
