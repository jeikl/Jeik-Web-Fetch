import os
import time
import json
import socket
import struct
import base64
import tempfile
import shutil
import subprocess
import urllib.request
from typing import Optional

from .browser import find_system_browser
from .converter import html_to_markdown

def _build_ws_frame(payload_dict: dict) -> bytearray:
    """构建标准 RFC 6455 WebSocket 客户端掩码帧 (支持大于 65535 字节的指令)"""
    raw = json.dumps(payload_dict).encode("utf-8")
    mask = os.urandom(4)
    length = len(raw)
    if length <= 125:
        header = bytearray([0x81, 0x80 | length])
    elif length <= 65535:
        header = bytearray([0x81, 0x80 | 126]) + struct.pack("!H", length)
    else:
        header = bytearray([0x81, 0x80 | 127]) + struct.pack("!Q", length)
    header += mask
    return header + bytearray(b ^ mask[i % 4] for i, b in enumerate(raw))

def firecrawl_fetch(
    url: str,
    timeout: float = 20.0,
    wait_render_sec: float = 4.0,
    browser_path: Optional[str] = None
) -> str:
    """
    Firecrawl 级别的高性能自愈抓取核心：
    - 无需安装 Playwright / Docker / Node.js
    - 启动系统级 Chrome/Edge，注入多维反爬探针绕过（Webdriver、Plugins、Permissions、Window-size）
    - 采用主动 CDP 会话控制，彻底避免被长轮询或埋点挂起
    - 穿透前端 Monaco / CodeMirror 内存模型，杜绝懒加载代码截断
    - 高保真提取并转为 Markdown
    """
    bin_path = browser_path or find_system_browser()
    if not bin_path:
        raise RuntimeError(
            "未检测到本地 Chromium/Chrome/Edge 浏览器。请安装 Chrome 或 Edge，或设置环境变量 JEIK_BROWSER_PATH。"
        )

    tmp_dir = tempfile.mkdtemp(prefix="jeik_web_fetch_")
    
    # 动态分配空闲可用端口
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    # 全套 Firecrawl + Stealth 命令行启动配置
    cmd = [
        bin_path,
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
        f"--remote-debugging-port={port}",
        f"--user-data-dir={tmp_dir}",
        url
    ]

    process = subprocess.Popen(cmd, stderr=subprocess.DEVNULL)
    t0 = time.time()

    try:
        # 1. 轮询等待 CDP 服务端口就绪
        connected = False
        while time.time() - t0 < timeout:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=0.5)
                connected = True
                break
            except Exception:
                time.sleep(0.1)

        if not connected:
            raise TimeoutError(f"CDP server on port {port} failed to initialize within {timeout}s.")

        # 2. 挑选目标 Page Tab（智能过滤掉插件与后台页面）
        tabs_res = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2)
        tabs = json.loads(tabs_res.read().decode())
        target = next((t for t in tabs if t.get("type") == "page" or "http" in t.get("url", "")), tabs[0])
        ws_url = target["webSocketDebuggerUrl"]

        # 3. 建立原生 WebSocket 链路
        parts = ws_url[5:].split("/", 1)
        host, port_str = parts[0].split(":")
        ws = socket.create_connection((host, int(port_str)), timeout=5)
        ws_key = base64.b64encode(os.urandom(16)).decode("utf-8")
        handshake = (
            f"GET /{parts[1]} HTTP/1.1\r\n"
            f"Host: {host}:{port_str}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {ws_key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        ws.sendall(handshake.encode("utf-8"))
        ws.recv(2048)

        # 4. 注入浏览器层反爬伪装探针 (Stealth Evasions)
        stealth_init_js = """
        (() => {
            try {
                if (navigator.webdriver) {
                    delete Object.getPrototypeOf(navigator).webdriver;
                }
                if (!navigator.plugins || navigator.plugins.length === 0) {
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5],
                    });
                }
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['zh-CN', 'zh', 'en-US', 'en'],
                });
                if (!window.chrome) {
                    window.chrome = {
                        app: { isInstalled: false },
                        runtime: { PlatformOs: { MAC: 'mac', WIN: 'win', ANDROID: 'android', CROS: 'cros', LINUX: 'linux', OPENBSD: 'openbsd' } }
                    };
                }
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
            } catch (e) {}
        })()
        """
        ws.sendall(_build_ws_frame({
            "id": 999,
            "method": "Runtime.evaluate",
            "params": {"expression": stealth_init_js}
        }))
        ws.recv(1024)

        # 5. 等待页面 SPA 异步渲染完成
        time.sleep(wait_render_sec)

        # 6. 主动提取完整 DOM（内聚 Monaco / CodeMirror 内存模型还原，彻底解决长代码截断）
        prepare_expr = """
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
        ws.sendall(_build_ws_frame({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {
                "expression": prepare_expr,
                "returnByValue": True
            }
        }))

        # 7. 接收并拼接分包数据
        ws.settimeout(timeout)
        response_json = None
        while True:
            b1_b2 = ws.recv(2)
            if not b1_b2:
                break
            payload_len = b1_b2[1] & 0x7f
            if payload_len == 126:
                payload_len = struct.unpack("!H", ws.recv(2))[0]
            elif payload_len == 127:
                payload_len = struct.unpack("!Q", ws.recv(8))[0]
            
            chunk_buf = bytearray()
            while len(chunk_buf) < payload_len:
                piece = ws.recv(payload_len - len(chunk_buf))
                if not piece:
                    break
                chunk_buf.extend(piece)

            try:
                msg = json.loads(chunk_buf.decode("utf-8", errors="ignore"))
                if msg.get("id") == 1:
                    response_json = msg
                    break
            except Exception:
                continue

        if not response_json or "result" not in response_json:
            raise RuntimeError("从浏览器会话提取 DOM 失败。")

        raw_html = response_json["result"]["result"].get("value", "")
        return html_to_markdown(raw_html)

    finally:
        process.kill()
        shutil.rmtree(tmp_dir, ignore_errors=True)

# 统一外部别名
fetch = firecrawl_fetch
fetch_markdown = firecrawl_fetch
