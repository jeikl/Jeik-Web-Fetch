import os
import time
import asyncio
from typing import List
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from ..core.models import ScrapeOptions, ScrapeResult, OutputFormat
from ..core.engine import default_engine

# 最近一次真实抓取活动时间。`--idle-exit` 的看门狗靠它判断能否退出。
_LAST_ACTIVITY = [time.time()]


def _touch_activity() -> None:
    _LAST_ACTIVITY[0] = time.time()


async def _idle_watchdog(idle_secs: float) -> None:
    """
    自动拉起（或带 `--idle-exit`）的守护进程：空闲超时后自行退出。

    `jeik fetch` 首次需要浏览器时会拉起一个后台守护；它不能永远占着内存，
    所以空闲一段时间就把浏览器一并收掉退出。
    """
    from ..core.updater import updater

    interval = max(5.0, min(30.0, idle_secs / 4.0))
    while True:
        await asyncio.sleep(interval)
        if not updater.is_idle():
            continue
        if time.time() - _LAST_ACTIVITY[0] < idle_secs:
            continue
        print(f"[*] 空闲超过 {idle_secs:.0f}s，自动退出后台守护进程", flush=True)
        try:
            await default_engine.stop()
        finally:
            os._exit(0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[*] 正在预热启动高性能 Chromium 常驻浏览器池...")
    # 常驻服务：复用同一个 profile（跨请求 / 跨重启），不再每重启一次就新建
    # 一份 131MB 的临时目录；同时保留磁盘缓存，供反复访问同类站点时复用。
    default_engine.use_persistent_profile()
    try:
        await default_engine.ensure_started()
    except BaseException:
        # lifespan 未 yield 时不会执行下方的 stop()；启动失败必须就地回收，
        # 否则这一轮拉起的 Chromium 会变成孤儿进程常驻内存。
        await default_engine.stop()
        raise
    print("[+] 浏览器池就绪，可支持高并发无缝爬取！")
    try:
        idle_exit = float(os.environ.get("JEIK_SERVE_IDLE_EXIT", "0") or 0)
        watchdog = asyncio.create_task(_idle_watchdog(idle_exit)) if idle_exit > 0 else None
        try:
            yield
        finally:
            if watchdog is not None:
                watchdog.cancel()
            print("[*] 正在关闭浏览器池...")
            await default_engine.stop()
    except BaseException:
        raise

app = FastAPI(
    title="Jeik-Web-Fetch",
    version="1.2.1",
    description="高性能通用动态网页抓取、多格式转换与工件存储引擎",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    # 守护无鉴权，且只应在回环地址上：不要把响应读权限开给任意网页
    # （否则任意网站都能通过浏览器驱动本地浏览器）。
    allow_origins=[],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$",
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
    _touch_activity()
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
    _touch_activity()
    res = await default_engine.scrape_url(options)
    return res

@app.post("/scrape/batch")
async def batch_scrape(options_list: List[ScrapeOptions]):
    """多线程/多协程高并发批量抓取"""
    _touch_activity()
    results = await default_engine.scrape_urls_concurrent(options_list, max_workers=8)
    return {"success": True, "count": len(results), "results": results}
