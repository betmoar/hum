"""Tests for the VideoDetails metadata cache (single-flight, deep-copy, live bypass)."""
from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from pytubefix import exceptions as pytubefix_exceptions

from app.adapters import youtube as adapter
from app.models import SearchHit


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
    # Bounded on BOTH sides: an upper-only bound would also pass if the clamp
    # collapsed the TTL to ~0 (e.g. min() operands swapped).
    assert before + adapter._CACHE_MAX_TTL - 5.0 <= expiry <= before + adapter._CACHE_MAX_TTL + 5.0


# ---- search cache ---------------------------------------------------------


def _mock_search_result() -> MagicMock:
    s = MagicMock()
    v = MagicMock()
    v.video_id = "vid00000001"
    v.title = "Hit"
    v.author = "A"
    v.thumbnail_url = "https://i.ytimg.com/vi/vid00000001/hq.jpg"
    v.length = 100
    v.is_live = False
    s.videos = [v]
    s.channels = []
    s.playlists = []
    return s


def _counting_search_factory(calls: dict[str, int]) -> Any:
    def factory(q: str, *, filters: Any = None) -> MagicMock:
        calls["n"] += 1
        return _mock_search_result()

    return factory


async def test_search_cache_hit_skips_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    monkeypatch.setattr(adapter, "_make_search", _counting_search_factory(calls))
    r1 = await adapter.search("cache me", limit=5)
    r2 = await adapter.search("cache me", limit=5)
    assert calls["n"] == 1
    assert [h.id for h in r1] == [h.id for h in r2] == ["vid00000001"]


