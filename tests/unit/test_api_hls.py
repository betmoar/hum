"""Tests for /api/hls/{id}.m3u8."""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import sign_url

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "m4a_head_sample.bin"


@pytest.fixture
def app_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.adapters import upstream_http
    from app.adapters import youtube as adapter

    head_bytes = _FIXTURE.read_bytes()

    async def fake_resolve(video_id: str, itag: int) -> str:
        return f"https://rr1---sn-test.googlevideo.com/videoplayback?id={video_id}"

    async def fake_fetch_range(url: str, *, start: int, end: int) -> bytes:
        # The endpoint requests bytes=0-65535; return the full fixture
        # (exactly 64 KB) so the sidx parser sees a real YouTube head.
        return head_bytes[start : end + 1]

    monkeypatch.setattr(adapter, "resolve_upstream_url", fake_resolve)
    monkeypatch.setattr(upstream_http, "fetch_range", fake_fetch_range)

    from app.main import app

    return TestClient(app)


@pytest.fixture
def hls_url_for(signing_key_hex: str) -> Callable[[str, int], str]:
    def _build(video_id: str, itag: int) -> str:
        path = f"/api/hls/{video_id}.m3u8"
        exp = int(time.time()) + 60
        sig = sign_url(path, itag=itag, exp=exp, key=bytes.fromhex(signing_key_hex))
        return f"{path}?itag={itag}&exp={exp}&sig={sig}"
    return _build


def test_unsigned_returns_403_with_structured_error(app_client: TestClient) -> None:
    r = app_client.get(
        "/api/hls/dQw4w9WgXcQ.m3u8?itag=140&exp=99999999999&sig=" + "0" * 32
    )
    assert r.status_code == 403
    # Matches the {error, message} shape the rest of the API uses.
    body = r.json()
    assert body["error"] == "BAD_SIGNATURE"
    assert "message" in body


def test_signed_returns_apple_mpegurl(app_client: TestClient, hls_url_for) -> None:
    r = app_client.get(hls_url_for("dQw4w9WgXcQ", 140))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.apple.mpegurl")


def test_manifest_has_required_hls_v7_shape(app_client: TestClient, hls_url_for) -> None:
    body = app_client.get(hls_url_for("dQw4w9WgXcQ", 140)).text
    assert body.startswith("#EXTM3U\n")
    assert "#EXT-X-VERSION:7" in body
    assert "#EXT-X-PLAYLIST-TYPE:VOD" in body
    # EXT-X-MAP carries the init segment (ftyp+moov+sidx, ending at 723 in the fixture).
    assert '#EXT-X-MAP:URI=' in body
    assert ',BYTERANGE="723@0"' in body
    assert body.rstrip().endswith("#EXT-X-ENDLIST")


def test_segment_uri_points_at_signed_audio_proxy(
    app_client: TestClient, hls_url_for
) -> None:
    body = app_client.get(hls_url_for("dQw4w9WgXcQ", 140)).text
    assert "/proxy/audio/dQw4w9WgXcQ?itag=140&exp=" in body
    assert "&sig=" in body


def test_segments_are_coalesced_well_below_raw_sidx_count(
    app_client: TestClient, hls_url_for
) -> None:
    """The fixture has 343 ~10s fragments; coalescing to 60s super-segments
    drops the count to roughly a sixth. Concrete assertion: well below 100.
    This guards against the byterange-burst storm we explicitly aim to avoid."""
    body = app_client.get(hls_url_for("dQw4w9WgXcQ", 140)).text
    extinf_lines = body.count("#EXTINF:")
    assert 30 < extinf_lines < 100, f"expected ~58, got {extinf_lines}"


