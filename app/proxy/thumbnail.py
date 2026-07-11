"""GET /proxy/thumbnail/{id} — pass-through thumbnail proxy with signature."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.adapters import upstream_http
from app.auth import SignatureError, verify_signature
from app.config import get_settings
from app.models import VideoID
from app.proxy._common import body_iterator, filter_response_headers

router = APIRouter(prefix="/proxy", tags=["proxy"])


_THUMB_URL_TEMPLATES = [
    "https://i.ytimg.com/vi/{id}/maxresdefault.jpg",
    "https://i.ytimg.com/vi/{id}/hqdefault.jpg",
]


@router.get("/thumbnail/{video_id}")
async def thumbnail(
    request: Request,
    video_id: VideoID,
    # itag is fixed to 0 for thumbnails (no real format selector); kept in the
    # signature so the same sign/verify pair works across all proxy URLs.
    itag: int = Query(0, ge=0, le=0),
    exp: int = Query(...),
    sig: str = Query(..., min_length=32, max_length=32),
) -> StreamingResponse:
    settings = get_settings()
    key = settings.signing_key_bytes()
    try:
        verify_signature(
            f"/proxy/thumbnail/{video_id}", itag=itag, exp=exp, sig=sig, key=key
        )
    except SignatureError as e:
        # HTTPException bypasses the global error_code-stashing handlers; set it
        # here so the access log carries the code for this route too.
        request.state.error_code = "BAD_SIGNATURE"
        raise HTTPException(status_code=e.status, detail=e.message) from e

    last_status = 502
    for tmpl in _THUMB_URL_TEMPLATES:
        url = tmpl.format(id=video_id)
        resp = await upstream_http.open_stream(url, headers={})
        if resp.status_code == 200:
            return StreamingResponse(
                body_iterator(resp),
                status_code=200,
                headers=filter_response_headers(dict(resp.headers)),
                media_type=resp.headers.get("content-type", "image/jpeg"),
            )
        last_status = resp.status_code
        await resp.aclose()
    request.state.error_code = "THUMBNAIL_NOT_FOUND"
    raise HTTPException(status_code=last_status, detail="thumbnail not found")
