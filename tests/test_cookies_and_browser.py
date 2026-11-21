import os
import sys
import json
import tempfile
from pathlib import Path

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from jeik_web_fetch.core.cookies import CookieHelper, CookieStore
from jeik_web_fetch.core.browser_mgr import BrowserManager
from jeik_web_fetch.core.models import ScrapeOptions, OutputFormat

def test_cookie_helper_parsing():
    print("[*] Testing CookieHelper parsing...")
    # 1. 字符串解析
    raw = "session_id=abc123456; token=jwt_xyz_987; user_pref=dark"
    cookies = CookieHelper.parse_cookie_string(raw)
    assert len(cookies) == 3
    assert cookies[0]["name"] == "session_id" and cookies[0]["value"] == "abc123456"
    assert cookies[1]["name"] == "token" and cookies[1]["value"] == "jwt_xyz_987"

    # 2. 带 Cookie: 前缀
    cookies_prefix = CookieHelper.parse_cookie_string("Cookie: foo=bar; hello=world")
    assert len(cookies_prefix) == 2
    assert cookies_prefix[0]["name"] == "foo"

    # 3. 字典归一化
    dict_cookies = CookieHelper.normalize_cookies({"uid": "1001", "is_admin": "true"})
    assert len(dict_cookies) == 2

    # 4. Netscape 格式解析
    netscape_content = """# Netscape HTTP Cookie File
.example.com\tTRUE\t/\tFALSE\t1893456000\tauth_token\tsecret_val_111
sub.example.com\tFALSE\t/api\tTRUE\t1893456000\tapi_key\tkey_999
"""
    parsed_netscape = CookieHelper.parse_netscape_cookies(netscape_content)
    assert len(parsed_netscape) == 2
    assert parsed_netscape[0]["name"] == "auth_token"
    assert parsed_netscape[0]["domain"] == ".example.com"
    assert parsed_netscape[1]["secure"] is True

    # 5. Header 字符串转换
    header_str = CookieHelper.to_cookie_header(cookies)
    assert "session_id=abc123456" in header_str
    assert "token=jwt_xyz_987" in header_str

    # 6. CDP 结构转换
    cdp_cookies = CookieHelper.to_cdp_cookies(cookies, "https://www.example.com/test")
    assert len(cdp_cookies) == 3
    assert cdp_cookies[0]["url"] == "https://www.example.com/test"
    assert cdp_cookies[0]["domain"] == "www.example.com"

    print("[✔] CookieHelper tests passed!")

def test_cookie_store_persistence():
    print("[*] Testing CookieStore persistence...")
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = CookieStore(storage_dir=tmp_dir)

        # 保存主域名 Cookie
        store.save_for_domain("example.com", "main_token=abc; lang=zh")
        # 保存子域名 Cookie
        store.save_for_domain("pan.baidu.com", "pan_token=pan123")

        # 验证列表
        items = store.list_all()
        assert len(items) == 2

        # 验证精确匹配
        pan_cookies = store.get_for_url_or_domain("https://pan.baidu.com/disk/home")
        assert len(pan_cookies) >= 1
        assert pan_cookies[0]["name"] == "pan_token"

        # 验证级联回退匹配 (访问 sub.example.com 自动继承 example.com 的 Cookie)
        sub_cookies = store.get_for_url_or_domain("https://deep.sub.example.com/page")
        assert len(sub_cookies) >= 1
        assert any(c["name"] == "main_token" for c in sub_cookies)

        # 验证删除
        deleted = store.delete_for_domain("pan.baidu.com")
        assert deleted is True
        assert len(store.get_for_url_or_domain("pan.baidu.com")) == 0

    print("[✔] CookieStore persistence tests passed!")

def test_browser_manager_tab_matching():
    print("[*] Testing BrowserManager tab fuzzy matching...")
    mock_tabs = [
        {"index": 1, "id": "TAB_1", "title": "阿里云 - 双11活动采购细则与询价", "url": "https://www.aliyun.com/activity"},
        {"index": 2, "id": "TAB_2", "title": "知乎 - 发现更大的世界", "url": "https://www.zhihu.com/explore"},
        {"index": 3, "id": "TAB_3", "title": "GitHub: Let's build from here", "url": "https://github.com/myrepo"}
    ]

    # 按序号匹配
    match_1 = BrowserManager.match_tab_by_query(mock_tabs, "2")
    assert match_1 and match_1["id"] == "TAB_2"

    # 按标题关键词匹配
    match_aliyun = BrowserManager.match_tab_by_query(mock_tabs, "阿里云")
    assert match_aliyun and match_aliyun["id"] == "TAB_1"

    match_activity = BrowserManager.match_tab_by_query(mock_tabs, "双11")
    assert match_activity and match_activity["id"] == "TAB_1"

    # 按 URL 关键词匹配
    match_url = BrowserManager.match_tab_by_query(mock_tabs, "github.com")
    assert match_url and match_url["id"] == "TAB_3"

    print("[✔] BrowserManager tab matching tests passed!")

def test_authenticated_scraping_flow():
    print("[*] Testing end-to-end authenticated scraping flow...")
    import http.server, threading, time
    from jeik_web_fetch.core.models import ScrapeOptions, OutputFormat
    from jeik_web_fetch.core.engine import default_engine
    import asyncio

    SECRET_CONTENT = "# Welcome VIP Member\n\nYour secret balance is $99,999,999. Thank you for logging in."
    LOGIN_PAGE = "<html><body><h1>Please Login</h1><p>You must log in to view this page.</p></body></html>"

    class AuthHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                cookie_header = self.headers.get("Cookie", "")
                if "session_token=valid_vip_user" in cookie_header:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    html = f"<html><body>{SECRET_CONTENT}</body></html>"
                    self.wfile.write(html.encode("utf-8"))
                else:
                    self.send_response(401)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(LOGIN_PAGE.encode("utf-8"))
            except Exception:
                pass

        def log_message(self, format, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 19988), AuthHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)

    try:
        # 1. 携带正确 Cookie 抓取
        options = ScrapeOptions(
            url="http://127.0.0.1:19988",
            cookies="session_token=valid_vip_user",
            save_to_file=False
        )
        res = asyncio.run(default_engine.scrape_url(options))
        assert res.success is True, f"Scrape failed: {res.error}"
        assert "Welcome VIP Member" in (res.markdown or ""), "Failed to extract authenticated content!"
        assert "$99,999,999" in (res.markdown or "")
        print("  ✔ Authenticated content successfully extracted with cookies!")

        # 2. 不带 Cookie 抓取（应当被拦截或无法获取受保护内容）
        unauth_options = ScrapeOptions(
            url="http://127.0.0.1:19988",
            save_to_file=False
        )
        unauth_res = asyncio.run(default_engine.scrape_url(unauth_options))
        assert "Welcome VIP Member" not in (unauth_res.markdown or ""), "Unauthenticated request should NOT see VIP content!"
        print("  ✔ Unauthenticated request properly rejected!")
    finally:
        server.shutdown()
        server.server_close()

    print("[✔] End-to-end authenticated scraping test passed!")

if __name__ == "__main__":
    import asyncio
    from jeik_web_fetch.core.engine import default_engine
    try:
        test_cookie_helper_parsing()
        test_cookie_store_persistence()
        test_browser_manager_tab_matching()
        test_authenticated_scraping_flow()
        print("\n🎉 ALL NEW FEATURE TESTS PASSED!")
    finally:
        asyncio.run(default_engine.stop())
