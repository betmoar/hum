"""GET /api/playlist/{id}."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path

from app.adapters import youtube
from app.auth import require_bearer
from app.models import PlaylistInfo

router = APIRouter(prefix="/api", tags=["playlist"])


@router.get(
    "/playlist/{playlist_id}",
    response_model=PlaylistInfo,
    dependencies=[Depends(require_bearer)],
)
async def playlist(
    playlist_id: str = Path(..., min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
) -> PlaylistInfo:
    return await youtube.playlist(playlist_id)
