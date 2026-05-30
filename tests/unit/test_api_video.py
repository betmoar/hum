"""Tests for /api/video/{id}."""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.models import AudioFormat, VideoDetails, VideoFormat


@pytest.fixture
def app_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.adapters import youtube as adapter

    async def fake_video(video_id: str) -> VideoDetails:
        return VideoDetails(
            video_id=video_id,
            title="t",
            author="a",
            channel_id="c",
            duration_seconds=120,
            thumbnail_url=f"/proxy/thumbnail/{video_id}",
            audio_formats=[
                AudioFormat(
                    itag=140,
                    mime_type='audio/mp4; codecs="mp4a.40.2"',
                    bitrate=128000,
                    codec="aac",
                    url=f"/proxy/audio/{video_id}?itag=140",
                )
            ],
            video_formats=[
                VideoFormat(
                    itag=137,
                    mime_type='video/mp4; codecs="avc1.640028"',
                    bitrate=4_000_000,
                    codec="avc1",
                    width=1920,
                    height=1080,
                    fps=30,
                    has_audio=False,
                    url=f"/proxy/stream/{video_id}?itag=137",
                )
            ],
        )

    monkeypatch.setattr(adapter, "video", fake_video)
    from app.main import app

    return TestClient(app)


def test_video_requires_auth(app_client: TestClient) -> None:
    r = app_client.get("/api/video/dQw4w9WgXcQ")
    assert r.status_code == 401


def test_video_returns_signed_urls(app_client: TestClient, bearer_token: str) -> None:
    r = app_client.get(
        "/api/video/dQw4w9WgXcQ", headers={"Authorization": f"Bearer {bearer_token}"}
    )
    assert r.status_code == 200
    body = r.json()
    audio_url = body["audio_formats"][0]["url"]
    qs = parse_qs(urlparse(audio_url).query)
    assert "exp" in qs and "sig" in qs and qs["itag"] == ["140"]

    video_url = body["video_formats"][0]["url"]
    qs = parse_qs(urlparse(video_url).query)
    assert "exp" in qs and "sig" in qs and qs["itag"] == ["137"]


def test_video_signs_thumbnail_url(app_client: TestClient, bearer_token: str) -> None:
    r = app_client.get(
        "/api/video/dQw4w9WgXcQ", headers={"Authorization": f"Bearer {bearer_token}"}
    )
    body = r.json()
    qs = parse_qs(urlparse(body["thumbnail_url"]).query)
    assert "exp" in qs and "sig" in qs


def test_api_video_signs_live_stream_url(monkeypatch, bearer_token):
    """When the adapter returns is_live=True, the API signs live_stream_url."""
    from fastapi.testclient import TestClient
    from app.adapters import youtube as adapter
    from app.models import VideoDetails

    async def fake_video(video_id):
        return VideoDetails(
            video_id=video_id,
            title="Lofi Radio", author="ChilledCow", channel_id="UC1",
            duration_seconds=0,
            thumbnail_url=f"/proxy/thumbnail/{video_id}",
            audio_formats=[], video_formats=[],
            is_live=True,
            live_stream_url=f"/api/live/{video_id}/manifest.m3u8",
        )

    monkeypatch.setattr(adapter, "video", fake_video)
    from app.main import app
    client = TestClient(app)
    r = client.get(
        "/api/video/abc12345678",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["is_live"] is True
    assert body["live_stream_url"].startswith("/api/live/abc12345678/manifest.m3u8?exp=")
    assert "&sig=" in body["live_stream_url"]


def test_api_video_translates_live_not_supported(monkeypatch, bearer_token):
    """YouTubeError(422, LIVE_NOT_SUPPORTED) becomes a 422 response."""
    from fastapi.testclient import TestClient
    from app.adapters import youtube as adapter

    async def fake_video(video_id):
        raise adapter.YouTubeError(422, "LIVE_NOT_SUPPORTED", "Live stream metadata unavailable")

    monkeypatch.setattr(adapter, "video", fake_video)
    from app.main import app
    client = TestClient(app)
    r = client.get(
        "/api/video/abc12345678",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert r.status_code == 422
    body = r.json()
    assert body["error"] == "LIVE_NOT_SUPPORTED"
