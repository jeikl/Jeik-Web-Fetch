"""守护进程空闲退出的判定：HTTP 活动 + 槽位租约。

历史问题：看门狗只看 `/scrape` 的 `_LAST_ACTIVITY`，而 `jeik fetch` 借用守护时
走的是 CDP，不会刷新它。于是一个从 T 时刻拉起的守护会在 T+3600s 退出，不管这
期间 CLI 用了多久；极端情况下正好在抓取中把浏览器收掉。
"""

import time

from jeik_web_fetch.api import routes


def test_watchdog_exits_after_idle_window(monkeypatch):
    routes._LAST_ACTIVITY[0] = time.time() - 7200
    monkeypatch.setattr(routes, "_slot_is_leased", lambda: False)
    monkeypatch.setattr(routes.updater, "is_idle", lambda: True)

    assert routes._should_idle_exit(3600) is True


def test_watchdog_stays_while_a_cli_scrape_holds_a_lease(monkeypatch):
    routes._LAST_ACTIVITY[0] = time.time() - 7200
    monkeypatch.setattr(routes, "_slot_is_leased", lambda: True)
    monkeypatch.setattr(routes.updater, "is_idle", lambda: True)

    assert routes._should_idle_exit(3600) is False
    # 租约活动会把计时基准推到当下，本次用完后重新计满一个空闲窗口
    assert time.time() - routes._LAST_ACTIVITY[0] < 5


def test_watchdog_never_exits_during_an_active_scrape(monkeypatch):
    routes._LAST_ACTIVITY[0] = time.time() - 7200
    monkeypatch.setattr(routes, "_slot_is_leased", lambda: False)
    monkeypatch.setattr(routes.updater, "is_idle", lambda: False)

    assert routes._should_idle_exit(3600) is False


def test_daemon_port_prefers_serve_port(monkeypatch):
    monkeypatch.setenv("JEIK_SERVE_PORT", "8899")
    assert routes._daemon_port() == 8899

    monkeypatch.delenv("JEIK_SERVE_PORT")
    monkeypatch.setenv("PORT", "8877")
    assert routes._daemon_port() == 8877
