"""On-disk cache of materialized media files for seekable (range) serving.

Used by the remux path so Sonos gets Content-Length + Range — a seek bar
(spec §4 mode (b)). Bounded by total size; least-recently-modified files are
evicted first. Off by default (SHIM_SEEKABLE_REMUX); the streaming pipe
(mode (a)) stays the latency-optimized default.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

from shim.config import DATA_DIR_DEFAULT, get_settings

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")

# Producer writes the materialized bytes to the given (temporary) path and
# returns True on success; False (or a missing file) means "could not produce".
Producer = Callable[[Path], Awaitable[bool]]


class MediaCache:
    def __init__(self, directory: Path, max_bytes: int) -> None:
        self._dir = directory
        self._max_bytes = max_bytes
        self._locks: dict[str, asyncio.Lock] = {}

    def path_for(self, key: str, suffix: str = ".m4a") -> Path:
        return self._dir / (_SAFE.sub("_", key) + suffix)

    def has(self, key: str, suffix: str = ".m4a") -> bool:
        return self.path_for(key, suffix).exists()

    async def get_or_produce(
        self, key: str, producer: Producer, suffix: str = ".m4a"
    ) -> Path | None:
        """Return the cached file for `key`, producing it if absent. Returns
        None if production fails (caller falls back to streaming). Single-
        flighted per key so concurrent requests don't transcode twice."""
        path = self.path_for(key, suffix)
        if path.exists():
            _touch(path)
            return path
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            if path.exists():  # produced while we waited on the lock
                _touch(path)
                return path
            self._dir.mkdir(parents=True, exist_ok=True)
            part = path.parent / (path.name + ".part")
            try:
                ok = await producer(part)
            except BaseException:
                _unlink(part)
                raise
            if not ok or not part.exists():
                _unlink(part)
                return None
            os.replace(part, path)  # atomic publish
            self._evict()
            return path

    def _evict(self) -> None:
        files = [p for p in self._dir.iterdir() if p.is_file() and p.suffix != ".part"]
        files.sort(key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        for p in files:
            if total <= self._max_bytes:
                break
            size = p.stat().st_size
            _unlink(p)
            total -= size


def _touch(path: Path) -> None:
    with contextlib.suppress(OSError):
        os.utime(path, None)


def _unlink(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


# ----- singleton (mirrors hum_client.get_client / store.get_store) ----------

_cache: MediaCache | None = None


def get_cache() -> MediaCache:
    global _cache
    if _cache is None:
        s = get_settings()
        directory = Path(s.temp_dir) if s.temp_dir else DATA_DIR_DEFAULT / "cache"
        _cache = MediaCache(directory, s.temp_cache_mb * 1024 * 1024)
    return _cache


def reset_cache() -> None:
    """Test seam: drop the singleton."""
    global _cache
    _cache = None
