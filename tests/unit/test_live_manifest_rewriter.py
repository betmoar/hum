"""Tests for app.live.manifest.rewrite_media_playlist."""
from __future__ import annotations

from app.live.manifest import rewrite_media_playlist


_BASE = "https://manifest.googlevideo.com/x/audio_only/playlist.m3u8"


def _builder(upstream: str) -> str:
    return f"/proxy/live-segment/abc?u={upstream}"


def test_rewrite_segment_uris() -> None:
    text = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:6\n"
        "#EXT-X-TARGETDURATION:6\n"
        "#EXTINF:5.000,\n"
        "segment1.mp4\n"
        "#EXTINF:5.000,\n"
        "segment2.mp4\n"
    )
    out = rewrite_media_playlist(text, _builder, base=_BASE)
    assert "/proxy/live-segment/abc?u=https://manifest.googlevideo.com/x/audio_only/segment1.mp4" in out
    assert "/proxy/live-segment/abc?u=https://manifest.googlevideo.com/x/audio_only/segment2.mp4" in out
    assert "segment1.mp4\n" not in out.replace("u=https://manifest.googlevideo.com/x/audio_only/segment1.mp4", "")


def test_rewrite_preserves_directives() -> None:
    text = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:6\n"
        "#EXT-X-TARGETDURATION:6\n"
        "#EXT-X-MEDIA-SEQUENCE:42\n"
        "#EXTINF:5.000,\n"
        "segment1.mp4\n"
        "#EXT-X-ENDLIST\n"
    )
    out = rewrite_media_playlist(text, _builder, base=_BASE)
    assert "#EXT-X-VERSION:6" in out
    assert "#EXT-X-TARGETDURATION:6" in out
    assert "#EXT-X-MEDIA-SEQUENCE:42" in out
    assert "#EXTINF:5.000," in out
    assert "#EXT-X-ENDLIST" in out


def test_rewrite_init_segment_via_ext_x_map() -> None:
    text = (
        "#EXTM3U\n"
        '#EXT-X-MAP:URI="init.mp4"\n'
        "#EXTINF:5.000,\n"
        "segment1.mp4\n"
    )
    out = rewrite_media_playlist(text, _builder, base=_BASE)
    assert '#EXT-X-MAP:URI="/proxy/live-segment/abc?u=https://manifest.googlevideo.com/x/audio_only/init.mp4"' in out


def test_rewrite_handles_absolute_segment_uri() -> None:
    text = (
        "#EXTM3U\n"
        "#EXTINF:5.000,\n"
        "https://other.googlevideo.com/seg.mp4\n"
    )
    out = rewrite_media_playlist(text, _builder, base=_BASE)
    assert "/proxy/live-segment/abc?u=https://other.googlevideo.com/seg.mp4" in out


def test_rewrite_strips_daterange_and_cuepoint() -> None:
    """Ad-cue markers must be removed — they stall Safari's <audio>+HLS."""
    text = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:6\n"
        "#EXT-X-TARGETDURATION:5\n"
        '#EXT-X-DATERANGE:CLASS="CUEPOINT-AD",DURATION=60.0,ID="ad-1"\n'
        '#EXT-X-CUEPOINT:CONTEXT=foo,EVENT=START\n'
        "#EXTINF:5.000,\n"
        "seg1.mp4\n"
    )
    out = rewrite_media_playlist(text, _builder, base=_BASE)
    assert "#EXT-X-DATERANGE" not in out
    assert "#EXT-X-CUEPOINT" not in out
    assert "/proxy/live-segment/abc?u=https://manifest.googlevideo.com/x/audio_only/seg1.mp4" in out


