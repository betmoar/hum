"""GET /api/hls/{video_id}.m3u8 — HLS playlist that wraps a fragmented-MP4
audio stream so Safari's native HLS player can seek inside it via byterange
without buffering the whole file. Direct-stream-capable browsers never hit
this endpoint; they use /proxy/audio.

If the upstream isn't a parseable fMP4 we return 415 so the frontend can
fall back to the direct stream rather than treating it as fatal.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, PlainTextResponse

from app.adapters import upstream_http, youtube
from app.adapters.upstream_http import UpstreamStatusError
from app.auth import SignatureError, sign_format_url, verify_signature
from app.config import get_settings
from app.hls import sidx
from app.models import VideoID

router = APIRouter(prefix="/api", tags=["hls"])

# How much of the upstream file to fetch when looking for the sidx. The
# largest sidx we've measured for a 1 h YouTube AAC stream is ~4 KB
# (~344 references × 12 B + header) and lives right after the moov.
# 64 KB is safely above that without making the head fetch expensive.
_HEAD_FETCH_BYTES = 64 * 1024

# Target super-segment length, in seconds. YouTube ships ~10 s sidx
# fragments; we coalesce a run of contiguous ones into one HLS segment.
# 60 s drops a 1 h mix from ~340 segments to ~58 — well below any
# concurrent-fetch threshold Safari's HLS engine triggers on startup,
# while still keeping seek granularity tighter than the prebuffer.
_TARGET_SEGMENT_SECONDS = 60.0


def _error(status: int, code: str, message: str) -> JSONResponse:
    """Match the {error, message} response shape the rest of the API uses
    (see the global exception handlers in app.main)."""
    return JSONResponse({"error": code, "message": message}, status_code=status)


@router.get("/hls/{video_id}.m3u8", response_model=None)
async def hls_manifest(
    video_id: VideoID,
    itag: int = Query(..., ge=1, le=9999),
    exp: int = Query(...),
    sig: str = Query(..., min_length=32, max_length=32),
) -> PlainTextResponse | JSONResponse:
    settings = get_settings()
    key = settings.signing_key_bytes()
    try:
        verify_signature(f"/api/hls/{video_id}.m3u8", itag=itag, exp=exp, sig=sig, key=key)
    except SignatureError as e:
        return _error(e.status, "BAD_SIGNATURE", e.message)

    upstream_url = await youtube.resolve_upstream_url(video_id, itag)
    try:
        head = await upstream_http.fetch_range(upstream_url, start=0, end=_HEAD_FETCH_BYTES - 1)
    except UpstreamStatusError as e:
        return _error(502, "UPSTREAM_ERROR", f"upstream returned {e.status}")

    index = sidx.parse(head)
    if index is None or not index.segments:
        # Not fragmented, sidx not where we expect, or an index with no
        # fragments — tell the caller to use /proxy/audio. This isn't fatal,
        # just "HLS not applicable here". Guarding the empty case also keeps
        # _render_manifest's `max(...)` from raising on a degenerate index.
        return _error(415, "NOT_FMP4", "stream not seekable via HLS byte-range")

    segment_uri = sign_format_url(
        f"/proxy/audio/{video_id}",
        itag=itag,
        key=key,
        ttl_seconds=settings.stream_url_ttl_seconds,
    )
    body = _render_manifest(index, segment_uri=segment_uri)
    return PlainTextResponse(
        content=body,
        media_type="application/vnd.apple.mpegurl",
        # The manifest embeds short-lived signed URLs; cache no longer than they live.
        headers={"Cache-Control": f"private, max-age={settings.stream_url_ttl_seconds}"},
    )


@dataclass(frozen=True)
class _Group:
    """Coalesced run of contiguous sidx fragments — one HLS super-segment."""

    offset: int
    size: int
    duration: float


def _render_manifest(index: sidx.ParsedIndex, *, segment_uri: str) -> str:
    """Render an HLS v7 VOD playlist with EXT-X-MAP + coalesced byteranges.

    Per RFC 8216 §4.3.2.2, when a segment continues immediately after the
    previous one on the same URI we omit the @offset, which keeps the
    manifest small on long mixes.
    """
    groups = _coalesce(index.segments, _TARGET_SEGMENT_SECONDS)
    target_duration = max(1, math.ceil(max(g.duration for g in groups)))

    lines: list[str] = [
        "#EXTM3U",
        "#EXT-X-VERSION:7",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        f"#EXT-X-TARGETDURATION:{target_duration}",
        "#EXT-X-MEDIA-SEQUENCE:0",
        f'#EXT-X-MAP:URI="{segment_uri}",BYTERANGE="{index.init_size}@0"',
    ]
    prev_end: int | None = None
    for g in groups:
        byterange = f"{g.size}" if prev_end == g.offset else f"{g.size}@{g.offset}"
        lines.append(f"#EXTINF:{g.duration:.3f},")
        lines.append(f"#EXT-X-BYTERANGE:{byterange}")
        lines.append(segment_uri)
        prev_end = g.offset + g.size
    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


def _coalesce(
    segments: tuple[sidx.Segment, ...], target_seconds: float
) -> list[_Group]:
    """Merge contiguous fragments until accumulated duration hits the target.
    A byte gap forces a new group regardless of duration."""
    out: list[_Group] = []
    cur: _Group | None = None
    for s in segments:
        if (
            cur is not None
            and s.offset == cur.offset + cur.size
            and cur.duration < target_seconds
        ):
            cur = _Group(cur.offset, cur.size + s.size, cur.duration + s.duration)
        else:
            if cur is not None:
                out.append(cur)
            cur = _Group(s.offset, s.size, s.duration)
    if cur is not None:
        out.append(cur)
    return out
