"""Tests for the yt-dlp-based YouTube adapter (app/adapters/youtube.py).

YoutubeDL is faked via youtube._make_ydl; no network. Covers format mapping,
error mapping, caching/single-flight, live-stream handling, channel/playlist
mapping, search sp-param filtering, and the deno startup check.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.parse
from pathlib import Path
from typing import Any

import pytest

from app.adapters import youtube
from app.adapters.search_params import build_search_sp
from app.adapters.youtube import YouTubeError
from app.models import ChannelInfo, PlaylistInfo, VideoDetails

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ytdlp"
EXPIRE = int(time.time()) + 20000  # beyond the 1 h clamp


def _fmt(format_id: str, **kw: Any) -> dict[str, Any]:
    base = {
        "format_id": format_id,
        "url": f"https://rr1---sn.googlevideo.com/videoplayback?itag={format_id}&expire={EXPIRE}",
        "protocol": "https",
        "vcodec": "none",
        "acodec": "none",
    }
    base.update(kw)
    return base


VOD_INFO: dict[str, Any] = {
    "id": "abc12345678",
    "title": "Song",
    "channel": "Artist",
    "uploader": "Artist - Topic",
    "channel_id": "UC123",
    "duration": 215,
    "view_count": 1000,
    "live_status": "not_live",
    "formats": [
        _fmt("sb0", ext="mhtml", protocol="mhtml"),
        _fmt("140", ext="m4a", acodec="mp4a.40.2", abr=129.5, asr=44100, audio_channels=2),
        _fmt("140-drc", ext="m4a", acodec="mp4a.40.2", abr=129.5),
        _fmt("251", ext="webm", acodec="opus", abr=140.1, asr=48000, audio_channels=2),
        _fmt("251", ext="webm", acodec="opus", abr=1.0),  # duplicate itag from a 2nd client
        _fmt("233", ext="mp4", acodec="mp4a.40.5", protocol="m3u8_native"),
        _fmt("18", ext="mp4", vcodec="avc1.42001E", acodec="mp4a.40.2", tbr=500.0,
             width=640, height=360, fps=30),
        _fmt("137", ext="mp4", vcodec="avc1.640028", tbr=4000.0, width=1920, height=1080, fps=30),
    ],
}

NO_FORMATS_INFO: dict[str, Any] = {
    "id": "noFormats00",
    "title": "No Formats",
    "channel": "A",
    "channel_id": "UCx",
    "duration": 10,
    "view_count": 1,
    "live_status": "not_live",
    "formats": [],
}

LIVE_INFO: dict[str, Any] = {
    "id": "live1234567",
    "title": "Radio",
    "channel": "Station",
    "channel_id": "UCLIVE",
    "live_status": "is_live",
    "formats": [_fmt("95", ext="mp4", protocol="m3u8_native", vcodec="avc1", acodec="mp4a.40.2",
                     manifest_url="https://manifest.googlevideo.com/api/manifest/hls_variant/x")],
}

LIVE_NO_MANIFEST_INFO: dict[str, Any] = {
    "id": "live1234567",
    "title": "Radio",
    "channel": "Station",
    "channel_id": "UCLIVE",
    "live_status": "is_live",
    "formats": [_fmt("95", ext="mp4", protocol="https", vcodec="avc1", acodec="mp4a.40.2")],
}

SEARCH_INFO: dict[str, Any] = {
    "_type": "playlist",
    "entries": [
        {"_type": "url", "ie_key": "Youtube", "id": "vid00000001", "title": "Track One",
         "channel": "Artist A", "duration": 200.0,
         "thumbnails": [{"url": "https://i.ytimg.com/vi/vid00000001/hq720.jpg"}],
         "url": "https://www.youtube.com/watch?v=vid00000001"},
        {"_type": "url", "ie_key": "Youtube", "id": "vid00000002", "title": "Live Set",
         "channel": "Artist B", "live_status": "is_live",
         "url": "https://www.youtube.com/watch?v=vid00000002"},
        {"_type": "url", "ie_key": "YoutubeTab", "id": "UCchan", "title": "Artist A",
         "url": "https://www.youtube.com/channel/UCchan",
         "thumbnails": [{"url": "//yt3.ggpht.com/abc"}]},
        {"_type": "url", "ie_key": "YoutubeTab", "id": "PLlist", "title": "Best Of",
         "uploader": "Curator", "playlist_count": 12,
         "url": "https://www.youtube.com/playlist?list=PLlist"},
    ],
}

CHANNEL_INFO: dict[str, Any] = {
    "id": "UCabc123",
    "channel_id": "UCabc123",
    "channel": "Test Channel",
    "description": "channel description",
    "channel_follower_count": 5000,
    "thumbnails": [
        # Widest is "banner", but avatar_uncropped must still win (preferred id).
        {"id": "avatar_uncropped", "url": "https://yt3.ggpht.com/avatar_uncropped.jpg", "width": 800},
        {"id": "banner_uncropped", "url": "https://yt3.ggpht.com/banner.jpg", "width": 1920},
    ],
}

PLAYLIST_INFO: dict[str, Any] = {
    "title": "My Playlist",
    "uploader": "Curator",
    "playlist_count": 2,
    "entries": [
        {"id": "vid1", "title": "Item One", "channel": "Author", "duration": 60,
         "thumbnails": [{"url": "https://i.ytimg.com/vi/vid1/default.jpg", "width": 120},
                        {"url": "https://i.ytimg.com/vi/vid1/hq720.jpg", "width": 1280}]},
        {"id": None, "title": "Skip Me — no id"},
        "not-a-dict",
    ],
}

PLAYLIST_MISSING_TITLE_INFO: dict[str, Any] = {
    "title": "",
    "entries": [],
}


def _captured(name: str, fallback: dict[str, Any]) -> dict[str, Any]:
    p = FIXTURES / name
    return json.loads(p.read_text()) if p.exists() else fallback


class FakeYDL:
    calls: list[tuple[dict[str, Any], str]] = []

    def __init__(self, opts: dict[str, Any], result: Any) -> None:
        self.opts = opts
        self.result = result

    def __enter__(self) -> FakeYDL:
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def extract_info(self, url: str, download: bool = True) -> Any:
        assert download is False
        FakeYDL.calls.append((self.opts, url))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


@pytest.fixture(autouse=True)
def _clean() -> None:
    # Adapter caches are cleared by the conftest autouse fixture; only the
    # FakeYDL call log is local to this file.
    FakeYDL.calls = []


def _install(monkeypatch: pytest.MonkeyPatch, result: Any) -> None:
    monkeypatch.setattr(youtube, "_make_ydl", lambda opts: FakeYDL(opts, result))


# ---- _fetch_video (sync, thread-bound) -------------------------------------


def test_vod_maps_formats_and_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, VOD_INFO)
    d = youtube._fetch_video("abc12345678")
    assert (d.title, d.author, d.channel_id, d.duration_seconds, d.view_count) == (
        "Song", "Artist", "UC123", 215, 1000)
    assert d.thumbnail_url == "/proxy/thumbnail/abc12345678"
    assert d.is_live is False
    assert [(a.itag, a.mime_type, a.codec, a.bitrate) for a in d.audio_formats] == [
        (140, 'audio/mp4; codecs="mp4a.40.2"', "aac", 129500),
        (251, 'audio/webm; codecs="opus"', "opus", 140100),
    ]
    assert d.audio_formats[0].url == "/proxy/audio/abc12345678?itag=140"
    assert d.audio_formats[0].sample_rate == 44100
    assert [(v.itag, v.has_audio, v.height) for v in d.video_formats] == [(18, True, 360), (137, False, 1080)]
    assert d.video_formats[0].url == "/proxy/stream/abc12345678?itag=18"


def test_vod_writes_stream_cache_with_clamped_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, VOD_INFO)
    before = time.time()
    youtube._fetch_video("abc12345678")
    url, expiry = youtube._stream_url_cache[("abc12345678", 140)]
    assert "itag=140" in url
    assert expiry <= time.time() + youtube._CACHE_MAX_TTL
    assert expiry >= before + youtube._CACHE_MAX_TTL - 5
    # First occurrence of a duplicated itag wins; non-numeric ids and manifests are skipped.
    assert "itag=251" in youtube._stream_url_cache[("abc12345678", 251)][0]
    assert ("abc12345678", 233) not in youtube._stream_url_cache


def test_vod_options(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, VOD_INFO)
    youtube._fetch_video("abc12345678")
    opts, url = FakeYDL.calls[0]
    assert url == "https://www.youtube.com/watch?v=abc12345678"
    assert opts["quiet"] and opts["skip_download"] and opts["noplaylist"]


def test_vod_with_no_formats_returns_empty_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, NO_FORMATS_INFO)
    d = youtube._fetch_video("noFormats00")
    assert d.audio_formats == []
    assert d.video_formats == []
    assert d.title == "No Formats"


def test_live_maps_to_live_route(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, LIVE_INFO)
    d = youtube._fetch_video("live1234567")
    assert d.is_live is True
    assert d.live_stream_url == "/api/live/live1234567/manifest.m3u8"
    assert d.audio_formats == [] and d.title == "Radio" and d.author == "Station"
    # Invariant 3: no raw CDN URL anywhere in what goes to the client.
    assert "googlevideo" not in d.model_dump_json()


def test_captured_fixtures_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    info = _captured("video_vod.json", VOD_INFO)
    _install(monkeypatch, info)
    d = youtube._fetch_video(str(info["id"]))
    assert {a.itag for a in d.audio_formats} & {140, 251}


# ---- errors -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "status", "code"),
    [
        ("ERROR: [youtube] x: Sign in to confirm you're not a bot", 503, "YOUTUBE_BLOCKED"),
        ("ERROR: [youtube] x: Sign in to confirm your age", 503, "YOUTUBE_BLOCKED"),
        ("ERROR: [youtube] x: This video requires a PO Token", 503, "YOUTUBE_BLOCKED"),
        ("ERROR: [youtube] x: Video unavailable", 404, "VIDEO_UNAVAILABLE"),
        ("ERROR: [youtube] aaaaaaaaaaa: This video is unavailable", 404, "VIDEO_UNAVAILABLE"),
        ("ERROR: [youtube] x: Private video", 404, "VIDEO_UNAVAILABLE"),
        ("ERROR: [youtube] x: This video has been removed by the uploader", 404, "VIDEO_UNAVAILABLE"),
        ("ERROR: [youtube:tab] x: This channel does not exist.", 404, "VIDEO_UNAVAILABLE"),
        ("ERROR: [youtube:tab] x: The playlist does not exist.", 404, "VIDEO_UNAVAILABLE"),
        ("ERROR: [youtube] x: nsig extraction failed", 502, "UPSTREAM_FAILURE"),
    ],
)
def test_error_mapping(monkeypatch: pytest.MonkeyPatch, message: str, status: int, code: str) -> None:
    from yt_dlp.utils import DownloadError

    _install(monkeypatch, DownloadError(message))
    with pytest.raises(YouTubeError) as ei:
        youtube._fetch_video("x")
    assert (ei.value.status, ei.value.code) == (status, code)


def test_unexpected_exception_is_upstream_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, KeyError("formats"))
    with pytest.raises(YouTubeError) as ei:
        youtube._fetch_video("x")
    assert ei.value.status == 502


# ---- _search_hits (sync, thread-bound) ---------------------------------------


def test_search_maps_flat_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, SEARCH_INFO)
    hits = youtube._search_hits("q", 10, None)
    assert [(h.kind, h.id, h.title) for h in hits] == [
        ("video", "vid00000001", "Track One"),
        ("video", "vid00000002", "Live Set"),
        ("channel", "UCchan", "Artist A"),
        ("playlist", "PLlist", "Best Of"),
    ]
    v = hits[0]
    assert (v.author, v.duration_seconds, v.thumbnail_url) == (
        "Artist A", 200, "https://i.ytimg.com/vi/vid00000001/hq720.jpg")
    assert hits[1].is_live is True
    # Fallback thumbnail from the id when the entry has none.
    assert hits[1].thumbnail_url == "https://i.ytimg.com/vi/vid00000002/hqdefault.jpg"
    assert hits[2].thumbnail_url == "https://yt3.ggpht.com/abc"
    assert (hits[3].author, hits[3].video_count) == ("Curator", 12)


def test_search_limit_and_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, SEARCH_INFO)
    hits = youtube._search_hits("daft punk", 2, "Eg0IAZoBCC9tLzA0cmxm")
    assert len(hits) == 2
    opts, url = FakeYDL.calls[0]
    # No kind filter passed: fetch exactly `limit` (over-fetch is tested separately).
    assert opts["extract_flat"] == "in_playlist" and opts["playlistend"] == 2
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert qs["search_query"] == ["daft punk"]
    assert qs["sp"] == ["Eg0IAZoBCC9tLzA0cmxm"]


def test_search_without_filter_has_no_sp(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, SEARCH_INFO)
    youtube._search_hits("q", 5, None)
    assert "sp=" not in FakeYDL.calls[0][1]


def test_search_skips_malformed_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, {"entries": [None, {"ie_key": "Youtube"}, SEARCH_INFO["entries"][0]]})
    assert [h.id for h in youtube._search_hits("q", 10, None)] == ["vid00000001"]


def test_yt_dlp_output_goes_to_logging_not_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, VOD_INFO)
    youtube._fetch_video("abc12345678")
    lg = FakeYDL.calls[0][0]["logger"]
    for method in ("debug", "info", "warning", "error"):
        getattr(lg, method)("msg")  # must not raise


def test_captured_search_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    p = FIXTURES / "search_flat.json"
    if not p.exists():
        pytest.skip("no captured search fixture (run scripts/capture_ytdlp_fixtures.py)")
    _install(monkeypatch, json.loads(p.read_text()))
    hits = youtube._search_hits("q", 20, None)
    videos = [h for h in hits if h.kind == "video"]
    assert videos and all(h.title for h in videos)


# ---- video() through the adapter (cache + single-flight) --------------------


async def test_video_returns_details_and_populates_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, VOD_INFO)
    v = await youtube.video("abc12345678")
    assert isinstance(v, VideoDetails)
    assert v.video_id == "abc12345678"
    assert v.title == "Song"
    assert v.audio_formats and v.video_formats
    assert ("abc12345678", 140) in youtube._stream_url_cache
    assert ("abc12345678", 251) in youtube._stream_url_cache


async def test_video_metadata_cached_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, VOD_INFO)
    d1 = await youtube.video("abc12345678")
    d2 = await youtube.video("abc12345678")
    assert d1.title == d2.title == "Song"
    assert len(FakeYDL.calls) == 1  # second call served from the metadata cache


async def test_video_with_no_formats_returns_empty_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, NO_FORMATS_INFO)
    v = await youtube.video("noFormats00")
    assert v.audio_formats == []
    assert v.video_formats == []


async def test_resolve_upstream_url_returns_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, VOD_INFO)
    await youtube.video("abc12345678")
    url = await youtube.resolve_upstream_url("abc12345678", 140)
    assert "itag=140" in url


async def test_resolve_upstream_url_unknown_itag_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, VOD_INFO)
    with pytest.raises(YouTubeError) as ei:
        await youtube.resolve_upstream_url("abc12345678", 9999)
    assert ei.value.status == 404
    assert ei.value.code == "ITAG_NOT_FOUND"


async def test_resolve_rejects_and_evicts_stale_itag_after_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A previously-cached itag the refresh no longer offers must yield 404 —
    not a resurrected expired URL — and the stale entry must be evicted."""
    _install(monkeypatch, VOD_INFO)
    youtube._stream_url_cache[("abc12345678", 999)] = (
        "https://stale.googlevideo.com/expired", time.time() - 1
    )

    with pytest.raises(YouTubeError) as ei:
        await youtube.resolve_upstream_url("abc12345678", 999)

    assert ei.value.status == 404
    assert ("abc12345678", 999) not in youtube._stream_url_cache


