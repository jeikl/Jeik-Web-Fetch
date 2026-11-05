"""临时 profile 回收回归测试。

历史问题：每次抓取都会 mkdtemp 一个完整 Chromium profile（Windows 上约 131MB）。
正常退出会删，但「进程被强杀」和「Windows 上 rmtree 静默失败」会留下永不清理的
目录，最终累积到几十 GB 撑满磁盘。这里锁定 owner 标记 + 遗留清扫的行为。
"""

import os
import stat
import time
import socket
import asyncio

import pytest

from jeik_web_fetch.core import engine as engine_mod


def _make_profile(root, name, owner_pid=None, age_secs=0.0):
    path = root / name
    (path / "Default").mkdir(parents=True, exist_ok=True)
    (path / "Default" / "Cache").write_text("x" * 4096, encoding="utf-8")
    if owner_pid is not None:
        (root / f"{name}.owner").write_text(str(owner_pid), encoding="utf-8")
    if age_secs:
        stamp = time.time() - age_secs
        os.utime(path, (stamp, stamp))
    return path


@pytest.fixture
def temp_root(tmp_path, monkeypatch):
    monkeypatch.setattr(engine_mod.tempfile, "gettempdir", lambda: str(tmp_path))
    return tmp_path


def test_sweep_removes_profile_whose_owner_is_gone(temp_root):
    dead_pid = 2**22 + 12345  # 实际不存在的 pid
    path = _make_profile(temp_root, "jeik_engine_dead", owner_pid=dead_pid)

    assert engine_mod.sweep_stale_profiles(min_age_secs=0) == 1
    assert not path.exists()
    assert not (temp_root / "jeik_engine_dead.owner").exists()


def test_sweep_keeps_profile_owned_by_a_live_process(temp_root):
    path = _make_profile(temp_root, "jeik_engine_live", owner_pid=os.getpid())

    assert engine_mod.sweep_stale_profiles(min_age_secs=0) == 0
    assert path.exists()
    assert (temp_root / "jeik_engine_live.owner").exists()


def test_sweep_skips_profiles_registered_in_this_process(temp_root):
    path = _make_profile(temp_root, "jeik_engine_active", owner_pid=os.getpid())
    engine_mod._register_live_profile(str(path), None)
    try:
        assert engine_mod.sweep_stale_profiles(min_age_secs=0) == 0
        assert path.exists()
    finally:
        engine_mod._unregister_live_profile(str(path))


def test_sweep_keeps_fresh_profile_without_owner(temp_root):
    """没有 owner 标记的老版本目录，只在足够老时才删（避免误删并发进程）。"""
    path = _make_profile(temp_root, "jeik_engine_fresh")

    assert engine_mod.sweep_stale_profiles(min_age_secs=3600) == 0
    assert path.exists()


def test_sweep_removes_stale_profile_without_owner(temp_root):
    path = _make_profile(temp_root, "jeik_engine_old", age_secs=7200)

    assert engine_mod.sweep_stale_profiles(min_age_secs=3600) == 1
    assert not path.exists()


def test_sweep_ignores_unrelated_directories(temp_root):
    other = temp_root / "some_other_cache"
    other.mkdir()
    (other / "f").write_text("x", encoding="utf-8")

    assert engine_mod.sweep_stale_profiles(min_age_secs=0) == 0
    assert other.exists()


def test_remove_tree_also_clears_owner_marker(temp_root):
    path = _make_profile(temp_root, "jeik_engine_x", owner_pid=os.getpid())

    assert engine_mod._remove_tree(str(path)) is True
    assert not path.exists()
    assert not (temp_root / "jeik_engine_x.owner").exists()


def test_process_alive_recognises_self_and_bogus_pid():
    assert engine_mod._process_alive(os.getpid()) is True
    assert engine_mod._process_alive(2**22 + 54321) is False
    assert engine_mod._process_alive(0) is False


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _capturing_browser(tmp_path):
    """假浏览器：把收到的参数写进文件，然后睡死（永远不打开 CDP 端口）。"""
    args_file = tmp_path / "argv.txt"
    script = tmp_path / "capturing_browser.sh"
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{args_file}"\n'
        "exec sleep 60\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script, args_file


def test_ephemeral_engine_uses_temp_profile_and_disables_disk_cache(tmp_path, monkeypatch):
    script, args_file = _capturing_browser(tmp_path)
    monkeypatch.setattr(engine_mod, "find_system_browser", lambda: str(script))
    monkeypatch.setenv("JEIK_BROWSER_START_TIMEOUT", "0.6")

    engine = engine_mod.ScrapeEngine(port=_free_port())
    with pytest.raises(TimeoutError):
        asyncio.run(engine.ensure_started())

    args = args_file.read_text(encoding="utf-8").splitlines()
    user_data = [arg for arg in args if arg.startswith("--user-data-dir=")]
    assert user_data and "jeik_engine_" in user_data[0]
    assert "--disk-cache-size=1" in args, "一次性实例应关掉磁盘缓存"


def test_persistent_engine_reuses_profile_and_keeps_cache(tmp_path, monkeypatch):
    script, args_file = _capturing_browser(tmp_path)
    profile = tmp_path / "persist_profile"
    monkeypatch.setattr(engine_mod, "find_system_browser", lambda: str(script))
    monkeypatch.setenv("JEIK_BROWSER_START_TIMEOUT", "0.6")

    engine = engine_mod.ScrapeEngine(port=_free_port(), profile_dir=str(profile))
    with pytest.raises(TimeoutError):
        asyncio.run(engine.ensure_started())

    assert profile.is_dir(), "常驻 profile 启动失败后也不应删除"
    args = args_file.read_text(encoding="utf-8").splitlines()
    assert f"--user-data-dir={profile}" in args
    assert "--disk-cache-size=1" not in args, "常驻实例应保留磁盘缓存"
    assert engine.tmp_dir is None


