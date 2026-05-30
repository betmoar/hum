"""GET /api/channel/{id}."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path

from app.adapters import youtube
from app.auth import require_bearer
from app.models import ChannelInfo

router = APIRouter(prefix="/api", tags=["channel"])


@router.get(
    "/channel/{channel_id}",
    response_model=ChannelInfo,
    dependencies=[Depends(require_bearer)],
)
async def channel(
    channel_id: str = Path(..., min_length=5, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
) -> ChannelInfo:
    return await youtube.channel(channel_id)