async def test_concurrent_resolve_dedupes_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrent cache-miss resolves for the same video must collapse onto a
    single yt-dlp extraction rather than each firing their own."""
    _install(monkeypatch, VOD_INFO)

    results = await asyncio.gather(
        *[youtube.resolve_upstream_url("abc12345678", 140) for _ in range(5)]
    )

    assert all("itag=140" in r for r in results)
    assert len(FakeYDL.calls) == 1, f"expected 1 extract_info call, got {len(FakeYDL.calls)}"
    assert youtube._inflight_refresh == {}


# ---- eviction (backend-neutral) ----------------------------------------------


def test_evict_expired_removes_stale_keeps_live() -> None:
    now = time.time()
    youtube._stream_url_cache[("vidA", 1)] = ("https://x/1", now - 10)    # expired
    youtube._stream_url_cache[("vidB", 2)] = ("https://x/2", now + 3600)  # live

    youtube._evict_expired()

    assert ("vidA", 1) not in youtube._stream_url_cache
    assert ("vidB", 2) in youtube._stream_url_cache


def test_evict_stream_url_removes_only_target_entry() -> None:
    youtube._stream_url_cache[("vidA", 140)] = ("https://x/1", time.time() + 100)
    youtube._stream_url_cache[("vidA", 251)] = ("https://x/2", time.time() + 100)

    youtube.evict_stream_url("vidA", 140)

    assert ("vidA", 140) not in youtube._stream_url_cache
    assert ("vidA", 251) in youtube._stream_url_cache


def test_evict_stream_url_missing_key_is_noop() -> None:
    youtube.evict_stream_url("nope", 999)  # must not raise


# ---- live: video() end-to-end ------------------------------------------------


async def test_video_live_returns_live_details_with_no_formats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, LIVE_INFO)
    v = await youtube.video("live1234567")
    assert v.is_live is True
    assert v.live_stream_url == "/api/live/live1234567/manifest.m3u8"
    assert v.audio_formats == [] and v.video_formats == []
    assert "googlevideo" not in v.model_dump_json()


# ---- _fetch_live_manifest (sync, thread-bound) -------------------------------


def test_fetch_live_manifest_returns_info_when_manifest_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, LIVE_INFO)
    info = youtube._fetch_live_manifest("live1234567")
    assert isinstance(info, youtube.LiveStreamInfo)
    assert info.master_hls_url == "https://manifest.googlevideo.com/api/manifest/hls_variant/x"
    assert info.title == "Radio"
    assert info.author == "Station"
    assert info.channel_id == "UCLIVE"


def test_fetch_live_manifest_returns_none_when_not_live(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, VOD_INFO)
    assert youtube._fetch_live_manifest("abc12345678") is None


def test_fetch_live_manifest_returns_none_when_no_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, LIVE_NO_MANIFEST_INFO)
    assert youtube._fetch_live_manifest("live1234567") is None


def test_fetch_live_manifest_returns_none_on_extraction_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yt_dlp.utils import DownloadError

    _install(monkeypatch, DownloadError("ERROR: [youtube] x: nsig extraction failed"))
    assert youtube._fetch_live_manifest("live1234567") is None


# ---- resolve_live_master_url (monkeypatches _fetch_live_manifest directly) --


async def test_resolve_live_master_url_returns_url_on_first_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        youtube, "_fetch_live_manifest",
        lambda vid: youtube.LiveStreamInfo(
            video_id=vid, title="t", author="a", channel_id="c",
            thumbnail_url="x",
            master_hls_url="https://manifest.googlevideo.com/abc?expire=4102444800",
        ),
    )
    url = await youtube.resolve_live_master_url("vid12345678")
    assert "manifest.googlevideo.com" in url


async def test_resolve_live_master_url_caches_result(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def fake_fetch(vid: str) -> youtube.LiveStreamInfo:
        calls["n"] += 1
        return youtube.LiveStreamInfo(
            video_id=vid, title="t", author="a", channel_id="c",
            thumbnail_url="x",
            master_hls_url="https://manifest.googlevideo.com/abc?expire=4102444800",
        )

    monkeypatch.setattr(youtube, "_fetch_live_manifest", fake_fetch)
    await youtube.resolve_live_master_url("vid12345678")
    await youtube.resolve_live_master_url("vid12345678")
    assert calls["n"] == 1


async def test_resolve_live_master_url_raises_when_fetch_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(youtube, "_fetch_live_manifest", lambda vid: None)
    with pytest.raises(YouTubeError) as exc_info:
        await youtube.resolve_live_master_url("vid12345678")
    assert exc_info.value.status == 502
    assert exc_info.value.code == "LIVE_UNAVAILABLE"


# ---- channel() ----------------------------------------------------------------


async def test_channel_maps_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, CHANNEL_INFO)
    info = await youtube.channel("UCabc123")
    assert isinstance(info, ChannelInfo)
    assert info.channel_id == "UCabc123"
    assert info.title == "Test Channel"
    assert info.description == "channel description"
    assert info.subscriber_count == 5000
    # avatar_uncropped wins over the wider "banner" thumbnail.
    assert info.thumbnail_url == "https://yt3.ggpht.com/avatar_uncropped.jpg"


async def test_channel_options(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, CHANNEL_INFO)
    await youtube.channel("UCabc123")
    opts, url = FakeYDL.calls[0]
    assert url == "https://www.youtube.com/channel/UCabc123"
    assert opts["extract_flat"] == "in_playlist" and opts["playlistend"] == 1


# ---- playlist() -----------------------------------------------------------------


async def test_playlist_maps_fields_and_skips_bad_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, PLAYLIST_INFO)
    info = await youtube.playlist("PLxyz")
    assert isinstance(info, PlaylistInfo)
    assert info.playlist_id == "PLxyz"
    assert info.title == "My Playlist"
    assert info.author == "Curator"
    assert info.video_count == 2  # from playlist_count, independent of items collected
    assert len(info.items) == 1  # entries without id / non-dict entries are skipped
    item = info.items[0]
    assert (item.video_id, item.title, item.author, item.duration_seconds) == (
        "vid1", "Item One", "Author", 60)
    assert item.thumbnail_url == "https://i.ytimg.com/vi/vid1/hq720.jpg"  # widest thumbnail


async def test_playlist_falls_back_to_placeholder_title(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, PLAYLIST_MISSING_TITLE_INFO)
    info = await youtube.playlist("PLbroken")
    assert info.title == "Playlist PLbroken"
    assert info.video_count == 0
    assert info.items == []


# ---- search() through the adapter (cache + single-flight + sp) --------------


@pytest.mark.parametrize(
    ("category", "live"),
    [(None, False), ("music", False), (None, True), ("music", True)],
)
async def test_search_caches_and_applies_sp(
    monkeypatch: pytest.MonkeyPatch, category: str | None, live: bool,
) -> None:
    _install(monkeypatch, SEARCH_INFO)
    hits1 = await youtube.search("q", 7, category=category, live=live)
    hits2 = await youtube.search("q", 7, category=category, live=live)
    assert [h.title for h in hits1] == [h.title for h in hits2]
    assert len(FakeYDL.calls) == 1  # second call served from the search cache

    opts, url = FakeYDL.calls[0]
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    expected_sp = build_search_sp(category=category, live=live)
    if expected_sp is None:
        assert "sp" not in qs
    else:
        assert qs["sp"] == [expected_sp]


# ---- check_backend_requirements (deno) ---------------------------------------


def test_requirement_check_warns_without_deno(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(youtube.shutil, "which", lambda name: None)
    with caplog.at_level(logging.ERROR):
        youtube.check_backend_requirements()
    assert any(
        "deno" in r.getMessage() for r in caplog.records if r.levelno == logging.ERROR
    )


def test_requirement_check_quiet_with_deno(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(youtube.shutil, "which", lambda name: "/usr/bin/deno")
    with caplog.at_level(logging.ERROR):
        youtube.check_backend_requirements()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_lifespan_runs_requirement_check(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    ran: list[bool] = []
    monkeypatch.setattr(youtube, "check_backend_requirements", lambda: ran.append(True))
    with TestClient(create_app()):
        pass
    assert ran == [True]


def test_ffmpeg_warning_is_debug_not_warning(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    ydl_logger = youtube._BASE_OPTS["logger"]
    with caplog.at_level(logging.DEBUG, logger="hum.youtube"):
        ydl_logger.warning("ffmpeg not found. The downloaded format may not be the best available.")
        ydl_logger.warning("Signature solving failed")
    levels = {r.getMessage(): r.levelno for r in caplog.records}
    assert levels["yt-dlp: ffmpeg not found. The downloaded format may not be the best available."] == logging.DEBUG
    assert levels["yt-dlp: Signature solving failed"] == logging.WARNING


# ---- review fixes (PR #16) --------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "ERROR: [youtube] x: Sign in to confirm you're not a bot",
        "ERROR: [youtube] x: Video unavailable",
        "ERROR: unable to download https://rr1---sn.googlevideo.com/videoplayback?ip=1.2.3.4&sig=SECRET",
    ],
)
def test_error_message_is_client_safe(monkeypatch: pytest.MonkeyPatch, message: str) -> None:
    """YouTubeError.message goes to clients in the JSON error body; yt-dlp's
    raw text can carry signed googlevideo URLs (invariant 3)."""
    from yt_dlp.utils import DownloadError

    _install(monkeypatch, DownloadError(message))
    with pytest.raises(YouTubeError) as ei:
        youtube._fetch_video("x")
    assert "yt-dlp:" not in ei.value.message
    assert "googlevideo" not in ei.value.message and "SECRET" not in ei.value.message


def test_live_without_manifest_is_not_advertised(monkeypatch: pytest.MonkeyPatch) -> None:
    info = {**LIVE_INFO, "formats": [f for f in LIVE_INFO["formats"] if not f.get("manifest_url")]}
    _install(monkeypatch, info)
    with pytest.raises(YouTubeError) as ei:
        youtube._fetch_video("live1234567")
    assert (ei.value.status, ei.value.code) == (502, "LIVE_UNAVAILABLE")


def test_live_fetch_primes_master_manifest_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """The metadata extraction already carries the master URL; caching it saves
    resolve_live_master_url a second ~2 s extraction when playback starts."""
    _install(monkeypatch, LIVE_INFO)
    youtube._fetch_video("live1234567")
    cached = youtube._stream_url_cache.get(("live", "live1234567"))
    assert cached is not None and "manifest" in cached[0]


def test_search_drops_unviewable_mix_playlists(monkeypatch: pytest.MonkeyPatch) -> None:
    """YouTube 'Mix' radios (list id RD...) show up in search but /api/playlist
    can't open them ('This playlist type is unviewable')."""
    entries = [
        {"_type": "url", "ie_key": "YoutubeTab", "id": "RDS-G9gMEY7pQ",
         "url": "https://www.youtube.com/playlist?list=RDS-G9gMEY7pQ", "title": "Mix - x"},
        {"_type": "url", "ie_key": "YoutubeTab", "id": "PLabcdefghijk",
         "url": "https://www.youtube.com/playlist?list=PLabcdefghijk", "title": "Real list"},
    ]
    _install(monkeypatch, {"entries": entries})
    assert [h.id for h in youtube._search_hits("q", 10, None)] == ["PLabcdefghijk"]


