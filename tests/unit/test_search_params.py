"""Tests for the search `sp=` encoder.

Field numbers verified against live YouTube on 2026-09-24: type=Video is field
2 of the filter message. The earlier encoding used field 1 (sort order), copied
from pytubefix; `sp={2:{1:1}}` returned 0 results for "verknipt".
"""
from __future__ import annotations

import pytest

from app.adapters.search_params import build_search_sp, encode_message


@pytest.mark.parametrize(
    ("category", "live", "expected"),
    [
        (None, False, None),
        ("music", False, "Eg0QAZoBCC9tLzA0cmxm"),
        (None, True, "EgQQAUAB"),
        ("music", True, "Eg8QAUABmgEIL20vMDRybGY="),
    ],
)
def test_build_search_sp_matches_reference_encoding(category: str | None, live: bool, expected: str | None) -> None:
    assert build_search_sp(category=category, live=live) == expected


def test_encode_message_video_type_only() -> None:
    # {2: {2: 1}} is the "type=Video" filter (YouTube UI: sp=EgIQAQ%3D%3D).
    assert encode_message({2: {2: 1}}) == "EgIQAQ=="


def test_encode_message_multibyte_varint() -> None:
    # Field numbers >= 16 need a two-byte tag (19 -> 0x9a 0x01).
    assert encode_message({19: "x"}) == "mgEBeA=="


def test_encode_message_rejects_unsupported_types() -> None:
    with pytest.raises(TypeError):
        encode_message({1: 1.5})  # type: ignore[dict-item]
