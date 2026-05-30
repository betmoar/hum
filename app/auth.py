"""Bearer-token API auth and Blake3-HMAC stream URL signing."""
from __future__ import annotations

import secrets
import time

from blake3 import blake3
from fastapi import Header, HTTPException

from app.config import get_settings


class SignatureError(Exception):
    """Raised when a stream URL signature is missing, malformed, or expired."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(message)


def sign_url(path: str, *, itag: int, exp: int, key: bytes) -> str:
    """Return a 32-char hex Blake3-HMAC signature for the given proxy URL components."""
    msg = f"{path}|{itag}|{exp}".encode()
    return blake3(msg, key=key).hexdigest()[:32]


def verify_signature(
    path: str, *, itag: int, exp: int, sig: str, key: bytes, now: int | None = None
) -> None:
    """Verify a signed proxy URL. Raises SignatureError on failure."""
    current = now if now is not None else int(time.time())
    if exp < current:
        raise SignatureError(410, "signed URL expired")
    expected = sign_url(path, itag=itag, exp=exp, key=key)
    if not secrets.compare_digest(expected, sig):
        raise SignatureError(403, "invalid signature")


def require_bearer(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency: enforce `Authorization: Bearer <token>` header."""
    settings = get_settings()
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization[len("Bearer "):]
    if not secrets.compare_digest(token, settings.api_bearer_token):
        raise HTTPException(status_code=401, detail="invalid bearer token")
    return None


def sign_format_url(
    path: str, *, itag: int, key: bytes, ttl_seconds: int, exp: int | None = None
) -> str:
    """Return a fully-formed signed proxy URL for a given path + itag."""
    if exp is None:
        exp = int(time.time()) + ttl_seconds
    sig = sign_url(path, itag=itag, exp=exp, key=key)
    return f"{path}?itag={itag}&exp={exp}&sig={sig}"


def sign_live_manifest_url(path: str, *, key: bytes, ttl_seconds: int) -> str:
    """Return a signed `/api/live/.../manifest.m3u8` URL.

    Signature payload: f"live-manifest|{path}|{exp}". Distinct prefix
    prevents cross-protocol confusion with `sign_url` / `sign_format_url`.
    """
    exp = int(time.time()) + ttl_seconds
    msg = f"live-manifest|{path}|{exp}".encode()
    sig = blake3(msg, key=key).hexdigest()[:32]
    return f"{path}?exp={exp}&sig={sig}"


def verify_live_manifest_signature(
    path: str, *, exp: int, sig: str, key: bytes, now: int | None = None
) -> None:
    current = now if now is not None else int(time.time())
    if exp < current:
        raise SignatureError(410, "signed URL expired")
    msg = f"live-manifest|{path}|{exp}".encode()
    expected = blake3(msg, key=key).hexdigest()[:32]
    if not secrets.compare_digest(expected, sig):
        raise SignatureError(403, "invalid signature")


def sign_live_segment_url(path: str, *, u: str, key: bytes, ttl_seconds: int) -> str:
    """Return a signed `/proxy/live-segment/...` URL.

    The base64-encoded upstream URL `u` is part of the signature payload
    so a leaked sig cannot be reused for arbitrary CDN access.
    """
    exp = int(time.time()) + ttl_seconds
    msg = f"live-segment|{path}|{u}|{exp}".encode()
    sig = blake3(msg, key=key).hexdigest()[:32]
    return f"{path}?u={u}&exp={exp}&sig={sig}"


def verify_live_segment_signature(
    path: str, *, u: str, exp: int, sig: str, key: bytes, now: int | None = None
) -> None:
    current = now if now is not None else int(time.time())
    if exp < current:
        raise SignatureError(410, "signed URL expired")
    msg = f"live-segment|{path}|{u}|{exp}".encode()
    expected = blake3(msg, key=key).hexdigest()[:32]
    if not secrets.compare_digest(expected, sig):
        raise SignatureError(403, "invalid signature")
