"""Tests for /api/playlist/{id}."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.models import PlaylistInfo, PlaylistItem


@pytest.fixture
def app_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.adapters import youtube as adapter

    async def fake(playlist_id: str) -> PlaylistInfo:
        return PlaylistInfo(
            playlist_id=playlist_id,
            title="t",
            author="a",
            video_count=1,
            items=[PlaylistItem(video_id="abc", title="t", thumbnail_url="https://x")],
        )

    monkeypatch.setattr(adapter, "playlist", fake)
    from app.main import app

    return TestClient(app)


def test_playlist_requires_auth(app_client: TestClient) -> None:
    assert app_client.get("/api/playlist/PLabc").status_code == 401


def test_playlist_returns_info(app_client: TestClient, bearer_token: str) -> None:
    r = app_client.get(
        "/api/playlist/PLabc", headers={"Authorization": f"Bearer {bearer_token}"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["playlist_id"] == "PLabc"
    assert len(body["items"]) == 1
