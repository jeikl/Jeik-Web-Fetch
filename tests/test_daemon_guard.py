"""守护进程安全性 + 自动拉起的回归测试。

`jeik serve` 没有任何鉴权，因此：
1. 默认必须只绑回环地址，绑公网需要显式 `--allow-public`；
2. CLI 绝不把非回环地址当成「本地守护」去连接；
3. 自动拉起守护进程时，永远只绑 127.0.0.1。
"""

import asyncio
import sys

import pytest

from jeik_web_fetch.cli import build_parser, guard_bind_host
from jeik_web_fetch.core import daemon_client as dc


def test_serve_defaults_to_loopback_host():
    args = build_parser().parse_args(["serve"])
    assert args.host == "127.0.0.1", "默认必须是回环地址，不能是 0.0.0.0"


def test_serve_rejects_public_host_without_flag(capsys):
    with pytest.raises(SystemExit) as excinfo:
        guard_bind_host("0.0.0.0", allow_public=False)

    assert excinfo.value.code == 2
    assert "拒绝" in capsys.readouterr().err


def test_serve_allows_public_host_with_flag():
    guard_bind_host("0.0.0.0", allow_public=True)  # 显式授权，不抛异常


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "127.0.1.5", "::1", "[::1]"])
def test_guard_accepts_loopback(host):
    guard_bind_host(host, allow_public=False)


def test_is_loopback_url():
    assert dc.is_loopback_url("http://127.0.0.1:8863")
    assert dc.is_loopback_url("http://localhost:8863")
    assert not dc.is_loopback_url("http://10.0.0.5:8863")
    assert not dc.is_loopback_url("http://example.com")


def test_resolve_endpoint_refuses_remote_base(monkeypatch):
    monkeypatch.setenv("JEIK_DAEMON_URL", "http://10.0.0.5:8863")
    spawned = []
    monkeypatch.setattr(dc, "_spawn_daemon", lambda *a: spawned.append(a) or True)

    assert asyncio.run(dc.resolve_endpoint()) is None
    assert spawned == [], "远端地址绝不能触发本地守护进程拉起"


def test_spawn_command_binds_loopback_only():
    cmd = dc._spawn_command(8863, dc.AUTO_IDLE_EXIT_SECS)

    assert cmd[cmd.index("--host") + 1] == "127.0.0.1"
    assert cmd[cmd.index("--idle-exit") + 1] == str(dc.AUTO_IDLE_EXIT_SECS)


def test_default_idle_exit_is_one_hour():
    """自动拉起的守护进程闲置 1 小时才退出，避免反复冷启动。"""
    assert dc.AUTO_IDLE_EXIT_SECS == 3600


def test_spawn_command_in_module_mode(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    cmd = dc._spawn_command(8863, 300)

    assert cmd[1:3] == ["-m", "jeik_web_fetch.cli"]
    assert cmd[3] == "serve"


def test_spawn_command_in_frozen_mode(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    cmd = dc._spawn_command(8863, 300)

    assert cmd[0] == sys.executable
    assert cmd[1] == "serve"


def test_resolve_endpoint_spawns_then_waits_for_health(monkeypatch):
    monkeypatch.setattr(dc, "SPAWN_WAIT_SECS", 2.0)
    calls = {"probe": 0, "spawn": 0}

    async def fake_probe(client, base):
        calls["probe"] += 1
        return None if calls["probe"] < 3 else "http://127.0.0.1:9527"

    monkeypatch.setattr(dc, "_probe", fake_probe)
    monkeypatch.setattr(dc, "_port_is_free", lambda port: True)
    monkeypatch.setattr(
        dc, "_spawn_daemon", lambda p, i: calls.__setitem__("spawn", calls["spawn"] + 1) or True
    )

    assert asyncio.run(dc.resolve_endpoint()) == "http://127.0.0.1:9527"
    assert calls["spawn"] == 1


def test_resolve_endpoint_skips_spawn_when_port_is_busy(monkeypatch):
    async def fake_probe(client, base):
        return None

    spawned = []
    monkeypatch.setattr(dc, "_probe", fake_probe)
    monkeypatch.setattr(dc, "_port_is_free", lambda port: False)
    monkeypatch.setattr(dc, "_spawn_daemon", lambda *a: spawned.append(a) or True)

    assert asyncio.run(dc.resolve_endpoint()) is None
    assert spawned == []


def test_resolve_endpoint_respects_kill_switches(monkeypatch):
    monkeypatch.setenv("JEIK_NO_DAEMON_REUSE", "1")
    assert asyncio.run(dc.resolve_endpoint()) is None

    monkeypatch.delenv("JEIK_NO_DAEMON_REUSE")
    monkeypatch.setenv("JEIK_NO_AUTO_DAEMON", "1")

    async def fake_probe(client, base):
        return None

    monkeypatch.setattr(dc, "_probe", fake_probe)
    spawned = []
    monkeypatch.setattr(dc, "_spawn_daemon", lambda *a: spawned.append(a) or True)

    assert asyncio.run(dc.resolve_endpoint()) is None
    assert spawned == []


def test_persistent_profile_is_isolated_per_port(monkeypatch, tmp_path):
    """多个 serve 实例不能争用同一个 user-data-dir。"""
    from jeik_web_fetch.core.engine import default_persistent_profile_dir

    monkeypatch.delenv("JEIK_ENGINE_PROFILE_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    monkeypatch.setenv("JEIK_SERVE_PORT", "8863")
    first = default_persistent_profile_dir()
    monkeypatch.setenv("JEIK_SERVE_PORT", "9000")
    second = default_persistent_profile_dir()

    assert first != second
    assert first.endswith("engine_profile_8863")
    assert second.endswith("engine_profile_9000")


def test_persistent_profile_env_override_wins(monkeypatch, tmp_path):
    from jeik_web_fetch.core.engine import default_persistent_profile_dir

    monkeypatch.setenv("JEIK_SERVE_PORT", "8863")
    monkeypatch.setenv("JEIK_ENGINE_PROFILE_DIR", str(tmp_path / "custom"))

    assert default_persistent_profile_dir() == str(tmp_path / "custom")
