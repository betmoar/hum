"""#18: single-video extractions reuse one YoutubeDL per worker thread.

A YoutubeDL instance is not thread-safe, so the guarantee under test is: reuse
within a thread, never sharing across threads. Listings (extra opts) still get
a fresh instance per call.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from app.adapters import youtube as adapter


class _RecordingYDL:
    created: list[_RecordingYDL] = []

    def __init__(self, opts: dict[str, Any]) -> None:
        self.opts = opts
        self.threads: set[int] = set()
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()
        _RecordingYDL.created.append(self)

    def __enter__(self) -> _RecordingYDL:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def extract_info(self, url: str, download: bool = False) -> dict[str, Any]:
        with self._lock:
            self.threads.add(threading.get_ident())
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.02)  # widen the window for an overlapping call
        with self._lock:
            self.active -= 1
        return {"id": url}


@pytest.fixture
def recording(monkeypatch: pytest.MonkeyPatch) -> type[_RecordingYDL]:
    _RecordingYDL.created = []

    def factory(opts: dict[str, Any]) -> _RecordingYDL:
        return _RecordingYDL(opts)

    monkeypatch.setattr(adapter, "_make_ydl", factory)
    return _RecordingYDL


def test_same_thread_reuses_one_instance(recording: type[_RecordingYDL]) -> None:
    for i in range(3):
        adapter._extract(f"https://www.youtube.com/watch?v=v{i}", {})
    assert len(recording.created) == 1


def test_concurrent_extractions_never_share_an_instance(recording: type[_RecordingYDL]) -> None:
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: adapter._extract(f"https://www.youtube.com/watch?v=v{i}", {}),
                      range(16)))
    assert 1 <= len(recording.created) <= 4
    for ydl in recording.created:
        assert len(ydl.threads) == 1, "a YoutubeDL instance was used from two threads"
        assert ydl.max_active == 1


def test_listings_get_a_fresh_instance_with_their_opts(recording: type[_RecordingYDL]) -> None:
    adapter._extract("https://www.youtube.com/watch?v=a", {})
    adapter._extract("https://www.youtube.com/playlist?list=x", adapter._FLAT_OPTS)
    adapter._extract("https://www.youtube.com/playlist?list=y", adapter._FLAT_OPTS)
    assert len(recording.created) == 3
    assert [y.opts.get("extract_flat") for y in recording.created] == [None, "in_playlist", "in_playlist"]


def test_a_failed_extraction_does_not_poison_the_reused_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}

    class _Flaky(_RecordingYDL):
        def extract_info(self, url: str, download: bool = False) -> dict[str, Any]:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("Sign in to confirm you're not a bot")
            return {"id": url}

    _RecordingYDL.created = []
    monkeypatch.setattr(adapter, "_make_ydl", lambda opts: _Flaky(opts))
    with pytest.raises(adapter.YouTubeError) as ei:
        adapter._extract("https://www.youtube.com/watch?v=a", {})
    assert ei.value.status == 503
    assert adapter._extract("https://www.youtube.com/watch?v=b", {}) == {
        "id": "https://www.youtube.com/watch?v=b"}
    assert len(_RecordingYDL.created) == 1
