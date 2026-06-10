"""Shim settings loaded from environment variables (SHIM_* prefix)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

# Anchor paths to the repo root (this file is <root>/shim/config.py), not the
# current working directory — launching from a subdir must not lose settings.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_ENV_FILE = str(_REPO_ROOT / ".env")
# Default location for shim-side runtime state (favourites). Gitignored.
DATA_DIR_DEFAULT = _REPO_ROOT / ".shim-data"


class ShimSettings(BaseSettings):
    """Single source of truth for shim runtime configuration."""

    model_config = SettingsConfigDict(
        env_prefix="SHIM_",
        env_file=_ENV_FILE,
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
    # Base URL Sonos speakers use to fetch radio streams directly (must be
    # LAN-reachable, e.g. http://192.168.1.10:8001). Empty → http://host:port,
    # which only works if host isn't 127.0.0.1.
    public_url: str = ""

    # Audio delivery (spec §4)
    ffmpeg_path: str = "ffmpeg"
    mp3_bitrate_kbps: int = 256

    # Shim-side state (favourites). Empty → DATA_DIR_DEFAULT (<repo>/.shim-data).
    data_dir: str = ""

    # Curated playlists for the Sonos "Playlist" shelf — comma-separated YouTube
    # playlist IDs. Combined with starred (pl:) playlists; Hum can't enumerate.
    pinned_playlists: str = ""

    # Seekable remux (spec §4 mode (b)): materialize the remuxed fMP4 to a
    # cached temp file and serve it with Range support (gives Sonos a seek bar)
    # at the cost of first-byte latency. Off by default — the streaming pipe
    # (mode (a)) stays the default; flip on and validate during the Sonos phase.
    seekable_remux: bool = False
    temp_dir: str = ""  # empty → DATA_DIR_DEFAULT/cache
    temp_cache_mb: int = 512

    # Details cache (spec §5): ttl = min(max_ttl, exp - now - safety)
    details_cache_max_ttl_seconds: float = 1800.0
    details_cache_safety_seconds: float = 60.0

    # Upstream HTTP
    upstream_connect_timeout: float = 10.0
    upstream_read_timeout: float = 30.0

    log_level: str = "INFO"

    def pinned_playlist_ids(self) -> list[str]:
        return [p.strip() for p in self.pinned_playlists.split(",") if p.strip()]

    def public_base_url(self) -> str:
        return (self.public_url or f"http://{self.host}:{self.port}").rstrip("/")


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