def test_unsupported_stream_returns_415_with_structured_error(
    monkeypatch: pytest.MonkeyPatch, hls_url_for
) -> None:
    """If the upstream head doesn't contain a sidx, return 415 so the
    frontend can fall back to /proxy/audio rather than treating as fatal."""
    from app.adapters import upstream_http
    from app.adapters import youtube as adapter

    async def fake_resolve(video_id: str, itag: int) -> str:
        return f"https://rr1---sn-test.googlevideo.com/videoplayback?id={video_id}"

    async def fake_fetch_range(url: str, *, start: int, end: int) -> bytes:
        # Looks like an MP4 head but no sidx (mdat right after moov).
        return b"".join([
            b"\x00\x00\x00\x08ftyp",
            b"\x00\x00\x00\x08moov",
            b"\x00\x00\x00\x08mdat",
        ])

    monkeypatch.setattr(adapter, "resolve_upstream_url", fake_resolve)
    monkeypatch.setattr(upstream_http, "fetch_range", fake_fetch_range)

    from app.main import app
    client = TestClient(app)
    r = client.get(hls_url_for("dQw4w9WgXcQ", 140))
    assert r.status_code == 415
    body = r.json()
    assert body["error"] == "NOT_FMP4"


def test_empty_segment_index_returns_415(
    monkeypatch: pytest.MonkeyPatch, hls_url_for: Callable[[str, int], str]
) -> None:
    """A parsed index with zero fragments must be treated as 'not HLS-able'
    (415) rather than 500ing inside manifest rendering."""
    from app.adapters import upstream_http
    from app.adapters import youtube as adapter
    from app.api import hls as hls_mod
    from app.hls.sidx import ParsedIndex

    async def fake_resolve(video_id: str, itag: int) -> str:
        return f"https://rr1---sn-test.googlevideo.com/videoplayback?id={video_id}"

    async def fake_fetch_range(url: str, *, start: int, end: int) -> bytes:
        return b"\x00" * 32

    monkeypatch.setattr(adapter, "resolve_upstream_url", fake_resolve)
    monkeypatch.setattr(upstream_http, "fetch_range", fake_fetch_range)
    monkeypatch.setattr(
        hls_mod.sidx, "parse", lambda data: ParsedIndex(init_size=100, segments=())
    )

    from app.main import app
    client = TestClient(app)
    r = client.get(hls_url_for("dQw4w9WgXcQ", 140))
    assert r.status_code == 415
    assert r.json()["error"] == "NOT_FMP4"


def test_render_manifest_tolerates_zero_duration_segments() -> None:
    """A zero-duration fragment must not crash rendering; target duration is
    clamped to a minimum of 1 second per the HLS spec."""
    from app.api.hls import _render_manifest
    from app.hls.sidx import ParsedIndex, Segment

    index = ParsedIndex(
        init_size=100,
        segments=(Segment(offset=100, size=10, duration=0.0),),
    )
    body = _render_manifest(index, segment_uri="/proxy/audio/x?itag=140")
    assert "#EXT-X-TARGETDURATION:1" in body
    assert body.rstrip().endswith("#EXT-X-ENDLIST")


def test_upstream_failure_returns_502_with_structured_error(
    monkeypatch: pytest.MonkeyPatch, hls_url_for
) -> None:
    """A 403/5xx from googlevideo while fetching the head bubbles as 502
    with the structured error code, not a bare FastAPI HTTPException shape."""
    from app.adapters import upstream_http
    from app.adapters import youtube as adapter
    from app.adapters.upstream_http import UpstreamStatusError

    async def fake_resolve(video_id: str, itag: int) -> str:
        return f"https://rr1---sn-test.googlevideo.com/videoplayback?id={video_id}"

    async def fake_fetch_range(url: str, *, start: int, end: int) -> bytes:
        raise UpstreamStatusError(403)

    monkeypatch.setattr(adapter, "resolve_upstream_url", fake_resolve)
    monkeypatch.setattr(upstream_http, "fetch_range", fake_fetch_range)

    from app.main import app
    client = TestClient(app)
    r = client.get(hls_url_for("dQw4w9WgXcQ", 140))
    assert r.status_code == 502
    body = r.json()
    assert body["error"] == "UPSTREAM_ERROR"
    assert "403" in body["message"]
