"""更新器连通性回归测试。

`check_remote_version()` 过去把所有异常吞成 `return None, None`，用户只能看到一句
"Could not reach GitHub releases"，无法区分 TLS 证书、DNS、代理还是限流。这里锁定：

1. 失败必须把真实原因写进 `AutoUpdater.last_error`；
2. 限流/404 不重试，瞬时错误按次数重试；
3. 平台资产匹配优先命中架构；
4. `jeik upgrade` 失败时把原因打到 stderr。
"""

import json
import ssl
import urllib.error

from jeik_web_fetch.core import updater as updater_mod
from jeik_web_fetch.core.updater import AutoUpdater


class _FakeResponse:
    def __init__(self, payload, status=200):
        self.status = status
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


RELEASE = {
    "tag_name": "v9.9.9",
    "assets": [
        {"name": "jeik-web-fetch-linux-x64", "browser_download_url": "https://example/linux-x64"},
        {"name": "jeik-web-fetch-windows-x64.exe", "browser_download_url": "https://example/win-x64.exe"},
        {"name": "jeik-web-fetch-windows-arm64.exe", "browser_download_url": "https://example/win-arm64.exe"},
    ],
}


def test_tls_failure_reports_real_reason(monkeypatch):
    monkeypatch.setattr(updater_mod, "GITHUB_API_RETRIES", 1)

    def boom(*args, **kwargs):
        raise ssl.SSLCertVerificationError("certificate verify failed")

    monkeypatch.setattr(updater_mod.urllib.request, "urlopen", boom)

    assert AutoUpdater.check_remote_version() == (None, None)
    assert AutoUpdater.last_error
    assert "SSLCertVerificationError" in AutoUpdater.last_error


def test_http_error_is_not_retried(monkeypatch):
    calls = []

    def boom(*args, **kwargs):
        calls.append(1)
        raise urllib.error.HTTPError("https://api.github.com", 404, "Not Found", {}, None)

    monkeypatch.setattr(updater_mod.urllib.request, "urlopen", boom)

    assert AutoUpdater.check_remote_version() == (None, None)
    assert len(calls) == 1, "404/429 不应重试"
    assert "404" in (AutoUpdater.last_error or "")


def test_transient_failure_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr(updater_mod.time, "sleep", lambda *_: None)
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise TimeoutError("timed out")
        return _FakeResponse(RELEASE)

    monkeypatch.setattr(updater_mod.urllib.request, "urlopen", flaky)

    version, url = AutoUpdater.check_remote_version()

    assert version == "9.9.9"
    assert url is not None
    assert len(calls) == 3
    assert AutoUpdater.last_error is None


def test_release_without_platform_asset_still_returns_version(monkeypatch):
    payload = {"tag_name": "v9.9.9", "assets": []}
    monkeypatch.setattr(
        updater_mod.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(payload)
    )

    assert AutoUpdater.check_remote_version() == ("9.9.9", None)


def test_pick_asset_prefers_matching_arch():
    assets = [
        {"name": "jeik-web-fetch-windows-arm64.exe", "browser_download_url": "arm"},
        {"name": "jeik-web-fetch-windows-x64.exe", "browser_download_url": "x64"},
        {"name": "jeik-web-fetch-linux-x64", "browser_download_url": "linux-x64"},
        {"name": "jeik-web-fetch-linux-arm64", "browser_download_url": "linux-arm64"},
        {"name": "jeik-web-fetch-darwin-arm64", "browser_download_url": "darwin-arm64"},
    ]

    assert AutoUpdater._pick_asset(assets, "win32", "x64") == "x64"
    assert AutoUpdater._pick_asset(assets, "win32", "arm64") == "arm"
    assert AutoUpdater._pick_asset(assets, "linux", "x64") == "linux-x64"
    assert AutoUpdater._pick_asset(assets, "linux", "arm64") == "linux-arm64"
    assert AutoUpdater._pick_asset(assets, "darwin", "arm64") == "darwin-arm64"
    # 未知架构时仍要能落到一个本平台包上
    assert AutoUpdater._pick_asset(assets, "win32", "i386") is not None


def test_upgrade_prints_actionable_reason(monkeypatch, capsys):
    monkeypatch.setattr(
        AutoUpdater, "check_remote_version", classmethod(lambda cls: (None, None))
    )
    AutoUpdater.last_error = "URLError: [Errno -3] Temporary failure in name resolution"

    assert AutoUpdater().perform_upgrade_and_restart(direct_cli=True) is False

    err = capsys.readouterr().err
    assert "Reason" in err
    assert "Temporary failure in name resolution" in err
    assert "HTTPS_PROXY" in err, "应提示代理用法"