async def test_search_cache_key_includes_params(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    monkeypatch.setattr(adapter, "_make_search", _counting_search_factory(calls))
    await adapter.search("q", limit=5)
    await adapter.search("q", limit=10)          # different limit -> miss
    await adapter.search("q", limit=5, live=True)  # different live -> miss
    assert calls["n"] == 3


async def test_search_cache_expiry_refetches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    monkeypatch.setattr(adapter, "_make_search", _counting_search_factory(calls))
    await adapter.search("q", limit=5)
    key = ("q", None, False, 5)
    hits, _ = adapter._search_cache[key]
    adapter._search_cache[key] = (hits, time.time() - 1)
    await adapter.search("q", limit=5)
    assert calls["n"] == 2


async def test_search_write_sweeps_all_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    """A search-only session must still evict expired entries everywhere —
    _refresh_cache (the old sole sweep site) never runs on this path."""
    monkeypatch.setattr(adapter, "_make_search", _counting_search_factory({"n": 0}))
    stale = time.time() - 10
    adapter._stream_url_cache[("dead", 140)] = ("https://x", stale)
    adapter._video_details_cache["dead"] = (MagicMock(), stale)
    adapter._search_cache[("old", None, False, 20)] = ([], stale)
    await adapter.search("fresh", limit=5)
    assert ("dead", 140) not in adapter._stream_url_cache
    assert "dead" not in adapter._video_details_cache
    assert ("old", None, False, 20) not in adapter._search_cache
    assert ("fresh", None, False, 5) in adapter._search_cache


async def test_search_cache_key_includes_category(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    monkeypatch.setattr(adapter, "_make_search", _counting_search_factory(calls))
    await adapter.search("q", limit=5)
    await adapter.search("q", limit=5, category="music")  # different category -> miss
    assert calls["n"] == 2


async def test_search_ttl_clamped_to_cache_max(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = MagicMock()
    settings.search_cache_ttl_seconds = 10_000_000
    monkeypatch.setattr(adapter, "get_settings", lambda: settings)
    monkeypatch.setattr(adapter, "_make_search", _counting_search_factory({"n": 0}))
    before = time.time()
    await adapter.search("q", limit=5)
    _, expiry = adapter._search_cache[("q", None, False, 5)]
    assert before + adapter._CACHE_MAX_TTL - 5.0 <= expiry <= before + adapter._CACHE_MAX_TTL + 5.0


async def test_concurrent_searches_single_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def slow_factory(q: str, *, filters: Any = None) -> MagicMock:
        calls["n"] += 1
        time.sleep(0.05)
        return _mock_search_result()

    monkeypatch.setattr(adapter, "_make_search", slow_factory)
    results = await asyncio.gather(*(adapter.search("same", limit=5) for _ in range(5)))
    assert calls["n"] == 1
    assert all([h.id for h in r] == ["vid00000001"] for r in results)
    # Each caller owns its own list (may filter/reorder); hits themselves are shared.
    assert len({id(r) for r in results}) == 5
    assert adapter._inflight_search == {}


async def test_search_hits_are_frozen() -> None:
    """The search cache hands out shallow list copies, so a mutable SearchHit
    would let one caller poison every later cache hit. Frozen makes it raise."""
    hit = SearchHit(kind="video", id="vid00000001", title="T", thumbnail_url="https://x/t.jpg")
    with pytest.raises(ValidationError):
        hit.title = "mutated"  # type: ignore[misc]


# ---- failure / cancellation paths -----------------------------------------


async def test_failed_video_fetch_is_not_cached_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient fetch failure must not be cached, must not wedge the
    in-flight registry, and must let the next call retry."""
    calls = {"n": 0}

    def flaky(vid: str) -> MagicMock:
        calls["n"] += 1
        if calls["n"] == 1:
            raise pytubefix_exceptions.PytubeFixError("transient upstream failure")
        return _mock_youtube(vid)

    monkeypatch.setattr(adapter, "_make_youtube", flaky)
    # _to_thread_mapped sends a bare PytubeFixError to the catch-all 502 bucket.
    with pytest.raises(adapter.YouTubeError) as exc:
        await adapter.video("dQw4w9WgXcQ")
    assert exc.value.status == 502
    assert "dQw4w9WgXcQ" not in adapter._video_details_cache
    assert adapter._inflight_video == {}
    details = await adapter.video("dQw4w9WgXcQ")  # retry succeeds
    assert details.title == "Test Title"
    assert calls["n"] == 2


async def test_video_joiner_survives_creator_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client disconnecting mid-fetch cancels ITS request task. That must not
    cancel the shared single-flight task other callers are waiting on — a
    CancelledError reaching a route handler is BaseException, so it escapes
    every handler in app.main and the client gets a torn connection instead of
    the mapped 4xx/5xx the frontend's recovery keys off.
    """
    monkeypatch.setattr(adapter, "_make_youtube", _counting_factory({"n": 0}, delay=0.3))

    creator = asyncio.create_task(adapter.video("dQw4w9WgXcQ"))
    await asyncio.sleep(0.05)  # let the creator register the in-flight task
    joiner = asyncio.create_task(adapter.video("dQw4w9WgXcQ"))
    await asyncio.sleep(0.05)  # let the joiner attach to it
    assert "dQw4w9WgXcQ" in adapter._inflight_video

    creator.cancel()  # client A disconnects
    with pytest.raises(asyncio.CancelledError):
        await creator

    assert (await joiner).title == "Test Title"  # client B still gets its answer


async def test_search_joiner_survives_creator_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same cancellation contract as video() — see that test for why."""

    def slow_factory(q: str, *, filters: Any = None) -> MagicMock:
        time.sleep(0.3)
        return _mock_search_result()

    monkeypatch.setattr(adapter, "_make_search", slow_factory)

    creator = asyncio.create_task(adapter.search("q", limit=5))
    await asyncio.sleep(0.05)
    joiner = asyncio.create_task(adapter.search("q", limit=5))
    await asyncio.sleep(0.05)
    assert ("q", None, False, 5) in adapter._inflight_search

    creator.cancel()
    with pytest.raises(asyncio.CancelledError):
        await creator

    assert [h.id for h in await joiner] == ["vid00000001"]
