"""GET /api/search — proxy to YouTube search via pytubefix adapter."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.adapters import youtube
from app.auth import require_bearer
from app.models import SearchResponse

router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search", response_model=SearchResponse, dependencies=[Depends(require_bearer)])
async def search(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(20, ge=1, le=50),
    category: Literal["music"] | None = Query(None),
    live: bool = Query(False),
) -> SearchResponse:
    items = await youtube.search(q, limit=limit, category=category, live=live)
    return SearchResponse(query=q, items=items)
