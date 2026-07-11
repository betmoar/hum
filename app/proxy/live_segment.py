"""GET /proxy/live-segment/{id} — signed proxy for live HLS segments.

The `u` query param is the base64url-encoded upstream segment URL. The
signature wraps (path, u, exp) so a leaked sig can't be reused for
arbitrary CDN access.
"""
from __future__ import annotations

import base64

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.adapters import upstream_http
from app.adapters.upstream_http import UpstreamHostError
from app.auth import SignatureError, verify_live_segment_signature
from app.config import get_settings
from app.proxy._common import body_iterator, filter_response_headers

router = APIRouter(prefix="/proxy", tags=["live-segment"])


def _error(request: Request, status: int, code: str, message: str) -> JSONResponse:
    # Records the code on request.state so the access-log middleware in
    # app/main.py appends code=<CODE>; response body/status are unchanged.
    request.state.error_code = code
    return JSONResponse({"error": code, "message": message}, status_code=status)


@router.get("/live-segment/{video_id}", response_model=None)
async def live_segment(
    request: Request,
    video_id: str = Path(..., min_length=11, max_length=11, pattern=r"^[A-Za-z0-9_-]{11}$"),
    u: str = Query(..., max_length=4096),
    exp: int = Query(...),
    sig: str = Query(..., min_length=32, max_length=32),
) -> StreamingResponse | JSONResponse:
    settings = get_settings()
    key = settings.signing_key_bytes()
    path = f"/proxy/live-segment/{video_id}"
    try:
        verify_live_segment_signature(path, u=u, exp=exp, sig=sig, key=key)
    except SignatureError as e:
        return _error(request, e.status, "BAD_SIGNATURE", e.message)

    try:
        padded = u + "=" * (-len(u) % 4)
        upstream_url = base64.urlsafe_b64decode(padded).decode()
    except Exception:
        return _error(request, 400, "BAD_UPSTREAM_URL", "could not decode upstream URL")

    if not upstream_http.is_allowed_host(upstream_url):
        return _error(request, 400, "BAD_UPSTREAM_HOST", "upstream host not allowed")

    try:
        resp = await upstream_http.open_stream(upstream_url, headers={})
    except UpstreamHostError:
        return _error(request, 400, "BAD_UPSTREAM_HOST", "upstream host not allowed")

    return StreamingResponse(
        body_iterator(resp),
        status_code=resp.status_code,
        headers=filter_response_headers(dict(resp.headers)),
        media_type=resp.headers.get("content-type"),
    )
