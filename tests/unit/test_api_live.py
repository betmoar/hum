"""Tests for /api/live/{id}/manifest.m3u8."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _clear_master_cache() -> None:
    """The endpoint caches the parsed master playlist for 2s. Clear it
    between tests so monkeypatched fetch_text doesn't get bypassed."""
    from app.api.live import _master_cache
    _master_cache.clear()


@pytest.fixture
def live_client(monkeypatch, bearer_token, signing_key_hex):
    from app.adapters import upstream_http
    from app.adapters import youtube as adapter

    fetch_calls = {"n": 0}

    async def fake_resolve_live_master_url(video_id):
        return "https://manifest.googlevideo.com/x/master.m3u8"

    async def fake_fetch_text(url):
        fetch_calls["n"] += 1
        if "master.m3u8" in url:
            return (
                "#EXTM3U\n"
                "#EXT-X-STREAM-INF:BANDWIDTH=500000\n"
                "audio/playlist.m3u8\n"
            ), url
        if "audio/playlist.m3u8" in url:
            return (
                "#EXTM3U\n"
                "#EXT-X-TARGETDURATION:6\n"
                "#EXTINF:5.000,\n"
                "seg1.mp4\n"
                "#EXTINF:5.000,\n"
                "seg2.mp4\n"
            ), url
        return "#EXTM3U\n", url

    monkeypatch.setattr(adapter, "resolve_live_master_url", fake_resolve_live_master_url)
    monkeypatch.setattr(upstream_http, "fetch_text", fake_fetch_text)

    from app.main import app
    return TestClient(app), fetch_calls


def _signed_manifest_url(video_id, signing_key_hex):
    from app.auth import sign_live_manifest_url
    key = bytes.fromhex(signing_key_hex)
    return sign_live_manifest_url(
        f"/api/live/{video_id}/manifest.m3u8", key=key, ttl_seconds=3600
    )


def test_live_manifest_rejects_unsigned_request(live_client, signing_key_hex):
    client, _ = live_client
    r = client.get("/api/live/abc12345678/manifest.m3u8")
    assert r.status_code == 422  # FastAPI rejects missing required query params


def test_live_manifest_rejects_bad_signature(live_client):
    client, _ = live_client
    r = client.get(
        "/api/live/abc12345678/manifest.m3u8?exp=9999999999&sig=" + "0" * 32
    )
    assert r.status_code == 403


def test_live_manifest_returns_rewritten_playlist(live_client, signing_key_hex):
    import base64
    import re

    client, _ = live_client
    signed = _signed_manifest_url("abc12345678", signing_key_hex)
    r = client.get(signed)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.apple.mpegurl")
    body = r.text
    assert "#EXTM3U" in body
    assert "/proxy/live-segment/abc12345678" in body

    # Segment URIs use a base64url-encoded `u=` payload that decodes to the
    # absolute upstream segment URL (relative paths resolved against the
    # media playlist's base URL).
    u_values = re.findall(r"[?&]u=([^&\s]+)", body)
    assert u_values, "expected at least one signed segment URL with a u= param"
    decoded = [
        base64.urlsafe_b64decode(v + "=" * (-len(v) % 4)).decode()
        for v in u_values
    ]
    assert "https://manifest.googlevideo.com/x/audio/seg1.mp4" in decoded
    assert "https://manifest.googlevideo.com/x/audio/seg2.mp4" in decoded


def test_live_manifest_returns_502_on_malformed_master(monkeypatch, signing_key_hex, bearer_token):
    from app.adapters import upstream_http
    from app.adapters import youtube as adapter

    async def fake_resolve(video_id):
        return "https://manifest.googlevideo.com/x/master.m3u8"

    async def fake_fetch(url):
        return ("not a playlist", url)

    monkeypatch.setattr(adapter, "resolve_live_master_url", fake_resolve)
    monkeypatch.setattr(upstream_http, "fetch_text", fake_fetch)

    from app.main import app
    client = TestClient(app)
    signed = _signed_manifest_url("abc12345678", signing_key_hex)
    r = client.get(signed)
    assert r.status_code == 502
    assert r.json()["error"] == "MALFORMED_MANIFEST"
