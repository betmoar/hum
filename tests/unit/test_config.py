"""Tests for app.config.Settings."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_loads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_BEARER_TOKEN", "abcdefghijklmnop")
    monkeypatch.setenv("STREAM_SIGNING_KEY", "ff" * 32)
    from importlib import reload

    from app import config as config_mod

    reload(config_mod)
    s = config_mod.get_settings()
    assert s.api_bearer_token == "abcdefghijklmnop"
    assert s.stream_signing_key == "ff" * 32
    assert s.stream_url_ttl_seconds == 21600
    assert s.cors_origins.startswith("http://")


def test_settings_rejects_short_signing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_BEARER_TOKEN", "abcdefghijklmnop")
    monkeypatch.setenv("STREAM_SIGNING_KEY", "deadbeef")
    from importlib import reload

    from app import config as config_mod

    reload(config_mod)
    with pytest.raises(ValueError, match="STREAM_SIGNING_KEY"):
        config_mod.get_settings()


def _settings(cors_origins: str) -> Settings:
    return Settings(cors_origins=cors_origins)  # type: ignore[call-arg]


def test_cors_origins_list_parses_multiple() -> None:
    assert _settings("http://a.com,http://b.com").cors_origins_list() == [
        "http://a.com",
        "http://b.com",
    ]


def test_cors_origins_list_strips_whitespace_and_drops_empties() -> None:
    # Leading/trailing spaces, doubled and trailing commas must not produce
    # empty or padded origins (a stray "" origin would match nothing / mislead).
    assert _settings("  http://a.com , , http://b.com ,").cors_origins_list() == [
        "http://a.com",
        "http://b.com",
    ]


def test_cors_origins_list_empty_string_yields_empty_list() -> None:
    assert _settings("").cors_origins_list() == []


def test_cors_origins_list_single_origin() -> None:
    assert _settings("http://only.com").cors_origins_list() == ["http://only.com"]


def test_cache_ttl_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VIDEO_CACHE_TTL_SECONDS", raising=False)
    monkeypatch.delenv("SEARCH_CACHE_TTL_SECONDS", raising=False)
    s = Settings(api_bearer_token="x" * 16, stream_signing_key="00" * 32)
    assert s.video_cache_ttl_seconds == 3600
    assert s.search_cache_ttl_seconds == 300


def test_cache_ttl_rejects_zero() -> None:
    with pytest.raises(ValidationError):
        Settings(
            api_bearer_token="x" * 16,
            stream_signing_key="00" * 32,
            video_cache_ttl_seconds=0,
        )
