"""Smoke tests for response models."""
from __future__ import annotations

from app.models import (
    AudioFormat,
    ChannelInfo,
    PlaylistInfo,
    SearchHit,
    VideoDetails,
    VideoFormat,
)


def test_search_hit_minimal() -> None:
    h = SearchHit(
        kind="video", id="abc", title="t", author="a", thumbnail_url="https://x"
    )
    assert h.kind == "video"


def test_video_details_with_formats() -> None:
    v = VideoDetails(
        video_id="abc",
        title="t",
        author="a",
        channel_id="c",
        duration_seconds=212,
        thumbnail_url="/proxy/thumbnail/abc?...",
        audio_formats=[
            AudioFormat(itag=140, mime_type="audio/mp4; codecs=mp4a.40.2",
                        bitrate=128000, codec="aac", url="/proxy/audio/abc?...")
        ],
        video_formats=[
            VideoFormat(itag=137, mime_type="video/mp4; codecs=avc1.640028",
                        bitrate=4_000_000, codec="avc1",
                        width=1920, height=1080, fps=30,
                        url="/proxy/stream/abc?...")
        ],
    )
    assert v.audio_formats[0].itag == 140
    assert v.video_formats[0].width == 1920


def test_channel_info_minimal() -> None:
    c = ChannelInfo(channel_id="c", title="t", subscriber_count=None, thumbnail_url="https://x")
    assert c.subscriber_count is None


def test_playlist_info_minimal() -> None:
    p = PlaylistInfo(playlist_id="p", title="t", author="a", video_count=0, items=[])
    assert p.items == []


def test_search_hit_is_live_defaults_to_none() -> None:
    from app.models import SearchHit
    hit = SearchHit(kind="video", id="a", title="t", thumbnail_url="x")
    assert hit.is_live is None


def test_search_hit_is_live_accepts_bool() -> None:
    from app.models import SearchHit
    hit = SearchHit(kind="video", id="a", title="t", thumbnail_url="x", is_live=True)
    assert hit.is_live is True


def test_video_details_is_live_defaults_to_false() -> None:
    from app.models import VideoDetails
    d = VideoDetails(
        video_id="abc12345678",
        title="t", author="a", channel_id="c",
        duration_seconds=0, thumbnail_url="x",
    )
    assert d.is_live is False
    assert d.live_stream_url is None


def test_video_details_accepts_live_fields() -> None:
    from app.models import VideoDetails
    d = VideoDetails(
        video_id="abc12345678",
        title="t", author="a", channel_id="c",
        duration_seconds=0, thumbnail_url="x",
        is_live=True, live_stream_url="/api/live/abc12345678/manifest.m3u8",
    )
    assert d.is_live is True
    assert d.live_stream_url == "/api/live/abc12345678/manifest.m3u8"
