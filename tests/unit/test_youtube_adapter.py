"""Tests for the pytubefix-based YouTube adapter."""
from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.adapters import youtube as adapter
from app.models import ChannelInfo, PlaylistInfo, VideoDetails


def _mock_stream(itag: int, mime_type: str, bitrate: int, **kw: Any) -> MagicMock:
    s = MagicMock()
    s.itag = itag
    s.mime_type = mime_type
    s.bitrate = bitrate
    s.url = f"https://rr1---sn-test.googlevideo.com/videoplayback?itag={itag}"
    s.includes_audio_track = "audio" in mime_type or kw.get("has_audio", False)
    s.includes_video_track = mime_type.startswith("video/")
    s.resolution = kw.get("resolution")
    s.fps = kw.get("fps")
    s.audio_sample_rate = kw.get("audio_sample_rate")
    # pytubefix-style attributes
    s.width = kw.get("width")
    s.height = kw.get("height")
    return s


def _mock_youtube(video_id: str = "dQw4w9WgXcQ") -> MagicMock:
    yt = MagicMock()
    yt.video_id = video_id
    yt.title = "Test Title"
    yt.author = "Test Author"
    yt.channel_id = "UCtest"
    yt.length = 213
    yt.views = 1_400_000_000
    yt.description = "Test description"
    yt.thumbnail_url = "https://i.ytimg.com/vi/" + video_id + "/maxres.jpg"
    streams = [
        _mock_stream(140, 'audio/mp4; codecs="mp4a.40.2"', 128000, audio_sample_rate=44100),
        _mock_stream(251, 'audio/webm; codecs="opus"', 160000, audio_sample_rate=48000),
        _mock_stream(
            137, 'video/mp4; codecs="avc1.640028"', 4_000_000,
            width=1920, height=1080, fps=30, resolution="1080p",
        ),
    ]
    sq = MagicMock()
    sq.__iter__ = lambda self: iter(streams)
    yt.streams = sq
    return yt


@pytest.fixture(autouse=True)
def reset_cache() -> None:
    adapter._stream_url_cache.clear()
    adapter._inflight_refresh.clear()


async def test_video_returns_details(monkeypatch: pytest.MonkeyPatch) -> None:
    yt_mock = _mock_youtube()
    monkeypatch.setattr(adapter, "_make_youtube", lambda vid: yt_mock)

    v = await adapter.video("dQw4w9WgXcQ")

    assert isinstance(v, VideoDetails)
    assert v.video_id == "dQw4w9WgXcQ"
    assert v.title == "Test Title"
    assert v.duration_seconds == 213
    assert v.audio_formats, "expected audio formats"
    assert v.video_formats, "expected video formats"
    # audio first format is one of the audio itags
    assert v.audio_formats[0].itag in {140, 251}


async def test_video_populates_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    yt_mock = _mock_youtube()
    monkeypatch.setattr(adapter, "_make_youtube", lambda vid: yt_mock)

    await adapter.video("dQw4w9WgXcQ")

    # Cache should have entries for each itag.
    keys = list(adapter._stream_url_cache.keys())
    assert ("dQw4w9WgXcQ", 140) in keys
    assert ("dQw4w9WgXcQ", 251) in keys


async def test_resolve_upstream_url_returns_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    yt_mock = _mock_youtube()
    monkeypatch.setattr(adapter, "_make_youtube", lambda vid: yt_mock)

    await adapter.video("dQw4w9WgXcQ")
    url = await adapter.resolve_upstream_url("dQw4w9WgXcQ", 140)
    assert url.startswith("https://rr1---sn-test.googlevideo.com/")


async def test_resolve_upstream_url_unknown_itag_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    yt_mock = _mock_youtube()
    monkeypatch.setattr(adapter, "_make_youtube", lambda vid: yt_mock)

    with pytest.raises(adapter.YouTubeError) as ei:
        await adapter.resolve_upstream_url("dQw4w9WgXcQ", 9999)
    assert ei.value.status == 404


def test_iter_streams_swallows_pytubefix_errors() -> None:
    """A yt whose .streams access raises (LiveStreamError, MembersOnly, …) must
    yield an empty iterator rather than propagating — a single dead video must
    not 500 the whole request."""
    class Boom:
        @property
        def streams(self) -> list[Any]:
            raise RuntimeError("LiveStreamError")

    assert list(adapter._iter_streams(Boom())) == []


