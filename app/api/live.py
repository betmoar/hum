"""GET /api/live/{video_id}/manifest.m3u8 — proxied HLS playlist for live streams.

Resolves YouTube's master HLS URL, picks the audio rendition (or lowest-bandwidth
variant), fetches the resulting media playlist, and rewrites each segment URI
to a signed /proxy/live-segment/... path.
"""
from __future__ import annotations

import base64
import time

from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.adapters import upstream_http, youtube
from app.adapters.upstream_http import UpstreamStatusError
from app.auth import (
    SignatureError,
    require_bearer,
    sign_live_segment_url,
    verify_live_manifest_signature,
)
from app.config import get_settings
from app.live.manifest import parse_master, rewrite_media_playlist

router = APIRouter(prefix="/api", tags=["live"])

# Master playlist + picked audio URL cache. hls.js polls the manifest every
# TARGETDURATION (~5s). Each poll used to hit YouTube twice (master + media);
# the master content is stable across that window, so cache it for 2 seconds
# to cut response time roughly in half. The media playlist is always fetched
# fresh because it advances with the live edge.
_MASTER_CACHE_TTL_S = 2.0
_master_cache: dict[str, tuple[str, str, str, float]] = {}
# Mapping video_id -> (master_text, master_base, audio_url, expiry_epoch)


def _error(request: Request, status: int, code: str, message: str) -> JSONResponse:
    # Stash the code on request.state so the access-log middleware in
    # app/main.py appends code=<CODE>; response body/status are unchanged.
    request.state.error_code = code
    return JSONResponse({"error": code, "message": message}, status_code=status)


async def _get_master_and_audio_url(video_id: str) -> tuple[str, str, str]:
    """Return (master_text, master_base, audio_url) for a live video.

    Caches the YouTube master fetch + parse for 2s to amortize across the
    rapid manifest polls hls.js makes. Raises YouTubeError if the master
    URL is unresolvable, UpstreamStatusError if the master fetch fails,
    and returns audio_url="" if no audio rendition can be parsed.
    """
    now = time.monotonic()
    cached = _master_cache.get(video_id)
    if cached and cached[3] > now:
        return cached[0], cached[1], cached[2]
    master_url = await youtube.resolve_live_master_url(video_id)
    master_text, master_base = await upstream_http.fetch_text(master_url)
    audio_url = parse_master(master_text, base=master_base) or ""
    # Evict expired entries on write so the cache can't grow unbounded over a
    # long-running process (one stale entry per live video ever played).
    for k in [k for k, v in _master_cache.items() if v[3] <= now]:
        _master_cache.pop(k, None)
    _master_cache[video_id] = (master_text, master_base, audio_url, now + _MASTER_CACHE_TTL_S)
    return master_text, master_base, audio_url


@router.get("/live/{video_id}/manifest.m3u8", response_model=None)
async def live_manifest(
    request: Request,
    video_id: str = Path(..., min_length=11, max_length=11, pattern=r"^[A-Za-z0-9_-]{11}$"),
    exp: int = Query(...),
    sig: str = Query(..., min_length=32, max_length=32),
) -> PlainTextResponse | JSONResponse:
    settings = get_settings()
    key = settings.signing_key_bytes()
    path = f"/api/live/{video_id}/manifest.m3u8"
    try:
        verify_live_manifest_signature(path, exp=exp, sig=sig, key=key)
    except SignatureError as e:
        return _error(request, e.status, "BAD_SIGNATURE", e.message)

    try:
        _master_text, _master_base, audio_url = await _get_master_and_audio_url(video_id)
    except youtube.YouTubeError as e:
        return _error(request, e.status, e.code, e.message)
    except UpstreamStatusError as e:
        return _error(request, 502, "UPSTREAM_ERROR", f"master fetch failed: {e.status}")

    if not audio_url:
        return _error(request, 502, "MALFORMED_MANIFEST", "no audio rendition in master")

    try:
        media_text, media_base = await upstream_http.fetch_text(audio_url)
    except UpstreamStatusError as e:
        return _error(request, 502, "UPSTREAM_ERROR", f"media fetch failed: {e.status}")

    def segment_url_builder(upstream_seg_url: str) -> str:
        u = base64.urlsafe_b64encode(upstream_seg_url.encode()).decode().rstrip("=")
        return sign_live_segment_url(
            f"/proxy/live-segment/{video_id}",
            u=u, key=key,
            ttl_seconds=settings.stream_url_ttl_seconds,
        )

    # Tail-trim: YouTube serves a multi-hour DVR window (thousands of EXTINF
    # entries). Safari's <audio>+HLS stalls on the resulting load. Keep only
    # the last 10 segments (~50s of live edge) so each manifest refresh is
    # tiny and parses fast.
    rewritten = rewrite_media_playlist(
        media_text, segment_url_builder, base=media_base, tail_segments=10
    )
    return PlainTextResponse(
        content=rewritten,
        media_type="application/vnd.apple.mpegurl",
        headers={"Cache-Control": "no-store"},
    )


@router.get(
    "/debug/live/{video_id}/upstream",
    response_model=None,
    dependencies=[Depends(require_bearer)],
)
async def debug_live_upstream(
    request: Request,
    video_id: str = Path(..., min_length=11, max_length=11, pattern=r"^[A-Za-z0-9_-]{11}$"),
) -> JSONResponse:
    """Debug-only — returns YouTube's raw master + media playlist content so we
    can inspect TARGETDURATION, sliding-window size, MEDIA-SEQUENCE, and any
    directives causing Safari to misbehave. Bearer-protected AND gated on
    DEBUG=true: it exposes raw CDN URLs, which the signing scheme exists to
    keep server-side (invariant #3)."""
    if not get_settings().debug:
        return _error(request, 404, "NOT_FOUND", "debug endpoints are disabled")
    try:
        master_url = await youtube.resolve_live_master_url(video_id)
    except youtube.YouTubeError as e:
        return _error(request, e.status, e.code, e.message)
    try:
        master_text, master_base = await upstream_http.fetch_text(master_url)
    except UpstreamStatusError as e:
        return _error(request, 502, "UPSTREAM_ERROR", f"master fetch failed: {e.status}")
    audio_url = parse_master(master_text, base=master_base)
    media_text: str | None = None
    media_base: str | None = None
    if audio_url:
        try:
            media_text, media_base = await upstream_http.fetch_text(audio_url)
        except UpstreamStatusError as e:
            media_text = f"<fetch failed: {e.status}>"
    return JSONResponse(
        {
            "master_url": master_url,
            "master_base": master_base,
            "master_text": master_text,
            "picked_audio_url": audio_url,
            "media_base": media_base,
            "media_text": media_text,
        },
        headers={"Cache-Control": "no-store"},
    )
