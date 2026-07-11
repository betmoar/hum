"""Shared helpers for proxy routes: hop-by-hop header strip, body lifecycle,
and a factory for signed-stream proxy routers (audio + video).
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.adapters import upstream_http, youtube
from app.auth import SignatureError, verify_signature
from app.config import get_settings
from app.models import VideoID

logger = logging.getLogger("hum.proxy")

# Upstream statuses that mean "the cached CDN URL is stale" (not "the itag is
# gone"). YouTube can invalidate a cached URL early (IP change); retrying with
# the same stale URL just repeats the failure, so on these we evict the cache
# entry and re-resolve once. Bounded: see stream_proxy's single `if` below.
_RETRIABLE_UPSTREAM_STATUSES = frozenset({403, 410})

# RFC 7230 §6.1 hop-by-hop headers + a few cookie/server fingerprints we
# don't want to leak from the upstream (YouTube) to our API clients.
_STRIP_HEADERS = {
    # Hop-by-hop (RFC 7230 §6.1)
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "trailers",
    "transfer-encoding",
    "upgrade",
    # Don't pass through YouTube's cookies / server fingerprints / alt-svc hints.
    "set-cookie",
    "alt-svc",
    "server",
}


def filter_response_headers(src: dict[str, str]) -> dict[str, str]:
    return {k: v for k, v in src.items() if k.lower() not in _STRIP_HEADERS}


def body_iterator(resp: httpx.Response) -> AsyncIterator[bytes]:
    """Async-iterate the response body, guaranteeing close on exit."""

    async def _iter() -> AsyncIterator[bytes]:
        try:
            async for chunk in resp.aiter_bytes():
                yield chunk
        finally:
            await resp.aclose()

    return _iter()


def create_signed_stream_router(
    prefix: str,
    route_path: str,
    proxy_base: str,
    *,
    tag: str = "proxy",
) -> APIRouter:
    """Factory for signed-proxy stream routes (audio, video).

    Encapsulates the shared verify → resolve → stream → respond pipeline
    so audio.py and video.py don't duplicate it.
    """
    router = APIRouter(prefix=prefix, tags=[tag])

    @router.get(route_path)
    async def stream_proxy(
        request: Request,
        video_id: VideoID,
        itag: int = Query(..., ge=1, le=9999),
        exp: int = Query(...),
        sig: str = Query(..., min_length=32, max_length=32),
    ) -> StreamingResponse:
        settings = get_settings()
        key = settings.signing_key_bytes()
        try:
            verify_signature(
                f"{proxy_base}/{video_id}", itag=itag, exp=exp, sig=sig, key=key
            )
        except SignatureError as e:
            # HTTPException is handled by Starlette directly, bypassing the
            # global handlers that stash error_code — set it here so the access
            # log carries code=BAD_SIGNATURE for this route too.
            request.state.error_code = "BAD_SIGNATURE"
            raise HTTPException(status_code=e.status, detail=e.message) from e

        upstream_url = await youtube.resolve_upstream_url(video_id, itag)

        upstream_headers: dict[str, str] = {}
        if rng := request.headers.get("range"):
            upstream_headers["Range"] = rng

        resp = await upstream_http.open_stream(upstream_url, headers=upstream_headers)
        if resp.status_code in _RETRIABLE_UPSTREAM_STATUSES:
            await resp.aclose()
            logger.info(
                "upstream %d for %s itag=%d; evicting cached stream URL and retrying once",
                resp.status_code, video_id, itag,
            )
            youtube.evict_stream_url(video_id, itag)
            upstream_url = await youtube.resolve_upstream_url(video_id, itag)
            resp = await upstream_http.open_stream(upstream_url, headers=upstream_headers)

        return StreamingResponse(
            body_iterator(resp),
            status_code=resp.status_code,
            headers=filter_response_headers(dict(resp.headers)),
            media_type=resp.headers.get("content-type"),
        )

    return router
