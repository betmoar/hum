"""yt-dlp backend adapter (spike). YoutubeDL is faked; no network."""
from __future__ import annotations

import json
import time
import urllib.parse
from pathlib import Path
from typing import Any

import pytest

from app.adapters import youtube
from app.adapters import youtube_ytdlp as ytdlp
from app.adapters.youtube import YouTubeError

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

LIVE_INFO: dict[str, Any] = {
    "id": "live1234567",
    "title": "Radio",
    "channel": "Station",
    "channel_id": "UCLIVE",
    "live_status": "is_live",
    "formats": [_fmt("95", ext="mp4", protocol="m3u8_native", vcodec="avc1", acodec="mp4a.40.2",
                     manifest_url="https://manifest.googlevideo.com/api/manifest/hls_variant/x")],
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
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeYDL.calls = []
    youtube._stream_url_cache.clear()


def _install(monkeypatch: pytest.MonkeyPatch, result: Any) -> None:
    monkeypatch.setattr(ytdlp, "_make_ydl", lambda opts: FakeYDL(opts, result))


# ---- video ----------------------------------------------------------------


def test_vod_maps_formats_and_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, VOD_INFO)
    d = ytdlp.fetch_video("abc12345678")
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
    ytdlp.fetch_video("abc12345678")
    url, expiry = youtube._stream_url_cache[("abc12345678", 140)]
    assert "itag=140" in url
    assert expiry <= time.time() + youtube._CACHE_MAX_TTL
    assert expiry >= before + youtube._CACHE_MAX_TTL - 5
    # First occurrence of a duplicated itag wins; non-numeric ids and manifests are skipped.
    assert "itag=251" in youtube._stream_url_cache[("abc12345678", 251)][0]
    assert ("abc12345678", 233) not in youtube._stream_url_cache


def test_vod_options(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, VOD_INFO)
    ytdlp.fetch_video("abc12345678")
    opts, url = FakeYDL.calls[0]
    assert url == "https://www.youtube.com/watch?v=abc12345678"
    assert opts["quiet"] and opts["skip_download"] and opts["noplaylist"]


def test_live_maps_to_live_route(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, LIVE_INFO)
    d = ytdlp.fetch_video("live1234567")
    assert d.is_live is True
    assert d.live_stream_url == "/api/live/live1234567/manifest.m3u8"
    assert d.audio_formats == [] and d.title == "Radio" and d.author == "Station"
    # Invariant 3: no raw CDN URL anywhere in what goes to the client.
    assert "googlevideo" not in d.model_dump_json()


def test_captured_fixtures_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    info = _captured("video_vod.json", VOD_INFO)
    _install(monkeypatch, info)
    d = ytdlp.fetch_video(str(info["id"]))
    assert {a.itag for a in d.audio_formats} & {140, 251}


# ---- errors ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "status", "code"),
    [
        ("ERROR: [youtube] x: Sign in to confirm you're not a bot", 503, "YOUTUBE_BLOCKED"),
        ("ERROR: [youtube] x: Sign in to confirm your age", 503, "YOUTUBE_BLOCKED"),
        ("ERROR: [youtube] x: This video requires a PO Token", 503, "YOUTUBE_BLOCKED"),
        ("ERROR: [youtube] x: Video unavailable", 404, "VIDEO_UNAVAILABLE"),
        ("ERROR: [youtube] x: Private video", 404, "VIDEO_UNAVAILABLE"),
        ("ERROR: [youtube] x: This video has been removed by the uploader", 404, "VIDEO_UNAVAILABLE"),
        ("ERROR: [youtube] x: nsig extraction failed", 502, "UPSTREAM_FAILURE"),
    ],
)
def test_error_mapping(monkeypatch: pytest.MonkeyPatch, message: str, status: int, code: str) -> None:
    from yt_dlp.utils import DownloadError

    _install(monkeypatch, DownloadError(message))
    with pytest.raises(YouTubeError) as ei:
        ytdlp.fetch_video("x")
    assert (ei.value.status, ei.value.code) == (status, code)


def test_unexpected_exception_is_upstream_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, KeyError("formats"))
    with pytest.raises(YouTubeError) as ei:
        ytdlp.fetch_video("x")
    assert ei.value.status == 502


# ---- search ---------------------------------------------------------------


def test_search_maps_flat_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, SEARCH_INFO)
    hits = ytdlp.search_hits("q", 10, None)
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
    hits = ytdlp.search_hits("daft punk", 2, "Eg0IAZoBCC9tLzA0cmxm")
    assert len(hits) == 2
    opts, url = FakeYDL.calls[0]
    assert opts["extract_flat"] == "in_playlist" and opts["playlistend"] == 2
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert qs["search_query"] == ["daft punk"]
    assert qs["sp"] == ["Eg0IAZoBCC9tLzA0cmxm"]


def test_search_without_filter_has_no_sp(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, SEARCH_INFO)
    ytdlp.search_hits("q", 5, None)
    assert "sp=" not in FakeYDL.calls[0][1]


def test_search_skips_malformed_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, {"entries": [None, {"ie_key": "Youtube"}, SEARCH_INFO["entries"][0]]})
    assert [h.id for h in ytdlp.search_hits("q", 10, None)] == ["vid00000001"]
