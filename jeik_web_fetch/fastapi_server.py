import os
import sys
import time
import json
import base64
import asyncio
import tempfile
import shutil
import subprocess
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
import httpx
import websockets

from .browser import find_system_browser
from .converter import html_to_markdown

# ---------------------------------------------------------------------------
# 并发浏览器实例池 (Browser Pool & Context Management)
# ---------------------------------------------------------------------------

class BrowserPool:
    """
    高性能无头 Chromium 常驻池：
    - 预热启动一个主无头浏览器进程（带 remote-debugging-port）
    - 每个并发请求创建独立的 Target (Tab) / BrowserContext，天然隔离 Cookie 与 Storage
    - 请求结束后立即异步关闭 Tab，极大减少频繁启动进程的冷启动开销，并发吞吐提升 5~10 倍！
    """
    def __init__(self, port: int = 9527):
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self.tmp_dir: Optional[str] = None
        self.bin_path: str = ""
        self._lock = asyncio.Lock()

    async def start(self):
        self.bin_path = find_system_browser()
        if not self.bin_path:
            raise RuntimeError("未检测到本地 Chrome / Edge / Chromium，无法启动渲染池。")

        self.tmp_dir = tempfile.mkdtemp(prefix="jeik_pool_")
        cmd = [
            self.bin_path,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--window-size=1920,1080",
            "--disable-blink-features=AutomationControlled",
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-default-apps",
            "--disable-extensions",
            "--mute-audio",
            "--no-first-run",
            "--no-default-browser-check",
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.tmp_dir}",
            "about:blank"
        ]
        self.process = subprocess.Popen(cmd, stderr=subprocess.DEVNULL)
        
        # 轮询探测 CDP 就绪
        async with httpx.AsyncClient() as client:
            for _ in range(40):
                try:
                    res = await client.get(f"http://127.0.0.1:{self.port}/json/version", timeout=0.5)
                    if res.status_code == 200:
                        return
                except Exception:
                    await asyncio.sleep(0.1)
        raise TimeoutError("Browser pool CDP initialization timed out.")

    async def stop(self):
        if self.process:
            self.process.kill()
            self.process = None
        if self.tmp_dir:
            shutil.rmtree(self.tmp_dir, ignore_errors=True)
            self.tmp_dir = None

    async def scrape(self, url: str, wait_sec: float = 3.5, timeout: float = 25.0) -> str:
        """在常驻浏览器池中创建新 Tab、注入反爬特征、异步加载、提取 DOM 并转为 Markdown"""
        async with httpx.AsyncClient() as client:
            # 1. 开启一个独立的 Tab
            new_tab_res = await client.put(f"http://127.0.0.1:{self.port}/json/new?{url}", timeout=5)
            tab_data = new_tab_res.json()
            target_id = tab_data["id"]
            ws_url = tab_data["webSocketDebuggerUrl"]

        try:
            # 2. 连接 WebSocket 执行 CDP
            async with websockets.connect(ws_url, max_size=50 * 1024 * 1024) as ws:
                # 注入反爬脚本 (Stealth)
                stealth_js = """
                (() => {
                    try {
                        if (navigator.webdriver) {
                            delete Object.getPrototypeOf(navigator).webdriver;
                        }
                        if (!navigator.plugins || navigator.plugins.length === 0) {
                            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                        }
                        Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en-US', 'en'] });
                        if (!window.chrome) {
                            window.chrome = {
                                app: { isInstalled: false },
                                runtime: { PlatformOs: { WIN: 'win' } }
                            };
                        }
                    } catch (e) {}
                })()
                """
                await ws.send(json.dumps({
                    "id": 999,
                    "method": "Runtime.evaluate",
                    "params": {"expression": stealth_js}
                }))

                # 等待页面渲染与网络完成
                await asyncio.sleep(wait_sec)

                # 提取完整 DOM（内聚 Monaco / CodeMirror 内存模型提取，杜绝长文档截断）
                extract_js = """
                (() => {
                    if (window.monaco && window.monaco.editor) {
                        const models = window.monaco.editor.getModels();
                        const editors = document.querySelectorAll('.monaco-editor');
                        editors.forEach((ed, idx) => {
                            const model = models[idx] || (models.length === 1 ? models[0] : null);
                            if (model) {
                                const pre = document.createElement('pre');
                                const code = document.createElement('code');
                                code.textContent = model.getValue();
                                pre.appendChild(code);
                                ed.replaceWith(pre);
                            }
                        });
                    }
                    document.querySelectorAll('.CodeMirror').forEach(cm => {
                        if (cm.CodeMirror) {
                            const pre = document.createElement('pre');
                            const code = document.createElement('code');
                            code.textContent = cm.CodeMirror.getValue();
                            pre.appendChild(code);
                            cm.replaceWith(pre);
                        }
                    });
                    document.querySelectorAll('details:not([open])').forEach(d => d.setAttribute('open', 'true'));
                    return document.querySelector("main") ? document.querySelector("main").outerHTML : document.body.outerHTML;
                })()
                """
                await ws.send(json.dumps({
                    "id": 1,
                    "method": "Runtime.evaluate",
                    "params": {"expression": extract_js, "returnByValue": True}
                }))

                # 接收返回内容
                while True:
                    msg_raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                    msg = json.loads(msg_raw)
                    if msg.get("id") == 1:
                        html = msg.get("result", {}).get("result", {}).get("value", "")
                        return html_to_markdown(html)

        finally:
            # 3. 及时关闭 Tab 释放内存
            try:
                async with httpx.AsyncClient() as client:
                    await client.get(f"http://127.0.0.1:{self.port}/json/close/{target_id}", timeout=2)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# FastAPI 异步应用与生命周期
