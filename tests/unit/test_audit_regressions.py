"""Regression tests from the 2026-07 handoff audit.

Each test locks in a specific fix. If one of these breaks, read the matching
comment before "fixing" the test — every case here was a real production
failure mode (500s, hung players, SSRF-via-redirect).
"""
from __future__ import annotations

import struct
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from app.auth import sign_url


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


def _signed(path: str, itag: int, signing_key_hex: str) -> str:
    key = bytes.fromhex(signing_key_hex)
    exp = int(time.time()) + 60
    sig = sign_url(path, itag=itag, exp=exp, key=key)
    return f"{path}?itag={itag}&exp={exp}&sig={sig}"


# ---- Error mapping: upstream failures must never surface as bare 500s ----


def test_proxy_audio_unknown_itag_is_404_not_500(
    client: TestClient, signing_key_hex: str, mocker: MockerFixture
) -> None:
    """An expired/unknown itag (the most common runtime failure: cache entry
    expired and the refreshed video no longer offers that itag) must return a
    clean 404 the frontend's recovery path can act on — not a 500."""
    from app.adapters import youtube

    async def raise_itag(video_id: str, itag: int) -> str:
        raise youtube.YouTubeError(404, "ITAG_NOT_FOUND", "gone")

    mocker.patch.object(youtube, "resolve_upstream_url", raise_itag)
    r = client.get(_signed("/proxy/audio/dQw4w9WgXcQ", 140, signing_key_hex))
    assert r.status_code == 404
    assert r.json()["error"] == "ITAG_NOT_FOUND"


def test_api_hls_unknown_itag_is_404_not_500(
    client: TestClient, signing_key_hex: str, mocker: MockerFixture
) -> None:
    from app.adapters import youtube

    async def raise_itag(video_id: str, itag: int) -> str:
        raise youtube.YouTubeError(404, "ITAG_NOT_FOUND", "gone")

    mocker.patch.object(youtube, "resolve_upstream_url", raise_itag)
    r = client.get(_signed("/api/hls/dQw4w9WgXcQ.m3u8", 140, signing_key_hex))
    assert r.status_code == 404


def test_api_video_unavailable_video_is_404_not_500(
    client: TestClient, bearer_token: str, mocker: MockerFixture
) -> None:
    """pytubefix raises VideoUnavailable (private/removed video). The adapter
    must map the whole PytubeFixError hierarchy to YouTubeError."""
    from pytubefix.exceptions import VideoUnavailable

    from app.adapters import youtube

    def raise_unavailable(video_id: str) -> object:
        raise VideoUnavailable(video_id)

    mocker.patch.object(youtube, "_make_youtube", raise_unavailable)
    r = client.get(
        "/api/video/dQw4w9WgXcQ", headers={"Authorization": f"Bearer {bearer_token}"}
    )
    assert r.status_code == 404
    assert r.json()["error"] == "VIDEO_UNAVAILABLE"


def test_api_video_bot_detection_is_503(
    client: TestClient, bearer_token: str, mocker: MockerFixture
) -> None:
    """Anti-bot walls are an operational incident ("YouTube is blocking us"),
    not a missing video. 503 + YOUTUBE_BLOCKED is the 3am signal."""
    from pytubefix.exceptions import BotDetection

    from app.adapters import youtube

    def raise_bot(video_id: str) -> object:
        raise BotDetection(video_id)

    mocker.patch.object(youtube, "_make_youtube", raise_bot)
    r = client.get(
        "/api/video/dQw4w9WgXcQ", headers={"Authorization": f"Bearer {bearer_token}"}
    )
    assert r.status_code == 503
    assert r.json()["error"] == "YOUTUBE_BLOCKED"


def test_upstream_host_error_is_502_not_500(
    client: TestClient, signing_key_hex: str, mocker: MockerFixture
) -> None:
    from app.adapters import upstream_http, youtube

    async def fake_resolve(video_id: str, itag: int) -> str:
        return "https://rr1.googlevideo.com/videoplayback"

    async def raise_host(url: str, *, headers: dict[str, str]) -> httpx.Response:
        raise upstream_http.UpstreamHostError("host 'evil.example' not in allowlist")

    mocker.patch.object(youtube, "resolve_upstream_url", fake_resolve)
    mocker.patch.object(upstream_http, "open_stream", raise_host)
    r = client.get(_signed("/proxy/audio/dQw4w9WgXcQ", 140, signing_key_hex))
    assert r.status_code == 502
    assert r.json()["error"] == "UPSTREAM_HOST_BLOCKED"


