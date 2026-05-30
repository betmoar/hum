"""Shared pytest fixtures for the Hum test suite."""
from __future__ import annotations

import os

import pytest


# Pre-populate env vars required by Settings before any test imports app modules
_TEST_BEARER_TOKEN = "test-bearer-token"
_TEST_SIGNING_KEY = "00" * 32

os.environ.setdefault("API_BEARER_TOKEN", _TEST_BEARER_TOKEN)
os.environ.setdefault("STREAM_SIGNING_KEY", _TEST_SIGNING_KEY)


@pytest.fixture
def bearer_token() -> str:
    """The bearer token configured in the test environment."""
    return _TEST_BEARER_TOKEN


@pytest.fixture
def signing_key_hex() -> str:
    """Hex-encoded 32-byte signing key for the test environment."""
    return _TEST_SIGNING_KEY
