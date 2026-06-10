"""Subsonic response envelopes (JSON + XML) and protocol error codes.

All Subsonic responses — including errors — travel inside an HTTP 200 with a
`subsonic-response` envelope; clients read `status` + `error.code`, not the
HTTP status line.

Format negotiation: the Subsonic `f` query param selects JSON (`f=json`) or
XML (anything else, including absent — XML is the protocol default, which is
what Amperfy and other older clients expect). The per-request format is stashed
in a ContextVar by the auth dependency so endpoints can keep returning
`ok_response(payload)` without threading the format through every signature.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from contextvars import ContextVar
from typing import Any

from fastapi import Response
from fastapi.responses import JSONResponse

SUBSONIC_API_VERSION = "1.16.1"
SUBSONIC_XMLNS = "http://subsonic.org/restapi"
SHIM_NAME = "hum-subsonic-shim"

# Subsonic protocol error codes (the subset the shim uses).
GENERIC = 0
MISSING_PARAMETER = 10
WRONG_CREDENTIALS = 40
NOT_FOUND = 70

_response_fmt: ContextVar[str] = ContextVar("subsonic_response_fmt", default="xml")


def set_response_format(f: str | None) -> None:
    """Record the request's desired format. Absent/unknown → XML (the Subsonic
    default — clients like Amperfy omit `f` and expect XML)."""
    _response_fmt.set("json" if f == "json" else "xml")


def current_response_format() -> str:
    return _response_fmt.get()


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


# ----- XML rendering --------------------------------------------------------


def _xml_scalar(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _build(parent: ET.Element, key: str, value: object) -> None:
    """Subsonic XML shape: scalars become attributes on their parent element,
    nested dicts become child elements, and lists become repeated child
    elements named for the key (e.g. song/album/musicFolder)."""
    if isinstance(value, dict):
        el = ET.SubElement(parent, key)
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                _build(el, k, v)
            elif v is not None:
                el.set(k, _xml_scalar(v))
    elif isinstance(value, list):
        for item in value:
            _build(parent, key, item)
    elif value is not None:
        parent.set(key, _xml_scalar(value))


def to_xml(payload: dict[str, Any] | None, *, status: str) -> str:
    root = ET.Element(
        "subsonic-response",
        {
            "xmlns": SUBSONIC_XMLNS,
            "status": status,
            "version": SUBSONIC_API_VERSION,
            "type": SHIM_NAME,
        },
    )
    for key, value in (payload or {}).items():
        _build(root, key, value)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


# ----- response builders ----------------------------------------------------


def _render(payload: dict[str, Any] | None, *, status: str, fmt: str | None) -> Response:
    fmt = fmt or current_response_format()
    if fmt == "json":
        return JSONResponse(envelope(payload, status=status))
    return Response(to_xml(payload, status=status), media_type="text/xml; charset=utf-8")


def ok_response(payload: dict[str, Any] | None = None, *, fmt: str | None = None) -> Response:
    return _render(payload, status="ok", fmt=fmt)


def error_response(code: int, message: str, *, fmt: str | None = None) -> Response:
    return _render({"error": {"code": code, "message": message}}, status="failed", fmt=fmt)
