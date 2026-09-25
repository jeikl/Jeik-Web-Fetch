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
from concurrent.futures import ThreadPoolExecutor

import httpx
import websockets

from .models import ScrapeOptions, ScrapeResult, OutputFormat
from .dns import DNSResolverConfig
from .classifier import ContentQualityClassifier
from ..browser import find_system_browser
from ..transformers.content import ContentTransformer
from ..storage.manager import default_storage

class ScrapeEngine:
    """
    Jeik-Web-Fetch 核心渲染引擎 (异步 I/O + CPU 密集型多线程混合架构)：
    - 常驻 Chromium 连接池管理多 Tab 隔离会话
    - 内置专用 ThreadPoolExecutor 线程池，解决 Python GIL 下巨型 HTML/DOM 转换阻塞事件循环的性能痛点
    - 结合 ContentTransformer 进行多线程并行提取
    - 结合 StorageManager 自动保存到本地临时文件或指定工程目录
    """
    def __init__(self, port: int = 9527, thread_workers: Optional[int] = None):
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self.tmp_dir: Optional[str] = None
        self.bin_path: str = ""
        self._lock = asyncio.Lock()
        # 针对 CPU 密集的 HTML/DOM/正则/Markdown 转换分配专用多线程池
        self.executor = ThreadPoolExecutor(max_workers=thread_workers or min(32, (os.cpu_count() or 4) * 2))

    async def ensure_started(self, dns: Optional[str] = None):
        async with self._lock:
            if self.process and self.process.poll() is None:
                return

            self.bin_path = find_system_browser()
            if not self.bin_path:
                raise RuntimeError("未检测到本地 Chrome / Edge / Chromium，无法启动渲染引擎。")

            self.tmp_dir = tempfile.mkdtemp(prefix="jeik_engine_")
            dns_args = DNSResolverConfig.build_chrome_args(dns)
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
            ] + dns_args + ["about:blank"]
            self.process = subprocess.Popen(cmd, stderr=subprocess.DEVNULL)

            async with httpx.AsyncClient() as client:
                for _ in range(40):
                    try:
                        res = await client.get(f"http://127.0.0.1:{self.port}/json/version", timeout=0.5)
                        if res.status_code == 200:
                            return
                    except Exception:
                        await asyncio.sleep(0.1)
            raise TimeoutError("Browser pool initialization timed out.")

    async def stop(self):
        async with self._lock:
            if self.process:
                self.process.kill()
                self.process = None
            if self.tmp_dir:
                shutil.rmtree(self.tmp_dir, ignore_errors=True)
                self.tmp_dir = None

    async def _try_fast_fetch(self, options: ScrapeOptions) -> Optional[ScrapeResult]:
        """
        本质性内容质量裁决器（零域名白名单）：
        - 对任何未知 URL 先以毫秒级 HTTP 探针试探；
        - 根据“文本密度、语义结构、反爬/SPA 骨架特征”由 ContentQualityClassifier 进行本质裁决；
        - 只有真实内容充沛且非骨架屏的页面才会直接输出，绝无误判；
        - 一旦属于 SPA 空壳或风控拦截，毫秒级无感降级至无头浏览器！
        """
        t0 = time.time()
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            }
            async with httpx.AsyncClient(follow_redirects=True, timeout=6.0, verify=False) as client:
                res = await client.get(options.url, headers=headers)
                
                # 本质特征裁决
                is_valid, reason = ContentQualityClassifier.evaluate_html(res.text, res.status_code)
                if not is_valid:
                    return None

                raw_html = res.text

                # 快速并行转换
                loop = asyncio.get_running_loop()
                transformed = await loop.run_in_executor(
                    self.executor,
                    ContentTransformer.transform,
                    raw_html,
                    options.formats,
                    options.only_main_content,
                    None
                )

                md = transformed.get("markdown", "")
                if len(md.strip()) < 200:
                    return None

                saved = {}
                if options.save_to_file:
                    if "markdown" in transformed:
                        saved["markdown"] = default_storage.save_content(options.url, transformed["markdown"], "md", options.output_dir)
                    if "html" in transformed:
                        saved["html"] = default_storage.save_content(options.url, transformed["html"], "html", options.output_dir)
                    if "rawHtml" in transformed:
                        saved["rawHtml"] = default_storage.save_content(options.url, transformed["rawHtml"], "raw.html", options.output_dir)
                    if "text" in transformed:
                        saved["text"] = default_storage.save_content(options.url, transformed["text"], "txt", options.output_dir)

                return ScrapeResult(
                    success=True,
                    url=options.url,
                    markdown=transformed.get("markdown"),
                    html=transformed.get("html"),
                    rawHtml=transformed.get("rawHtml"),
                    text=transformed.get("text"),
                    links=transformed.get("links"),
                    metadata=transformed.get("metadata", {}),
                    saved_files=saved,
                    elapsed_seconds=round(time.time() - t0, 2)
                )
        except Exception:
            return None

    async def scrape_url(self, options: ScrapeOptions) -> ScrapeResult:
        # Tier 1: 极速智能路由（GitHub / SSR 站点 0.5s~1s 秒出）
        fast_res = await self._try_fast_fetch(options)
        if fast_res:
            return fast_res

        # Tier 2: 降级自愈升级至无头浏览器深度探索流
        t0 = time.time()
        await self.ensure_started(dns=options.dns)

        async with httpx.AsyncClient() as client:
            new_tab = await client.put(f"http://127.0.0.1:{self.port}/json/new?{options.url}", timeout=10)
            tab_info = new_tab.json()
            target_id = tab_info["id"]
            ws_url = tab_info["webSocketDebuggerUrl"]

        try:
            async with websockets.connect(ws_url, max_size=50 * 1024 * 1024) as ws:
                # 注入反爬特征
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
                await ws.send(json.dumps({"id": 999, "method": "Runtime.evaluate", "params": {"expression": stealth_js}}))

                # 等待渲染就绪
                await asyncio.sleep(options.waitFor)

                # 4. 深度交互探索 (若开启 deep_explore)
                # 包含：步进平滑滚动结算价格、遍历所有 Tab、点击并采集所有隐藏活动规则/FAQ 抽屉
                dom_extract_js = r"""
                (async () => {
                    const extractedDrawers = [];

                    // 1. 深度平滑步进滚动（触发 IntersectionObserver 异步询价与懒加载）
                    const totalH = document.body.scrollHeight;
                    for (let y = 0; y < totalH; y += 1200) {
                        window.scrollTo(0, y);
                        await new Promise(r => setTimeout(r, 60));
                    }
                    window.scrollTo(0, 0);
                    await new Promise(r => setTimeout(r, 1000));

                    // 2. 扫描并点击【活动规则 / 细则 / FAQ / 须知】抽屉弹窗
                    const ruleLinks = Array.from(document.querySelectorAll("a, button, span")).filter(
                        e => e.innerText && /活动规则|详细细则|规则说明|使用须知/i.test(e.innerText.trim()) && e.innerText.trim().length <= 10
                    );
                    for (let i = 0; i < Math.min(ruleLinks.length, 10); i++) {
                        const btn = ruleLinks[i];
                        try {
                            btn.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
                            await new Promise(r => setTimeout(r, 450));
                            const drawer = document.querySelector(".next-drawer, [role=\"dialog\"], .next-dialog, .ant-modal, .ant-drawer");
                            if (drawer && drawer.innerText) {
                                const txt = drawer.innerText.trim();
                                if (txt && !extractedDrawers.includes(txt)) {
                                    extractedDrawers.push(txt);
                                }
                            }
                            const close = document.querySelector(".next-drawer-close, .next-dialog-close, [aria-label=\"Close\"], .ant-modal-close");
                            if (close) {
                                close.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
                                await new Promise(r => setTimeout(r, 150));
                            }
                        } catch(e) {}
                    }

                    // 3. 遍历未激活的选项卡 (Tab Switching)
                    const tabs = Array.from(document.querySelectorAll("[role=\"tab\"], .next-tabs-tab, .ant-tabs-tab, .tab-item"));
                    for (let i = 0; i < Math.min(tabs.length, 15); i++) {
                        const t = tabs[i];
                        try {
                            t.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
                            await new Promise(r => setTimeout(r, 200));
                        } catch(e) {}
                    }

                    // 4. Monaco Editor 内存模型还原 (杜绝长代码截断)
                    if (window.monaco && window.monaco.editor) {
                        const models = window.monaco.editor.getModels();
                        const editors = document.querySelectorAll(".monaco-editor");
                        editors.forEach((ed, idx) => {
                            const model = models[idx] || (models.length === 1 ? models[0] : null);
                            if (model) {
                                const pre = document.createElement("pre");
                                const code = document.createElement("code");
                                code.textContent = model.getValue();
                                pre.appendChild(code);
                                ed.replaceWith(pre);
                            }
                        });
                    }

                    // 5. CodeMirror 还原
                    document.querySelectorAll(".CodeMirror").forEach(cm => {
                        if (cm.CodeMirror) {
                            const pre = document.createElement("pre");
                            const code = document.createElement("code");
                            code.textContent = cm.CodeMirror.getValue();
                            pre.appendChild(code);
                            cm.replaceWith(pre);
                        }
                    });

                    // 6. 展开常见折叠抽屉
                    document.querySelectorAll("details:not([open])").forEach(d => d.setAttribute("open", "true"));

                    return {
                        html: document.querySelector("main") ? document.querySelector("main").outerHTML : document.body.outerHTML,
                        drawers: extractedDrawers.join("\n\n")
                    };
                })()
                """
                await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": dom_extract_js, "awaitPromise": True, "returnByValue": True}}))

                # 接收完整响应
                raw_html = ""
                drawers_text = ""
                while True:
                    msg_str = await asyncio.wait_for(ws.recv(), timeout=options.timeout)
                    msg = json.loads(msg_str)
                    if msg.get("id") == 1:
                        val = msg.get("result", {}).get("result", {}).get("value", {})
                        if isinstance(val, dict):
                            raw_html = val.get("html", "")
                            drawers_text = val.get("drawers", "")
                        else:
                            raw_html = str(val)
                        break

            # 多格式转换 (移交给 CPU 密集型多线程池并行处理，完全释放主事件循环)
            loop = asyncio.get_running_loop()
            transformed = await loop.run_in_executor(
                self.executor,
                ContentTransformer.transform,
                raw_html,
                options.formats,
                options.only_main_content,
                drawers_text
            )

            # 持久化到临时/本地文件（如果指定）
            saved = {}
            if options.save_to_file:
                if "markdown" in transformed:
                    p = default_storage.save_content(options.url, transformed["markdown"], "md", options.output_dir)
                    saved["markdown"] = p
                if "html" in transformed:
                    p = default_storage.save_content(options.url, transformed["html"], "html", options.output_dir)
                    saved["html"] = p
                if "rawHtml" in transformed:
                    p = default_storage.save_content(options.url, transformed["rawHtml"], "raw.html", options.output_dir)
                    saved["rawHtml"] = p
                if "text" in transformed:
                    p = default_storage.save_content(options.url, transformed["text"], "txt", options.output_dir)
                    saved["text"] = p

            return ScrapeResult(
                success=True,
                url=options.url,
                markdown=transformed.get("markdown"),
                html=transformed.get("html"),
                rawHtml=transformed.get("rawHtml"),
                text=transformed.get("text"),
                links=transformed.get("links"),
                drawers=drawers_text if drawers_text else None,
                metadata=transformed.get("metadata", {}),
                saved_files=saved,
                elapsed_seconds=round(time.time() - t0, 2)
            )

        except Exception as e:
            return ScrapeResult(
                success=False,
                url=options.url,
                error=str(e),
                elapsed_seconds=round(time.time() - t0, 2)
            )

        finally:
            try:
                async with httpx.AsyncClient() as client:
                    await client.get(f"http://127.0.0.1:{self.port}/json/close/{target_id}", timeout=2)
            except Exception:
                pass

    async def scrape_urls_concurrent(
        self,
        options_list: List[ScrapeOptions],
        max_workers: int = 4
    ) -> List[ScrapeResult]:
        """
        高并发多线程/多协程并行遍历：
        - 结合 asyncio.Semaphore 限制最大并行 Tab 数量，防止内存与连接过载
        - 在常驻 Chromium 池中并发开辟多个隔离 Target 标签页同时执行
        """
        await self.ensure_started()
        sem = asyncio.Semaphore(max_workers)

        async def worker(opt: ScrapeOptions) -> ScrapeResult:
            async with sem:
                return await self.scrape_url(opt)

        tasks = [worker(opt) for opt in options_list]
        return await asyncio.gather(*tasks)

# 全局默认引擎实例
default_engine = ScrapeEngine()
