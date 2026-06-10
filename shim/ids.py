"""Stable Subsonic↔YouTube ID scheme: vid:<video>, pl:<playlist>, art:<channel>.

Every ID handed to a Subsonic client must round-trip back to the right Hum
call (spec §3.4). Patterns mirror Hum's own validators (app/models.py,
app/api/playlist.py, app/api/channel.py) so malformed IDs are rejected here
instead of surfacing as Hum 422s.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from shim.subsonic import NOT_FOUND, SubsonicError

Kind = Literal["video", "playlist", "artist"]

_PATTERNS: dict[str, tuple[Kind, re.Pattern[str]]] = {
    "vid": ("video", re.compile(r"^[A-Za-z0-9_-]{11}$")),
    "pl": ("playlist", re.compile(r"^[A-Za-z0-9_-]{2,64}$")),
    "art": ("artist", re.compile(r"^[A-Za-z0-9_-]{5,64}$")),
}

_PREFIXES: dict[Kind, str] = {"video": "vid", "playlist": "pl", "artist": "art"}


@dataclass(frozen=True)
class SubsonicId:
    kind: Kind
    value: str

    def __str__(self) -> str:
        return f"{_PREFIXES[self.kind]}:{self.value}"


def video_id(ytid: str) -> str:
    return f"vid:{ytid}"


def playlist_id(yt_playlist_id: str) -> str:
    return f"pl:{yt_playlist_id}"


def artist_id(channel_id: str) -> str:
    return f"art:{channel_id}"


def parse_id(raw: str) -> SubsonicId:
    prefix, sep, value = raw.partition(":")
    if not sep or prefix not in _PATTERNS:
        raise SubsonicError(NOT_FOUND, f"unrecognized id: {raw!r}")
    kind, pattern = _PATTERNS[prefix]
    if not pattern.match(value):
        raise SubsonicError(NOT_FOUND, f"malformed {kind} id: {raw!r}")
    return SubsonicId(kind=kind, value=value)