def test_use_persistent_profile_switches_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("JEIK_ENGINE_PROFILE_DIR", str(tmp_path / "engine_profile"))
    engine = engine_mod.ScrapeEngine()
    assert engine.profile_dir is None

    engine.use_persistent_profile()

    assert engine.profile_dir == str(tmp_path / "engine_profile")


def test_serve_lifespan_enables_persistent_profile(monkeypatch):
    """`jeik serve` 必须走常驻复用模式，而不是每次都新建临时 profile。"""
    from jeik_web_fetch.api import routes
    from jeik_web_fetch.core.engine import default_engine

    seen = {}

    async def fake_ensure(*args, **kwargs):
        raise TimeoutError("stop here")

    async def fake_stop():
        seen["stopped"] = True

    monkeypatch.setattr(
        default_engine, "use_persistent_profile", lambda path=None: seen.update(persistent=True)
    )
    monkeypatch.setattr(default_engine, "ensure_started", fake_ensure)
    monkeypatch.setattr(default_engine, "stop", fake_stop)

    async def run():
        async with routes.lifespan(routes.app):
            pass

    with pytest.raises(TimeoutError):
        asyncio.run(run())

    assert seen.get("persistent") is True
    assert seen.get("stopped") is True


class _FakeHttpResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, timeout=None):
        if url.endswith("/health"):
            return _FakeHttpResponse(200, {"status": "healthy", "pool_port": 9527})
        return _FakeHttpResponse(200, {"Browser": "Chrome/124"})


def test_daemon_endpoint_is_discovered_from_health(monkeypatch):
    """CLI 应该能拿到守护进程的 pool_port，从而复用它的浏览器而不再新建 profile。"""
    monkeypatch.setattr(engine_mod.httpx, "AsyncClient", _FakeAsyncClient)
    engine = engine_mod.ScrapeEngine()

    assert asyncio.run(engine._resolve_daemon_endpoint()) == "http://127.0.0.1:9527"


def test_daemon_reuse_kill_switch(monkeypatch):
    monkeypatch.setenv("JEIK_NO_DAEMON_REUSE", "1")
    engine = engine_mod.ScrapeEngine()

    assert asyncio.run(engine._resolve_daemon_endpoint()) is None


def test_daemon_endpoint_none_when_unreachable(monkeypatch):
    class _BrokenClient(_FakeAsyncClient):
        async def get(self, url, timeout=None):
            raise OSError("connection refused")

    monkeypatch.setattr(engine_mod.httpx, "AsyncClient", _BrokenClient)
    engine = engine_mod.ScrapeEngine()

    assert asyncio.run(engine._resolve_daemon_endpoint()) is None


def test_remove_profile_also_removes_snap_mirror(temp_root):
    """snap 会把真实数据写到 snap-private-tmp，只删宿主空壳等于没删。"""
    host = _make_profile(temp_root, "jeik_engine_snap", owner_pid=os.getpid())
    mirror = temp_root / "snap-private-tmp" / "snap.chromium" / "tmp" / "jeik_engine_snap"
    (mirror / "Default").mkdir(parents=True, exist_ok=True)
    (mirror / "Default" / "data").write_text("x" * 1024, encoding="utf-8")

    assert engine_mod._remove_profile(str(host)) is True

    assert not host.exists()
    assert not mirror.exists(), "snap 私有目录镜像也必须一并删除"


def test_sweep_removes_snap_mirror_without_host_dir(temp_root):
    mirror = temp_root / "snap-private-tmp" / "snap.chromium" / "tmp" / "jeik_engine_mirroronly"
    (mirror / "Default").mkdir(parents=True, exist_ok=True)
    (mirror / "Default" / "data").write_text("x", encoding="utf-8")
    old = time.time() - 7200
    os.utime(mirror, (old, old))

    assert engine_mod.sweep_stale_profiles(min_age_secs=3600) == 1
    assert not mirror.exists()


def test_sweep_kills_orphan_processes_for_dead_owner(temp_root, monkeypatch):
    """owner 被 SIGKILL 后浏览器可能还活着，清扫时必须把它一起收掉。"""
    path = _make_profile(temp_root, "jeik_engine_deadowner", owner_pid=2**22 + 777)
    killed = []
    monkeypatch.setattr(engine_mod, "_profile_pids", lambda p: [4242])
    monkeypatch.setattr(engine_mod, "_kill_processes", lambda pids: killed.extend(pids))

    assert engine_mod.sweep_stale_profiles(min_age_secs=0) == 1
    assert killed == [4242]
    assert not path.exists()


def test_sweep_keeps_in_use_profile_without_owner(temp_root, monkeypatch):
    """旧版本没有 owner 标记：只要还有进程在用就绝不删。"""
    path = _make_profile(temp_root, "jeik_engine_inuse", age_secs=7200)
    monkeypatch.setattr(engine_mod, "_profile_pids", lambda p: [12345])

    assert engine_mod.sweep_stale_profiles(min_age_secs=3600) == 0
    assert path.exists()


def test_shared_browser_detection():
    """共享浏览器不能清整站 Cookie，否则并发抓取会互相抹掉登录态。"""
    ephemeral = engine_mod.ScrapeEngine()
    assert ephemeral._is_shared_browser(None) is False
    assert ephemeral._is_shared_browser("http://127.0.0.1:9222") is True

    persistent = engine_mod.ScrapeEngine(profile_dir="/tmp/jeik_profile_probe")
    assert persistent._is_shared_browser(None) is True
