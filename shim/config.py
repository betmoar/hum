"""Shim settings loaded from environment variables (SHIM_* prefix)."""
from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class ShimSettings(BaseSettings):
    """Single source of truth for shim runtime configuration."""

    model_config = SettingsConfigDict(
        env_prefix="SHIM_",
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    # Upstream Hum — the bearer token lives here server-side and is never
    # exposed to bonob/Sonos (spec §5). Falls back to Hum's own
    # API_BEARER_TOKEN since the services share an .env in this repo.
    hum_base_url: str = "http://127.0.0.1:8000"
    hum_bearer_token: str = Field(
        ...,
        min_length=16,
        validation_alias=AliasChoices("shim_hum_bearer_token", "api_bearer_token"),
    )

    # Subsonic credentials bonob/Amperfy authenticate with. bonob sends
    # salted-MD5 token auth by default (spec §9.5); plaintext `p` is a
    # dev-only fallback for Amperfy testing — keep it off in production.
    subsonic_user: str = "hum"
    subsonic_password: str = Field(..., min_length=8)
    allow_plain_password: bool = False

    # Server
    host: str = "127.0.0.1"
    port: int = 8001
    debug: bool = False

    # Audio delivery (spec §4)
    ffmpeg_path: str = "ffmpeg"
    mp3_bitrate_kbps: int = 256

    # Details cache (spec §5): ttl = min(max_ttl, exp - now - safety)
    details_cache_max_ttl_seconds: float = 1800.0
    details_cache_safety_seconds: float = 60.0

    # Upstream HTTP
    upstream_connect_timeout: float = 10.0
    upstream_read_timeout: float = 30.0

    log_level: str = "INFO"


@lru_cache
def get_settings() -> ShimSettings:
    try:
        return ShimSettings()  # type: ignore[call-arg]
    except ValidationError as e:
        missing = sorted(
            str(err["loc"][0]).upper() for err in e.errors() if err["type"] == "missing"
        )
        if missing:
            names = ", ".join(n if n.startswith("SHIM_") else f"SHIM_{n}" for n in missing)
            # A concise exit beats a pydantic traceback that echoes .env values.
            raise SystemExit(
                f"hum-subsonic-shim: missing required settings: {names} (see .env.example)"
            ) from e
        raise
