"""Unit tests for the on-disk media cache (seekable remux backing store)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from shim.mediacache import MediaCache


def _writer(data: bytes, calls: list[int]) -> object:
    async def produce(dest: Path) -> bool:
        calls.append(1)
        dest.write_bytes(data)
        return True

    return produce


async def test_produces_then_caches(tmp_path: Path) -> None:
    cache = MediaCache(tmp_path, max_bytes=10 * 1024 * 1024)
    calls: list[int] = []
    p1 = await cache.get_or_produce("vid:abc", _writer(b"DATA", calls))
    assert p1 is not None and p1.read_bytes() == b"DATA"
    # Second call is served from cache — producer not invoked again.
    p2 = await cache.get_or_produce("vid:abc", _writer(b"DATA", calls))
    assert p2 == p1
    assert calls == [1]


async def test_producer_failure_returns_none(tmp_path: Path) -> None:
    cache = MediaCache(tmp_path, max_bytes=1024)

    async def fail(dest: Path) -> bool:
        return False

    assert await cache.get_or_produce("vid:x", fail) is None
    # No partial left behind.
    assert list(tmp_path.iterdir()) == []


async def test_producer_not_writing_returns_none(tmp_path: Path) -> None:
    cache = MediaCache(tmp_path, max_bytes=1024)

    async def claims_ok_but_writes_nothing(dest: Path) -> bool:
        return True  # returns success without creating dest

    assert await cache.get_or_produce("vid:x", claims_ok_but_writes_nothing) is None


async def test_eviction_drops_oldest_over_cap(tmp_path: Path) -> None:
    cache = MediaCache(tmp_path, max_bytes=100)
    calls: list[int] = []
    # Three 40-byte entries = 120 bytes > 100 cap → oldest evicted.
    a = await cache.get_or_produce("a", _writer(b"x" * 40, calls))
    assert a is not None
    os.utime(a, (1, 1))  # make 'a' the oldest by mtime
    b = await cache.get_or_produce("b", _writer(b"x" * 40, calls))
    assert b is not None
    os.utime(b, (2, 2))
    await cache.get_or_produce("c", _writer(b"x" * 40, calls))
    assert not cache.has("a")  # evicted
    assert cache.has("c")


def test_path_for_sanitizes_key(tmp_path: Path) -> None:
    cache = MediaCache(tmp_path, max_bytes=1024)
    p = cache.path_for("vid:dQw4/../w9", ".m4a")
    # The real safety property: separators are stripped, so the result is a
    # single component directly under the cache dir (no traversal). Dots are
    # kept, but "a.._b" is a plain filename, not a parent ref.
    assert p.parent == tmp_path
    assert os.sep not in p.name
    assert os.altsep is None or os.altsep not in p.name
