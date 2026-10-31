"""回归测试：浏览器池启动失败时必须回收自己拉起的 Chromium。

历史 BUG：`ScrapeEngine.ensure_started()` 在 CDP 就绪超时后直接 raise，
既没有 kill 刚拉起的浏览器，也没有删除它的临时 profile。叠加外层的
`Restart=always` / `KillMode=control-group` 后，每次失败都会留下一个常驻的
无头 Chromium（实测单实例 PSS ≈ 389MB），最终吃光整机内存。

这里用一个「永远不会就绪」的假浏览器脚本复现该路径，不依赖真实 Chromium。
"""

import asyncio
import os
import shutil
import socket
import stat
import subprocess
import time

import pytest

from jeik_web_fetch.core import engine as engine_mod
from jeik_web_fetch.core.engine import ScrapeEngine


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _fake_browser(tmp_path, pid_name: str = "browser.pid"):
    """造一个永远不会打开 CDP 端口的假浏览器：记录自身 PID 后睡死。"""
    pid_file = tmp_path / pid_name
    script = tmp_path / "fake_browser.sh"
    script.write_text(
        "#!/bin/sh\n"
        f'echo $$ > "{pid_file}"\n'
        "exec sleep 60\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script, pid_file


def _wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_failed_start_reaps_browser_and_profile(tmp_path, monkeypatch):
    script, pid_file = _fake_browser(tmp_path)
    monkeypatch.setattr(engine_mod, "find_system_browser", lambda: str(script))
    monkeypatch.setenv("JEIK_BROWSER_START_TIMEOUT", "1.0")

    # 记录本轮分配的临时 profile，用于断言它被删除
    created = []
    real_mkdtemp = engine_mod.tempfile.mkdtemp
    monkeypatch.setattr(
        engine_mod.tempfile,
        "mkdtemp",
        lambda *a, **kw: created.append(real_mkdtemp(*a, **kw)) or created[-1],
    )

    engine = ScrapeEngine(port=_free_port())
    with pytest.raises(TimeoutError):
        asyncio.run(engine.ensure_started())

    # 引擎状态被复位
    assert engine.process is None
    assert engine.tmp_dir is None

    # 浏览器进程被真正杀掉（而不是变成孤儿常驻）
    assert pid_file.exists(), "假浏览器没有启动，测试前提不成立"
    pid = int(pid_file.read_text().strip())
    assert _wait_for(lambda: not _is_alive(pid), 3.0), "启动超时后浏览器进程仍存活 → 内存泄漏"

    # 临时 profile 被清理
    assert created, "未观察到临时 profile 创建"
    assert _wait_for(lambda: not os.path.exists(created[0]), 3.0), "临时 profile 目录未被清理"


def test_timeout_is_wall_clock_not_fixed_attempts(tmp_path, monkeypatch):
    """超时必须按墙钟计时：旧实现固定 40 次循环，连接被拒绝时 4 秒就放弃。"""
    script, _ = _fake_browser(tmp_path)
    monkeypatch.setattr(engine_mod, "find_system_browser", lambda: str(script))
    monkeypatch.setenv("JEIK_BROWSER_START_TIMEOUT", "1.2")

    engine = ScrapeEngine(port=_free_port())
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        asyncio.run(engine.ensure_started())
    elapsed = time.monotonic() - started

    assert elapsed >= 1.0, f"提前放弃（{elapsed:.2f}s），没有用满配置的等待预算"
    assert elapsed < 4.0, f"等待过久（{elapsed:.2f}s），可能仍在按固定次数轮询"


def test_stop_reaps_running_browser(tmp_path):
    engine = ScrapeEngine(port=_free_port())
    profile = tmp_path / "profile"
    profile.mkdir()
    pid_file = tmp_path / "stop.pid"

    proc = subprocess.Popen(
        ["/bin/sh", "-c", f'echo $$ > "{pid_file}"; exec sleep 60']
    )
    engine.process = proc
    engine.tmp_dir = str(profile)

    asyncio.run(engine.stop())

    assert engine.process is None
    assert engine.tmp_dir is None
    assert proc.returncode is not None, "子进程未被 wait() 回收，可能留下僵尸"
    assert _wait_for(lambda: not profile.exists(), 3.0), "stop() 未清理临时 profile"
    assert not _is_alive(proc.pid)


def test_lifespan_reaps_when_prewarm_fails(monkeypatch):
    """预热失败时 lifespan 不会走到 yield 之后，必须显式回收。"""
    from jeik_web_fetch.api import routes

    calls = []

    async def boom():
        raise TimeoutError("boom")

    async def fake_stop():
        calls.append("stop")

    monkeypatch.setattr(routes.default_engine, "ensure_started", boom)
    monkeypatch.setattr(routes.default_engine, "stop", fake_stop)

    async def run():
        async with routes.lifespan(routes.app):
            pass  # pragma: no cover - 不应执行到这里

    with pytest.raises(TimeoutError):
        asyncio.run(run())

    assert calls == ["stop"], "预热失败时没有回收浏览器池"
