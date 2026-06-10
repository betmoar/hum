"""XML response format (Subsonic default; Amperfy omits f=json and expects XML)."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from shim.models import HumSearchHit
from shim.subsonic import SUBSONIC_XMLNS

_NS = {"s": SUBSONIC_XMLNS}


def _auth_no_format(subsonic_auth: dict[str, str]) -> dict[str, str]:
    # Drop f=json so the request takes the XML default, like Amperfy.
    return {k: v for k, v in subsonic_auth.items() if k != "f"}


def test_ping_defaults_to_xml(
    shim_client: TestClient, subsonic_auth: dict[str, str]
) -> None:
    r = shim_client.get("/rest/ping.view", params=_auth_no_format(subsonic_auth))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/xml")
    root = ET.fromstring(r.text)
    assert root.tag == f"{{{SUBSONIC_XMLNS}}}subsonic-response"
    assert root.attrib["status"] == "ok"
    assert root.attrib["version"] == "1.16.1"


def test_explicit_json_still_works(
    shim_client: TestClient, subsonic_auth: dict[str, str]
) -> None:
    r = shim_client.get("/rest/ping.view", params={**subsonic_auth, "f": "json"})
    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["subsonic-response"]["status"] == "ok"


def test_search3_xml_has_song_elements(
    shim_client: TestClient, subsonic_auth: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    hits = [
        HumSearchHit(
            kind="video", id="dQw4w9WgXcQ", title="A Song", author="Chan",
            thumbnail_url="https://i/x.jpg", duration_seconds=215,
        )
    ]

    class _Fake:
        async def search(self, q: str, limit: int) -> list[HumSearchHit]:
            return hits

    from shim import hum_client

    monkeypatch.setattr(hum_client, "get_client", lambda: _Fake())
    r = shim_client.get(
        "/rest/search3", params={**_auth_no_format(subsonic_auth), "query": "x"}
    )
    root = ET.fromstring(r.text)
    songs = root.findall(".//s:searchResult3/s:song", _NS)
    assert len(songs) == 1
    assert songs[0].attrib["id"] == "vid:dQw4w9WgXcQ"
    assert songs[0].attrib["title"] == "A Song"
    assert songs[0].attrib["duration"] == "215"
    # Booleans render as true/false, not Python's True/False.
    assert songs[0].attrib["isDir"] == "false"


def test_error_renders_as_xml(shim_client: TestClient) -> None:
    # No credentials, XML default → a failed envelope with <error> as XML.
    r = shim_client.get("/rest/ping.view")
    assert r.headers["content-type"].startswith("text/xml")
    root = ET.fromstring(r.text)
    assert root.attrib["status"] == "failed"
    err = root.find("s:error", _NS)
    assert err is not None
    assert err.attrib["code"] == "10"
