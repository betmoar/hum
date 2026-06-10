"""Unit tests for the Subsonic credential check (token auth + dev fallback)."""
from __future__ import annotations

import hashlib

import pytest

from shim.auth import check_credentials
from shim.config import ShimSettings
from shim.subsonic import MISSING_PARAMETER, WRONG_CREDENTIALS, SubsonicError

_PASSWORD = "correct-horse-battery"


def make_settings(**overrides: object) -> ShimSettings:
    kwargs: dict[str, object] = {
        "hum_bearer_token": "x" * 16,
        "subsonic_user": "tester",
        "subsonic_password": _PASSWORD,
    }
    kwargs.update(overrides)
    return ShimSettings(**kwargs)  # type: ignore[arg-type]


def token_for(salt: str) -> str:
    return hashlib.md5((_PASSWORD + salt).encode(), usedforsecurity=False).hexdigest()


def test_valid_token_auth_passes() -> None:
    check_credentials(make_settings(), "tester", None, token_for("s4lt"), "s4lt")


def test_uppercase_token_accepted() -> None:
    check_credentials(make_settings(), "tester", None, token_for("s4lt").upper(), "s4lt")


def test_wrong_token_rejected() -> None:
    with pytest.raises(SubsonicError) as exc:
        check_credentials(make_settings(), "tester", None, "0" * 32, "s4lt")
    assert exc.value.code == WRONG_CREDENTIALS


def test_wrong_user_rejected() -> None:
    with pytest.raises(SubsonicError) as exc:
        check_credentials(make_settings(), "intruder", None, token_for("s4lt"), "s4lt")
    assert exc.value.code == WRONG_CREDENTIALS


def test_missing_user_is_missing_parameter() -> None:
    with pytest.raises(SubsonicError) as exc:
        check_credentials(make_settings(), None, None, token_for("s4lt"), "s4lt")
    assert exc.value.code == MISSING_PARAMETER


def test_plain_password_rejected_by_default() -> None:
    with pytest.raises(SubsonicError) as exc:
        check_credentials(make_settings(), "tester", _PASSWORD, None, None)
    assert exc.value.code == MISSING_PARAMETER  # told to use token auth


def test_plain_password_accepted_in_dev_mode() -> None:
    settings = make_settings(allow_plain_password=True)
    check_credentials(settings, "tester", _PASSWORD, None, None)


def test_enc_hex_password_accepted_in_dev_mode() -> None:
    settings = make_settings(allow_plain_password=True)
    enc = "enc:" + _PASSWORD.encode().hex()
    check_credentials(settings, "tester", enc, None, None)


def test_wrong_plain_password_rejected_in_dev_mode() -> None:
    settings = make_settings(allow_plain_password=True)
    with pytest.raises(SubsonicError) as exc:
        check_credentials(settings, "tester", "not-the-password", None, None)
    assert exc.value.code == WRONG_CREDENTIALS
