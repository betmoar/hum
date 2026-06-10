"""Unit tests for the vid:/pl:/art: ID scheme."""
from __future__ import annotations

import pytest

from shim.ids import SubsonicId, parse_id, video_id
from shim.subsonic import NOT_FOUND, SubsonicError

_YTID = "dQw4w9WgXcQ"


def test_video_round_trip() -> None:
    sid = parse_id(video_id(_YTID))
    assert sid == SubsonicId(kind="video", value=_YTID)
    assert str(sid) == f"vid:{_YTID}"


def test_playlist_parse() -> None:
    sid = parse_id("pl:PLabc123")
    assert sid.kind == "playlist"
    assert sid.value == "PLabc123"


def test_artist_parse() -> None:
    sid = parse_id("art:UCabcdef")
    assert sid.kind == "artist"
    assert sid.value == "UCabcdef"


@pytest.mark.parametrize(
    "raw",
    [
        "vid:short",  # not 11 chars
        "vid:" + "x" * 12,  # too long
        "vid:bad!chars$$",  # invalid chars
        "art:abc",  # below channel minimum length
        "unknown:xyz",  # unknown prefix
        "noprefix",  # no separator
        "",  # empty
    ],
)
def test_malformed_ids_rejected(raw: str) -> None:
    with pytest.raises(SubsonicError) as exc:
        parse_id(raw)
    assert exc.value.code == NOT_FOUND
