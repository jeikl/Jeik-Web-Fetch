"""守护进程安全性 + 槽位池的回归测试。

安全底线：
1. `jeik serve` 默认只绑回环，绑公网必须 `--allow-public`；
2. CLI 绝不把非回环地址当成「本地守护」去连接，也不会因此拉起本地守护；
3. 自动拉起守护进程时，永远只绑 127.0.0.1。

槽位池：
4. 空池建 anchor；anchor 被占用时建 temp；到上限直接返回 None（走私有实例）；
5. 空闲槽可复用，死槽会被清理，租约可归还/可过期接管。
"""

import asyncio
import os
import sys

import pytest

from jeik_web_fetch.cli import build_parser, guard_bind_host
from jeik_web_fetch.core import daemon_client as dc


@pytest.fixture
def pool_dir(tmp_path, monkeypatch):
    """把池目录重定向到临时目录，并清空进程级缓存。"""
    monkeypatch.setattr(dc, "POOL_DIR", str(tmp_path))
    monkeypatch.setattr(dc, "SLOT_DIR", str(tmp_path / "slots"))
    monkeypatch.setattr(dc, "LEASE_DIR", str(tmp_path / "leases"))
    monkeypatch.setattr(dc, "PORT_DIR", str(tmp_path / "ports"))
    dc.reset_for_tests()
    yield tmp_path
    dc.reset_for_tests()


# ---------------------------------------------------------------------------
# 安全：绑定地址
# ---------------------------------------------------------------------------

def test_serve_defaults_to_loopback_host():
    args = build_parser().parse_args(["serve"])
    assert args.host == "127.0.0.1", "默认必须是回环地址，不能是 0.0.0.0"


def test_serve_rejects_public_host_without_flag(capsys):
    with pytest.raises(SystemExit) as excinfo:
        guard_bind_host("0.0.0.0", allow_public=False)

    assert excinfo.value.code == 2
    assert "拒绝" in capsys.readouterr().err


def test_serve_allows_public_host_with_flag():
    guard_bind_host("0.0.0.0", allow_public=True)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "127.0.1.5", "::1", "[::1]"])
def test_guard_accepts_loopback(host):
    guard_bind_host(host, allow_public=False)


def test_is_loopback_url():
    assert dc.is_loopback_url("http://127.0.0.1:8863")
    assert dc.is_loopback_url("http://localhost:8863")
    assert not dc.is_loopback_url("http://10.0.0.5:8863")
    assert not dc.is_loopback_url("http://example.com")


def test_resolve_endpoint_refuses_remote_base(pool_dir, monkeypatch):
    monkeypatch.setenv("JEIK_DAEMON_URL", "http://10.0.0.5:8863")
    spawned = []
    monkeypatch.setattr(dc, "_spawn_daemon", lambda *a: spawned.append(a) or 1234)

    assert asyncio.run(dc.resolve_endpoint()) is None
    assert spawned == [], "远端地址绝不能触发本地守护进程拉起"


# ---------------------------------------------------------------------------
# 拉起命令
# ---------------------------------------------------------------------------

def test_spawn_command_binds_loopback_only():
    cmd = dc._spawn_command(8863, dc.ANCHOR_TTL_SECS)

    assert cmd[cmd.index("--host") + 1] == "127.0.0.1"
    assert cmd[cmd.index("--idle-exit") + 1] == str(dc.ANCHOR_TTL_SECS)


def test_default_ttls():
    """anchor 1 小时、temp 20 分钟。"""
    assert dc.ANCHOR_TTL_SECS == 3600
    assert dc.TEMP_TTL_SECS == 1200


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


# ---------------------------------------------------------------------------
# 槽位池
# ---------------------------------------------------------------------------

def _probe_returning(endpoint):
    async def fake_probe(client, base):
        return endpoint

    return fake_probe


def test_empty_pool_creates_anchor(pool_dir, monkeypatch):
    spawned = []
    monkeypatch.setattr(dc, "_port_is_free", lambda port: True)
    monkeypatch.setattr(
        dc, "_spawn_daemon", lambda port, ttl: spawned.append((port, ttl)) or 4242
    )

    calls = {"n": 0}

    async def fake_probe(client, base):
        calls["n"] += 1
        # 第一次是收编探测（默认端口无人监听），之后才是新建槽的就绪探测
        return None if calls["n"] == 1 else "http://127.0.0.1:9527"

    monkeypatch.setattr(dc, "_probe", fake_probe)

    endpoint = asyncio.run(dc.borrow())

    assert endpoint == "http://127.0.0.1:9527"
    slots = dc.read_slots()
    assert len(slots) == 1
    assert slots[0]["role"] == "anchor"
    assert slots[0]["idle_exit"] == dc.ANCHOR_TTL_SECS
    assert spawned and spawned[0][0] == dc.DEFAULT_DAEMON_PORT


