"""Tests for /api/search."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.models import SearchHit


@pytest.fixture
def app_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from app.adapters import youtube as adapter

    async def fake_search(q: str, limit: int = 20, **kwargs) -> list[SearchHit]:
        return [
            SearchHit(kind="video", id="a", title="t", thumbnail_url="https://x"),
            SearchHit(kind="channel", id="c", title="ct", thumbnail_url="https://x"),
        ]

    monkeypatch.setattr(adapter, "search", fake_search)
    from app.main import app

    return TestClient(app)


def test_search_requires_auth(app_client: TestClient) -> None:
    r = app_client.get("/api/search?q=test")
    assert r.status_code == 401


def test_search_returns_results(app_client: TestClient, bearer_token: str) -> None:
    r = app_client.get(
        "/api/search?q=test&limit=5",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "test"
    assert len(body["items"]) == 2
    assert body["items"][0]["kind"] == "video"


def test_search_validates_query_length(app_client: TestClient, bearer_token: str) -> None:
    r = app_client.get(
        "/api/search?q=",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert r.status_code == 422


def test_search_forwards_category_to_adapter(monkeypatch, bearer_token):
    from app.adapters import youtube as adapter
    from fastapi.testclient import TestClient

    captured = {}
    async def fake_search(q, limit=20, *, category=None, live=False):
        captured["category"] = category
        captured["live"] = live
        return []
    monkeypatch.setattr(adapter, "search", fake_search)

    from app.main import app
    client = TestClient(app)
    r = client.get(
        "/api/search?q=test&category=music",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert r.status_code == 200
    assert captured["category"] == "music"
    assert captured["live"] is False


def test_search_forwards_live_to_adapter(monkeypatch, bearer_token):
    from app.adapters import youtube as adapter
    from fastapi.testclient import TestClient

    captured = {}
    async def fake_search(q, limit=20, *, category=None, live=False):
        captured["live"] = live
        return []
    monkeypatch.setattr(adapter, "search", fake_search)

    from app.main import app
    client = TestClient(app)
    r = client.get(
        "/api/search?q=test&live=true",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert r.status_code == 200
    assert captured["live"] is True


def test_search_rejects_unknown_category(bearer_token):
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    r = client.get(
        "/api/search?q=test&category=video",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert r.status_code == 422
