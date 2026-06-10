"""The /rest Subsonic surface — Phase 1 endpoints (spec §3.1, §7).

Every endpoint answers both /name and /name.view (Subsonic clients vary).
All endpoints authenticate, ping included; errors surface as failed
envelopes via the SubsonicError handler in shim.main.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse, StreamingResponse

from shim import hum_client, ids, transcode
from shim.auth import require_subsonic_auth
from shim.config import get_settings
from shim.models import HumPlaylistItem, HumSearchHit, looks_live
from shim.subsonic import NOT_FOUND, SubsonicError, ok_response

router = APIRouter(prefix="/rest", dependencies=[Depends(require_subsonic_auth)])


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
async def ping() -> JSONResponse:
    return ok_response()


@router.get("/getLicense")
@router.get("/getLicense.view")
async def get_license() -> JSONResponse:
    return ok_response({"license": {"valid": True}})


@router.get("/search3")
@router.get("/search3.view")
async def search3(
    query: str = Query(..., min_length=1, max_length=200),
    song_count: int = Query(20, alias="songCount", ge=1, le=50),
) -> JSONResponse:
    hits = await hum_client.get_client().search(query, limit=song_count)
    songs = [
        _song_from_hit(h)
        for h in hits
        # Spec §3.4 polarity: radio.py keeps live hits, search3 drops them.
        if h.kind == "video" and not looks_live(h)
    ][:song_count]
    # Playlist hits become drill-in albums; channels (artists) are out of scope
    # for the Search + Playlists hierarchy.
    albums = [_album_from_hit(h) for h in hits if h.kind == "playlist"][:song_count]
    return ok_response({"searchResult3": {"artist": [], "album": albums, "song": songs}})


# ----- browsing (spec §3.2; Search + Playlists hierarchy) -------------------


@router.get("/getMusicFolders")
@router.get("/getMusicFolders.view")
async def get_music_folders() -> JSONResponse:
    return ok_response({"musicFolders": {"musicFolder": [{"id": 0, "name": "Hum"}]}})


@router.get("/getArtists")
@router.get("/getArtists.view")
async def get_artists() -> JSONResponse:
    # A search-centric source has no static artist catalog; discovery is the
    # search box plus playlist drill-in. A valid empty index, not a stub.
    return ok_response({"artists": {"ignoredArticles": "", "index": []}})


@router.get("/getIndexes")
@router.get("/getIndexes.view")
async def get_indexes() -> JSONResponse:
    return ok_response(
        {"indexes": {"ignoredArticles": "", "lastModified": 0, "index": []}}
    )


@router.get("/getAlbumList2")
@router.get("/getAlbumList2.view")
async def get_album_list2(
    list_type: str = Query("newest", alias="type"),
    size: int = Query(10, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    # Hum has no catalog or play history (spec §3.2/§9.4), so recent/frequent/
    # newest/random are all empty; discovery happens through search.
    return ok_response({"albumList2": {"album": []}})


@router.get("/getPlaylists")
@router.get("/getPlaylists.view")
async def get_playlists() -> JSONResponse:
    # Hum can't enumerate playlists (no library); they're reached via search →
    # getPlaylist by id. Pinning would need shim-side storage (favourites).
    return ok_response({"playlists": {"playlist": []}})


@router.get("/getPlaylist")
@router.get("/getPlaylist.view")
async def get_playlist(item_id: str = Query(..., alias="id")) -> JSONResponse:
    sid = ids.parse_id(item_id)
    if sid.kind != "playlist":
        raise SubsonicError(NOT_FOUND, "getPlaylist expects a pl: id")
    info = await hum_client.get_client().playlist(sid.value)
    entries = [_song_from_playlist_item(i) for i in info.items]
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
async def get_album(item_id: str = Query(..., alias="id")) -> JSONResponse:
    sid = ids.parse_id(item_id)
    if sid.kind != "playlist":
        raise SubsonicError(NOT_FOUND, "getAlbum expects a pl: id")
    info = await hum_client.get_client().playlist(sid.value)
    songs = [_song_from_playlist_item(i) for i in info.items]
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


@router.get("/getCoverArt")
@router.get("/getCoverArt.view")
async def get_cover_art(
    item_id: str = Query(..., alias="id"),
    size: int | None = Query(None, ge=1),  # accepted; resizing is Phase 5
) -> Response:
    sid = ids.parse_id(item_id)
    content, media_type = await hum_client.get_client().fetch_art(sid.kind, sid.value)
    return Response(content=content, media_type=media_type)


@router.get("/stream")
@router.get("/stream.view")
async def stream(item_id: str = Query(..., alias="id")) -> StreamingResponse:
    sid = ids.parse_id(item_id)
    if sid.kind != "video":
        raise SubsonicError(NOT_FOUND, "only vid: ids are streamable")
    client = hum_client.get_client()
    details = await client.video_details(sid.value)
    fmt, mode = transcode.pick_audio_format(details.audio_formats)
    settings = get_settings()
    args = transcode.ffmpeg_args(
        client.absolute(fmt.url),
        mode,
        ffmpeg_path=settings.ffmpeg_path,
        mp3_bitrate_kbps=settings.mp3_bitrate_kbps,
    )
    # Range-ignoring mode (a) from spec §4: stream straight through.
    return StreamingResponse(
        transcode.stream_ffmpeg(args), media_type=transcode.media_type_for(mode)
    )
