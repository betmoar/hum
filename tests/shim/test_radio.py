"""Internet radio: getInternetRadioStations listing + the /radio/{id} stream."""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from shim.models import HumSearchHit
from shim.transcode import live_radio_args

_LIVE = "dQw4w9WgXcQ"


class _FakeClient:
    def __init__(self, hits: list[HumSearchHit]) -> None:
        self._hits = hits

    async def radio(self, limit: int) -> list[HumSearchHit]:
        return self._hits

    async def live_manifest_url(self, video_id: str) -> str:
        return f"http://hum.local/api/live/{video_id}/manifest.m3u8?exp=1&sig=ab"


def test_get_internet_radio_stations_maps_hits(
    shim_client: TestClient, subsonic_auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from shim import hum_client
    from shim.config import get_settings

    hits = [HumSearchHit(kind="video", id=_LIVE, title="Lofi Radio", is_live=True)]
    monkeypatch.setattr(hum_client, "get_client", lambda: _FakeClient(hits))
    monkeypatch.setattr(get_settings(), "public_url", "http://192.168.1.10:8001")

    r = shim_client.get("/rest/getInternetRadioStations", params=subsonic_auth)
    body = r.json()["subsonic-response"]
    assert body["status"] == "ok"
    stations = body["internetRadioStations"]["internetRadioStation"]
    assert len(stations) == 1
    assert stations[0]["id"] == f"rad:{_LIVE}"
    assert stations[0]["name"] == "Lofi Radio"
    assert stations[0]["streamUrl"] == f"http://192.168.1.10:8001/radio/{_LIVE}"


def test_radio_stations_require_auth(shim_client: TestClient) -> None:
    r = shim_client.get("/rest/getInternetRadioStations", params={"f": "json"})
    assert r.json()["subsonic-response"]["status"] == "failed"


def test_radio_stream_is_unauthenticated_and_pipes_audio(
    shim_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from shim import hum_client, transcode

    monkeypatch.setattr(hum_client, "get_client", lambda: _FakeClient([]))

    captured: dict[str, list[str]] = {}

    async def fake_stream(args: list[str]) -> AsyncIterator[bytes]:
        captured["args"] = args
        yield b"MP3DATA"

    monkeypatch.setattr(transcode, "stream_ffmpeg", fake_stream)

    # No Subsonic credentials — Sonos fetches the stream URL directly.
    r = shim_client.get(f"/radio/{_LIVE}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"MP3DATA"
    # ffmpeg reads the resolved live manifest and emits mp3.
    assert "manifest.m3u8" in captured["args"][captured["args"].index("-i") + 1]
    assert "libmp3lame" in captured["args"]


def test_radio_stream_rejects_bad_id(shim_client: TestClient) -> None:
    # Path pattern rejects a malformed id; the global validation handler turns
    # it into a failed envelope. Either way, no audio stream is produced.
    r = shim_client.get("/radio/not-an-id")
    assert r.headers.get("content-type") != "audio/mpeg"


def test_live_radio_args_shape() -> None:
    args = live_radio_args("http://x/m.m3u8", ffmpeg_path="ffmpeg", bitrate_kbps=256)
    assert args[args.index("-i") + 1] == "http://x/m.m3u8"
    assert "libmp3lame" in args and "256k" in args
    assert args[-1] == "-"
