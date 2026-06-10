"""Endpoint tests for star/unstar/getStarred2 and scrobble."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from shim import store

_YTID = "dQw4w9WgXcQ"
_PLID = "PLabcdef123"


def _ok(client: TestClient, auth: dict[str, str], path: str, **params: str) -> dict:
    r = client.get(path, params={**auth, **params})
    assert r.status_code == 200
    body = r.json()["subsonic-response"]
    assert body["status"] == "ok"
    return body


def test_star_then_getstarred2_uses_seen_metadata(
    shim_client: TestClient, subsonic_auth: dict[str, str]
) -> None:
    # Simulate the song having been emitted by a prior search3/getAlbum.
    store.remember(f"vid:{_YTID}", "song", "Never Gonna", "Rick Astley")
    _ok(shim_client, subsonic_auth, "/rest/star", id=f"vid:{_YTID}")

    body = _ok(shim_client, subsonic_auth, "/rest/getStarred2")
    songs = body["starred2"]["song"]
    assert len(songs) == 1
    assert songs[0]["id"] == f"vid:{_YTID}"
    assert songs[0]["title"] == "Never Gonna"
    assert songs[0]["artist"] == "Rick Astley"


def test_star_album_appears_in_albums(
    shim_client: TestClient, subsonic_auth: dict[str, str]
) -> None:
    store.remember(f"pl:{_PLID}", "album", "Chill Mix", "Curator")
    _ok(shim_client, subsonic_auth, "/rest/star", id=f"pl:{_PLID}")
    body = _ok(shim_client, subsonic_auth, "/rest/getStarred2")
    albums = body["starred2"]["album"]
    assert [a["id"] for a in albums] == [f"pl:{_PLID}"]
    assert albums[0]["name"] == "Chill Mix"


def test_star_without_seen_falls_back_to_id_title(
    shim_client: TestClient, subsonic_auth: dict[str, str]
) -> None:
    _ok(shim_client, subsonic_auth, "/rest/star", id=f"vid:{_YTID}")
    body = _ok(shim_client, subsonic_auth, "/rest/getStarred2")
    assert body["starred2"]["song"][0]["title"] == f"vid:{_YTID}"


def test_unstar_removes(
    shim_client: TestClient, subsonic_auth: dict[str, str]
) -> None:
    _ok(shim_client, subsonic_auth, "/rest/star", id=f"vid:{_YTID}")
    _ok(shim_client, subsonic_auth, "/rest/unstar", id=f"vid:{_YTID}")
    body = _ok(shim_client, subsonic_auth, "/rest/getStarred2")
    assert body["starred2"]["song"] == []


def test_star_rejects_malformed_id(
    shim_client: TestClient, subsonic_auth: dict[str, str]
) -> None:
    r = shim_client.get("/rest/star", params={**subsonic_auth, "id": "vid:bad"})
    body = r.json()["subsonic-response"]
    assert body["status"] == "failed"
    assert body["error"]["code"] == 70


def test_scrobble_is_accepted(
    shim_client: TestClient, subsonic_auth: dict[str, str]
) -> None:
    _ok(shim_client, subsonic_auth, "/rest/scrobble", id=f"vid:{_YTID}", submission="true")


def test_favourites_require_auth(shim_client: TestClient) -> None:
    r = shim_client.get("/rest/getStarred2", params={"f": "json"})
    assert r.json()["subsonic-response"]["status"] == "failed"