def test_search_music_filter_sends_video_type() -> None:
    """Hum's category/live filters mean 'videos only'. YouTube's type=Video is
    field 2 of the filter message; field 1 is sort order, and sp={2:{1:1}}
    (sort-by-upload-date) returned 0 results for 'verknipt' (measured 2026-09-24)."""
    from app.adapters.search_params import build_search_sp, encode_message

    # Music alone: topic only, no type=Video, so playlists stay in the results.
    assert build_search_sp(category="music", live=False) == encode_message({2: {19: "/m/04rlf"}})
    assert build_search_sp(category=None, live=True) == encode_message({2: {2: 1, 8: 1}})


_MIXED_ENTRIES: list[dict[str, Any]] = [
    {"_type": "url", "ie_key": "YoutubeTab", "id": "UCchannel0000000000000",
     "url": "https://www.youtube.com/channel/UCchannel0000000000000", "title": "Chan"},
    {"_type": "url", "ie_key": "YoutubeTab", "id": "PLabcdefghijk",
     "url": "https://www.youtube.com/playlist?list=PLabcdefghijk", "title": "List"},
    SEARCH_INFO["entries"][0],
]


@pytest.mark.parametrize(
    ("category", "live", "kinds"),
    [
        (None, False, ["channel", "playlist", "video"]),
        # Music: playlists stay browsable; channels can't be opened in Hum.
        ("music", False, ["playlist", "video"]),
        # Live: only videos can be live streams.
        (None, True, ["video"]),
        ("music", True, ["video"]),
    ],
)
async def test_search_kinds_per_filter(
    monkeypatch: pytest.MonkeyPatch, category: str | None, live: bool, kinds: list[str]
) -> None:
    """YouTube ignores type=Video once a topic is set (measured 2026-09-24),
    so the adapter decides which kinds each filter returns."""
    _install(monkeypatch, {"entries": _MIXED_ENTRIES})
    hits = await youtube.search("q", limit=10, category=category, live=live)
    assert sorted(h.kind for h in hits) == kinds


