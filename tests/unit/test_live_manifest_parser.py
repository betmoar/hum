"""Tests for app.live.manifest.parse_master."""
from __future__ import annotations

from app.live.manifest import parse_master

_BASE = "https://manifest.googlevideo.com/api/manifest/hls_variant/x/master.m3u8"


def test_parse_master_picks_audio_rendition_when_present() -> None:
    text = (
        "#EXTM3U\n"
        '#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="English",DEFAULT=YES,'
        'AUTOSELECT=YES,URI="audio_only/playlist.m3u8"\n'
        '#EXT-X-STREAM-INF:BANDWIDTH=1000000,AUDIO="audio"\n'
        "video/playlist.m3u8\n"
    )
    result = parse_master(text, base=_BASE)
    assert result is not None
    assert result.endswith("/audio_only/playlist.m3u8")


def test_parse_master_falls_back_to_lowest_bandwidth_variant() -> None:
    text = (
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=3000000\n"
        "high/playlist.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=500000\n"
        "low/playlist.m3u8\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=1500000\n"
        "mid/playlist.m3u8\n"
    )
    result = parse_master(text, base=_BASE)
    assert result is not None
    assert result.endswith("/low/playlist.m3u8")


def test_parse_master_returns_none_when_empty() -> None:
    text = "#EXTM3U\n"
    assert parse_master(text, base=_BASE) is None


def test_parse_master_returns_none_on_malformed_input() -> None:
    text = "this is not a playlist"
    assert parse_master(text, base=_BASE) is None


def test_parse_master_resolves_relative_uri_against_base() -> None:
    text = (
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=500000\n"
        "low/playlist.m3u8\n"
    )
    result = parse_master(text, base="https://manifest.googlevideo.com/x/master.m3u8")
    assert result == "https://manifest.googlevideo.com/x/low/playlist.m3u8"


def test_parse_master_handles_absolute_uri() -> None:
    text = (
        "#EXTM3U\n"
        "#EXT-X-STREAM-INF:BANDWIDTH=500000\n"
        "https://other.googlevideo.com/full/playlist.m3u8\n"
    )
    result = parse_master(text, base=_BASE)
    assert result == "https://other.googlevideo.com/full/playlist.m3u8"
