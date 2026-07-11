"""GET /api/video/{id} — returns metadata with signed proxy URLs."""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.adapters import youtube
from app.auth import require_bearer, sign_format_url, sign_live_manifest_url
from app.config import get_settings
from app.models import VideoDetails, VideoID

router = APIRouter(prefix="/api", tags=["video"])


@router.get(
    "/video/{video_id}",
    response_model=VideoDetails,
    dependencies=[Depends(require_bearer)],
)
async def video(
    request: Request,
    video_id: VideoID,
) -> VideoDetails | JSONResponse:
    try:
        details = await youtube.video(video_id)
    except youtube.YouTubeError as e:
        # Surface the mapped code on the hum.access log line (this local catch
        # never reaches app/main.py's global handler). Response is unchanged.
        request.state.error_code = e.code
        return JSONResponse(
            {"error": e.code, "message": e.message},
            status_code=e.status,
        )

    settings = get_settings()
    key = settings.signing_key_bytes()
    ttl = settings.stream_url_ttl_seconds
    exp = int(time.time()) + ttl

    for af in details.audio_formats:
        af.url = sign_format_url(
            f"/proxy/audio/{video_id}", itag=af.itag, key=key, ttl_seconds=ttl, exp=exp
        )
        if af.mime_type.startswith("audio/mp4"):
            af.hls_url = sign_format_url(
                f"/api/hls/{video_id}.m3u8", itag=af.itag, key=key, ttl_seconds=ttl, exp=exp
            )
    for vf in details.video_formats:
        vf.url = sign_format_url(
            f"/proxy/stream/{video_id}", itag=vf.itag, key=key, ttl_seconds=ttl, exp=exp
        )
    if details.thumbnail_url:
        details.thumbnail_url = sign_format_url(
            f"/proxy/thumbnail/{video_id}", itag=0, key=key, ttl_seconds=ttl, exp=exp
        )
    if details.is_live and details.live_stream_url:
        details.live_stream_url = sign_live_manifest_url(
            details.live_stream_url, key=key, ttl_seconds=ttl
        )

    return details
