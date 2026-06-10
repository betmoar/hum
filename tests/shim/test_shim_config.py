"""Tests for ShimSettings loading: token fallback and friendly failure."""
from __future__ import annotations

import pytest

from shim.config import ShimSettings, get_settings

_PASSWORD = "correct-horse-battery"


def test_bearer_token_falls_back_to_hum_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.chdir(str(tmp_path))  # keep any local .env out of the picture
    monkeypatch.delenv("SHIM_HUM_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("API_BEARER_TOKEN", "shared-hum-token-123")
    s = ShimSettings(subsonic_password=_PASSWORD)
    assert s.hum_bearer_token == "shared-hum-token-123"


def test_explicit_shim_token_wins_over_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setenv("SHIM_HUM_BEARER_TOKEN", "shim-specific-token-1")
    monkeypatch.setenv("API_BEARER_TOKEN", "shared-hum-token-123")
    s = ShimSettings(subsonic_password=_PASSWORD)
    assert s.hum_bearer_token == "shim-specific-token-1"


def test_missing_required_settings_exit_cleanly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: object
) -> None:
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.delenv("SHIM_SUBSONIC_PASSWORD", raising=False)
    monkeypatch.delenv("SHIM_HUM_BEARER_TOKEN", raising=False)
    monkeypatch.delenv("API_BEARER_TOKEN", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit) as exc:
            get_settings()
        message = str(exc.value)
        assert "SHIM_SUBSONIC_PASSWORD" in message
        assert "SHIM_HUM_BEARER_TOKEN" in message
        assert ".env.example" in message
        # No secret values echoed, unlike the raw pydantic ValidationError.
        assert "input_value" not in message
    finally:
        get_settings.cache_clear()
