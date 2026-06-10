"""Seekable remux (spec §4 mode b): stream served from a cached file with Range."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from shim import hum_client, mediacache, transcode
from shim.config import get_settings
from shim.mediacache import MediaCache
from shim.models import HumAudioFormat, HumVideoDetails

_YTID = "dQw4w9WgXcQ"
_BODY = b"FMP4-MATERIALIZED-BYTES"


class _FakeClient:
    def __init__(self, details: HumVideoDetails) -> None:
        self._details = details

    async def video_details(self, video_id: str) -> HumVideoDetails:
        return self._details

    def absolute(self, signed_path: str) -> str:
        return f"http://hum.local{signed_path}"


@pytest.fixture
def seekable_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    details = HumVideoDetails(
        video_id=_YTID,
        title="A Song",
        author="Chan",
        duration_seconds=200,
        audio_formats=[
            HumAudioFormat(
                itag=140, mime_type="audio/mp4", bitrate=130000, codec="aac",
                url=f"/proxy/audio/{_YTID}?itag=140&exp=99999999999&sig=ab",
            )
        ],
    )
    monkeypatch.setattr(hum_client, "get_client", lambda: _FakeClient(details))
    monkeypatch.setattr(get_settings(), "seekable_remux", True)
    # Real MediaCache in a temp dir; fake the ffmpeg materialize to write bytes.
    cache = MediaCache(tmp_path, max_bytes=10 * 1024 * 1024)
    monkeypatch.setattr(mediacache, "get_cache", lambda: cache)

    async def fake_materialize(args: list[str]) -> bool:
        dest = Path(args[-1])  # remux_file_args ends with the dest path
        dest.write_bytes(_BODY)
        return True

    monkeypatch.setattr(transcode, "materialize", fake_materialize)


def test_seekable_stream_serves_full_body(
    shim_client: TestClient, subsonic_auth: dict[str, str], seekable_env: None
) -> None:
    r = shim_client.get("/rest/stream", params={**subsonic_auth, "id": f"vid:{_YTID}"})
    assert r.status_code == 200
    assert r.content == _BODY
    assert r.headers["content-type"] == "audio/mp4"
    # FileResponse advertises range support — that's what gives Sonos a seek bar.
    assert r.headers.get("accept-ranges") == "bytes"
    assert r.headers["content-length"] == str(len(_BODY))


def test_seekable_stream_honors_range(
    shim_client: TestClient, subsonic_auth: dict[str, str], seekable_env: None
) -> None:
    r = shim_client.get(
        "/rest/stream",
        params={**subsonic_auth, "id": f"vid:{_YTID}"},
        headers={"Range": "bytes=0-3"},
    )
    assert r.status_code == 206
    assert r.content == _BODY[:4]
    assert r.headers["content-range"] == f"bytes 0-3/{len(_BODY)}"


def test_materialize_failure_falls_back_to_pipe(
    shim_client: TestClient,
    subsonic_auth: dict[str, str],
    seekable_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # If materialization fails, stream must still work via the pipe (mode a).
    async def fail_materialize(args: list[str]) -> bool:
        return False

    monkeypatch.setattr(transcode, "materialize", fail_materialize)

    async def fake_pipe(args: list[str]):
        yield b"PIPED"

    monkeypatch.setattr(transcode, "stream_ffmpeg", fake_pipe)
    r = shim_client.get("/rest/stream", params={**subsonic_auth, "id": f"vid:{_YTID}"})
    assert r.status_code == 200
    assert r.content == b"PIPED"
