"""Tests for the fMP4 sidx parser."""
from __future__ import annotations

from pathlib import Path

from app.hls.sidx import parse

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "m4a_head_sample.bin"


def test_parse_real_youtube_m4a_head() -> None:
    """The fixture is the first 64 KB of a real YouTube AAC fMP4 stream."""
    idx = parse(_FIXTURE.read_bytes())
    assert idx is not None
    # Init segment is ftyp+moov+sidx; ends at the start of the first moof.
    # The fixture's first reported fragment starts at 4871.
    assert idx.init_size == 723
    assert idx.segments
    assert idx.segments[0].offset == 4871
    # YouTube ships ~10 s fragments for music streams.
    assert 9.0 < idx.segments[0].duration < 11.0
    # All fragments contiguous (size accumulates).
    expected_off = idx.segments[0].offset
    for s in idx.segments:
        assert s.offset == expected_off
        expected_off += s.size


def test_parse_returns_none_for_non_fmp4() -> None:
    """Garbage in → None out; never raise."""
    assert parse(b"not an mp4 file at all") is None
    assert parse(b"") is None
    assert parse(b"\x00" * 64) is None


def test_parse_returns_none_when_mdat_precedes_sidx() -> None:
    """A non-fragmented MP4 (moov+mdat without sidx) is unseekable via HLS
    byterange and must report None so the caller falls back to direct stream."""
    # Minimal: ftyp (8B header + 0 body), moov (8B + 0), mdat (8B + 0).
    blob = b"".join([
        b"\x00\x00\x00\x08ftyp",
        b"\x00\x00\x00\x08moov",
        b"\x00\x00\x00\x08mdat",
    ])
    assert parse(blob) is None
