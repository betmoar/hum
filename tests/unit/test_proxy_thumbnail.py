"""Tests for /proxy/thumbnail/{id}."""
from __future__ import annotations

import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth import sign_url


@pytest.fixture
def app_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.adapters import upstream_http

    async def fake_open_stream(url: str, *, headers: dict[str, str]) -> httpx.Response:
        body = b"jpeg-bytes"
        request = httpx.Request("GET", url, headers=headers)
        return httpx.Response(
            200,
            headers={"Content-Type": "image/jpeg", "Content-Length": str(len(body))},
            content=body,
            request=request,
        )

    monkeypatch.setattr(upstream_http, "open_stream", fake_open_stream)
    from app.main import app

    return TestClient(app)


def test_thumbnail_unsigned_returns_403_or_422(app_client: TestClient) -> None:
    # No sig query param — FastAPI returns 422 for missing required query
    r = app_client.get("/proxy/thumbnail/dQw4w9WgXcQ")
    assert r.status_code in (403, 422)


def test_thumbnail_signed_returns_200(app_client: TestClient, signing_key_hex: str) -> None:
    key = bytes.fromhex(signing_key_hex)
    exp = int(time.time()) + 60
    sig = sign_url("/proxy/thumbnail/dQw4w9WgXcQ", itag=0, exp=exp, key=key)
    r = app_client.get(f"/proxy/thumbnail/dQw4w9WgXcQ?itag=0&exp={exp}&sig={sig}")
    assert r.status_code == 200
    assert r.content == b"jpeg-bytes"
