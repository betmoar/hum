"""Tests for /api/radio."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.models import SearchHit


@pytest.fixture
def radio_client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, dict]:
    from app.adapters import youtube as adapter

    captured: dict = {}

    async def fake_search(q, limit=20, *, category=None, live=False):
        captured["q"] = q
        captured["category"] = category
        captured["live"] = live
        captured["limit"] = limit
        return [
            SearchHit(
                kind="video", id="live1", title="Lofi Radio",
                thumbnail_url="x", is_live=True,
            ),
        ]

    monkeypatch.setattr(adapter, "search", fake_search)
    from app.main import app
    yield (TestClient(app), captured)


def test_radio_requires_auth(radio_client: tuple[TestClient, dict]) -> None:
    client, _ = radio_client
    r = client.get("/api/radio")
    assert r.status_code == 401


def test_radio_calls_adapter_with_music_and_live(radio_client: tuple[TestClient, dict], bearer_token: str) -> None:
    client, captured = radio_client
    r = client.get(
        "/api/radio?limit=10",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["is_live"] is True
    assert captured["q"] == "live music"
    assert captured["category"] == "music"
    assert captured["live"] is True
    # Endpoint over-fetches 3x (capped at 50) to give the is_live post-filter
    # something to work with — YouTube's `features=[Live]` is loose.
    assert captured["limit"] == 30


def test_radio_filters_out_confirmed_vod_items(monkeypatch: pytest.MonkeyPatch, bearer_token: str) -> None:
    """Items where pytubefix marks is_live=False are dropped. Items where
    is_live=True are kept. Items where is_live=None are kept iff they have
    no duration (true live broadcasts don't advertise a length)."""
    from app.adapters import youtube as adapter

    async def fake_search(q, limit=20, *, category=None, live=False):
        return [
            SearchHit(kind="video", id="live1", title="Live Lofi", thumbnail_url="x", is_live=True, duration_seconds=0),
            SearchHit(kind="video", id="vod1", title="Old VOD", thumbnail_url="x", is_live=False, duration_seconds=240),
            SearchHit(kind="video", id="unk_live", title="Unknown but live", thumbnail_url="x", is_live=None, duration_seconds=None),
            SearchHit(kind="video", id="unk_vod", title="Unknown but VOD", thumbnail_url="x", is_live=None, duration_seconds=600),
            SearchHit(kind="video", id="live2", title="Live Chill", thumbnail_url="x", is_live=True, duration_seconds=None),
        ]

    monkeypatch.setattr(adapter, "search", fake_search)
    from app.main import app
    client = TestClient(app)
    r = client.get(
        "/api/radio?limit=20",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert r.status_code == 200
    ids = [it["id"] for it in r.json()["items"]]
    assert ids == ["live1", "unk_live", "live2"]


def test_radio_respects_limit_after_filter(monkeypatch: pytest.MonkeyPatch, bearer_token: str) -> None:
    """When over-fetch returns more live items than requested, trim to limit."""
    from app.adapters import youtube as adapter

    async def fake_search(q, limit=20, *, category=None, live=False):
        return [
            SearchHit(kind="video", id=f"live{i}", title=f"Live {i}", thumbnail_url="x", is_live=True)
            for i in range(15)
        ]

    monkeypatch.setattr(adapter, "search", fake_search)
    from app.main import app
    client = TestClient(app)
    r = client.get(
        "/api/radio?limit=5",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert r.status_code == 200
    assert len(r.json()["items"]) == 5


def test_radio_validates_limit(bearer_token: str) -> None:
    from app.main import app
    client = TestClient(app)
    r = client.get(
        "/api/radio?limit=0",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert r.status_code == 422
