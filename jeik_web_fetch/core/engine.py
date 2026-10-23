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
from .cookies import CookieHelper, default_cookie_store
from .browser_mgr import browser_mgr
from .updater import updater
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

            # 动态检测并分配可用端口，彻底避免多进程并发调用时端口冲突
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("127.0.0.1", self.port))
                except OSError:
                    s.bind(("127.0.0.1", 0))
                    self.port = s.getsockname()[1]

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

    def _resolve_cdp_endpoint(self, options: ScrapeOptions) -> Optional[str]:
        """
        解析外部 CDP 浏览器端点：
        - 优先级 1: options.cdp_endpoint (形如 http://127.0.0.1:9222 或 127.0.0.1:9222)
        - 优先级 2: options.browser_port (形如 9222)
        - 优先级 3: 环境变量 JEIK_CDP_ENDPOINT / JEIK_BROWSER_PORT
        - 优先级 4: 当用户指定了 options.attach_tab 或 options.tab，或未指定端口时，全自动智能探测本地运行中的浏览器！
        若未提供且未探测到，则返回 None (表示使用内置的无头 Chromium 常驻池)
        """
        endpoint = options.cdp_endpoint or os.environ.get("JEIK_CDP_ENDPOINT")
        if not endpoint:
            port = options.browser_port or os.environ.get("JEIK_BROWSER_PORT")
            if port:
                endpoint = f"http://127.0.0.1:{port}"

        # 若用户启用了 attach_tab 或指定了 tab，尝试全自动探测本地运行中的浏览器实例
        if not endpoint and (options.attach_tab or options.tab):
            discovered = browser_mgr.auto_discover_cdp_endpoint()
            if discovered:
                endpoint = discovered

        if endpoint:
            endpoint = str(endpoint).strip()
            if not endpoint.startswith("http://") and not endpoint.startswith("https://"):
                endpoint = f"http://{endpoint}"
            return endpoint.rstrip("/")
        return None

    def _resolve_cookies_and_headers(
        self, options: ScrapeOptions
    ) -> tuple[List[Dict[str, Any]], Dict[str, str]]:
        """
        解析并合并显式 Cookie、文件 Cookie、持久化 Cookie 与自定义 Header
        返回: (normalized_cookies, extra_headers)
        """
        raw_cookies_list = []

        # 1. 从 cookie_file 读取
        if options.cookie_file:
            try:
                raw_cookies_list.extend(CookieHelper.load_from_file(options.cookie_file))
            except Exception:
                pass

        # 2. 从 options.cookies 解析
        if options.cookies:
            raw_cookies_list.extend(CookieHelper.normalize_cookies(options.cookies, target_url=options.url))

        # 3. 若未显式传入任何 Cookie，自动检索对应域名的全局持久化登录态
        if not raw_cookies_list:
            saved_cookies = default_cookie_store.get_for_url_or_domain(options.url)
            if saved_cookies:
                raw_cookies_list.extend(saved_cookies)

        normalized_cookies = CookieHelper.normalize_cookies(raw_cookies_list, target_url=options.url)

        # 4. 解析并合并 headers
        headers = dict(options.headers or {})
        if normalized_cookies:
            cookie_header_val = CookieHelper.to_cookie_header(normalized_cookies)
            if cookie_header_val and "cookie" not in [k.lower() for k in headers]:
                headers["Cookie"] = cookie_header_val

        return normalized_cookies, headers

    async def _try_fast_fetch(
        self, options: ScrapeOptions, extra_headers: Optional[Dict[str, str]] = None
    ) -> Optional[ScrapeResult]:
        """
        本质性内容质量裁决器（零域名白名单）：
        - 对任何未知 URL 先以毫秒级 HTTP 探针试探（包含登录态 Cookie 与 Headers）；
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
            if extra_headers:
                headers.update(extra_headers)

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
                    None,
                    options.url,
                    options.include_sidebar,
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
        updater.enter_task()
        target_id = None
        cdp_base = None
        should_close_tab = False
        t0 = time.time()
        try:
            # 模式策略自适配 (--fast / --common / --complex)
            from .models import FetchMode
            if options.mode == FetchMode.COMMON:
                options.headless = True
            elif options.mode == FetchMode.COMPLEX:
                options.headless = True
                options.deep_explore = True
                if options.waitFor < 3.5:
                    options.waitFor = 3.5

            # 解析外部现有浏览器端点（若指定，则直接接入该运行中的浏览器实例）
            external_cdp = self._resolve_cdp_endpoint(options)
            cdp_base = external_cdp or f"http://127.0.0.1:{self.port}"

            # 解析并收集 Cookies 与自定义 Headers (含自动全局持久化登录态匹配)
            cookies, extra_headers = self._resolve_cookies_and_headers(options)

            # 若指定了接管标签页但未找到任何运行中的浏览器实例，给出针对非技术用户的极简指引
            if (options.attach_tab or options.tab) and not external_cdp:
                return ScrapeResult(
                    success=False,
                    url=options.url,
                    error=(
                        "未检测到正在运行且已开启调试通道的浏览器。\n\n"
                        "💡 针对非技术人员的 1 秒极简解决方案:\n"
                        "  1. 在终端运行: `jeik open <网址>` (系统会自动弹出已配置好的 Chrome/Edge 浏览器窗口)；\n"
                        "  2. 在弹出的浏览器中正常查看网页或扫码登录；\n"
                        "  3. 再次运行: `jeik fetch --active-tab` 或 `jeik fetch --tab \"关键词\"` 即可瞬间自动提取！"
                    ),
                    elapsed_seconds=round(time.time() - t0, 2)
                )

            # 若未指定外部浏览器且未开启 attach_tab/tab/headless，优先尝试 Tier 1 极速探针
            if not external_cdp and not options.attach_tab and not options.tab and not options.headless:
                fast_res = await self._try_fast_fetch(options, extra_headers=extra_headers)
                if fast_res:
                    return fast_res

            # Tier 2: 降级自愈升级至无头浏览器 / 连接现有运行中的浏览器实例
            if not external_cdp:
                await self.ensure_started(dns=options.dns)
                cdp_base = f"http://127.0.0.1:{self.port}"

            async with httpx.AsyncClient() as client:
                # 连通性校验
                try:
                    ver_res = await client.get(f"{cdp_base}/json/version", timeout=3.0)
                    if ver_res.status_code != 200:
                        raise ConnectionError(f"HTTP {ver_res.status_code}")
                except Exception as conn_err:
                    err_msg = (
                        f"无法连接到正在运行的浏览器实例 ({cdp_base}): {conn_err}。\n"
                        f"提示: 请运行 `jeik open` 一键启动已配置好调试通道的浏览器。"
                    )
                    return ScrapeResult(
                        success=False,
                        url=options.url,
                        error=err_msg,
                        elapsed_seconds=round(time.time() - t0, 2)
                    )

                if (options.attach_tab or options.tab) and external_cdp:
                    # 接管外部浏览器当前活跃或指定的标签页 (不新建也不关闭 Tab)
                    tabs = browser_mgr.get_open_tabs(cdp_base, timeout=3.0)
                    if not tabs:
                        return ScrapeResult(
                            success=False,
                            url=options.url,
                            error="在正在运行的浏览器实例中未找到任何打开的网页标签页 (Page Tab)。",
                            elapsed_seconds=round(time.time() - t0, 2)
                        )
                    matched = None
                    if options.tab:
                        matched = browser_mgr.match_tab_by_query(tabs, options.tab)
                        if not matched:
                            tabs_summary = "\n".join([f"  [{t['index']}] {t['title']} ({t['url']})" for t in tabs[:10]])
                            return ScrapeResult(
                                success=False,
                                url=options.url,
                                error=(
                                    f"未在运行的浏览器中找到匹配 '{options.tab}' 的标签页。\n"
                                    f"当前打开的标签页列表:\n{tabs_summary}\n\n"
                                    f"提示: 您可以直接使用标签序号或标题关键词，例如: `jeik fetch --tab 1` 或 `jeik fetch --tab \"{tabs[0]['title'][:6]}\"`"
                                ),
                                elapsed_seconds=round(time.time() - t0, 2)
                            )
                    else:
                        # 优先匹配当前正在访问 options.url 的标签页，否则直接接管最顶层活跃标签页
                        matched = next((t for t in tabs if options.url and options.url in t.get("url", "")), tabs[0])

                    target_id = matched["id"]
                    ws_url = matched["webSocketDebuggerUrl"]
                    should_close_tab = False
                    # 动态反向同步实际标签页 URL
                    if matched.get("url") and (not options.url or options.url == "about:blank"):
                        options.url = matched["url"]
                else:
                    # 在浏览器中预先创建干净空白页，以便在页面导航前完整注入反爬脚本与登录态 Cookie
                    new_tab = await client.put(f"{cdp_base}/json/new?about:blank", timeout=10)
                    tab_info = new_tab.json()
                    target_id = tab_info["id"]
                    ws_url = tab_info["webSocketDebuggerUrl"]
                    should_close_tab = True

            async with websockets.connect(ws_url, max_size=50 * 1024 * 1024) as ws:
                # 1. 开启 Network 与 Page 域
                await ws.send(json.dumps({"id": 101, "method": "Network.enable"}))
                await ws.send(json.dumps({"id": 102, "method": "Page.enable"}))

                # 若是新建的独立临时 Tab，清理上一轮可能残留的临时 Cookie，确保请求与请求之间的会话天然隔离
                if should_close_tab:
                    await ws.send(json.dumps({"id": 100, "method": "Network.clearBrowserCookies"}))

                # 2. 注入反爬特征 (页面导航前注册生命周期脚本 + 当前运行时求值)
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
                await ws.send(json.dumps({"id": 103, "method": "Page.addScriptToEvaluateOnNewDocument", "params": {"source": stealth_js}}))
                await ws.send(json.dumps({"id": 104, "method": "Runtime.evaluate", "params": {"expression": stealth_js}}))

                # 3. 注入登录态 Cookies
                cdp_cookies = CookieHelper.to_cdp_cookies(cookies, options.url)
                if cdp_cookies:
                    await ws.send(json.dumps({
                        "id": 105,
                        "method": "Network.setCookies",
                        "params": {"cookies": cdp_cookies}
                    }))

                # 4. 注入额外 HTTP 请求头 (如 Authorization 等)
                if extra_headers:
                    await ws.send(json.dumps({
                        "id": 106,
                        "method": "Network.setExtraHTTPHeaders",
                        "params": {"headers": extra_headers}
                    }))

                # 5. 导航到目标网页 (如果是接管已打开的活跃页面且未强制跳转，则跳过 navigate)
                if not options.attach_tab or (options.url and options.url != "about:blank"):
                    await ws.send(json.dumps({
                        "id": 107,
                        "method": "Page.navigate",
                        "params": {"url": options.url}
                    }))

                # 6. 动态智能内容就绪侦听 (Dynamic Content Settle)
                # 替代固定的 sleep 傻等，只要页面出现实质文字且脱离 Loading 状态，立即提前进入提取！
                poll_js = r"""
                (() => {
                    const text = document.body ? document.body.innerText : "";
                    const hasSubstance = text.length > 500 && !text.includes("Loading...");
                    return hasSubstance;
                })()
                """
                settled = False
                max_polls = int(options.waitFor * 10)
                for _ in range(max_polls):
                    await asyncio.sleep(0.1)
                    await ws.send(json.dumps({
                        "id": 888,
                        "method": "Runtime.evaluate",
                        "params": {"expression": poll_js, "returnByValue": True}
                    }))
                    try:
                        # 兼容过滤其他异步事件广播，精确寻找 id=888 的响应
                        for _ in range(4):
                            msg_str = await asyncio.wait_for(ws.recv(), timeout=0.5)
                            msg_obj = json.loads(msg_str)
                            if msg_obj.get("id") == 888:
                                if msg_obj.get("result", {}).get("result", {}).get("value") is True:
                                    settled = True
                                break
                    except (asyncio.TimeoutError, Exception):
                        pass
                    if settled:
                        break

                # 4. 深度交互探索 (若开启 deep_explore)
                dom_extract_js = r"""
                (async () => {
                    const extractedDrawers = [];

                    // 1. 全容器平滑步进滚动（同时覆盖 window、main 以及所有内部滚动容器，彻底触发异步请求与懒加载）
                    const scrollables = [
                        window,
                        ...Array.from(document.querySelectorAll("main, [class*='content'], [class*='container'], [class*='scroll'], .mdxContent"))
                            .filter(el => el && el.scrollHeight > el.clientHeight + 100)
                    ];
                    for (const sc of scrollables) {
                        const isWin = sc === window;
                        const maxH = isWin ? document.body.scrollHeight : sc.scrollHeight;
                        for (let y = 0; y < Math.min(maxH, 25000); y += 1200) {
                            if (isWin) window.scrollTo(0, y);
                            else sc.scrollTop = y;
                            await new Promise(r => setTimeout(r, 40));
                        }
                        if (isWin) window.scrollTo(0, 0);
                        else sc.scrollTop = 0;
                    }
                    await new Promise(r => setTimeout(r, 400));

                    // 2. 递归多轮深度折叠展开 (Recursive Multi-pass Unfolding)
                    // 彻底展开：原生 details、展开子属性、Body参数、响应参数、aria-expanded="false" 按钮
                    for (let pass = 0; pass < 3; pass++) {
                        document.querySelectorAll("details:not([open])").forEach(d => d.setAttribute("open", "true"));
                        document.querySelectorAll("[aria-expanded='false']").forEach(btn => {
                            try { btn.click(); } catch(e) {}
                        });
                        const toggles = Array.from(document.querySelectorAll("button, [role='button'], span, div, a")).filter(el => {
                            const txt = (el.innerText || "").trim();
                            return /^(展开|展开子属性|显示全部|更多|View more|Expand|Show more)$/i.test(txt) && el.children.length <= 1;
                        });
                        if (toggles.length === 0) break;
                        for (const btn of toggles.slice(0, 50)) {
                            try {
                                btn.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
                            } catch(e) {}
                        }
                        await new Promise(r => setTimeout(r, 200));
                    }

                    // 3. 侧边栏折叠目录全量展开 (Sidebar Accordion Unfolding - Mintlify / Docusaurus / VitePress)
                    const sidebarContainers = Array.from(document.querySelectorAll("aside, nav[class*='sticky'], [class*='sidebar'], [class*='docSidebar'], nav[aria-label*='sidebar' i]"));
                    for (const sb of sidebarContainers) {
                        const expandBtns = Array.from(sb.querySelectorAll("button, [role='button'], [aria-expanded='false']"));
                        for (const b of expandBtns.slice(0, 30)) {
                            try { b.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })); } catch(e) {}
                        }
                    }
                    await new Promise(r => setTimeout(r, 200));

                    // 4. 扫描并提取通用活动细则/规则抽屉 (抽屉探针)
                    const ruleLinks = Array.from(document.querySelectorAll("a, button, span")).filter(
                        e => e.innerText && /活动规则|详细细则|规则说明|使用须知/i.test(e.innerText.trim()) && e.innerText.trim().length <= 10
                    );
                    for (let i = 0; i < Math.min(ruleLinks.length, 10); i++) {
                        const btn = ruleLinks[i];
                        try {
                            btn.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
                            await new Promise(r => setTimeout(r, 350));
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
                                await new Promise(r => setTimeout(r, 100));
                            }
                        } catch(e) {}
                    }

                    // 4. 场景与用例选项卡全量捕获 (基础调用, 流式响应, 函数调用, 联网搜索, 图像输入, 深度思考, 结构化输出...)
                    const scenarioNames = [
                        "基础调用", "流式响应", "函数调用", "联网搜索", "图像输入", "音频输入", "视频输入",
                        "深度思考", "结构化输出", "基础文本对话", "流式输出", "图片理解", "Function Calling"
                    ];
                    const scenarioTabs = Array.from(document.querySelectorAll("button, [role='tab'], span, div")).filter(el => {
                        const txt = (el.innerText || "").trim();
                        return scenarioNames.includes(txt) && el.children.length === 0;
                    });
                    const uniqueScenarios = [];
                    const seenScenarioNames = new Set();
                    for (const st of scenarioTabs) {
                        const txt = st.innerText.trim();
                        if (!seenScenarioNames.has(txt)) {
                            seenScenarioNames.add(txt);
                            uniqueScenarios.push({ name: txt, el: st });
                        }
                    }

                    const harvestedScenarios = [];
                    if (uniqueScenarios.length > 0) {
                        for (const sc of uniqueScenarios.slice(0, 8)) {
                            try {
                                sc.el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
                                await new Promise(r => setTimeout(r, 200));
                            } catch(e) {}
                            const pres = Array.from(document.querySelectorAll("pre")).map(p => p.innerText.trim()).filter(s => s.length > 10);
                            const reqCode = pres.find(c => c.includes("curl") || c.includes("POST") || c.includes("GET") || c.includes("http")) || pres[0] || "";
                            const resJson = pres.find(c => c !== reqCode && (c.startsWith("{") || c.startsWith("[") || c.includes("\"id\":") || c.includes("\"choices\":"))) || (pres.length > 1 ? pres[1] : "");
                            harvestedScenarios.push({
                                scenario: sc.name,
                                requestCode: reqCode,
                                responseJson: resJson
                            });
                        }
                        // 重置回首个场景
                        try {
                            uniqueScenarios[0].el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
                            await new Promise(r => setTimeout(r, 100));
                        } catch(e) {}
                    }

                    // 5. 多语言代码 Tab 遍历与全量采集 (cURL, Python, Go, Node.js, Java 等)
                    const langCodeSamples = [];
                    const codeTabs = Array.from(document.querySelectorAll("[role='tab'], .openapi-tabs__tab, .tabs__item, button")).filter(t => {
                        const txt = (t.innerText || "").trim().toUpperCase();
                        return ["CURL", "PYTHON", "GO", "NODEJS", "JAVA", "PHP", "RUBY", "C#", "JAVASCRIPT", "TYPESCRIPT", "RUST", "BASH", "SHELL"].includes(txt);
                    });
                    const seenLangs = new Set();
                    for (const t of codeTabs) {
                        const lang = t.innerText.trim();
                        if (seenLangs.has(lang)) continue;
                        seenLangs.add(lang);
                        try {
                            t.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
                            await new Promise(r => setTimeout(r, 200));
                            const rightPanel = document.querySelector(".openapi-right-panel__container, [class*='right-panel'], [class*='code-panel']") || document.body;
                            const pres = Array.from(rightPanel.querySelectorAll("pre"));
                            const activePre = pres[pres.length - 1];
                            if (activePre && activePre.innerText.trim().length > 10) {
                                langCodeSamples.push({
                                    language: lang,
                                    code: activePre.innerText.trim()
                                });
                            }
                        } catch(e) {}
                    }
                    if (codeTabs.length > 0) {
                        try {
                            codeTabs[0].dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
                            await new Promise(r => setTimeout(r, 100));
                        } catch(e) {}
                    }

                    // 6. 遍历对象分支与变体 Tab (OneOf / AnyOf: 如 Developer message, System message, User message...)
                    const variantTabs = Array.from(document.querySelectorAll("button, [role='tab'], span")).filter(el => {
                        const txt = (el.innerText || "").trim();
                        return /^(Developer message|System message|User message|Assistant message|Tool message|Text content|Array of content parts)/i.test(txt) && el.children.length === 0;
                    });
                    for (const vt of variantTabs.slice(0, 10)) {
                        try {
                            vt.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
                            await new Promise(r => setTimeout(r, 150));
                        } catch(e) {}
                    }

                    // 7. Monaco Editor 内存模型还原 (杜绝长代码截断)
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

                    // 8. CodeMirror 还原
                    document.querySelectorAll(".CodeMirror").forEach(cm => {
                        if (cm.CodeMirror) {
                            const pre = document.createElement("pre");
                            const code = document.createElement("code");
                            code.textContent = cm.CodeMirror.getValue();
                            pre.appendChild(code);
                            cm.replaceWith(pre);
                        }
                    });

                    // 9. 通用侧边栏精确定位 (包含 Mintlify, Docusaurus, Ark, MiMo, VitePress 几何/类名双模探测)
                    let asideEl = null;
                    const asideCandidates = Array.from(document.querySelectorAll("aside, nav[class*='sticky'], [class*='sidebar'], [class*='docSidebar'], nav[aria-label*='sidebar' i], nav[class*='menu']"));
                    asideEl = asideCandidates.find(el => el.querySelectorAll("a").length >= 2);
                    if (!asideEl) {
                        const leftNavs = Array.from(document.querySelectorAll("div, nav, section")).filter(el => {
                            const rect = el.getBoundingClientRect();
                            return rect.left < 80 && rect.top < 300 && rect.width > 120 && rect.width < 420 && el.querySelectorAll("a").length >= 3 && el.querySelectorAll("a").length < 300;
                        });
                        if (leftNavs.length > 0) {
                            asideEl = leftNavs.sort((a, b) => b.querySelectorAll("a").length - a.querySelectorAll("a").length)[0];
                        }
                    }

                    // 10. 捕获底部分页导航 (Previous / Next)
                    const paginationEl = document.querySelector(".pagination-nav, nav[aria-label*='pagination' i], nav[aria-label*='Pages' i], [class*='pagination']");

                    return {
                        html: document.querySelector("main") ? document.querySelector("main").outerHTML : document.body.outerHTML,
                        drawers: extractedDrawers.join("\n\n"),
                        sidebar: asideEl ? asideEl.outerHTML : "",
                        pagination: paginationEl ? paginationEl.outerHTML : "",
                        code_samples: langCodeSamples,
                        scenarios: harvestedScenarios
                    };
                })()
                """
                await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": dom_extract_js, "awaitPromise": True, "returnByValue": True}}))

                # 接收完整响应
                raw_html = ""
                drawers_text = ""
                sidebar_html = ""
                pagination_html = ""
                code_samples = []
                scenarios = []
                while True:
                    msg_str = await asyncio.wait_for(ws.recv(), timeout=options.timeout)
                    msg = json.loads(msg_str)
                    if msg.get("id") == 1:
                        val = msg.get("result", {}).get("result", {}).get("value", {})
                        if isinstance(val, dict):
                            raw_html = val.get("html", "")
                            drawers_text = val.get("drawers", "")
                            sidebar_html = val.get("sidebar", "")
                            pagination_html = val.get("pagination", "")
                            code_samples = val.get("code_samples", [])
                            scenarios = val.get("scenarios", [])
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
                drawers_text,
                options.url,
                options.include_sidebar,
                sidebar_html,
                code_samples,
                pagination_html,
                scenarios
            )

            # 严格错误校验：如果提取出的 Markdown 与纯文本全为空，且 HTML 包含网络阻断错误
            markdown_content = transformed.get("markdown", "")
            if not markdown_content.strip():
                # 检查浏览器是否遇到了网络连接重置或超时错误 (如 GFW 阻断、DNS 不可达)
                error_match = None
                if "net::ERR_" in raw_html:
                    import re
                    m = re.search(r'net::ERR_[A-Z_]+', raw_html)
                    if m:
                        error_match = m.group(0)
                
                err_msg = (
                    f"Navigation failed or connection was reset ({error_match or 'net::ERR_CONNECTION_TIMED_OUT'}). "
                    f"Target host is unreachable from your network environment."
                )
                return ScrapeResult(
                    success=False,
                    url=options.url,
                    error=err_msg,
                    elapsed_seconds=round(time.time() - t0, 2)
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
            updater.leave_task()
            if should_close_tab and target_id and cdp_base:
                try:
                    async with httpx.AsyncClient() as client:
                        await client.get(f"{cdp_base}/json/close/{target_id}", timeout=2)
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
