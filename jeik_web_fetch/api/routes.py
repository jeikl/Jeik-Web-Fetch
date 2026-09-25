import asyncio
from typing import List
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from ..core.models import ScrapeOptions, ScrapeResult, OutputFormat
from ..core.engine import default_engine

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[*] 正在预热启动高性能 Chromium 常驻浏览器池...")
    await default_engine.ensure_started()
    print("[+] 浏览器池就绪，可支持高并发无缝爬取！")
    yield
    print("[*] 正在关闭浏览器池...")
    await default_engine.stop()

app = FastAPI(
    title="Jeik-Web-Fetch",
    version="1.1.0",
    description="高性能通用动态网页抓取、多格式转换与工件存储引擎",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "jeik-web-fetch",
        "browser": default_engine.bin_path,
        "pool_port": default_engine.port
    }

@app.get("/scrape")
@app.get("/md")
async def scrape_get(
    url: str = Query(..., description="目标网页 URL"),
    waitFor: float = 3.5,
    save_to_file: bool = False
):
    """支持 GET 请求快速抓取"""
    options = ScrapeOptions(url=url, waitFor=waitFor, save_to_file=save_to_file)
    res = await default_engine.scrape_url(options)
    if not res.success:
        raise HTTPException(status_code=500, detail=res.error)
    return res

@app.post("/scrape", response_model=ScrapeResult)
@app.post("/md", response_model=ScrapeResult)
@app.post("/v1/scrape", response_model=ScrapeResult)
async def scrape_post(options: ScrapeOptions):
    """
    单页面全能抓取（兼容 Firecrawl /v1/scrape 格式，支持多格式与文件存储）：
    - formats: ["markdown", "html", "rawHtml", "text", "links"]
    - save_to_file: true (自动落盘至临时目录或 output_dir)
    """
    res = await default_engine.scrape_url(options)
    return res

@app.post("/scrape/batch")
async def batch_scrape(options_list: List[ScrapeOptions]):
    """多线程/多协程高并发批量抓取"""
    results = await default_engine.scrape_urls_concurrent(options_list, max_workers=8)
    return {"success": True, "count": len(results), "results": results}
