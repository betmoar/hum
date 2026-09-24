"""GET /api/playlist/{id}."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query

from app.adapters import youtube
from app.auth import require_bearer
from app.models import PlaylistInfo

router = APIRouter(prefix="/api", tags=["playlist"])

# Kept in sync with youtube._PLAYLIST_DEFAULT_LIMIT (the adapter's own default
# when called without `limit`, e.g. from tests) — this is the route's cap on
# what a client may request per page.
_MAX_LIMIT = 200


@router.get(
    "/playlist/{playlist_id}",
    response_model=PlaylistInfo,
    dependencies=[Depends(require_bearer)],
)
async def playlist(
    playlist_id: str = Path(..., min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
    start: int = Query(1, ge=1, description="1-based index of the first item to fetch"),
    limit: int = Query(_MAX_LIMIT, ge=1, le=_MAX_LIMIT),
) -> PlaylistInfo:
    return await youtube.playlist(playlist_id, start=start, limit=limit)
