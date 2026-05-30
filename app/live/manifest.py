"""Minimal HLS master/media playlist parser + rewriter.

Just enough to:
  - pick the audio-only rendition (or lowest-bandwidth variant) from a master
  - rewrite each segment URI in a media playlist through a builder callable

No full HLS parser; we only touch the directives we need.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from urllib.parse import urljoin

_AUDIO_RENDITION_URI_RE = re.compile(
    r'#EXT-X-MEDIA:[^\n]*TYPE=AUDIO[^\n]*URI="([^"]+)"',
    re.IGNORECASE,
)
_STREAM_INF_BANDWIDTH_RE = re.compile(r"BANDWIDTH=(\d+)", re.IGNORECASE)


def parse_master(text: str, *, base: str) -> str | None:
    """Pick the URI of the audio rendition or lowest-bandwidth variant.

    Returns an absolute URL (relative URIs resolved against `base`),
    or None if no rendition/variant is present.
    """
    if not text or not text.lstrip().startswith("#EXTM3U"):
        return None

    audio_match = _AUDIO_RENDITION_URI_RE.search(text)
    if audio_match:
        return urljoin(base, str(audio_match.group(1)).strip())

    best_bandwidth: int | None = None
    best_uri: str | None = None
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue
        bw_match = _STREAM_INF_BANDWIDTH_RE.search(line)
        if not bw_match:
            continue
        bandwidth = int(bw_match.group(1))
        for j in range(i + 1, len(lines)):
            candidate = lines[j].strip()
            if not candidate or candidate.startswith("#"):
                continue
            if best_bandwidth is None or bandwidth < best_bandwidth:
                best_bandwidth = bandwidth
                best_uri = candidate
            break

    if best_uri is None:
        return None
    return urljoin(base, best_uri)


_HEADER_TAGS = (
    "#EXTM3U",
    "#EXT-X-VERSION",
    "#EXT-X-TARGETDURATION",
    "#EXT-X-PLAYLIST-TYPE",
    "#EXT-X-INDEPENDENT-SEGMENTS",
    "#EXT-X-DISCONTINUITY-SEQUENCE",
    "#EXT-X-START",
)
# Strip these — they're ad-cue metadata that confuses Safari's <audio>+HLS
# during DVR-style live playback, and we have no UI for them.
_DROP_TAGS = (
    "#EXT-X-DATERANGE",
    "#EXT-X-CUEPOINT",
)


def rewrite_media_playlist(
    text: str,
    segment_url_builder: Callable[[str], str],
    *,
    base: str,
    tail_segments: int | None = None,
) -> str:
    """Rewrite each segment URI and `#EXT-X-MAP:URI=` through the builder.

    Relative segment URIs are resolved against `base` BEFORE being passed
    to the builder so the builder always sees an absolute upstream URL.

    When `tail_segments` is set, only the last N segments are emitted (with
    `#EXT-X-MEDIA-SEQUENCE` adjusted forward to reflect the trim) and
    `#EXT-X-PROGRAM-DATE-TIME` lines are dropped (their absolute timing
    becomes meaningless once we trim). Ad-cue markers
    (`#EXT-X-DATERANGE`, `#EXT-X-CUEPOINT`) are always stripped — Safari's
    `<audio>` element stalls on them in DVR-style live playlists.

    Other directives pass through unchanged.
    """
    has_trailing_newline = text.endswith("\n")
    lines = text.splitlines()

    if tail_segments is None:
        return _rewrite_full(lines, segment_url_builder, base, has_trailing_newline)
    return _rewrite_tail(
        lines, segment_url_builder, base, tail_segments, has_trailing_newline
    )


def _rewrite_full(
    lines: list[str],
    segment_url_builder: Callable[[str], str],
    base: str,
    has_trailing_newline: bool,
) -> str:
    """Original passthrough rewrite — keeps all segments, drops ad-cue markers."""
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            out.append(line)
            continue
        if stripped.startswith(_DROP_TAGS):
            continue
        if stripped.startswith("#EXT-X-MAP"):
            out.append(_rewrite_ext_x_map(stripped, segment_url_builder, base=base))
            continue
        if stripped.startswith("#"):
            out.append(line)
            continue
        absolute = urljoin(base, stripped)
        out.append(segment_url_builder(absolute))
    return "\n".join(out) + ("\n" if has_trailing_newline else "")


def _rewrite_tail(
    lines: list[str],
    segment_url_builder: Callable[[str], str],
    base: str,
    tail_segments: int,
    has_trailing_newline: bool,
) -> str:
    """Tail-trim rewrite: keep only the last N (per-segment-tags + URL) pairs.

    Adjusts MEDIA-SEQUENCE forward by the number of dropped segments. Drops
    PROGRAM-DATE-TIME entirely (its anchor is meaningless after trimming).
    """
    header: list[str] = []
    media_sequence = 0
    map_line: str | None = None
    segments: list[tuple[list[str], str]] = []
    pending_tags: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(_DROP_TAGS):
            continue
        if stripped.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                media_sequence = int(stripped.split(":", 1)[1])
            except (ValueError, IndexError):
                media_sequence = 0
            continue
        if stripped.startswith("#EXT-X-MAP"):
            map_line = _rewrite_ext_x_map(stripped, segment_url_builder, base=base)
            continue
        if stripped.startswith("#EXT-X-PROGRAM-DATE-TIME"):
            # Drop — absolute timing is meaningless after tail trim.
            continue
        if stripped.startswith(_HEADER_TAGS):
            header.append(line)
            continue
        if stripped.startswith("#EXT-X-ENDLIST"):
            # Live playlist; ENDLIST shouldn't appear. If it does, preserve.
            pending_tags.append(line)
            continue
        if stripped.startswith("#EXTINF") or stripped.startswith("#EXT-X-DISCONTINUITY"):
            pending_tags.append(line)
            continue
        if stripped.startswith("#"):
            # Unknown per-segment tag; keep with current segment.
            pending_tags.append(line)
            continue
        absolute = urljoin(base, stripped)
        segments.append((pending_tags, segment_url_builder(absolute)))
        pending_tags = []

    dropped = max(0, len(segments) - tail_segments)
    kept = segments[-tail_segments:] if tail_segments > 0 else []
    new_media_sequence = media_sequence + dropped

    out: list[str] = []
    out.extend(header)
    out.append(f"#EXT-X-MEDIA-SEQUENCE:{new_media_sequence}")
    if map_line is not None:
        out.append(map_line)
    for seg_tags, seg_url in kept:
        out.extend(seg_tags)
        out.append(seg_url)
    return "\n".join(out) + ("\n" if has_trailing_newline else "")


_EXT_X_MAP_URI_RE = re.compile(r'URI="([^"]+)"')


def _rewrite_ext_x_map(
    line: str,
    segment_url_builder: Callable[[str], str],
    *,
    base: str,
) -> str:
    def repl(m: re.Match[str]) -> str:
        absolute = urljoin(base, m.group(1).strip())
        return f'URI="{segment_url_builder(absolute)}"'
    return _EXT_X_MAP_URI_RE.sub(repl, line)
