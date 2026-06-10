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
from shim.models import HumSearchHit, looks_live
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
    return ok_response({"searchResult3": {"artist": [], "album": [], "song": songs}})


@router.get("/getCoverArt")
@router.get("/getCoverArt.view")
async def get_cover_art(
    item_id: str = Query(..., alias="id"),
    size: int | None = Query(None, ge=1),  # accepted; resizing is Phase 5
) -> Response:
    sid = ids.parse_id(item_id)
    if sid.kind != "video":
        raise SubsonicError(NOT_FOUND, f"no cover art for {sid.kind} ids yet")
    content, media_type = await hum_client.get_client().fetch_art(sid.value)
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
