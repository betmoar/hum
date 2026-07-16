"""Tests for the VideoDetails metadata cache (single-flight, deep-copy, live bypass)."""
from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.adapters import youtube as adapter


def _mock_stream(itag: int, mime_type: str) -> MagicMock:
    s = MagicMock()
    s.itag = itag
    s.mime_type = mime_type
    s.bitrate = 128000
    s.url = f"https://rr1---sn-test.googlevideo.com/videoplayback?itag={itag}"
    s.audio_sample_rate = 44100
    s.width = None
    s.height = None
    s.fps = None
    return s


def _mock_youtube(video_id: str = "dQw4w9WgXcQ") -> MagicMock:
    yt = MagicMock()
    yt.video_id = video_id
    yt.title = "Test Title"
    yt.author = "Test Author"
    yt.channel_id = "UCtest"
    yt.length = 213
    yt.views = 1000
    yt.description = "d"
    yt.vid_info = {"videoDetails": {"isLive": False}}
    streams = [_mock_stream(140, 'audio/mp4; codecs="mp4a.40.2"')]
    sq = MagicMock()
    sq.__iter__ = lambda self: iter(streams)
    yt.streams = sq
    return yt


def _counting_factory(calls: dict[str, int], delay: float = 0.0) -> Any:
    def factory(vid: str) -> MagicMock:
        calls["n"] += 1
        if delay:
            time.sleep(delay)
        return _mock_youtube(vid)

    return factory


async def test_video_cache_hit_skips_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    monkeypatch.setattr(adapter, "_make_youtube", _counting_factory(calls))
    v1 = await adapter.video("dQw4w9WgXcQ")
    v2 = await adapter.video("dQw4w9WgXcQ")
    assert calls["n"] == 1
    assert v1.title == v2.title == "Test Title"


async def test_video_cache_expiry_refetches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    monkeypatch.setattr(adapter, "_make_youtube", _counting_factory(calls))
    await adapter.video("dQw4w9WgXcQ")
    details, _ = adapter._video_details_cache["dQw4w9WgXcQ"]
    adapter._video_details_cache["dQw4w9WgXcQ"] = (details, time.time() - 1)
    await adapter.video("dQw4w9WgXcQ")
    assert calls["n"] == 2


async def test_cache_hit_returns_independent_unsigned_copies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """/api/video signs by mutating the returned object; the cached canonical
    copy must stay unsigned and later hits must be unaffected."""
    monkeypatch.setattr(adapter, "_make_youtube", lambda vid: _mock_youtube(vid))
    v1 = await adapter.video("dQw4w9WgXcQ")
    v2 = await adapter.video("dQw4w9WgXcQ")
    assert v1 is not v2
    v1.audio_formats[0].url += "&exp=1&sig=" + "ab" * 16  # simulate signing
    assert "sig=" not in v2.audio_formats[0].url
    cached, _ = adapter._video_details_cache["dQw4w9WgXcQ"]
    assert all("sig=" not in af.url for af in cached.audio_formats)


async def test_concurrent_misses_single_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    monkeypatch.setattr(adapter, "_make_youtube", _counting_factory(calls, delay=0.05))

    # Simulate /api/video's signing-by-mutation happening synchronously right
    # after each caller's `await adapter.video(...)` returns — as it does in
    # the real route handler — rather than after all callers have finished.
    # This is what actually exercises the creator/joiner race: if `video()`'s
    # single-flight *creator* path returned the raw task result (no copy),
    # caller 0's mutation would land on the same object every joiner's
    # `.model_copy(deep=True)` reads from, tainting all of them.
    async def caller(idx: int) -> Any:
        v = await adapter.video("dQw4w9WgXcQ")
        if idx == 0:
            v.audio_formats[0].url += "&exp=1&sig=" + "ab" * 16
        return v

    results = await asyncio.gather(*(caller(i) for i in range(5)))
    assert calls["n"] == 1
    # No two callers share an instance (each signs independently downstream).
    assert len({id(r) for r in results}) == 5
    assert adapter._inflight_video == {}
    assert "sig=" in results[0].audio_formats[0].url
    for r in results[1:]:
        assert "sig=" not in r.audio_formats[0].url


async def test_live_video_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    def live_factory(vid: str) -> MagicMock:
        yt = _mock_youtube(vid)
        yt.vid_info = {
            "videoDetails": {"isLive": True, "title": "L", "author": "A", "channelId": "C"},
            "streamingData": {"hlsManifestUrl": "https://manifest.googlevideo.com/x.m3u8"},
        }
        return yt

    monkeypatch.setattr(adapter, "_make_youtube", live_factory)
    v1 = await adapter.video("livevid12345")
    v2 = await adapter.video("livevid12345")
    assert v1.is_live and v2.is_live
    assert adapter._video_details_cache == {}


async def test_video_ttl_clamped_to_cache_max(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = MagicMock()
    settings.video_cache_ttl_seconds = 10_000_000
    monkeypatch.setattr(adapter, "get_settings", lambda: settings)
    monkeypatch.setattr(adapter, "_make_youtube", lambda vid: _mock_youtube(vid))
    before = time.time()
    await adapter.video("dQw4w9WgXcQ")
    _, expiry = adapter._video_details_cache["dQw4w9WgXcQ"]
    assert expiry <= before + adapter._CACHE_MAX_TTL + 5.0
