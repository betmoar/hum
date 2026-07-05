"""Tests for app.auth: bearer dependency and Blake3 URL signing."""
from __future__ import annotations

import time

import pytest
from fastapi import HTTPException

from app.auth import (
    SignatureError,
    require_bearer,
    sign_url,
    verify_signature,
)


def test_sign_url_is_deterministic(signing_key_hex: str) -> None:
    key = bytes.fromhex(signing_key_hex)
    a = sign_url("/proxy/audio/abc", itag=140, exp=1_700_000_000, key=key)
    b = sign_url("/proxy/audio/abc", itag=140, exp=1_700_000_000, key=key)
    assert a == b
    assert len(a) == 32


def test_sign_url_differs_for_different_inputs(signing_key_hex: str) -> None:
    key = bytes.fromhex(signing_key_hex)
    a = sign_url("/proxy/audio/abc", itag=140, exp=1_700_000_000, key=key)
    b = sign_url("/proxy/audio/abc", itag=141, exp=1_700_000_000, key=key)
    c = sign_url("/proxy/audio/xyz", itag=140, exp=1_700_000_000, key=key)
    d = sign_url("/proxy/audio/abc", itag=140, exp=1_700_000_001, key=key)
    assert len({a, b, c, d}) == 4


def test_verify_signature_valid(signing_key_hex: str) -> None:
    key = bytes.fromhex(signing_key_hex)
    exp = int(time.time()) + 60
    sig = sign_url("/proxy/audio/abc", itag=140, exp=exp, key=key)
    verify_signature("/proxy/audio/abc", itag=140, exp=exp, sig=sig, key=key)


def test_verify_signature_wrong_sig_raises(signing_key_hex: str) -> None:
    key = bytes.fromhex(signing_key_hex)
    exp = int(time.time()) + 60
    with pytest.raises(SignatureError) as ei:
        verify_signature("/proxy/audio/abc", itag=140, exp=exp, sig="0" * 32, key=key)
    assert ei.value.status == 403


def test_verify_signature_expired_raises(signing_key_hex: str) -> None:
    key = bytes.fromhex(signing_key_hex)
    exp = int(time.time()) - 1
    sig = sign_url("/proxy/audio/abc", itag=140, exp=exp, key=key)
    with pytest.raises(SignatureError) as ei:
        verify_signature("/proxy/audio/abc", itag=140, exp=exp, sig=sig, key=key)
    assert ei.value.status == 410


def test_require_bearer_missing_header_raises_401() -> None:
    with pytest.raises(HTTPException) as ei:
        require_bearer(authorization=None)
    assert ei.value.status_code == 401


def test_require_bearer_wrong_token_raises_401(bearer_token: str) -> None:
    with pytest.raises(HTTPException) as ei:
        require_bearer(authorization="Bearer not-the-token")
    assert ei.value.status_code == 401


def test_require_bearer_correct_token_returns_none(bearer_token: str) -> None:
    assert require_bearer(authorization=f"Bearer {bearer_token}") is None


def test_sign_format_url_round_trip(signing_key_hex: str) -> None:
    from app.auth import sign_format_url, verify_signature

    key = bytes.fromhex(signing_key_hex)
    url = sign_format_url("/proxy/audio/abc", itag=140, key=key, ttl_seconds=60)
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(url).query)
    assert qs["itag"] == ["140"]
    exp = int(qs["exp"][0])
    sig = qs["sig"][0]
    verify_signature("/proxy/audio/abc", itag=140, exp=exp, sig=sig, key=key)


def test_sign_and_verify_live_manifest_roundtrip(signing_key_hex) -> None:
    import urllib.parse

    from app.auth import sign_live_manifest_url, verify_live_manifest_signature

    key = bytes.fromhex(signing_key_hex)
    path = "/api/live/abc12345678/manifest.m3u8"
    signed = sign_live_manifest_url(path, key=key, ttl_seconds=3600)
    qs = urllib.parse.urlparse(signed).query
    params = urllib.parse.parse_qs(qs)
    exp = int(params["exp"][0])
    sig = params["sig"][0]
    verify_live_manifest_signature(path, exp=exp, sig=sig, key=key)


def test_verify_live_manifest_signature_rejects_tampered(signing_key_hex) -> None:
    import urllib.parse

    import pytest

    from app.auth import SignatureError, sign_live_manifest_url, verify_live_manifest_signature

    key = bytes.fromhex(signing_key_hex)
    path = "/api/live/abc12345678/manifest.m3u8"
    signed = sign_live_manifest_url(path, key=key, ttl_seconds=3600)
    qs = urllib.parse.urlparse(signed).query
    params = urllib.parse.parse_qs(qs)
    exp = int(params["exp"][0])
    bad_sig = "0" * 32
    with pytest.raises(SignatureError):
        verify_live_manifest_signature(path, exp=exp, sig=bad_sig, key=key)


def test_verify_live_manifest_signature_rejects_expired(signing_key_hex) -> None:
    import urllib.parse

    import pytest

    from app.auth import SignatureError, sign_live_manifest_url, verify_live_manifest_signature

    key = bytes.fromhex(signing_key_hex)
    path = "/api/live/abc12345678/manifest.m3u8"
    signed = sign_live_manifest_url(path, key=key, ttl_seconds=-1)
    qs = urllib.parse.urlparse(signed).query
    params = urllib.parse.parse_qs(qs)
    exp = int(params["exp"][0])
    sig = params["sig"][0]
    with pytest.raises(SignatureError):
        verify_live_manifest_signature(path, exp=exp, sig=sig, key=key)


def test_sign_and_verify_live_segment_roundtrip(signing_key_hex) -> None:
    import urllib.parse

    from app.auth import sign_live_segment_url, verify_live_segment_signature

    key = bytes.fromhex(signing_key_hex)
    path = "/proxy/live-segment/abc12345678"
    u = "aHR0cHM6Ly9zb21lLnVwc3RyZWFtL3NlZ21lbnQubXA0"
    signed = sign_live_segment_url(path, u=u, key=key, ttl_seconds=3600)
    qs = urllib.parse.urlparse(signed).query
    params = urllib.parse.parse_qs(qs)
    exp = int(params["exp"][0])
    sig = params["sig"][0]
    verify_live_segment_signature(path, u=u, exp=exp, sig=sig, key=key)


def test_verify_live_segment_signature_rejects_tampered_u(signing_key_hex) -> None:
    import urllib.parse

    import pytest

    from app.auth import SignatureError, sign_live_segment_url, verify_live_segment_signature

    key = bytes.fromhex(signing_key_hex)
    path = "/proxy/live-segment/abc12345678"
    u = "aHR0cHM6Ly9vbmU="
    signed = sign_live_segment_url(path, u=u, key=key, ttl_seconds=3600)
    qs = urllib.parse.urlparse(signed).query
    params = urllib.parse.parse_qs(qs)
    exp = int(params["exp"][0])
    sig = params["sig"][0]
    with pytest.raises(SignatureError):
        verify_live_segment_signature(
            path, u="aHR0cHM6Ly9vdGhlcg==", exp=exp, sig=sig, key=key
        )
