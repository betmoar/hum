"""Tests for the VideoDetails metadata cache (single-flight, deep-copy, live bypass)."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from yt_dlp.utils import DownloadError

from app.adapters import youtube as adapter
from app.models import SearchHit

# ---- yt-dlp fakes -----------------------------------------------------------
#
# `adapter._make_ydl(opts)` is the seam: it returns a YoutubeDL-like context
# manager whose `extract_info(url, download=False)` either returns a yt-dlp
# info dict or raises. `_FakeYDL` stands in for the real YoutubeDL; `respond`
# dispatches on the requested URL so the same fake can serve both video
# ("/watch?v=") and search ("/results?") extractions.


class _FakeYDL:
    """Test double for yt_dlp.YoutubeDL: a context manager whose extract_info
    counts calls, can sleep to simulate a slow fetch, and can raise."""

    def __init__(
        self, respond: Callable[[str], dict[str, Any]], calls: dict[str, int], delay: float,
    ) -> None:
        self._respond = respond
        self._calls = calls
        self._delay = delay

    def __enter__(self) -> _FakeYDL:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def extract_info(self, url: str, download: bool = False) -> dict[str, Any]:
        self._calls["n"] += 1
        if self._delay:
            time.sleep(self._delay)
        return self._respond(url)


def _video_info(
    video_id: str = "dQw4w9WgXcQ",
    *,
    title: str = "Test Title",
    channel: str = "Test Author",
    channel_id: str = "UCtest",
    duration: int = 213,
    view_count: int | None = 1000,
    description: str | None = "d",
    itag: int = 140,
) -> dict[str, Any]:
    expire = int(time.time()) + 3600
    return {
        "id": video_id,
        "title": title,
        "channel": channel,
        "channel_id": channel_id,
        "duration": duration,
        "view_count": view_count,
        "description": description,
        "live_status": "not_live",
        "formats": [
            {
                "format_id": str(itag),
                "url": (
                    "https://rr1---sn-test.googlevideo.com/videoplayback"
                    f"?itag={itag}&expire={expire}"
                ),
                "protocol": "https",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "ext": "m4a",
                "abr": 128,
            }
        ],
    }


def _live_video_info(
    video_id: str = "livevid12345",
    *,
    title: str = "L",
    author: str = "A",
    channel_id: str = "C",
) -> dict[str, Any]:
    manifest = "https://manifest.googlevideo.com/x.m3u8"
    return {
        "id": video_id,
        "title": title,
        "channel": author,
        "channel_id": channel_id,
        "duration": 0,
        "view_count": None,
        "description": None,
        "live_status": "is_live",
        "formats": [
            {
                "format_id": "233",
                "protocol": "m3u8_native",
                "manifest_url": manifest,
                "url": manifest,
            }
        ],
    }


def _search_info(
    *, hit_id: str = "vid00000001", title: str = "Hit", channel: str = "A",
) -> dict[str, Any]:
    return {
        "_type": "playlist",
        "entries": [
            {
                "_type": "url",
                "ie_key": "Youtube",
                "id": hit_id,
                "url": f"https://www.youtube.com/watch?v={hit_id}",
                "title": title,
                "channel": channel,
                "duration": 100,
            }
        ],
    }


def _playlist_info(
    *, playlist_id: str = "PLtest", title: str = "P", count: int = 1,
) -> dict[str, Any]:
    return {
        "title": title,
        "uploader": "Curator",
        "playlist_count": count,
        "entries": [
            {"id": "vid1", "title": "Item One", "channel": "Author", "duration": 60},
        ],
    }


def _default_respond(url: str) -> dict[str, Any]:
    """Dispatch a canned info dict by URL shape: search hits an entries page,
    playlist hits a playlist page, video hits a watch page."""
    if "/results?" in url:
        return _search_info()
    if "/playlist?" in url:
        return _playlist_info()
    return _video_info()


def _ydl_factory(
    respond: Callable[[str], dict[str, Any]] = _default_respond,
    *,
    delay: float = 0.0,
    calls: dict[str, int] | None = None,
) -> tuple[Callable[[dict[str, Any]], _FakeYDL], dict[str, int]]:
    calls = calls if calls is not None else {"n": 0}

    def factory(opts: dict[str, Any]) -> _FakeYDL:
        return _FakeYDL(respond, calls, delay)

    return factory, calls


async def test_video_cache_hit_skips_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    factory, _ = _ydl_factory(calls=calls)
    monkeypatch.setattr(adapter, "_make_ydl", factory)
    v1 = await adapter.video("dQw4w9WgXcQ")
    v2 = await adapter.video("dQw4w9WgXcQ")
    assert calls["n"] == 1
    assert v1.title == v2.title == "Test Title"


async def test_video_cache_expiry_refetches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    factory, _ = _ydl_factory(calls=calls)
    monkeypatch.setattr(adapter, "_make_ydl", factory)
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
    factory, _ = _ydl_factory()
    monkeypatch.setattr(adapter, "_make_ydl", factory)
    v1 = await adapter.video("dQw4w9WgXcQ")
    v2 = await adapter.video("dQw4w9WgXcQ")
    assert v1 is not v2
    v1.audio_formats[0].url += "&exp=1&sig=" + "ab" * 16  # simulate signing
    assert "sig=" not in v2.audio_formats[0].url
    cached, _ = adapter._video_details_cache["dQw4w9WgXcQ"]
    assert all("sig=" not in af.url for af in cached.audio_formats)


async def test_concurrent_misses_single_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    factory, _ = _ydl_factory(calls=calls, delay=0.05)
    monkeypatch.setattr(adapter, "_make_ydl", factory)

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
    def respond(url: str) -> dict[str, Any]:
        return _live_video_info("livevid12345", title="L", author="A", channel_id="C")

    factory, _ = _ydl_factory(respond)
    monkeypatch.setattr(adapter, "_make_ydl", factory)
    v1 = await adapter.video("livevid12345")
    v2 = await adapter.video("livevid12345")
    assert v1.is_live and v2.is_live
    assert adapter._video_details_cache == {}


async def test_video_ttl_clamped_to_cache_max(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = MagicMock()
    settings.video_cache_ttl_seconds = 10_000_000
    monkeypatch.setattr(adapter, "get_settings", lambda: settings)
    factory, _ = _ydl_factory()
    monkeypatch.setattr(adapter, "_make_ydl", factory)
    before = time.time()
    await adapter.video("dQw4w9WgXcQ")
    _, expiry = adapter._video_details_cache["dQw4w9WgXcQ"]
    # Bounded on BOTH sides: an upper-only bound would also pass if the clamp
    # collapsed the TTL to ~0 (e.g. min() operands swapped).
    assert before + adapter._CACHE_MAX_TTL - 5.0 <= expiry <= before + adapter._CACHE_MAX_TTL + 5.0


# ---- search cache ---------------------------------------------------------


async def test_search_cache_hit_skips_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    factory, _ = _ydl_factory(calls=calls)
    monkeypatch.setattr(adapter, "_make_ydl", factory)
    r1 = await adapter.search("cache me", limit=5)
    r2 = await adapter.search("cache me", limit=5)
    assert calls["n"] == 1
    assert [h.id for h in r1] == [h.id for h in r2] == ["vid00000001"]


async def test_search_cache_key_includes_params(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    factory, _ = _ydl_factory(calls=calls)
    monkeypatch.setattr(adapter, "_make_ydl", factory)
    await adapter.search("q", limit=5)
    await adapter.search("q", limit=10)          # different limit -> miss
    await adapter.search("q", limit=5, live=True)  # different live -> miss
    assert calls["n"] == 3


async def test_search_cache_expiry_refetches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    factory, _ = _ydl_factory(calls=calls)
    monkeypatch.setattr(adapter, "_make_ydl", factory)
    await adapter.search("q", limit=5)
    key = ("q", None, False, 5)
    hits, _ = adapter._search_cache[key]
    adapter._search_cache[key] = (hits, time.time() - 1)
    await adapter.search("q", limit=5)
    assert calls["n"] == 2


async def test_search_write_sweeps_all_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    """A search-only session must still evict expired entries everywhere —
    _refresh_cache (the old sole sweep site) never runs on this path."""
    factory, _ = _ydl_factory()
    monkeypatch.setattr(adapter, "_make_ydl", factory)
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
    factory, _ = _ydl_factory(calls=calls)
    monkeypatch.setattr(adapter, "_make_ydl", factory)
    await adapter.search("q", limit=5)
    await adapter.search("q", limit=5, category="music")  # different category -> miss
    assert calls["n"] == 2


async def test_search_ttl_clamped_to_cache_max(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = MagicMock()
    settings.search_cache_ttl_seconds = 10_000_000
    monkeypatch.setattr(adapter, "get_settings", lambda: settings)
    factory, _ = _ydl_factory()
    monkeypatch.setattr(adapter, "_make_ydl", factory)
    before = time.time()
    await adapter.search("q", limit=5)
    _, expiry = adapter._search_cache[("q", None, False, 5)]
    assert before + adapter._CACHE_MAX_TTL - 5.0 <= expiry <= before + adapter._CACHE_MAX_TTL + 5.0


async def test_concurrent_searches_single_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    factory, _ = _ydl_factory(calls=calls, delay=0.05)
    monkeypatch.setattr(adapter, "_make_ydl", factory)
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


# ---- playlist cache --------------------------------------------------------


async def test_playlist_cache_hit_skips_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    factory, _ = _ydl_factory(calls=calls)
    monkeypatch.setattr(adapter, "_make_ydl", factory)
    p1 = await adapter.playlist("PLtest")
    p2 = await adapter.playlist("PLtest")
    assert calls["n"] == 1
    assert p1.title == p2.title == "P"


async def test_playlist_cache_key_includes_start_and_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    factory, _ = _ydl_factory(calls=calls)
    monkeypatch.setattr(adapter, "_make_ydl", factory)
    await adapter.playlist("PLtest", start=1, limit=50)
    await adapter.playlist("PLtest", start=1, limit=100)  # different limit -> miss
    await adapter.playlist("PLtest", start=51, limit=50)  # different start -> miss
    assert calls["n"] == 3


async def test_playlist_cache_expiry_refetches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    factory, _ = _ydl_factory(calls=calls)
    monkeypatch.setattr(adapter, "_make_ydl", factory)
    await adapter.playlist("PLtest")
    key = ("PLtest", 1, adapter._PLAYLIST_DEFAULT_LIMIT)
    info, _ = adapter._playlist_cache[key]
    adapter._playlist_cache[key] = (info, time.time() - 1)
    await adapter.playlist("PLtest")
    assert calls["n"] == 2


async def test_playlist_ttl_clamped_to_cache_max(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = MagicMock()
    settings.playlist_cache_ttl_seconds = 10_000_000
    monkeypatch.setattr(adapter, "get_settings", lambda: settings)
    factory, _ = _ydl_factory()
    monkeypatch.setattr(adapter, "_make_ydl", factory)
    before = time.time()
    await adapter.playlist("PLtest")
    key = ("PLtest", 1, adapter._PLAYLIST_DEFAULT_LIMIT)
    _, expiry = adapter._playlist_cache[key]
    assert before + adapter._CACHE_MAX_TTL - 5.0 <= expiry <= before + adapter._CACHE_MAX_TTL + 5.0


async def test_playlist_write_sweeps_all_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    """A playlist-only session must still evict expired entries everywhere —
    the video/search sweep sites never run on this path."""
    factory, _ = _ydl_factory()
    monkeypatch.setattr(adapter, "_make_ydl", factory)
    stale = time.time() - 10
    adapter._stream_url_cache[("dead", 140)] = ("https://x", stale)
    adapter._video_details_cache["dead"] = (MagicMock(), stale)
    adapter._search_cache[("old", None, False, 20)] = ([], stale)
    old_key = ("PLold", 1, 200)
    adapter._playlist_cache[old_key] = (MagicMock(), stale)
    await adapter.playlist("PLtest")
    assert ("dead", 140) not in adapter._stream_url_cache
    assert "dead" not in adapter._video_details_cache
    assert ("old", None, False, 20) not in adapter._search_cache
    assert old_key not in adapter._playlist_cache
    assert ("PLtest", 1, adapter._PLAYLIST_DEFAULT_LIMIT) in adapter._playlist_cache


async def test_concurrent_playlist_fetches_single_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    factory, _ = _ydl_factory(calls=calls, delay=0.05)
    monkeypatch.setattr(adapter, "_make_ydl", factory)
    results = await asyncio.gather(*(adapter.playlist("PLtest") for _ in range(5)))
    assert calls["n"] == 1
    assert all(r.title == "P" for r in results)
    assert len({id(r) for r in results}) == 5
    assert adapter._inflight_playlist == {}


async def test_failed_playlist_fetch_is_not_cached_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same contract as test_failed_video_fetch_is_not_cached_and_retries."""
    calls = {"n": 0}

    def respond(url: str) -> dict[str, Any]:
        if calls["n"] == 1:
            raise DownloadError("ERROR: [youtube:tab] PLtest: HTTP Error 500")
        return _default_respond(url)

    factory, calls = _ydl_factory(respond, calls=calls)
    monkeypatch.setattr(adapter, "_make_ydl", factory)
    with pytest.raises(adapter.YouTubeError) as exc:
        await adapter.playlist("PLtest")
    assert exc.value.status == 502
    assert adapter._playlist_cache == {}
    assert adapter._inflight_playlist == {}
    info = await adapter.playlist("PLtest")  # retry succeeds
    assert info.title == "P"
    assert calls["n"] == 2


