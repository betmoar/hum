"""Shared fixtures for the shim test suite."""
from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator

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


@pytest.fixture(autouse=True)
def isolate_favourites(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> Iterator[None]:
    """Point the favourites store at a per-test temp dir and clear the
    seen-cache + singleton, so star/unstar state never leaks across tests
    or touches the repo's real .shim-data."""
    from shim import store

    store.reset_store()
    monkeypatch.setattr(store, "DATA_DIR_DEFAULT", tmp_path)
    yield
    store.reset_store()