def test_rewrite_tail_keeps_only_last_n_segments() -> None:
    """tail_segments=3 keeps last 3 segments and advances MEDIA-SEQUENCE."""
    text = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:6\n"
        "#EXT-X-TARGETDURATION:5\n"
        "#EXT-X-MEDIA-SEQUENCE:100\n"
        "#EXTINF:5.000,\nseg1.mp4\n"
        "#EXTINF:5.000,\nseg2.mp4\n"
        "#EXTINF:5.000,\nseg3.mp4\n"
        "#EXTINF:5.000,\nseg4.mp4\n"
        "#EXTINF:5.000,\nseg5.mp4\n"
    )
    out = rewrite_media_playlist(text, _builder, base=_BASE, tail_segments=3)
    # Dropped 2 (seg1, seg2) → media-sequence 100 + 2 = 102
    assert "#EXT-X-MEDIA-SEQUENCE:102" in out
    assert "seg1.mp4" not in out
    assert "seg2.mp4" not in out
    # Last 3 preserved
    assert "/proxy/live-segment/abc?u=https://manifest.googlevideo.com/x/audio_only/seg3.mp4" in out
    assert "/proxy/live-segment/abc?u=https://manifest.googlevideo.com/x/audio_only/seg4.mp4" in out
    assert "/proxy/live-segment/abc?u=https://manifest.googlevideo.com/x/audio_only/seg5.mp4" in out
    # Header preserved
    assert "#EXT-X-VERSION:6" in out
    assert "#EXT-X-TARGETDURATION:5" in out


def test_rewrite_tail_drops_program_date_time() -> None:
    """PROGRAM-DATE-TIME's anchor is meaningless once we trim — drop it."""
    text = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:6\n"
        "#EXT-X-TARGETDURATION:5\n"
        "#EXT-X-MEDIA-SEQUENCE:50\n"
        "#EXT-X-PROGRAM-DATE-TIME:2026-05-28T16:10:25.099+00:00\n"
        "#EXTINF:5.000,\nseg1.mp4\n"
        "#EXTINF:5.000,\nseg2.mp4\n"
    )
    out = rewrite_media_playlist(text, _builder, base=_BASE, tail_segments=2)
    assert "#EXT-X-PROGRAM-DATE-TIME" not in out


def test_rewrite_tail_preserves_discontinuity_sequence() -> None:
    """DISCONTINUITY-SEQUENCE in the header must survive tail-trim."""
    text = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:6\n"
        "#EXT-X-TARGETDURATION:5\n"
        "#EXT-X-MEDIA-SEQUENCE:0\n"
        "#EXT-X-DISCONTINUITY-SEQUENCE:7\n"
        "#EXTINF:5.000,\nseg1.mp4\n"
        "#EXTINF:5.000,\nseg2.mp4\n"
    )
    out = rewrite_media_playlist(text, _builder, base=_BASE, tail_segments=2)
    assert "#EXT-X-DISCONTINUITY-SEQUENCE:7" in out


def test_rewrite_tail_handles_n_larger_than_segment_count() -> None:
    """When tail_segments > available, keep everything; MEDIA-SEQUENCE unchanged."""
    text = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:6\n"
        "#EXT-X-TARGETDURATION:5\n"
        "#EXT-X-MEDIA-SEQUENCE:42\n"
        "#EXTINF:5.000,\nseg1.mp4\n"
        "#EXTINF:5.000,\nseg2.mp4\n"
    )
    out = rewrite_media_playlist(text, _builder, base=_BASE, tail_segments=10)
    assert "#EXT-X-MEDIA-SEQUENCE:42" in out
    assert "seg1.mp4" in out  # nothing trimmed
    assert "seg2.mp4" in out


def test_rewrite_tail_strips_ad_cue_markers() -> None:
    """Ad-cue markers between segments must be dropped in tail mode too."""
    text = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:6\n"
        "#EXT-X-TARGETDURATION:5\n"
        "#EXT-X-MEDIA-SEQUENCE:0\n"
        "#EXTINF:5.000,\nseg1.mp4\n"
        '#EXT-X-DATERANGE:CLASS="CUEPOINT-AD",ID="ad-1"\n'
        '#EXT-X-CUEPOINT:CONTEXT=foo\n'
        "#EXTINF:5.000,\nseg2.mp4\n"
    )
    out = rewrite_media_playlist(text, _builder, base=_BASE, tail_segments=10)
    assert "#EXT-X-DATERANGE" not in out
    assert "#EXT-X-CUEPOINT" not in out
