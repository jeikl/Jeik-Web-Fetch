"""裸域名 / 缺 scheme 输入的回归测试。

历史行为：`jeik fetch www.baidu.com` 走到 `Page.navigate` 时被 CDP 拒绝
（`Cannot navigate to invalid URL`），页面停在 about:blank，最后被误报成
`ERR_CONNECTION_TIMED_OUT`「目标主机不可达」。
"""

import pytest

from jeik_web_fetch.core.engine import navigation_failure_message, net_error_code
from jeik_web_fetch.core.models import ScrapeOptions
from jeik_web_fetch.core.urls import is_navigable_url, normalize_target_url


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("www.baidu.com", "https://www.baidu.com"),
        ("baidu.com/a/b?q=1#top", "https://baidu.com/a/b?q=1#top"),
        ("example.com:8443/api", "https://example.com:8443/api"),
        ("example.com:80/plain", "http://example.com:80/plain"),
        ("example.com:443/secure", "https://example.com:443/secure"),
        ("[::1]:8080/x", "http://[::1]:8080/x"),
        ("localhost:8863/health", "http://localhost:8863/health"),
        ("127.0.0.1:9527/json/version", "http://127.0.0.1:9527/json/version"),
        ("192.168.1.10:8080/admin", "http://192.168.1.10:8080/admin"),
        ("intranet-host/doc", "http://intranet-host/doc"),
        ("//cdn.example.com/app.js", "https://cdn.example.com/app.js"),
        ("  www.baidu.com  ", "https://www.baidu.com"),
    ],
)
def test_bare_hosts_get_a_scheme(raw, expected):
    assert normalize_target_url(raw) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.baidu.com",
        "http://127.0.0.1:8863",
        "about:blank",
        "data:text/html,<p>hi</p>",
        "file:///C:/page.html",
        "view-source:https://example.com",
    ],
)
def test_absolute_urls_are_left_untouched(url):
    assert normalize_target_url(url) == url


def test_empty_input_stays_empty():
    assert normalize_target_url("") == ""
    assert normalize_target_url(None) == ""


def test_normalization_is_idempotent():
    once = normalize_target_url("www.baidu.com")
    assert normalize_target_url(once) == once


def test_scrape_options_normalizes_on_construction():
    """CLI 之外的入口（HTTP API / SDK）也必须走同一条归一化。"""
    assert ScrapeOptions(url="www.baidu.com").url == "https://www.baidu.com"
    assert ScrapeOptions(url="https://www.baidu.com").url == "https://www.baidu.com"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.baidu.com", True),
        ("http://localhost:8863/health", True),
        ("about:blank", True),
        ("www.baidu.com", False),
        ("", False),
        ("not a url", False),
        ("ftp://example.com/file", False),
    ],
)
def test_is_navigable_url(url, expected):
    assert is_navigable_url(url) is expected


def test_net_error_code_from_browser_error_page():
    page_text = "This site can’t be reached\nERR_NAME_NOT_RESOLVED\n"
    assert net_error_code(page_text) == "ERR_NAME_NOT_RESOLVED"
    assert net_error_code("net::ERR_CONNECTION_TIMED_OUT") == "net::ERR_CONNECTION_TIMED_OUT"
    assert net_error_code("plain text") is None


def test_failure_message_does_not_fake_a_timeout():
    """没有证据时绝不能编造 ERR_CONNECTION_TIMED_OUT。"""
    message = navigation_failure_message("https://example.com", None)
    assert "ERR_CONNECTION_TIMED_OUT" not in message
    assert "no readable content" in message


def test_failure_message_reports_the_real_reason():
    message = navigation_failure_message(
        "www.baidu.com", "Cannot navigate to invalid URL"
    )
    assert "Cannot navigate to invalid URL" in message
    assert "www.baidu.com" in message
