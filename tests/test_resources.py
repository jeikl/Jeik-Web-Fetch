"""设备内存探测与槽位上限的回归测试。

槽位上限 = 并发浏览器数量上限，直接对应峰值内存。规则：
    <= 1.5 GB → 1
    <= 2.5 GB → 2
    <= 6 GB   → 3
    其余      → 4
"""

import os

import pytest

from jeik_web_fetch.core import resources as res


@pytest.mark.parametrize(
    "memory_gb,expected",
    [
        (0.5, 1),
        (1.0, 1),
        (1.5, 1),
        (1.9, 2),
        (2.0, 2),
        (2.5, 2),
        (3.0, 3),
        (4.0, 3),
        (6.0, 3),
        (7.9, 4),
        (8.0, 4),
        (32.0, 4),
    ],
)
def test_pool_max_tiers(monkeypatch, memory_gb, expected):
    monkeypatch.setattr(res, "total_memory_gb", lambda: memory_gb)
    assert res.default_pool_max() == expected


def test_unknown_memory_falls_back_to_two(monkeypatch):
    monkeypatch.setattr(res, "total_memory_gb", lambda: 0.0)
    assert res.default_pool_max() == 2


def test_total_memory_is_detected_on_this_host():
    assert res.total_memory_gb() > 0


def test_process_alive_recognises_self_and_bogus_pid():
    assert res.process_alive(os.getpid()) is True
    assert res.process_alive(2**22 + 4242) is False
    assert res.process_alive(0) is False
