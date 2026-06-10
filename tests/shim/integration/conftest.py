"""Fixtures for opt-in integration tests against a LIVE shim + Hum.

These do not use the in-process TestClient: they hit a running shim over HTTP
(start `hum` and `hum-shim` first), so they exercise the real Hum bearer token,
ffmpeg, and YouTube. Run explicitly:

    hum &              # :8000
    hum-shim &         # :8001  (needs SHIM_SUBSONIC_PASSWORD in .env)
    pytest -m integration tests/shim/integration

Everything skips cleanly if the shim isn't reachable or ffprobe is missing, so
the suite never fails just because the services aren't up.
"""
from __future__ import annotations

import hashlib
import shutil

import httpx
import pytest
from dotenv import dotenv_values

from shim.config import _REPO_ROOT

pytestmark = pytest.mark.integration

_ENV = dotenv_values(_REPO_ROOT / ".env")


def _shim_base() -> str:
    host = _ENV.get("SHIM_HOST") or "127.0.0.1"
    port = _ENV.get("SHIM_PORT") or "8001"
    return f"http://{host}:{port}"


def _health_or_skip(base: str, what: str) -> None:
    try:
        httpx.get(f"{base}/health", timeout=2.0).raise_for_status()
    except (httpx.HTTPError, OSError) as e:
        pytest.skip(f"{what} not reachable at {base}: {e}")


@pytest.fixture(scope="session")
def shim_base() -> str:
    base = _shim_base()
    _health_or_skip(base, "shim")
    # The live tests exercise the whole chain, so Hum must be up too — without
    # this, a stopped Hum surfaces as a confusing error instead of a skip.
    hum_base = _ENV.get("SHIM_HUM_BASE_URL") or "http://127.0.0.1:8000"
    _health_or_skip(hum_base, "Hum")
    return base


@pytest.fixture(scope="session")
def shim_auth() -> dict[str, str]:
    user = _ENV.get("SHIM_SUBSONIC_USER") or "hum"
    password = _ENV.get("SHIM_SUBSONIC_PASSWORD")
    if not password:
        pytest.skip("SHIM_SUBSONIC_PASSWORD not set in .env")
    salt = "integ-salt"
    token = hashlib.md5((password + salt).encode(), usedforsecurity=False).hexdigest()
    return {"u": user, "t": token, "s": salt, "v": "1.16.1", "c": "integ", "f": "json"}


@pytest.fixture(scope="session")
def ffprobe() -> str:
    path = shutil.which("ffprobe")
    if not path:
        pytest.skip("ffprobe not installed")
    return path
