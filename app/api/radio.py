"""GET /api/radio — live music streams via the YouTube adapter."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.adapters import youtube
from app.auth import require_bearer
from app.models import SearchHit, SearchResponse

router = APIRouter(prefix="/api", tags=["radio"])

# pytubefix Search requires a non-empty query string; this seed query plus
# the Live + music-topic filters produce a live-music-only result set.
RADIO_SEED_QUERY = "live music"


def _looks_live(h: SearchHit) -> bool:
    """Decide whether a search hit is currently a live stream.

    pytubefix's `v.is_live` is unreliable for search results — it's often
    `None` even for currently-live streams. Combine the explicit flag with
    the duration heuristic: true live streams have no duration set (None
    or 0); VOD has a real length.
    """
    if h.is_live is True:
        return True
    if h.is_live is False:
        return False
    # is_live is None — ambiguous. Treat zero/missing duration as the
    # tiebreak signal that this is a live broadcast rather than a VOD.
    return h.duration_seconds is None or h.duration_seconds == 0


@router.get("/radio", response_model=SearchResponse, dependencies=[Depends(require_bearer)])
async def radio(limit: int = Query(20, ge=1, le=50)) -> SearchResponse:
    # YouTube's `features=[Live]` filter is loose — it lets finished broadcasts
    # and related VODs slip through. Over-fetch by 3× to give the post-filter
    # something to work with, then keep items that look live.
    raw = await youtube.search(
        RADIO_SEED_QUERY, limit=min(limit * 3, 50), category="music", live=True
    )
    items = [h for h in raw if _looks_live(h)][:limit]
    return SearchResponse(query=RADIO_SEED_QUERY, items=items)
