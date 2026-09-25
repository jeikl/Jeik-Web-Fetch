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

import httpx
import websockets

from .models import ScrapeOptions, ScrapeResult, OutputFormat
from ..core.dns import DNSResolverConfig
from ..browser import find_system_browser
from ..transformers.content import ContentTransformer
from ..storage.manager import default_storage

class ScrapeEngine:
    """
    Jeik-Web-Fetch 核心渲染引擎：
    - 管理单例/常驻 Chromium 实例连接池
    - 执行 CDP 会话生命周期与反爬脚本注入
    - 结合 ContentTransformer 进行多格式派发
    - 结合 StorageManager 自动保存到本地临时文件或指定工程目录
    """
    def __init__(self, port: int = 9527):
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self.tmp_dir: Optional[str] = None
        self.bin_path: str = ""
        self._lock = asyncio.Lock()

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

    async def scrape_url(self, options: ScrapeOptions) -> ScrapeResult:
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

                # 提取完整 DOM (含 Monaco Editor 内存穿透)
                dom_extract_js = """
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
                await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": dom_extract_js, "returnByValue": True}}))

                # 接收完整响应
                raw_html = ""
                while True:
                    msg_str = await asyncio.wait_for(ws.recv(), timeout=options.timeout)
                    msg = json.loads(msg_str)
                    if msg.get("id") == 1:
                        raw_html = msg.get("result", {}).get("result", {}).get("value", "")
                        break

            # 多格式转换
            transformed = ContentTransformer.transform(
                raw_html,
                formats=options.formats,
                only_main_content=options.only_main_content
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

# 全局默认引擎实例
default_engine = ScrapeEngine()
