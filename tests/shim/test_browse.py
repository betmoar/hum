"""Phase 2 browsing tests: synthetic hierarchy + playlist drill-in (Search + Playlists)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from shim.models import HumPlaylistInfo, HumPlaylistItem, HumSearchHit

_PLID = "PLabcdef123"


class FakeHumClient:
    def __init__(
        self,
        hits: list[HumSearchHit] | None = None,
        playlist: HumPlaylistInfo | None = None,
    ) -> None:
        self._hits = hits or []
        self._playlist = playlist

    async def search(self, q: str, limit: int) -> list[HumSearchHit]:
        return self._hits[:limit]

    async def playlist(self, playlist_id: str) -> HumPlaylistInfo:
        assert self._playlist is not None
        return self._playlist

    async def fetch_art(
        self, kind: str, value: str, size: int | None = None
    ) -> tuple[bytes, str]:
        return b"art-bytes", "image/jpeg"


def _install(monkeypatch: pytest.MonkeyPatch, fake: FakeHumClient) -> None:
    from shim import hum_client

    monkeypatch.setattr(hum_client, "get_client", lambda: fake)


def _resp(client: TestClient, auth: dict[str, str], path: str, **params: str) -> dict:
    r = client.get(path, params={**auth, **params})
    assert r.status_code == 200
    return r.json()["subsonic-response"]


def test_get_music_folders(shim_client: TestClient, subsonic_auth: dict[str, str]) -> None:
    body = _resp(shim_client, subsonic_auth, "/rest/getMusicFolders")
    folders = body["musicFolders"]["musicFolder"]
    assert folders == [{"id": 0, "name": "Hum"}]


def test_get_artists_and_indexes_empty(
    shim_client: TestClient, subsonic_auth: dict[str, str]
) -> None:
    assert _resp(shim_client, subsonic_auth, "/rest/getArtists")["artists"]["index"] == []
    assert _resp(shim_client, subsonic_auth, "/rest/getIndexes")["indexes"]["index"] == []


def test_get_album_list2_empty(
    shim_client: TestClient, subsonic_auth: dict[str, str]
) -> None:
    body = _resp(shim_client, subsonic_auth, "/rest/getAlbumList2", type="newest")
    assert body["albumList2"]["album"] == []


def test_get_playlists_empty_without_pins(
    shim_client: TestClient, subsonic_auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, FakeHumClient())
    body = _resp(shim_client, subsonic_auth, "/rest/getPlaylists")
    assert body["playlists"]["playlist"] == []


def test_get_playlists_lists_config_pins(
    shim_client: TestClient, subsonic_auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from shim.config import get_settings

    _install(monkeypatch, FakeHumClient(playlist=_playlist()))
    monkeypatch.setattr(get_settings(), "pinned_playlists", _PLID)
    body = _resp(shim_client, subsonic_auth, "/rest/getPlaylists")
    playlists = body["playlists"]["playlist"]
    assert [p["id"] for p in playlists] == [f"pl:{_PLID}"]
    assert playlists[0]["name"] == "Chill Mix"
    assert playlists[0]["songCount"] == 2


def test_get_playlists_includes_starred(
    shim_client: TestClient, subsonic_auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from shim import store

    _install(monkeypatch, FakeHumClient(playlist=_playlist()))
    store.get_store().star(
        store.StarredItem(id=f"pl:{_PLID}", kind="album", title="Chill Mix", artist="Curator")
    )
    body = _resp(shim_client, subsonic_auth, "/rest/getPlaylists")
    assert [p["id"] for p in body["playlists"]["playlist"]] == [f"pl:{_PLID}"]


def test_get_playlists_drops_failed_lookups(
    shim_client: TestClient, subsonic_auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from shim.config import get_settings

    class _Failing(FakeHumClient):
        async def playlist(self, playlist_id: str) -> HumPlaylistInfo:
            raise RuntimeError("deleted playlist")

    _install(monkeypatch, _Failing())
    monkeypatch.setattr(get_settings(), "pinned_playlists", _PLID)
    body = _resp(shim_client, subsonic_auth, "/rest/getPlaylists")
    # A failing pin is skipped, not fatal.
    assert body["playlists"]["playlist"] == []


def test_search3_surfaces_playlist_as_album(
    shim_client: TestClient, subsonic_auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    hits = [
        HumSearchHit(
            kind="playlist",
            id=_PLID,
            title="Chill Mix",
            author="Curator",
            thumbnail_url="https://i.ytimg.com/x.jpg",
            video_count=42,
        ),
    ]
    _install(monkeypatch, FakeHumClient(hits=hits))
    body = _resp(shim_client, subsonic_auth, "/rest/search3", query="chill")
    albums = body["searchResult3"]["album"]
    assert len(albums) == 1
    assert albums[0]["id"] == f"pl:{_PLID}"
    assert albums[0]["name"] == "Chill Mix"
    assert albums[0]["songCount"] == 42
    assert body["searchResult3"]["song"] == []


def _playlist() -> HumPlaylistInfo:
    return HumPlaylistInfo(
        playlist_id=_PLID,
        title="Chill Mix",
        author="Curator",
        video_count=2,
        items=[
            HumPlaylistItem(video_id="dQw4w9WgXcQ", title="Track 1", duration_seconds=200),
            HumPlaylistItem(video_id="abcdefghijk", title="Track 2", duration_seconds=180),
        ],
    )


def test_get_playlist_expands_to_entries(
    shim_client: TestClient, subsonic_auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, FakeHumClient(playlist=_playlist()))
    body = _resp(shim_client, subsonic_auth, "/rest/getPlaylist", id=f"pl:{_PLID}")
    pl = body["playlist"]
    assert pl["id"] == f"pl:{_PLID}"
    assert pl["songCount"] == 2
    assert [e["id"] for e in pl["entry"]] == ["vid:dQw4w9WgXcQ", "vid:abcdefghijk"]
    assert pl["entry"][0]["title"] == "Track 1"


def test_get_album_expands_to_songs(
    shim_client: TestClient, subsonic_auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, FakeHumClient(playlist=_playlist()))
    body = _resp(shim_client, subsonic_auth, "/rest/getAlbum", id=f"pl:{_PLID}")
    album = body["album"]
    assert album["id"] == f"pl:{_PLID}"
    assert album["coverArt"] == f"pl:{_PLID}"
    assert len(album["song"]) == 2
    assert album["song"][0]["id"] == "vid:dQw4w9WgXcQ"


def test_get_playlist_rejects_video_id(
    shim_client: TestClient, subsonic_auth: dict[str, str]
) -> None:
    r = shim_client.get(
        "/rest/getPlaylist", params={**subsonic_auth, "id": "vid:dQw4w9WgXcQ"}
    )
    body = r.json()["subsonic-response"]
    assert body["status"] == "failed"
    assert body["error"]["code"] == 70


def test_get_cover_art_for_playlist(
    shim_client: TestClient, subsonic_auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, FakeHumClient())
    r = shim_client.get("/rest/getCoverArt", params={**subsonic_auth, "id": f"pl:{_PLID}"})
    assert r.status_code == 200
    assert r.content == b"art-bytes"


def test_browse_requires_auth(shim_client: TestClient) -> None:
    r = shim_client.get("/rest/getMusicFolders", params={"f": "json"})
    assert r.json()["subsonic-response"]["status"] == "failed"