# ---- review round 2 (PR #16) ------------------------------------------------


def test_url_expire_epoch_reads_path_style_expire() -> None:
    """Live HLS manifests carry expire as a path segment (/expire/<epoch>/),
    not a query param (captured from yt-dlp 2026-09-24)."""
    now = 1_790_000_000.0
    u = "https://manifest.googlevideo.com/api/manifest/hls_variant/expire/1790001234/ei/x/id/y"
    assert youtube._url_expire_epoch(u, now=now) == 1_790_001_234.0


def test_expired_live_master_url_is_not_cached() -> None:
    """A past `expire` means the URL is dead; caching it would keep /api/live
    broken until the 5-minute TTL runs out."""
    past = int(time.time()) - 60
    youtube._cache_live_master("vidLIVE0001", f"https://manifest.googlevideo.com/m?expire={past}")
    assert youtube._stream_url_cache.get(("live", "vidLIVE0001")) is None


def test_live_master_ttl_clamped_to_upstream_expire() -> None:
    soon = int(time.time()) + 60
    youtube._cache_live_master("vidLIVE0002", f"https://manifest.googlevideo.com/m/expire/{soon}/x")
    _, expiry = youtube._stream_url_cache[("live", "vidLIVE0002")]
    assert expiry <= soon


def test_yt_dlp_failure_log_redacts_signed_urls(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    from yt_dlp.utils import DownloadError

    msg = "ERROR: unable to download https://rr1---sn.googlevideo.com/videoplayback?ip=1.2.3.4&sig=SECRET"
    _install(monkeypatch, DownloadError(msg))
    with caplog.at_level(logging.DEBUG, logger="hum.youtube"), pytest.raises(YouTubeError):
        youtube._fetch_video("x")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "unable to download" in text  # diagnostic kept
    assert "SECRET" not in text and "1.2.3.4" not in text


def test_ydl_logger_redacts_signed_urls_at_every_level(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    lg = youtube._BASE_OPTS["logger"]
    url = "https://rr1---sn.googlevideo.com/videoplayback?ip=1.2.3.4&sig=SECRET"
    with caplog.at_level(logging.DEBUG, logger="hum.youtube"):
        for method in ("debug", "info", "warning", "error"):
            getattr(lg, method)(f"{method} {url}")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert text.count("<googlevideo-url>") == 4
    assert "SECRET" not in text and "1.2.3.4" not in text


# ---- review round 4 (PR #16) ------------------------------------------------


@pytest.mark.parametrize("fetch", ["channel", "playlist"])
def test_listing_extractions_allow_playlists(monkeypatch: pytest.MonkeyPatch, fetch: str) -> None:
    """_BASE_OPTS sets noplaylist for single-video extraction; listings must
    override it or yt-dlp may collapse them to one entry."""
    _install(monkeypatch, {"id": "X", "title": "T", "entries": []})
    getattr(youtube, f"_fetch_{fetch}")("PLabcdefghijk" if fetch == "playlist" else "UCabc")
    assert FakeYDL.calls[0][0]["noplaylist"] is False


def test_search_extraction_allows_playlists(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, SEARCH_INFO)
    youtube._search_hits("q", 5, None)
    assert FakeYDL.calls[0][0]["noplaylist"] is False


def test_captured_live_fixture_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    info = _captured("video_live.json", LIVE_INFO)
    _install(monkeypatch, info)
    d = youtube._fetch_video(str(info["id"]))
    assert d.is_live is True
    master = youtube._stream_url_cache[("live", str(info["id"]))][0]
    assert master.startswith("https://manifest.googlevideo.com/") and master.endswith(".m3u8")


# ---- review round 6 (PR #16) ------------------------------------------------


def test_filtered_search_overfetches_to_keep_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-video entries are dropped after extraction, so a filtered search
    must ask yt-dlp for more than `limit` or return short."""
    chan = {"_type": "url", "ie_key": "YoutubeTab", "id": "UCchannel0000000000000",
            "url": "https://www.youtube.com/channel/UCchannel0000000000000", "title": "Chan"}
    vids = [{**SEARCH_INFO["entries"][0], "id": f"vid0000000{i}"} for i in range(3)]
    _install(monkeypatch, {"entries": [chan, *vids]})
    hits = youtube._search_hits("q", 3, "Eg0QAZoBCC9tLzA0cmxm", kinds=frozenset({"video"}))
    assert [h.kind for h in hits] == ["video"] * 3
    assert FakeYDL.calls[0][0]["playlistend"] > 3


def test_captured_fixture_urls_do_not_expire() -> None:
    """Captured fixtures must not carry real expiry times: the adapter drops
    expired live masters, so a real `expire` turns fixture tests red hours later."""
    for name in ("video_vod.json", "video_live.json"):
        p = FIXTURES / name
        if not p.exists():
            continue
        for f in json.loads(p.read_text())["formats"]:
            for key in ("url", "manifest_url"):
                if isinstance(f.get(key), str) and "googlevideo.com" in f[key]:
                    assert youtube._url_expire_epoch(f[key]) > time.time() + 10 * 365 * 86400, f[key]


def test_unfiltered_search_fetches_exactly_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, SEARCH_INFO)
    youtube._search_hits("q", 7, None, kinds=None)
    assert FakeYDL.calls[0][0]["playlistend"] == 7
