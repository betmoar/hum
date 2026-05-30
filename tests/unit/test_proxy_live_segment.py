"""Tests for /proxy/live-segment/{id}."""
from __future__ import annotations

import base64
import pytest
from fastapi.testclient import TestClient


def _b64(url: str) -> str:
    return base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")


def _signed(video_id, u, signing_key_hex):
    from app.auth import sign_live_segment_url
    key = bytes.fromhex(signing_key_hex)
    return sign_live_segment_url(
        f"/proxy/live-segment/{video_id}", u=u, key=key, ttl_seconds=3600,
    )


def test_live_segment_rejects_missing_params():
    from app.main import app
    client = TestClient(app)
    r = client.get("/proxy/live-segment/abc12345678")
    assert r.status_code == 422


def test_live_segment_rejects_bad_signature():
    from app.main import app
    client = TestClient(app)
    u = _b64("https://manifest.googlevideo.com/seg.mp4")
    r = client.get(
        f"/proxy/live-segment/abc12345678?u={u}&exp=9999999999&sig={'0' * 32}"
    )
    assert r.status_code == 403


def test_live_segment_rejects_bad_upstream_host(monkeypatch, signing_key_hex):
    from app.main import app
    client = TestClient(app)
    u = _b64("https://evil.example.com/seg.mp4")
    signed = _signed("abc12345678", u, signing_key_hex)
    r = client.get(signed)
    assert r.status_code == 400
    assert r.json()["error"] == "BAD_UPSTREAM_HOST"


def test_live_segment_streams_upstream(monkeypatch, signing_key_hex):
    import httpx
    from app.adapters import upstream_http

    class FakeResponse:
        status_code = 200
        headers = {"content-type": "video/mp4", "content-length": "5"}
        async def aiter_bytes(self, chunk_size=None):
            yield b"hello"
        async def aclose(self):
            pass

    async def fake_open_stream(url, headers):
        return FakeResponse()

    monkeypatch.setattr(upstream_http, "open_stream", fake_open_stream)
    from app.main import app
    client = TestClient(app)
    u = _b64("https://manifest.googlevideo.com/seg.mp4")
    signed = _signed("abc12345678", u, signing_key_hex)
    r = client.get(signed)
    assert r.status_code == 200
    assert r.content == b"hello"
    assert r.headers["content-type"].startswith("video/mp4")
