"""Subsonic JSON envelope helpers and protocol error codes.

All Subsonic responses — including errors — travel inside an HTTP 200 with a
`subsonic-response` envelope; clients read `status` + `error.code`, not the
HTTP status line.
"""
from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse

SUBSONIC_API_VERSION = "1.16.1"
SHIM_NAME = "hum-subsonic-shim"

# Subsonic protocol error codes (the subset the shim uses).
GENERIC = 0
MISSING_PARAMETER = 10
WRONG_CREDENTIALS = 40
NOT_FOUND = 70


class SubsonicError(Exception):
    """Raised by handlers/dependencies; rendered as a failed envelope."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def envelope(payload: dict[str, Any] | None = None, *, status: str = "ok") -> dict[str, Any]:
    body: dict[str, Any] = {
        "status": status,
        "version": SUBSONIC_API_VERSION,
        "type": SHIM_NAME,
    }
    if payload:
        body.update(payload)
    return {"subsonic-response": body}


def ok_response(payload: dict[str, Any] | None = None) -> JSONResponse:
    return JSONResponse(envelope(payload))


def error_response(code: int, message: str) -> JSONResponse:
    return JSONResponse(
        envelope({"error": {"code": code, "message": message}}, status="failed")
    )
