"""Backend-neutral search `sp=` encoder.

Expected strings are pytubefix 10.7.3's own encodings of the same filter
dicts (captured via pytubefix.protobuf.encode_protobuf), so the yt-dlp backend
sends YouTube byte-identical filters to what the pytubefix path sends today.
"""
from __future__ import annotations

import pytest

from app.adapters.search_params import build_search_sp, encode_message


@pytest.mark.parametrize(
    ("category", "live", "expected"),
    [
        (None, False, None),
        ("music", False, "Eg0IAZoBCC9tLzA0cmxm"),
        (None, True, "EgQIAUAB"),
        ("music", True, "Eg8IAUABmgEIL20vMDRybGY="),
    ],
)
def test_build_search_sp_matches_pytubefix(category: str | None, live: bool, expected: str | None) -> None:
    assert build_search_sp(category=category, live=live) == expected


def test_encode_message_video_type_only() -> None:
    # {2: {1: 1}} is pytubefix's "type=Video" filter.
    assert encode_message({2: {1: 1}}) == "EgIIAQ=="


def test_encode_message_multibyte_varint() -> None:
    # Field numbers >= 16 need a two-byte tag (19 -> 0x9a 0x01).
    assert encode_message({19: "x"}) == "mgEBeA=="


def test_encode_message_rejects_unsupported_types() -> None:
    with pytest.raises(TypeError):
        encode_message({1: 1.5})  # type: ignore[dict-item]