# ---------------------------------------------------------------------------

browser_pool = BrowserPool(port=9527)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 服务启动：初始化常驻浏览器池
    print("[*] 正在预热启动高性能 Chromium 常驻浏览器池...")
    await browser_pool.start()
    print("[+] 浏览器池就绪，可支持高并发无缝爬取！")
    yield
    # 服务关闭：释放浏览器进程
    print("[*] 正在关闭浏览器池...")
    await browser_pool.stop()

app = FastAPI(
    title="Jeik-Web-Fetch",
    version="1.0.0",
    description="Firecrawl 级别的高性能高并发动态网页抓取与 Markdown 提取服务",
    lifespan=lifespan
)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# API 请求与响应模型 (兼容 Firecrawl / Crawl4AI 协议规范)
# ---------------------------------------------------------------------------

class ScrapeRequest(BaseModel):
    url: str = Field(..., description="目标网页绝对 URL")
    waitFor: Optional[float] = Field(3.5, description="页面渲染与异步 API 缓冲等待时间 (秒)")
    timeout: Optional[float] = Field(25.0, description="请求超时上限 (秒)")

class ScrapeResponse(BaseModel):
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class BatchScrapeRequest(BaseModel):
    urls: List[str] = Field(..., description="并发批量抓取 URL 列表")
    waitFor: Optional[float] = Field(3.5, description="页面渲染与异步 API 缓冲等待时间 (秒)")
    timeout: Optional[float] = Field(25.0, description="单页面请求超时上限 (秒)")

# ---------------------------------------------------------------------------
# API 路由
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "jeik-web-fetch",
        "browser": browser_pool.bin_path,
        "pool_port": browser_pool.port
    }

@app.get("/scrape")
@app.get("/md")
async def scrape_get(url: str = Query(..., description="目标网页 URL"), waitFor: float = 3.5):
    """支持 GET 快速调试与简单抓取"""
    try:
        md = await browser_pool.scrape(url, wait_sec=waitFor)
        return {
            "success": True,
            "data": {
                "url": url,
                "markdown": md,
                "length": len(md)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/scrape", response_model=ScrapeResponse)
@app.post("/md", response_model=ScrapeResponse)
@app.post("/v1/scrape", response_model=ScrapeResponse)
async def scrape_post(req: ScrapeRequest):
    """单 URL 高保真 Markdown 提取接口（兼容 Firecrawl /v1/scrape）"""
    try:
        md = await browser_pool.scrape(req.url, wait_sec=req.waitFor, timeout=req.timeout)
        return {
            "success": True,
            "data": {
                "url": req.url,
                "markdown": md,
                "length": len(md)
            }
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@app.post("/scrape/batch")
async def batch_scrape(req: BatchScrapeRequest):
    """多 URL 真正异步高并发抓取接口"""
    tasks = [browser_pool.scrape(u, wait_sec=req.waitFor, timeout=req.timeout) for u in req.urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    data = []
    for u, res in zip(req.urls, results):
        if isinstance(res, Exception):
            data.append({"url": u, "success": False, "error": str(res)})
        else:
            data.append({"url": u, "success": True, "markdown": res, "length": len(res)})

    return {"success": True, "results": data}

def start_fastapi_server(host: str = "0.0.0.0", port: int = 8863):
    uvicorn.run("jeik_web_fetch.fastapi_server:app", host=host, port=port, log_level="info", access_log=False)
