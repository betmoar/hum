"""Tests for /proxy/stream/{id} — signed video stream proxy."""
from __future__ import annotations

import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth import sign_url


@pytest.fixture
def app_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.adapters import upstream_http
    from app.adapters import youtube as adapter

    async def fake_resolve(video_id: str, itag: int) -> str:
        return "https://rr2---sn-test.googlevideo.com/videoplayback?id=" + video_id

    async def fake_open_stream(url: str, *, headers: dict[str, str]) -> httpx.Response:
        body = b"video-bytes-payload"
        request = httpx.Request("GET", url, headers=headers)
        return httpx.Response(
            200,
            headers={"Content-Type": "video/mp4", "Content-Length": str(len(body))},
            content=body,
            request=request,
        )

    monkeypatch.setattr(adapter, "resolve_upstream_url", fake_resolve)
    monkeypatch.setattr(upstream_http, "open_stream", fake_open_stream)

    from app.main import app

    return TestClient(app)


def test_video_proxy_unsigned_returns_403(app_client: TestClient) -> None:
    r = app_client.get("/proxy/stream/dQw4w9WgXcQ?itag=137&exp=99999999999&sig=" + "0" * 32)
    assert r.status_code == 403


def test_video_proxy_signed_returns_200(app_client: TestClient, signing_key_hex: str) -> None:
    key = bytes.fromhex(signing_key_hex)
    exp = int(time.time()) + 60
    sig = sign_url("/proxy/stream/dQw4w9WgXcQ", itag=137, exp=exp, key=key)
    r = app_client.get(f"/proxy/stream/dQw4w9WgXcQ?itag=137&exp={exp}&sig={sig}")
    assert r.status_code == 200
    assert r.content == b"video-bytes-payload"
