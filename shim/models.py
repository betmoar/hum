"""Pydantic mirrors of the subset of Hum responses the shim consumes."""
from __future__ import annotations

from pydantic import BaseModel, Field


class HumSearchHit(BaseModel):
    kind: str
    id: str
    title: str
    author: str | None = None
    thumbnail_url: str = ""
    duration_seconds: int | None = None
    video_count: int | None = None  # playlist hits only
    is_live: bool | None = None


class HumPlaylistItem(BaseModel):
    video_id: str
    title: str
    author: str | None = None
    duration_seconds: int | None = None
    thumbnail_url: str = ""


class HumPlaylistInfo(BaseModel):
    playlist_id: str
    title: str
    author: str | None = None
    video_count: int = 0
    items: list[HumPlaylistItem] = Field(default_factory=list)


class HumAudioFormat(BaseModel):
    itag: int
    mime_type: str
    bitrate: int
    codec: str
    url: str  # Hum-relative signed proxy URL


class HumVideoDetails(BaseModel):
    video_id: str
    title: str
    author: str
    duration_seconds: int
    thumbnail_url: str = ""
    audio_formats: list[HumAudioFormat] = Field(default_factory=list)


def looks_live(hit: HumSearchHit) -> bool:
    """Duration heuristic from app/api/radio.py:_looks_live. Polarity note
    from spec §3.4: search3 *drops* hits where this returns True —
    `[h for h in hits if not looks_live(h)]` — whereas /api/radio keeps them.
    """
    if hit.is_live is True:
        return True
    if hit.is_live is False:
        return False
    # is_live is None — ambiguous; zero/missing duration means live.
    return not hit.duration_seconds
