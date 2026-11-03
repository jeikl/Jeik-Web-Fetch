"""临时 profile 回收回归测试。

历史问题：每次抓取都会 mkdtemp 一个完整 Chromium profile（Windows 上约 131MB）。
正常退出会删，但「进程被强杀」和「Windows 上 rmtree 静默失败」会留下永不清理的
目录，最终累积到几十 GB 撑满磁盘。这里锁定 owner 标记 + 遗留清扫的行为。
"""

import os
import time

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
