"""Tests for /proxy/audio/{id} — signature, range support, hop-by-hop strip."""
from __future__ import annotations

import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth import sign_url


@pytest.fixture
def app_client(monkeypatch: pytest.MonkeyPatch, signing_key_hex: str) -> TestClient:
    from app.adapters import upstream_http
    from app.adapters import youtube as adapter

    async def fake_resolve(video_id: str, itag: int) -> str:
        return "https://rr1---sn-test.googlevideo.com/videoplayback?id=" + video_id

    async def fake_open_stream(url: str, *, headers: dict[str, str]) -> httpx.Response:
        body = b"audio-bytes-payload"
        request = httpx.Request("GET", url, headers=headers)
        range_header = headers.get("range") or headers.get("Range")
        if range_header:
            resp_headers = {
                "Content-Type": "audio/mp4",
                "Content-Length": str(len(body)),
                "Content-Range": f"bytes 0-{len(body) - 1}/{len(body)}",
                "Accept-Ranges": "bytes",
                "Connection": "keep-alive",
            }
            return httpx.Response(206, headers=resp_headers, content=body, request=request)
        resp_headers = {
            "Content-Type": "audio/mp4",
            "Content-Length": str(len(body)),
            "Accept-Ranges": "bytes",
            "Connection": "keep-alive",
        }
        return httpx.Response(200, headers=resp_headers, content=body, request=request)

    monkeypatch.setattr(adapter, "resolve_upstream_url", fake_resolve)
    monkeypatch.setattr(upstream_http, "open_stream", fake_open_stream)

    from app.main import app

    return TestClient(app)


def _signed_url(path: str, itag: int, signing_key_hex: str, ttl: int = 60) -> str:
    key = bytes.fromhex(signing_key_hex)
    exp = int(time.time()) + ttl
    sig = sign_url(path, itag=itag, exp=exp, key=key)
    return f"{path}?itag={itag}&exp={exp}&sig={sig}"


def test_audio_unsigned_returns_403(app_client: TestClient) -> None:
    r = app_client.get("/proxy/audio/dQw4w9WgXcQ?itag=140&exp=99999999999&sig=" + "0" * 32)
    assert r.status_code == 403


def test_audio_expired_returns_410(app_client: TestClient, signing_key_hex: str) -> None:
    key = bytes.fromhex(signing_key_hex)
    exp = int(time.time()) - 1
    sig = sign_url("/proxy/audio/dQw4w9WgXcQ", itag=140, exp=exp, key=key)
    r = app_client.get(f"/proxy/audio/dQw4w9WgXcQ?itag=140&exp={exp}&sig={sig}")
    assert r.status_code == 410


def test_audio_signed_full_returns_200(app_client: TestClient, signing_key_hex: str) -> None:
    url = _signed_url("/proxy/audio/dQw4w9WgXcQ", 140, signing_key_hex)
    r = app_client.get(url)
    assert r.status_code == 200
    assert r.content == b"audio-bytes-payload"
    assert "connection" not in {k.lower() for k in r.headers}


def test_audio_range_returns_206(app_client: TestClient, signing_key_hex: str) -> None:
    url = _signed_url("/proxy/audio/dQw4w9WgXcQ", 140, signing_key_hex)
    r = app_client.get(url, headers={"Range": "bytes=0-"})
    assert r.status_code == 206
    assert r.headers["accept-ranges"] == "bytes"
