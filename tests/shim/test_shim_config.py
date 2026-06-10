"""Tests for ShimSettings loading: env_file anchoring, token fallback, friendly failure."""
from __future__ import annotations

from pathlib import Path

import pytest

from shim.config import ShimSettings, get_settings

_PASSWORD = "correct-horse-battery"


@pytest.fixture(autouse=True)
def isolate_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the settings at a non-existent .env so these tests never read a
    developer's real repo-root .env. env vars (monkeypatch.setenv) still apply."""
    monkeypatch.setitem(
        ShimSettings.model_config, "env_file", str(tmp_path / "nonexistent.env")
    )


def test_env_file_is_absolute_and_cwd_independent() -> None:
    # The footgun: a relative ".env" resolves against cwd, so launching from a
    # subdir loses settings. The configured path must be absolute.
    configured = ShimSettings.model_config["env_file"]
    assert configured is not None
    assert Path(str(configured)).is_absolute()


def test_bearer_token_falls_back_to_hum_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHIM_HUM_BEARER_TOKEN", raising=False)
    monkeypatch.setenv("API_BEARER_TOKEN", "shared-hum-token-123")
    s = ShimSettings(subsonic_password=_PASSWORD)
    assert s.hum_bearer_token == "shared-hum-token-123"


def test_explicit_shim_token_wins_over_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHIM_HUM_BEARER_TOKEN", "shim-specific-token-1")
    monkeypatch.setenv("API_BEARER_TOKEN", "shared-hum-token-123")
    s = ShimSettings(subsonic_password=_PASSWORD)
    assert s.hum_bearer_token == "shim-specific-token-1"


def test_missing_required_settings_exit_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
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
