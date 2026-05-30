"""Tests for /api/channel/{id}."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.models import ChannelInfo


@pytest.fixture
def app_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.adapters import youtube as adapter

    async def fake(channel_id: str) -> ChannelInfo:
        return ChannelInfo(
            channel_id=channel_id, title="t", subscriber_count=1000, thumbnail_url="https://x"
        )

    monkeypatch.setattr(adapter, "channel", fake)
    from app.main import app

    return TestClient(app)


def test_channel_requires_auth(app_client: TestClient) -> None:
    assert app_client.get("/api/channel/UC1234567890").status_code == 401


def test_channel_returns_info(app_client: TestClient, bearer_token: str) -> None:
    r = app_client.get(
        "/api/channel/UC1234567890",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert r.status_code == 200
    assert r.json()["channel_id"] == "UC1234567890"