# ---- Auth: malformed input must be 401, never 500 ------------------------


def test_non_ascii_bearer_token_is_401_not_500(client: TestClient) -> None:
    """Header values arrive latin-1 decoded; secrets.compare_digest raises
    TypeError on non-ASCII str. Compare as bytes."""
    # Bypass httpx's ASCII header validation by driving the dependency directly.
    from fastapi import HTTPException

    from app.auth import require_bearer

    with pytest.raises(HTTPException) as exc_info:
        require_bearer("Bearer tok\xe9n-with-latin1")
    assert exc_info.value.status_code == 401


# ---- sidx: truncated index must fall back, not crash ---------------------


def _box(btype: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + btype + payload


def test_sidx_truncated_at_head_returns_none() -> None:
    """A sidx box that claims to extend past the fetched head (long streams
    can exceed the 64 KB head fetch) must return None → 415 → direct-stream
    fallback. It used to raise struct.error → 500."""
    from app.hls import sidx

    ftyp = _box(b"ftyp", b"\x00" * 8)
    moov = _box(b"moov", b"\x00" * 16)
    # sidx header claims 2000 bytes but the buffer ends long before that.
    sidx_hdr = struct.pack(">I", 2000) + b"sidx"
    body = bytes([1]) + b"\x00\x00\x00" + struct.pack(">I", 1) + struct.pack(">I", 1000)
    data = ftyp + moov + sidx_hdr + body
    assert sidx.parse(data) is None


# ---- Live manifest: ENDLIST must survive the tail trim --------------------


def test_tail_trim_preserves_endlist() -> None:
    """A finished broadcast's #EXT-X-ENDLIST must be re-emitted after the kept
    segments. Dropping it leaves players polling a dead stream forever."""
    from app.live.manifest import rewrite_media_playlist

    text = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        "#EXT-X-TARGETDURATION:5\n"
        "#EXT-X-MEDIA-SEQUENCE:100\n"
        "#EXTINF:5.0,\nseg100.ts\n"
        "#EXTINF:5.0,\nseg101.ts\n"
        "#EXTINF:5.0,\nseg102.ts\n"
        "#EXT-X-ENDLIST\n"
    )
    out = rewrite_media_playlist(
        text, lambda u: u, base="https://x.googlevideo.com/", tail_segments=2
    )
    lines = [line for line in out.splitlines() if line]
    assert lines[-1] == "#EXT-X-ENDLIST"
    # And the trim itself still works.
    assert "seg100.ts" not in out
    assert "#EXT-X-MEDIA-SEQUENCE:101" in out


# ---- Redirects: allowlist must hold on every hop (SSRF hardening) ---------


async def test_redirect_off_allowlist_is_blocked(mocker: MockerFixture) -> None:
    """follow_redirects=True means a compromised/misbehaving upstream could
    3xx us to an arbitrary host. The per-request event hook must refuse."""
    from app.adapters import upstream_http

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host.endswith("googlevideo.com"):
            return httpx.Response(302, headers={"Location": "https://evil.example/x"})
        return httpx.Response(200, content=b"should never get here")

    hooked = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        event_hooks={"request": [upstream_http._enforce_allowlist_per_request]},
    )
    mocker.patch.object(upstream_http, "_client", hooked)
    try:
        with pytest.raises(upstream_http.UpstreamHostError):
            await upstream_http.fetch_text("https://rr1.googlevideo.com/manifest.m3u8")
    finally:
        await hooked.aclose()
        mocker.patch.object(upstream_http, "_client", None)


# ---- Debug endpoint: must be gated on DEBUG, not just bearer ---------------


def test_debug_live_upstream_is_404_when_debug_off(
    client: TestClient, bearer_token: str
) -> None:
    """The debug endpoint leaks raw CDN URLs (invariant #3 exists to keep them
    server-side). With DEBUG=false it must not exist."""
    r = client.get(
        "/api/debug/live/dQw4w9WgXcQ/upstream",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert r.status_code == 404
    assert r.json()["error"] == "NOT_FOUND"
