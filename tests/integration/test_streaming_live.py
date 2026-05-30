"""End-to-end: API → signed URL → upstream stream → first chunk."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


def test_video_endpoint_to_audio_first_chunk(client: TestClient) -> None:
    token = os.environ["API_BEARER_TOKEN"]
    r = client.get(
        "/api/video/dQw4w9WgXcQ",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["audio_formats"], "expected audio formats in response"
    audio = body["audio_formats"][0]["url"]
    assert "sig=" in audio and "exp=" in audio, "expected signed URL"

    r2 = client.get(audio, headers={"Range": "bytes=0-1023"})
    assert r2.status_code in (200, 206), f"unexpected status {r2.status_code}: {r2.text[:200]}"
    assert len(r2.content) > 0
