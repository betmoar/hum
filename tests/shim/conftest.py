"""Shared fixtures for the shim test suite."""
from __future__ import annotations

import hashlib
import os

import pytest
from fastapi.testclient import TestClient

_TEST_USER = "tester"
_TEST_PASSWORD = "correct-horse-battery"

# Pre-populate env vars required by ShimSettings before any test imports
# shim modules (same pattern as the root conftest for app/).
os.environ.setdefault("SHIM_HUM_BEARER_TOKEN", "test-hum-bearer-token")
os.environ.setdefault("SHIM_SUBSONIC_USER", _TEST_USER)
os.environ.setdefault("SHIM_SUBSONIC_PASSWORD", _TEST_PASSWORD)


@pytest.fixture
def shim_user() -> str:
    return _TEST_USER


@pytest.fixture
def shim_password() -> str:
    return _TEST_PASSWORD


@pytest.fixture
def subsonic_auth() -> dict[str, str]:
    """Valid token-auth query params for the test credentials."""
    salt = "abc123"
    token = hashlib.md5(
        (_TEST_PASSWORD + salt).encode(), usedforsecurity=False
    ).hexdigest()
    return {"u": _TEST_USER, "t": token, "s": salt, "v": "1.16.1", "c": "tests", "f": "json"}


@pytest.fixture
def shim_client() -> TestClient:
    from shim.main import app

    return TestClient(app)
