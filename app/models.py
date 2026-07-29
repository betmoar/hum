"""Pydantic response shapes for the Hum API."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

VideoID = Annotated[str, Field(min_length=11, max_length=11, pattern=r"^[A-Za-z0-9_-]{11}$")]


class SearchHit(BaseModel):
    # Frozen because the adapter's search cache hands out SHALLOW list copies —
    # the SearchHit instances themselves are shared across every cache hit for a
    # key. In-place mutation of one (the way /api/video signs VideoDetails by
    # mutation) would poison the cache for all later readers. Freezing turns
    # that into an immediate error instead of a silent corruption.
    model_config = ConfigDict(frozen=True)

    kind: Literal["video", "channel", "playlist"]
    id: str
    title: str
    author: str | None = None
    thumbnail_url: str
    duration_seconds: int | None = None  # video only
    video_count: int | None = None  # playlist only
    is_live: bool | None = None  # video only; None when unknown


class SearchResponse(BaseModel):
    query: str
    items: list[SearchHit]


class AudioFormat(BaseModel):
    itag: int
    mime_type: str
    bitrate: int
    codec: str  # "aac" | "opus" | other
    sample_rate: int | None = None
    channels: int | None = None
    url: str  # signed proxy URL
    hls_url: str | None = None


class VideoFormat(BaseModel):
    itag: int
    mime_type: str
    bitrate: int
    codec: str
    width: int
    height: int
    fps: int | None = None
    has_audio: bool = False  # True for combined formats
    url: str  # signed proxy URL


class VideoDetails(BaseModel):
    video_id: str
    title: str
    description: str | None = None
    author: str
    channel_id: str
    duration_seconds: int
    view_count: int | None = None
    thumbnail_url: str
    audio_formats: list[AudioFormat] = Field(default_factory=list)
    video_formats: list[VideoFormat] = Field(default_factory=list)
    is_live: bool = False
    live_stream_url: str | None = None


class ChannelInfo(BaseModel):
    channel_id: str
    title: str
    description: str | None = None
    subscriber_count: int | None = None
    thumbnail_url: str


class PlaylistItem(BaseModel):
    video_id: str
    title: str
    author: str | None = None
    duration_seconds: int | None = None
    thumbnail_url: str


class PlaylistInfo(BaseModel):
    playlist_id: str
    title: str
    author: str | None = None
    video_count: int
    items: list[PlaylistItem]
