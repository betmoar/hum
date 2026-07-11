"""Parse a fragmented-MP4 segment index (sidx) from the head of a stream.

Reference: ISO/IEC 14496-12 §8.16.3.

We need three things to render an HLS playlist that Safari can seek inside:
  - where the init segment (ftyp+moov+sidx region) ends
  - the (offset, size, duration) of each fragment in the file
  - the timescale (so durations can be converted to seconds)

The parser is tolerant: if the head doesn't look like a parseable
ftyp+moov+sidx layout we return None, so the caller can fall back to
direct-stream rather than serve a broken playlist.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    offset: int        # absolute byte offset in the file
    size: int          # bytes
    duration: float    # seconds


@dataclass(frozen=True)
class ParsedIndex:
    init_size: int                  # bytes [0, init_size) form the HLS init segment
    segments: tuple[Segment, ...]

    @property
    def total_duration(self) -> float:
        return sum(s.duration for s in self.segments)


def parse(data: bytes) -> ParsedIndex | None:
    """Parse a fragmented MP4 head. Returns None if no usable index is found."""
    init_end: int | None = None
    sidx_off: int | None = None
    sidx_end: int | None = None

    off = 0
    n = len(data)
    while off + 8 <= n:
        size = _u32(data, off)
        btype = data[off + 4 : off + 8]
        hdr = 8
        if size == 1:
            if off + 16 > n:
                return None
            size = _u64(data, off + 8)
            hdr = 16
        if size < hdr:
            return None

        if btype == b"moov":
            init_end = off + size
        elif btype == b"sidx":
            sidx_off = off
            sidx_end = off + size
            break
        elif btype == b"mdat":
            # Past the index region without finding a sidx — not seekable.
            return None

        off += size

    if sidx_off is None or sidx_end is None or init_end is None:
        return None
    if sidx_off < init_end:
        return None
    # The sidx box claims to extend past the fetched head (very long streams
    # can exceed the 64 KB head fetch). Every read below is bounded by
    # `sidx_end`, so a truncated buffer would raise struct.error mid-parse.
    # Bail out instead — the caller falls back to the direct stream.
    if sidx_end > n:
        return None

    return _parse_sidx(data, sidx_off, sidx_end, init_end)


def _parse_sidx(data: bytes, off: int, end: int, init_end: int) -> ParsedIndex | None:
    body = off + 8
    if body + 12 > end:
        return None

    version = data[body]
    timescale = _u32(data, body + 8)
    if timescale == 0:
        return None

    p = body + 12
    if version == 0:
        if p + 8 > end:
            return None
        first_offset = _u32(data, p + 4)
        p += 8
    elif version == 1:
        if p + 16 > end:
            return None
        first_offset = _u64(data, p + 8)
        p += 16
    else:
        return None

    if p + 4 > end:
        return None
    ref_count = _u16(data, p + 2)
    p += 4

    if ref_count == 0 or p + ref_count * 12 > end:
        return None

    cursor = end + first_offset
    segments: list[Segment] = []
    for _ in range(ref_count):
        word1 = _u32(data, p)
        sub_dur = _u32(data, p + 4)
        p += 12

        ref_type = word1 >> 31
        ref_size = word1 & 0x7FFF_FFFF
        if ref_type != 0 or ref_size == 0:
            return None

        segments.append(Segment(
            offset=cursor,
            size=ref_size,
            duration=sub_dur / timescale,
        ))
        cursor += ref_size

    return ParsedIndex(init_size=init_end, segments=tuple(segments))


def _u16(b: bytes, o: int) -> int:
    (val,) = struct.unpack_from(">H", b, o)
    return int(val)


def _u32(b: bytes, o: int) -> int:
    (val,) = struct.unpack_from(">I", b, o)
    return int(val)


def _u64(b: bytes, o: int) -> int:
    (val,) = struct.unpack_from(">Q", b, o)
    return int(val)
