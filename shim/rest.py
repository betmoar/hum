"""The /rest Subsonic surface — Phase 1 endpoints (spec §3.1, §7).

Every endpoint answers both /name and /name.view (Subsonic clients vary).
All endpoints authenticate, ping included; errors surface as failed
envelopes via the SubsonicError handler in shim.main.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import FileResponse, StreamingResponse

from shim import hum_client, ids, mediacache, store, transcode
from shim.auth import require_subsonic_auth
from shim.config import get_settings
from shim.models import HumPlaylistItem, HumSearchHit, looks_live
from shim.store import StarredItem
from shim.subsonic import NOT_FOUND, SubsonicError, ok_response

router = APIRouter(prefix="/rest", dependencies=[Depends(require_subsonic_auth)])


def _remember(entry: dict[str, Any], kind: str) -> dict[str, Any]:
    """Record an emitted song/album so a later star can render its name
    without re-fetching from Hum. Returns the entry for inline use."""
    name = entry.get("title") or entry.get("name") or entry["id"]
    store.remember(entry["id"], kind, str(name), str(entry.get("artist", "Unknown")))
    return entry


def _song_from_hit(hit: HumSearchHit) -> dict[str, Any]:
    sid = ids.video_id(hit.id)
    # Single video → single-track "album" (spec §3.4) so it slots into
    # Subsonic's album/track expectations.
    return {
        "id": sid,
        "isDir": False,
        "type": "music",
        "title": hit.title,
        "album": hit.title,
        "artist": hit.author or "Unknown",
        "coverArt": sid,
        "duration": hit.duration_seconds or 0,
        "contentType": "audio/mp4",
        "suffix": "m4a",
    }


def _song_from_playlist_item(item: HumPlaylistItem) -> dict[str, Any]:
    sid = ids.video_id(item.video_id)
    return {
        "id": sid,
        "isDir": False,
        "type": "music",
        "title": item.title,
        "artist": item.author or "Unknown",
        "coverArt": sid,
        "duration": item.duration_seconds or 0,
        "contentType": "audio/mp4",
        "suffix": "m4a",
    }


def _album_from_hit(hit: HumSearchHit) -> dict[str, Any]:
    # A YouTube playlist → a Subsonic album the user can drill into via
    # getAlbum/getPlaylist (spec §3.4: playlists map cleanly).
    sid = ids.playlist_id(hit.id)
    return {
        "id": sid,
        "name": hit.title,
        "title": hit.title,
        "artist": hit.author or "Unknown",
        "coverArt": sid,
        "songCount": hit.video_count or 0,
    }


@router.get("/ping")
@router.get("/ping.view")
async def ping() -> Response:
    return ok_response()


@router.get("/getLicense")
@router.get("/getLicense.view")
async def get_license() -> Response:
    return ok_response({"license": {"valid": True}})


@router.get("/search3")
@router.get("/search3.view")
async def search3(
    query: str = Query(..., min_length=1, max_length=200),
    song_count: int = Query(20, alias="songCount", ge=1, le=50),
) -> Response:
    hits = await hum_client.get_client().search(query, limit=song_count)
    songs = [
        _remember(_song_from_hit(h), "song")
        for h in hits
        # Spec §3.4 polarity: radio.py keeps live hits, search3 drops them.
        if h.kind == "video" and not looks_live(h)
    ][:song_count]
    # Playlist hits become drill-in albums; channels (artists) are out of scope
    # for the Search + Playlists hierarchy.
    albums = [
        _remember(_album_from_hit(h), "album") for h in hits if h.kind == "playlist"
    ][:song_count]
    return ok_response({"searchResult3": {"artist": [], "album": albums, "song": songs}})


# ----- browsing (spec §3.2; Search + Playlists hierarchy) -------------------


@router.get("/getMusicFolders")
@router.get("/getMusicFolders.view")
async def get_music_folders() -> Response:
    return ok_response({"musicFolders": {"musicFolder": [{"id": 0, "name": "Hum"}]}})


@router.get("/getArtists")
@router.get("/getArtists.view")
async def get_artists() -> Response:
    # A search-centric source has no static artist catalog; discovery is the
    # search box plus playlist drill-in. A valid empty index, not a stub.
    return ok_response({"artists": {"ignoredArticles": "", "index": []}})


@router.get("/getIndexes")
@router.get("/getIndexes.view")
async def get_indexes() -> Response:
    return ok_response(
        {"indexes": {"ignoredArticles": "", "lastModified": 0, "index": []}}
    )


@router.get("/getAlbumList2")
@router.get("/getAlbumList2.view")
async def get_album_list2(
    list_type: str = Query("newest", alias="type"),
    size: int = Query(10, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Response:
    # Hum has no catalog or play history (spec §3.2/§9.4), so recent/frequent/
    # newest/random are all empty; discovery happens through search.
    return ok_response({"albumList2": {"album": []}})


def _pinned_playlist_ids() -> list[str]:
    """Playlist ids for the Sonos shelf: SHIM_PINNED_PLAYLISTS config first,
    then starred playlists (pl: ids), de-duplicated, order preserved."""
    ids_list = list(get_settings().pinned_playlist_ids())
    seen = set(ids_list)
    for it in store.get_store().starred():
        if it.kind == "album" and it.id.startswith("pl:"):
            value = it.id[len("pl:") :]
            if value not in seen:
                seen.add(value)
                ids_list.append(value)
    return ids_list


async def _playlist_summary(yt_playlist_id: str) -> dict[str, Any]:
    info = await hum_client.get_client().playlist(yt_playlist_id)
    return {
        "id": ids.playlist_id(yt_playlist_id),
        "name": info.title,
        "owner": info.author or "Unknown",
        "songCount": info.video_count,
    }


@router.get("/getPlaylists")
@router.get("/getPlaylists.view")
async def get_playlists() -> Response:
    # Hum can't enumerate playlists, so the shelf is the curated/starred set
    # (spec §3.2). Resolve summaries concurrently; drop any that fail (e.g. a
    # deleted playlist) rather than failing the whole shelf.
    pins = _pinned_playlist_ids()
    results = await asyncio.gather(
        *(_playlist_summary(pid) for pid in pins), return_exceptions=True
    )
    playlists = [r for r in results if isinstance(r, dict)]
    return ok_response({"playlists": {"playlist": playlists}})


@router.get("/getPlaylist")
@router.get("/getPlaylist.view")
async def get_playlist(item_id: str = Query(..., alias="id")) -> Response:
    sid = ids.parse_id(item_id)
    if sid.kind != "playlist":
        raise SubsonicError(NOT_FOUND, "getPlaylist expects a pl: id")
    info = await hum_client.get_client().playlist(sid.value)
    entries = [_remember(_song_from_playlist_item(i), "song") for i in info.items]
    return ok_response(
        {
            "playlist": {
                "id": ids.playlist_id(sid.value),
                "name": info.title,
                "owner": info.author or "Unknown",
                "songCount": info.video_count,
                "entry": entries,
            }
        }
    )


@router.get("/getAlbum")
@router.get("/getAlbum.view")
async def get_album(item_id: str = Query(..., alias="id")) -> Response:
    sid = ids.parse_id(item_id)
    if sid.kind != "playlist":
        raise SubsonicError(NOT_FOUND, "getAlbum expects a pl: id")
    info = await hum_client.get_client().playlist(sid.value)
    songs = [_remember(_song_from_playlist_item(i), "song") for i in info.items]
    pid = ids.playlist_id(sid.value)
    return ok_response(
        {
            "album": {
                "id": pid,
                "name": info.title,
                "artist": info.author or "Unknown",
                "coverArt": pid,
                "songCount": info.video_count,
                "song": songs,
            }
        }
    )


# ----- internet radio (spec §3.2 radio; backed by Hum /api/radio) -----------

_RADIO_LIMIT = 20


@router.get("/getInternetRadioStations")
@router.get("/getInternetRadioStations.view")
async def get_internet_radio_stations() -> Response:
    # bonob surfaces these as a non-library "Internet Radio" shelf in Sonos.
    # Each live music stream becomes a station whose streamUrl points back at
    # the shim's (unauthenticated) /radio/{id} continuous-stream endpoint.
    hits = await hum_client.get_client().radio(limit=_RADIO_LIMIT)
    base = get_settings().public_base_url()
    stations = [
        {
            "id": f"rad:{h.id}",
            "name": h.title,
            "streamUrl": f"{base}/radio/{h.id}",
            "homePageUrl": f"https://www.youtube.com/watch?v={h.id}",
        }
        for h in hits
    ]
    return ok_response(
        {"internetRadioStations": {"internetRadioStation": stations}}
    )


@router.get("/getCoverArt")
@router.get("/getCoverArt.view")
async def get_cover_art(
    item_id: str = Query(..., alias="id"),
    size: int | None = Query(None, ge=1),
) -> Response:
    sid = ids.parse_id(item_id)
    content, media_type = await hum_client.get_client().fetch_art(sid.kind, sid.value, size)
    return Response(content=content, media_type=media_type)


# ----- favourites + scrobble (spec §3.3 — shim-side; Hum stores nothing) ----


def _starred2_lists() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    songs: list[dict[str, Any]] = []
    albums: list[dict[str, Any]] = []
    for it in store.get_store().starred():
        if it.kind == "song":
            songs.append(
                {
                    "id": it.id,
                    "title": it.title,
                    "artist": it.artist,
                    "isDir": False,
                    "type": "music",
                    "coverArt": it.id,
                    "contentType": "audio/mp4",
                    "suffix": "m4a",
                }
            )
        else:
            albums.append(
                {
                    "id": it.id,
                    "name": it.title,
                    "title": it.title,
                    "artist": it.artist,
                    "coverArt": it.id,
                }
            )
    return songs, albums


@router.get("/star")
@router.get("/star.view")
async def star(item_id: str = Query(..., alias="id")) -> Response:
    sid = ids.parse_id(item_id)
    kind = "song" if sid.kind == "video" else "album"
    seen = store.recall(item_id)
    title, artist = (seen[1], seen[2]) if seen else (item_id, "Unknown")
    store.get_store().star(StarredItem(id=item_id, kind=kind, title=title, artist=artist))
    return ok_response()


@router.get("/unstar")
@router.get("/unstar.view")
async def unstar(item_id: str = Query(..., alias="id")) -> Response:
    ids.parse_id(item_id)  # validate shape; unknown ids are a harmless no-op
    store.get_store().unstar(item_id)
    return ok_response()


@router.get("/getStarred2")
@router.get("/getStarred2.view")
async def get_starred2() -> Response:
    songs, albums = _starred2_lists()
    return ok_response({"starred2": {"artist": [], "album": albums, "song": songs}})


@router.get("/getStarred")
@router.get("/getStarred.view")
async def get_starred() -> Response:
    songs, albums = _starred2_lists()
    return ok_response({"starred": {"artist": [], "album": albums, "song": songs}})


@router.get("/scrobble")
@router.get("/scrobble.view")
async def scrobble(
    item_id: str = Query(..., alias="id"),
    submission: bool = Query(True),
) -> Response:
    # Hum has no play history to write to (spec §9.4); accept gracefully so
    # bonob's now-playing/scrobble reports don't error.
    return ok_response()


@router.get("/stream")
@router.get("/stream.view")
async def stream(item_id: str = Query(..., alias="id")) -> Response:
    sid = ids.parse_id(item_id)
    if sid.kind != "video":
        raise SubsonicError(NOT_FOUND, "only vid: ids are streamable")
    client = hum_client.get_client()
    details = await client.video_details(sid.value)
    fmt, mode = transcode.pick_audio_format(details.audio_formats)
    settings = get_settings()
    input_url = client.absolute(fmt.url)

    # Seekable mode (b): materialize the remux to a cached file and let
    # Starlette serve it with Content-Length + Range (a Sonos seek bar). Falls
    # back to the streaming pipe if materialization fails.
    if mode == "remux" and settings.seekable_remux:

        async def _produce(dest: Path) -> bool:
            return await transcode.materialize(
                transcode.remux_file_args(
                    input_url, dest, ffmpeg_path=settings.ffmpeg_path
                )
            )

        path = await mediacache.get_cache().get_or_produce(sid.value, _produce)
        if path is not None:
            return FileResponse(path, media_type="audio/mp4")

    # Range-ignoring mode (a) from spec §4: stream straight through.
    args = transcode.ffmpeg_args(
        input_url,
        mode,
        ffmpeg_path=settings.ffmpeg_path,
        mp3_bitrate_kbps=settings.mp3_bitrate_kbps,
    )
    return StreamingResponse(
        transcode.stream_ffmpeg(args), media_type=transcode.media_type_for(mode)
    )
