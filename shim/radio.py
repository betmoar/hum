"""Unauthenticated /radio/{id} continuous-stream endpoint for Sonos radio.

Sonos fetches an internet-radio station's streamUrl directly, without Subsonic
credentials, so this router sits outside /rest and carries no auth dependency
(LAN-only exposure assumed; see SHIM_PUBLIC_URL). It resolves the live HLS
manifest via Hum and transcodes it to a continuous mp3 stream with ffmpeg.

NOTE: live-stream → Sonos-radio playback is unverified (spec §4/§7 hardware
gate). The station list and this pipe are in place; whether Sonos accepts the
output must be confirmed on real hardware.
"""
from __future__ import annotations

from fastapi import APIRouter, Path
from fastapi.responses import StreamingResponse

from shim import hum_client, transcode
from shim.config import get_settings

router = APIRouter(tags=["radio"])


@router.get("/radio/{video_id}")
async def radio_stream(
    video_id: str = Path(..., min_length=11, max_length=11, pattern=r"^[A-Za-z0-9_-]{11}$"),
) -> StreamingResponse:
    manifest_url = await hum_client.get_client().live_manifest_url(video_id)
    settings = get_settings()
    args = transcode.live_radio_args(
        manifest_url, ffmpeg_path=settings.ffmpeg_path, bitrate_kbps=settings.mp3_bitrate_kbps
    )
    return StreamingResponse(transcode.stream_ffmpeg(args), media_type="audio/mpeg")
