"""Tests for the music-topic protobuf helper."""
from __future__ import annotations

from app.adapters.youtube import _encode_music_topic_sp


def test_encode_music_topic_sp_returns_nonempty_string() -> None:
    """The helper must produce a non-empty sp= value when called."""
    result = _encode_music_topic_sp()
    assert isinstance(result, str)
    assert len(result) > 0


def test_encode_music_topic_sp_is_deterministic() -> None:
    """Same input -> same output (no randomness in protobuf encoding)."""
    assert _encode_music_topic_sp() == _encode_music_topic_sp()