async def test_playlist_joiner_survives_creator_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same cancellation contract as video()/search() — see test_video_joiner_
    survives_creator_cancellation for why."""
    factory, _ = _ydl_factory(delay=0.3)
    monkeypatch.setattr(adapter, "_make_ydl", factory)

    creator = asyncio.create_task(adapter.playlist("PLtest"))
    await asyncio.sleep(0.05)
    joiner = asyncio.create_task(adapter.playlist("PLtest"))
    await asyncio.sleep(0.05)
    assert ("PLtest", 1, adapter._PLAYLIST_DEFAULT_LIMIT) in adapter._inflight_playlist

    creator.cancel()
    with pytest.raises(asyncio.CancelledError):
        await creator

    assert (await joiner).title == "P"


# ---- failure / cancellation paths -----------------------------------------


async def test_failed_video_fetch_is_not_cached_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient fetch failure must not be cached, must not wedge the
    in-flight registry, and must let the next call retry."""
    calls = {"n": 0}

    def respond(url: str) -> dict[str, Any]:
        if calls["n"] == 1:
            raise DownloadError("ERROR: [youtube] dQw4w9WgXcQ: Video unavailable")
        return _video_info()

    factory, calls = _ydl_factory(respond, calls=calls)
    monkeypatch.setattr(adapter, "_make_ydl", factory)
    # A yt-dlp DownloadError with unavailable-style wording maps to a 404, not
    # a bare crash — the frontend's recovery path keys off the status.
    with pytest.raises(adapter.YouTubeError) as exc:
        await adapter.video("dQw4w9WgXcQ")
    assert exc.value.status == 404
    assert exc.value.code == "VIDEO_UNAVAILABLE"
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
    factory, _ = _ydl_factory(delay=0.3)
    monkeypatch.setattr(adapter, "_make_ydl", factory)

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
    factory, _ = _ydl_factory(delay=0.3)
    monkeypatch.setattr(adapter, "_make_ydl", factory)

    creator = asyncio.create_task(adapter.search("q", limit=5))
    await asyncio.sleep(0.05)
    joiner = asyncio.create_task(adapter.search("q", limit=5))
    await asyncio.sleep(0.05)
    assert ("q", None, False, 5) in adapter._inflight_search

    creator.cancel()
    with pytest.raises(asyncio.CancelledError):
        await creator

    assert [h.id for h in await joiner] == ["vid00000001"]
