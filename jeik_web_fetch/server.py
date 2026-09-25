import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from .fetcher import jeik_fetch
from .fetcher import jeik_fetch as fetch

logger = logging.getLogger("jeik_web_fetch.server")

class WebFetchHandler(BaseHTTPRequestHandler):
    """
    轻量高性能 HTTP 服务端：
    - 完全标准库实现，零第三方网络框架依赖
    - 提供 /scrape, /md, /health 接口
    - 兼容 Firecrawl API 数据格式
    """
    def _send_json(self, status_code: int, data: dict):
        response_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path in ("", "/health"):
            self._send_json(200, {"status": "ok", "service": "jeik-web-fetch"})
            return

        # 支持 GET /scrape?url=https://...
        if path in ("/scrape", "/md"):
            params = parse_qs(parsed.query)
            url = params.get("url", [None])[0]
            if not url:
                self._send_json(400, {"success": False, "error": "Missing 'url' query parameter"})
                return
            self._process_scrape(url, wait_sec=4.0)
            return

        self._send_json(404, {"success": False, "error": "Not Found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path not in ("/scrape", "/md", "/v1/scrape"):
            self._send_json(404, {"success": False, "error": "Not Found"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            self._send_json(400, {"success": False, "error": "Empty request body"})
            return

        body = self.rfile.read(content_length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception as e:
            self._send_json(400, {"success": False, "error": f"Invalid JSON: {e}"})
            return

        url = payload.get("url")
        if not url:
            self._send_json(400, {"success": False, "error": "Field 'url' is required"})
            return

        wait_sec = float(payload.get("waitFor", payload.get("wait_render_sec", 4.0)))
        timeout = float(payload.get("timeout", 25.0))
        self._process_scrape(url, wait_sec=wait_sec, timeout=timeout)

    def _process_scrape(self, url: str, wait_sec: float = 4.0, timeout: float = 25.0):
        try:
            md = jeik_fetch(url, timeout=timeout, wait_render_sec=wait_sec)
            self._send_json(200, {
                "success": True,
                "data": {
                    "url": url,
                    "markdown": md,
                    "length": len(md)
                }
            })
        except Exception as e:
            self._send_json(500, {
                "success": False,
                "error": str(e)
            })

    def log_message(self, format, *args):
        # 简化访问日志
        pass

def run_server(host: str = "0.0.0.0", port: int = 8000):
    server = HTTPServer((host, port), WebFetchHandler)
    print(f"[*] Jeik-Web-Fetch HTTP Server listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Server shutting down...")
    finally:
        server.server_close()
