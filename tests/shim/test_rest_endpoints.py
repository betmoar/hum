"""Endpoint tests for search3, getCoverArt, and stream with a fake Hum client."""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from shim.models import HumAudioFormat, HumSearchHit, HumVideoDetails

_YTID = "dQw4w9WgXcQ"


class FakeHumClient:
    def __init__(self, hits: list[HumSearchHit], details: HumVideoDetails | None = None) -> None:
        self._hits = hits
        self._details = details

    async def search(self, q: str, limit: int) -> list[HumSearchHit]:
        return self._hits[:limit]

    async def video_details(self, video_id: str) -> HumVideoDetails:
        assert self._details is not None
        return self._details

    async def fetch_art(self, kind: str, value: str) -> tuple[bytes, str]:
        return b"jpeg-bytes", "image/jpeg"

    def absolute(self, signed_path: str) -> str:
        return f"http://hum.local{signed_path}"


def _vod(ytid: str, title: str, duration: int) -> HumSearchHit:
    return HumSearchHit(
        kind="video",
        id=ytid,
        title=title,
        author="Some Channel",
        thumbnail_url="https://i.ytimg.com/vi/x/hq.jpg",
        duration_seconds=duration,
        is_live=None,
    )


class _Installer:
    """Install a FakeHumClient as the module singleton for one test."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, fake: FakeHumClient) -> None:
        from shim import hum_client

        monkeypatch.setattr(hum_client, "get_client", lambda: fake)


def test_search3_maps_and_filters(
    shim_client: TestClient,
    subsonic_auth: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hits = [
        _vod(_YTID, "A Song", 215),
        HumSearchHit(kind="video", id="live4567890", title="Live!", is_live=True),
        HumSearchHit(kind="video", id="nodur456789", title="Ambiguous"),  # no duration → live
        HumSearchHit(kind="channel", id="UCabcdef", title="A Channel"),
    ]
    _Installer(monkeypatch, FakeHumClient(hits))

    r = shim_client.get("/rest/search3", params={**subsonic_auth, "query": "a song"})
    body = r.json()["subsonic-response"]
    assert body["status"] == "ok"
    songs = body["searchResult3"]["song"]
    assert len(songs) == 1
    song = songs[0]
    assert song["id"] == f"vid:{_YTID}"
    assert song["title"] == "A Song"
    assert song["album"] == "A Song"  # single-track album model
    assert song["artist"] == "Some Channel"
    assert song["coverArt"] == f"vid:{_YTID}"
    assert song["duration"] == 215
    assert body["searchResult3"]["artist"] == []
    assert body["searchResult3"]["album"] == []


def test_search3_requires_query(
    shim_client: TestClient, subsonic_auth: dict[str, str]
) -> None:
    r = shim_client.get("/rest/search3", params=subsonic_auth)
    assert r.status_code == 200  # protocol error, not HTTP error
    body = r.json()["subsonic-response"]
    assert body["status"] == "failed"
    assert body["error"]["code"] == 10


def test_cover_art_returns_bytes(
    shim_client: TestClient,
    subsonic_auth: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _Installer(monkeypatch, FakeHumClient([]))
    r = shim_client.get(
        "/rest/getCoverArt", params={**subsonic_auth, "id": f"vid:{_YTID}"}
    )
    assert r.status_code == 200
    assert r.content == b"jpeg-bytes"
    assert r.headers["content-type"] == "image/jpeg"


def test_cover_art_rejects_malformed_id(
    shim_client: TestClient, subsonic_auth: dict[str, str]
) -> None:
    r = shim_client.get("/rest/getCoverArt", params={**subsonic_auth, "id": "vid:nope"})
    body = r.json()["subsonic-response"]
    assert body["status"] == "failed"
    assert body["error"]["code"] == 70


def test_stream_remuxes_aac(
    shim_client: TestClient,
    subsonic_auth: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    details = HumVideoDetails(
        video_id=_YTID,
        title="A Song",
        author="Some Channel",
        duration_seconds=215,
        audio_formats=[
            HumAudioFormat(
                itag=140,
                mime_type="audio/mp4",
                bitrate=130000,
                codec="aac",
                url=f"/proxy/audio/{_YTID}?itag=140&exp=99999999999&sig=ab",
            ),
            HumAudioFormat(
                itag=251,
                mime_type="audio/webm",
                bitrate=160000,
                codec="opus",
                url=f"/proxy/audio/{_YTID}?itag=251&exp=99999999999&sig=cd",
            ),
        ],
    )
    _Installer(monkeypatch, FakeHumClient([], details))

    captured: dict[str, list[str]] = {}

    async def fake_stream(args: list[str]) -> AsyncIterator[bytes]:
        captured["args"] = args
        yield b"fmp4-bytes"

    from shim import transcode

    monkeypatch.setattr(transcode, "stream_ffmpeg", fake_stream)

    r = shim_client.get("/rest/stream", params={**subsonic_auth, "id": f"vid:{_YTID}"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mp4"
    assert r.content == b"fmp4-bytes"
    # AAC preferred over the higher-bitrate Opus; remux args, not re-encode.
    assert "itag=140" in captured["args"][captured["args"].index("-i") + 1]
    assert "copy" in captured["args"]
    assert "libmp3lame" not in captured["args"]


def test_stream_rejects_playlist_id(
    shim_client: TestClient, subsonic_auth: dict[str, str]
) -> None:
    r = shim_client.get("/rest/stream", params={**subsonic_auth, "id": "pl:PLabc123"})
    body = r.json()["subsonic-response"]
    assert body["status"] == "failed"
    assert body["error"]["code"] == 70