def test_idle_slot_is_reused_without_spawning(pool_dir, monkeypatch):
    dc._write_slot(8863, os.getpid(), "anchor", dc.ANCHOR_TTL_SECS)
    spawned = []
    monkeypatch.setattr(dc, "_spawn_daemon", lambda *a: spawned.append(a) or 1)
    monkeypatch.setattr(dc, "_probe", _probe_returning("http://127.0.0.1:9527"))

    assert asyncio.run(dc.borrow()) == "http://127.0.0.1:9527"
    assert spawned == [], "空闲槽应直接复用"


def test_busy_anchor_creates_temp_slot(pool_dir, monkeypatch):
    dc._write_slot(8863, os.getpid(), "anchor", dc.ANCHOR_TTL_SECS)
    assert dc._try_lease(8863, os.getpid()) is True  # anchor 被占用

    monkeypatch.setattr(dc, "_port_is_free", lambda port: True)
    monkeypatch.setattr(dc, "_spawn_daemon", lambda port, ttl: 4243)
    monkeypatch.setattr(dc, "_probe", _probe_returning("http://127.0.0.1:9528"))

    assert asyncio.run(dc.borrow()) == "http://127.0.0.1:9528"

    roles = {slot["role"] for slot in dc.read_slots()}
    assert roles == {"anchor", "temp"}
    temp = [slot for slot in dc.read_slots() if slot["role"] == "temp"][0]
    assert temp["idle_exit"] == dc.TEMP_TTL_SECS


def test_pool_full_returns_none(pool_dir, monkeypatch):
    monkeypatch.setattr(dc, "POOL_MAX", 1)
    dc._write_slot(8863, os.getpid(), "anchor", dc.ANCHOR_TTL_SECS)
    dc._try_lease(8863, os.getpid())
    monkeypatch.setattr(dc, "_spawn_daemon", lambda *a: 1)
    monkeypatch.setattr(dc, "_probe", _probe_returning(None))

    assert asyncio.run(dc.borrow()) is None, "到上限必须立刻回退，不能排队"


def test_dead_slot_is_pruned(pool_dir, monkeypatch):
    dc._write_slot(8863, 2**22 + 999, "anchor", dc.ANCHOR_TTL_SECS)
    monkeypatch.setattr(dc, "_port_is_free", lambda port: True)
    monkeypatch.setattr(dc, "_spawn_daemon", lambda port, ttl: 4244)
    monkeypatch.setattr(dc, "_probe", _probe_returning("http://127.0.0.1:9530"))

    assert asyncio.run(dc.borrow()) == "http://127.0.0.1:9530"
    assert len(dc.read_slots()) == 1


def test_release_frees_the_lease(pool_dir):
    dc._write_slot(8863, os.getpid(), "anchor", dc.ANCHOR_TTL_SECS)
    assert dc._try_lease(8863, os.getpid()) is True

    dc._BORROWED_SLOT_PORT = 8863
    dc.release()

    assert dc._lease_alive(8863) is False
    assert dc._BORROWED_SLOT_PORT is None


def test_expired_lease_can_be_taken_over(pool_dir):
    dc._write_slot(8863, os.getpid(), "anchor", dc.ANCHOR_TTL_SECS)
    dc._ensure_dirs()
    with open(dc._lease_path(8863), "w", encoding="utf-8") as handle:
        handle.write(f"{2**22 + 111} {0}")

    assert dc._try_lease(8863, os.getpid()) is True


def test_kill_switches(pool_dir, monkeypatch):
    monkeypatch.setenv("JEIK_NO_DAEMON_REUSE", "1")
    assert asyncio.run(dc.borrow()) is None

    monkeypatch.delenv("JEIK_NO_DAEMON_REUSE")
    monkeypatch.setenv("JEIK_NO_AUTO_DAEMON", "1")
    monkeypatch.setattr(dc, "_spawn_daemon", lambda *a: 1)
    monkeypatch.setattr(dc, "_probe", _probe_returning(None))

    assert asyncio.run(dc.borrow()) is None


# ---------------------------------------------------------------------------
# 常驻 profile 目录
# ---------------------------------------------------------------------------

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


def test_adopts_existing_daemon_on_default_port(pool_dir, monkeypatch):
    """注册表为空但 8863 上已有手工 serve：直接收编，不再另起一个。"""
    monkeypatch.setattr(dc, "_probe", _probe_returning("http://127.0.0.1:9527"))
    monkeypatch.setattr(dc, "_port_is_free", lambda port: False)
    spawned = []
    monkeypatch.setattr(dc, "_spawn_daemon", lambda *a: spawned.append(a) or 1)

    assert asyncio.run(dc.borrow()) == "http://127.0.0.1:9527"
    assert spawned == []
    slots = dc.read_slots()
    assert len(slots) == 1
    assert slots[0]["port"] == dc.DEFAULT_DAEMON_PORT


def test_health_managed_slot_is_not_pruned(pool_dir, monkeypatch):
    """pid=0 的收编槽靠健康检查判断，不能被当成死槽清掉。"""
    dc._write_slot(8863, 0, "anchor", dc.ANCHOR_TTL_SECS)
    monkeypatch.setattr(dc, "_probe", _probe_returning("http://127.0.0.1:9527"))

    assert asyncio.run(dc.borrow()) == "http://127.0.0.1:9527"
    assert len(dc.read_slots()) == 1