def test_iter_streams_yields_when_iterable() -> None:
    class Ok:
        streams = [object(), object()]

    assert len(list(adapter._iter_streams(Ok()))) == 2


async def test_video_with_no_formats_returns_empty_lists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A video that exposes no usable streams yields empty format lists rather
    than erroring."""
    yt = MagicMock()
    yt.video_id = "noFormats00"
    yt.title = "No Formats"
    yt.author = "A"
    yt.channel_id = "UCx"
    yt.length = 10
    yt.views = 1
    yt.description = "d"
    empty = MagicMock()
    empty.__iter__ = lambda self: iter([])
    yt.streams = empty
    monkeypatch.setattr(adapter, "_make_youtube", lambda vid: yt)

    v = await adapter.video("noFormats00")
    assert v.audio_formats == []
    assert v.video_formats == []


def test_evict_expired_removes_stale_keeps_live() -> None:
    now = time.time()
    adapter._stream_url_cache[("vidA", 1)] = ("https://x/1", now - 10)    # expired
    adapter._stream_url_cache[("vidB", 2)] = ("https://x/2", now + 3600)  # live

    adapter._evict_expired()

    assert ("vidA", 1) not in adapter._stream_url_cache
    assert ("vidB", 2) in adapter._stream_url_cache


def test_evict_stream_url_removes_only_target_entry() -> None:
    adapter._stream_url_cache[("vidA", 140)] = ("https://x/1", time.time() + 100)
    adapter._stream_url_cache[("vidA", 251)] = ("https://x/2", time.time() + 100)

    adapter.evict_stream_url("vidA", 140)

    assert ("vidA", 140) not in adapter._stream_url_cache
    assert ("vidA", 251) in adapter._stream_url_cache


def test_evict_stream_url_missing_key_is_noop() -> None:
    adapter.evict_stream_url("nope", 999)  # must not raise


async def test_concurrent_resolve_dedupes_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent cache-miss resolves for the same video must collapse onto a
    single pytubefix fetch rather than each firing their own."""
    import asyncio

    yt_mock = _mock_youtube()
    calls = {"n": 0}

    def counting_make(vid: str) -> MagicMock:
        calls["n"] += 1
        return yt_mock

    monkeypatch.setattr(adapter, "_make_youtube", counting_make)

    results = await asyncio.gather(
        *[adapter.resolve_upstream_url("dQw4w9WgXcQ", 140) for _ in range(5)]
    )

    assert all(r.startswith("https://rr1---sn-test.googlevideo.com/") for r in results)
    assert calls["n"] == 1, f"expected 1 refresh, got {calls['n']}"
    # The in-flight entry must be cleaned up once the refresh completes.
    assert adapter._inflight_refresh == {}


