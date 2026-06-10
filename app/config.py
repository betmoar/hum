"""Application settings loaded from environment variables."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchor .env to the repo root (this file is <root>/app/config.py), not the
# current working directory — launching from a subdir must not lose settings.
_ENV_FILE = str(Path(__file__).resolve().parents[1] / ".env")


class Settings(BaseSettings):
    """Single source of truth for runtime configuration."""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, case_sensitive=False, extra="ignore")

    # App
    app_name: str = "Hum"
    app_version: str = "0.1.0"
    debug: bool = False

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    # Auth
    api_bearer_token: str = Field(..., min_length=16)
    stream_signing_key: str = Field(..., description="32-byte hex-encoded signing key")
    stream_url_ttl_seconds: int = 21600  # 6h

    # CORS — comma-separated origins; default localhost only
    cors_origins: str = "http://127.0.0.1,http://localhost"

    # Upstream
    upstream_connect_timeout: float = 10.0
    upstream_read_timeout: float = 30.0
    upstream_pool_max: int = 100

    # Logging
    log_level: str = "INFO"
    log_json: bool = False

    @field_validator("stream_signing_key")
    @classmethod
    def _validate_signing_key(cls, v: str) -> str:
        try:
            raw = bytes.fromhex(v)
        except ValueError as e:
            raise ValueError("STREAM_SIGNING_KEY must be hex") from e
        if len(raw) != 32:
            raise ValueError("STREAM_SIGNING_KEY must be 32 bytes (64 hex chars)")
        return v

    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def signing_key_bytes(self) -> bytes:
        return bytes.fromhex(self.stream_signing_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
