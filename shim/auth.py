"""Subsonic credential check: salted-MD5 token auth (spec §9.5).

bonob sends `t` (MD5 hex of password + salt) and `s` (random salt) by
default. Plaintext `p` — optionally hex-encoded as `enc:<hex>` — is accepted
only when SHIM_ALLOW_PLAIN_PASSWORD is on (Amperfy dev mode).
"""
from __future__ import annotations

import hashlib
import hmac

from fastapi import Request

from shim.config import ShimSettings, get_settings
from shim.subsonic import MISSING_PARAMETER, WRONG_CREDENTIALS, SubsonicError

_WRONG = "wrong username or password"


def _md5_hex(text: str) -> str:
    # MD5 is mandated by the Subsonic token-auth scheme, not a security choice.
    return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()


def check_credentials(
    settings: ShimSettings,
    u: str | None,
    p: str | None,
    t: str | None,
    s: str | None,
) -> None:
    if not u:
        raise SubsonicError(MISSING_PARAMETER, "missing required parameter: u")
    if not hmac.compare_digest(u.encode(), settings.subsonic_user.encode()):
        raise SubsonicError(WRONG_CREDENTIALS, _WRONG)

    if t is not None and s is not None:
        expected = _md5_hex(settings.subsonic_password + s)
        if not hmac.compare_digest(t.lower().encode(), expected.encode()):
            raise SubsonicError(WRONG_CREDENTIALS, _WRONG)
        return

    if p is not None and settings.allow_plain_password:
        password = p
        if p.startswith("enc:"):
            try:
                password = bytes.fromhex(p[4:]).decode()
            except (ValueError, UnicodeDecodeError) as e:
                raise SubsonicError(WRONG_CREDENTIALS, _WRONG) from e
        if not hmac.compare_digest(password.encode(), settings.subsonic_password.encode()):
            raise SubsonicError(WRONG_CREDENTIALS, _WRONG)
        return

    raise SubsonicError(
        MISSING_PARAMETER, "token auth required: pass t=md5(password+salt) and s=salt"
    )


async def require_subsonic_auth(request: Request) -> None:
    """FastAPI dependency: every /rest endpoint authenticates, ping included."""
    q = request.query_params
    check_credentials(get_settings(), q.get("u"), q.get("p"), q.get("t"), q.get("s"))