async def test_resolve_rejects_and_evicts_stale_itag_after_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A previously-cached itag the refresh no longer offers must yield 404 —
    not a resurrected expired URL — and the stale entry must be evicted."""
    yt_mock = _mock_youtube()
    monkeypatch.setattr(adapter, "_make_youtube", lambda vid: yt_mock)
    # Seed an expired entry for an itag the fresh fetch won't provide (140/251/137).
    adapter._stream_url_cache[("dQw4w9WgXcQ", 999)] = (
        "https://stale.googlevideo.com/expired", time.time() - 1
    )

    with pytest.raises(adapter.YouTubeError) as ei:
        await adapter.resolve_upstream_url("dQw4w9WgXcQ", 999)

    assert ei.value.status == 404
    assert ("dQw4w9WgXcQ", 999) not in adapter._stream_url_cache


async def test_search_returns_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    v1 = MagicMock()
    v1.video_id = "abc123"
    v1.title = "Video One"
    v1.author = "Author One"
    v1.length = 100
    v1.thumbnail_url = "https://x/1"
    v2 = MagicMock()
    v2.video_id = "def456"
    v2.title = "Video Two"
    v2.author = "Author Two"
    v2.length = 200
    v2.thumbnail_url = "https://x/2"

    search_mock = MagicMock()
    search_mock.videos = [v1, v2]
    monkeypatch.setattr(adapter, "_make_search", lambda q, **kw: search_mock)

    hits = await adapter.search("anything", limit=10)

    assert len(hits) == 2
    assert hits[0].kind == "video"
    assert hits[0].id == "abc123"
    assert hits[0].title == "Video One"
    assert hits[0].duration_seconds == 100


async def test_channel_returns_info(monkeypatch: pytest.MonkeyPatch) -> None:
    ch = MagicMock()
    ch.channel_name = "Test Channel"
    ch.channel_id = "UCabcdef"
    ch.description = "channel description"
    monkeypatch.setattr(adapter, "_make_channel", lambda cid: ch)

    info = await adapter.channel("UCabcdef")
    assert isinstance(info, ChannelInfo)
    assert info.channel_id == "UCabcdef"
    assert info.title == "Test Channel"


async def test_playlist_returns_info(monkeypatch: pytest.MonkeyPatch) -> None:
    v = MagicMock()
    v.video_id = "vid1"
    v.title = "Item One"
    v.author = "Author"
    v.length = 60
    v.thumbnail_url = "https://x"

    pl = MagicMock()
    pl.title = "My Playlist"
    pl.length = 1
    pl.owner = "Owner"
    pl.owner_id = "UCowner"
    pl.videos = [v]
    monkeypatch.setattr(adapter, "_make_playlist", lambda pid: pl)

    info = await adapter.playlist("PLabc")
    assert isinstance(info, PlaylistInfo)
    assert info.playlist_id == "PLabc"
    assert info.title == "My Playlist"
    assert info.video_count == 1
    assert info.items[0].video_id == "vid1"


async def test_playlist_handles_missing_title(monkeypatch: pytest.MonkeyPatch) -> None:
    """pytubefix sometimes raises on .title for some playlists. Adapter should fall back."""
    pl = MagicMock()
    # property that raises
    type(pl).title = property(lambda self: (_ for _ in ()).throw(KeyError("simpleText")))
    pl.length = 0
    pl.owner = "Owner"
    pl.owner_id = "UCowner"
    pl.videos = []
    monkeypatch.setattr(adapter, "_make_playlist", lambda pid: pl)

    info = await adapter.playlist("PLbroken")
    # Falls back to a placeholder.
    assert info.playlist_id == "PLbroken"
    assert info.title  # not empty string


def test_search_passes_type_video_when_category_set(monkeypatch) -> None:
    """When category='music' is requested, the adapter must apply Filter type=Video."""
    import asyncio

    from app.adapters import youtube as adapter

    captured: dict = {}

    class FakeSearch:
        def __init__(self, query, filters=None, **kwargs):  # noqa: D401
            captured["query"] = query
            captured["filters"] = filters
        @property
        def videos(self): return []
        @property
        def channels(self): return []
        @property
        def playlists(self): return []

    monkeypatch.setattr(adapter, "_make_search", lambda q, **kw: FakeSearch(q, **kw))

    asyncio.run(adapter.search("foo", limit=5, category="music"))
    assert captured["filters"] is not None


def test_search_passes_live_feature(monkeypatch) -> None:
    """When live=True is requested, the adapter must apply Filter features=Live."""
    import asyncio

    from app.adapters import youtube as adapter

    captured: dict = {}

    class FakeSearch:
        def __init__(self, query, filters=None):
            captured["filters"] = filters
        @property
        def videos(self): return []
        @property
        def channels(self): return []
        @property
        def playlists(self): return []

    monkeypatch.setattr(adapter, "_make_search", lambda q, **kw: FakeSearch(q, **kw))
    asyncio.run(adapter.search("foo", limit=5, live=True))
    assert captured["filters"] is not None


def test_search_without_filters_passes_no_filter(monkeypatch) -> None:
    """Plain search() must NOT pass a filters arg (preserves legacy callers)."""
    import asyncio

    from app.adapters import youtube as adapter

    captured: dict = {"called_with_filters": False}

    class FakeSearch:
        def __init__(self, query, **kwargs):
            captured["called_with_filters"] = "filters" in kwargs and kwargs["filters"] is not None
        @property
        def videos(self): return []
        @property
        def channels(self): return []
        @property
        def playlists(self): return []

    monkeypatch.setattr(adapter, "_make_search", lambda q, **kw: FakeSearch(q, **kw))
    asyncio.run(adapter.search("foo", limit=5))
    assert captured["called_with_filters"] is False


def test_hit_from_pytube_video_extracts_is_live() -> None:
    """is_live is populated from the pytubefix video object when present."""
    from app.adapters.youtube import _hit_from_pytube_video

    class V:
        video_id = "abc"
        title = "t"
        author = "a"
        thumbnail_url = "x"
        length = 100
        is_live = True

    hit = _hit_from_pytube_video(V())
    assert hit.is_live is True


def test_build_search_filters_includes_music_topic_when_category_music() -> None:
    """category='music' must produce a filters dict that triggers the music topic sp injection."""
    from app.adapters.youtube import _build_search_filters

    f = _build_search_filters(category="music", live=False)
    assert f is not None
    # The implementation marks the music filter with a sentinel key the
    # search() wrapper later recognises and acts on.
    assert f.get("_music_topic") is True


def test_search_overwrites_filter_when_category_music(monkeypatch) -> None:
    """When category='music' is requested, search() must overwrite `s.filter`
    via `_inject_music_topic` so the InnerTube call carries the music topic."""
    import asyncio

    from app.adapters import youtube as adapter

    class FakeSearch:
        def __init__(self, query, filters=None):
            self.filter = "PYTUBEFIX_DEFAULT"
        @property
        def videos(self): return []
        @property
        def channels(self): return []
        @property
        def playlists(self): return []

    monkeypatch.setattr(adapter, "_make_search", lambda q, **kw: FakeSearch(q, **kw))

    captured_args: dict = {}

    def fake_inject(search_instance, pytubefix_filters):
        captured_args["pytubefix_filters"] = pytubefix_filters
        search_instance.filter = "INJECTED"

    monkeypatch.setattr(adapter, "_inject_music_topic", fake_inject)

    asyncio.run(adapter.search("foo", limit=5, category="music"))
    # The injector was called with the type=Video filters dict (sans sentinel).
    assert captured_args["pytubefix_filters"] is not None
    assert "_music_topic" not in captured_args["pytubefix_filters"]


def test_search_does_not_inject_when_category_absent(monkeypatch) -> None:
    """category=None must not invoke `_inject_music_topic`."""
    import asyncio

    from app.adapters import youtube as adapter

    class FakeSearch:
        def __init__(self, query, filters=None):
            self.filter = None
        @property
        def videos(self): return []
        @property
        def channels(self): return []
        @property
        def playlists(self): return []

    monkeypatch.setattr(adapter, "_make_search", lambda q, **kw: FakeSearch(q, **kw))

    called = {"injected": False}

    def fake_inject(search_instance, pytubefix_filters):
        called["injected"] = True

    monkeypatch.setattr(adapter, "_inject_music_topic", fake_inject)

    asyncio.run(adapter.search("foo", limit=5, live=True))
    assert called["injected"] is False


def test_inject_music_topic_overwrites_filter() -> None:
    """`_inject_music_topic` rebuilds and overwrites `search_instance.filter`."""
    from app.adapters.youtube import _inject_music_topic

    class Stub:
        filter = "ORIGINAL"

    s = Stub()
    _inject_music_topic(s, {"type": {2: 1}, "features": [{8: 1}]})
    assert isinstance(s.filter, str)
    assert s.filter != "ORIGINAL"
    assert len(s.filter) > 0


def test_inject_music_topic_handles_empty_filters() -> None:
    """`_inject_music_topic` works even when pytubefix_filters is None."""
    from app.adapters.youtube import _inject_music_topic

    class Stub:
        filter = None

    s = Stub()
    _inject_music_topic(s, None)
    assert isinstance(s.filter, str)
    assert len(s.filter) > 0


def test_fetch_live_manifest_returns_info_when_url_present() -> None:
    from app.adapters.youtube import LiveStreamInfo, _fetch_live_manifest

    class FakeYouTube:
        video_id = "abc12345678"
        vid_info = {
            "streamingData": {
                "hlsManifestUrl": "https://manifest.googlevideo.com/api/manifest/hls_variant/x"
            },
            "videoDetails": {
                "title": "Lofi Hip Hop Radio",
                "author": "ChilledCow",
                "channelId": "UCSJ4gkVC6NrvII8umztf0Ow",
            },
        }

    import app.adapters.youtube as adapter
    saved = adapter._make_youtube
    try:
        adapter._make_youtube = lambda vid: FakeYouTube()
        info = _fetch_live_manifest("abc12345678")
    finally:
        adapter._make_youtube = saved

    assert isinstance(info, LiveStreamInfo)
    assert info.video_id == "abc12345678"
    assert info.title == "Lofi Hip Hop Radio"
    assert info.author == "ChilledCow"
    assert info.channel_id == "UCSJ4gkVC6NrvII8umztf0Ow"
    assert info.master_hls_url.startswith("https://manifest.googlevideo.com/")


def test_fetch_live_manifest_returns_none_when_hls_url_missing() -> None:
    from app.adapters.youtube import _fetch_live_manifest

    class FakeYouTube:
        video_id = "abc12345678"
        vid_info = {
            "streamingData": {},
            "videoDetails": {"title": "t", "author": "a", "channelId": "c"},
        }

    import app.adapters.youtube as adapter
    saved = adapter._make_youtube
    try:
        adapter._make_youtube = lambda vid: FakeYouTube()
        assert _fetch_live_manifest("abc12345678") is None
    finally:
        adapter._make_youtube = saved


def test_fetch_live_manifest_returns_none_on_exception() -> None:
    from app.adapters.youtube import _fetch_live_manifest

    def boom(vid):
        raise RuntimeError("upstream is sad")

    import app.adapters.youtube as adapter
    saved = adapter._make_youtube
    try:
        adapter._make_youtube = boom
        assert _fetch_live_manifest("abc12345678") is None
    finally:
        adapter._make_youtube = saved


def test_resolve_live_master_url_returns_url_on_first_call(monkeypatch) -> None:
    import asyncio

    import app.adapters.youtube as adapter
    from app.adapters.youtube import LiveStreamInfo

    monkeypatch.setattr(
        adapter, "_fetch_live_manifest",
        lambda vid: LiveStreamInfo(
            video_id=vid, title="t", author="a", channel_id="c",
            thumbnail_url="x",
            master_hls_url="https://manifest.googlevideo.com/abc?expire=999999999",
        ),
    )
    adapter._stream_url_cache.clear()
    url = asyncio.run(adapter.resolve_live_master_url("vid12345678"))
    assert "manifest.googlevideo.com" in url


def test_resolve_live_master_url_caches_result(monkeypatch) -> None:
    import asyncio

    import app.adapters.youtube as adapter
    from app.adapters.youtube import LiveStreamInfo

    calls = {"n": 0}
    def fake_fetch(vid):
        calls["n"] += 1
        return LiveStreamInfo(
            video_id=vid, title="t", author="a", channel_id="c",
            thumbnail_url="x",
            master_hls_url="https://manifest.googlevideo.com/abc?expire=999999999",
        )

    monkeypatch.setattr(adapter, "_fetch_live_manifest", fake_fetch)
    adapter._stream_url_cache.clear()
    asyncio.run(adapter.resolve_live_master_url("vid12345678"))
    asyncio.run(adapter.resolve_live_master_url("vid12345678"))
    assert calls["n"] == 1


def test_resolve_live_master_url_raises_when_fetch_returns_none(monkeypatch) -> None:
    import asyncio

    import pytest

    import app.adapters.youtube as adapter

    monkeypatch.setattr(adapter, "_fetch_live_manifest", lambda vid: None)
    adapter._stream_url_cache.clear()
    with pytest.raises(adapter.YouTubeError) as exc_info:
        asyncio.run(adapter.resolve_live_master_url("vid12345678"))
    assert exc_info.value.status == 502
    assert exc_info.value.code == "LIVE_UNAVAILABLE"


def test_normalise_video_returns_live_video_details_when_live() -> None:
    from pytubefix.exceptions import LiveStreamError

    import app.adapters.youtube as adapter
    from app.adapters.youtube import LiveStreamInfo, _normalise_video

    class FakeYouTube:
        video_id = "abc12345678"
        @property
        def length(self):
            raise LiveStreamError(video_id="abc12345678")

    saved = adapter._fetch_live_manifest
    try:
        adapter._fetch_live_manifest = lambda vid: LiveStreamInfo(
            video_id=vid, title="Lofi Radio", author="ChilledCow",
            channel_id="UC1", thumbnail_url=f"/proxy/thumbnail/{vid}",
            master_hls_url="https://manifest.googlevideo.com/abc",
        )
        details = _normalise_video("abc12345678", FakeYouTube())
    finally:
        adapter._fetch_live_manifest = saved

    assert details.is_live is True
    assert details.live_stream_url == "/api/live/abc12345678/manifest.m3u8"
    assert details.title == "Lofi Radio"
    assert details.author == "ChilledCow"
    assert details.audio_formats == []
    assert details.video_formats == []
    assert details.duration_seconds == 0


def test_normalise_video_raises_when_live_and_manifest_unavailable() -> None:
    import pytest
    from pytubefix.exceptions import LiveStreamError

    import app.adapters.youtube as adapter
    from app.adapters.youtube import _normalise_video

    class FakeYouTube:
        video_id = "abc12345678"
        @property
        def length(self):
            raise LiveStreamError(video_id="abc12345678")

    saved = adapter._fetch_live_manifest
    try:
        adapter._fetch_live_manifest = lambda vid: None
        with pytest.raises(adapter.YouTubeError) as exc_info:
            _normalise_video("abc12345678", FakeYouTube())
        assert exc_info.value.status == 422
        assert exc_info.value.code == "LIVE_NOT_SUPPORTED"
    finally:
        adapter._fetch_live_manifest = saved


def test_normalise_video_detects_live_via_vid_info_without_exception() -> None:
    """Some live videos don't raise LiveStreamError — vid_info.videoDetails.isLive
    is the only signal. Prefer the live path in that case."""
    import app.adapters.youtube as adapter
    from app.adapters.youtube import LiveStreamInfo, _normalise_video

    class FakeYouTube:
        video_id = "abc12345678"
        vid_info = {
            "videoDetails": {"isLive": True, "title": "ignored", "author": "ignored"},
            "streamingData": {"hlsManifestUrl": "https://manifest.googlevideo.com/x"},
        }
        # No exception on length — this is the "live but not LiveStreamError" case.
        length = 0
        title = "ignored"
        author = "ignored"
        channel_id = "ignored"
        description = None
        views = 0

    saved = adapter._fetch_live_manifest
    try:
        adapter._fetch_live_manifest = lambda vid: LiveStreamInfo(
            video_id=vid, title="Lofi Radio", author="ChilledCow",
            channel_id="UC1", thumbnail_url=f"/proxy/thumbnail/{vid}",
            master_hls_url="https://manifest.googlevideo.com/x",
        )
        details = _normalise_video("abc12345678", FakeYouTube())
    finally:
        adapter._fetch_live_manifest = saved

    assert details.is_live is True
    assert details.live_stream_url == "/api/live/abc12345678/manifest.m3u8"
    assert details.title == "Lofi Radio"
    assert details.audio_formats == []


def test_normalise_video_falls_through_to_vod_when_is_live_false() -> None:
    """vid_info.videoDetails.isLive=false → no upfront live dispatch; VOD path runs."""
    import app.adapters.youtube as adapter
    from app.adapters.youtube import _normalise_video

    class FakeStream:
        mime_type = "audio/mp4"
        itag = 140
        bitrate = 128000
        url = "https://upstream.example/seg"
        codecs = "mp4a.40.2"
        sample_rate = 44100
        channels = 2
        type = "audio"
        is_progressive = False

    class FakeYouTube:
        video_id = "abc12345678"
        vid_info = {"videoDetails": {"isLive": False}}
        length = 123
        title = "Normal VOD"
        author = "Some Author"
        channel_id = "UC1"
        description = "desc"
        views = 1000

        @property
        def streaming_data(self):
            return None

    # Avoid the full stream iteration path by stubbing _iter_streams.
    saved_iter = adapter._iter_streams
    try:
        adapter._iter_streams = lambda yt: []
        details = _normalise_video("abc12345678", FakeYouTube())
    finally:
        adapter._iter_streams = saved_iter

    assert details.is_live is False
    assert details.title == "Normal VOD"
