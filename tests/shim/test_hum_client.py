"""Unit tests for HumClient's playlist fetch and extraction-free cover-art sourcing."""
from __future__ import annotations

import httpx
import pytest

from shim.hum_client import HumClient, _raise_for_hum_error, _ytimg_variant
from shim.subsonic import GENERIC, NOT_FOUND, SubsonicError


def _client(handler: "httpx.MockTransport") -> HumClient:
    c = HumClient(
        "http://hum.local",
        "x" * 16,
        connect_timeout=1.0,
        read_timeout=1.0,
        cache_max_ttl=1800.0,
        cache_safety=60.0,
    )
    # Swap both internal AsyncClients for ones backed by the mock transport.
    c._hum = httpx.AsyncClient(  # type: ignore[attr-defined]
        base_url="http://hum.local",
        headers={"Authorization": "Bearer " + "x" * 16},
        transport=handler,
    )
    c._ext = httpx.AsyncClient(transport=handler)  # type: ignore[attr-defined]
    return c


@pytest.mark.asyncio
async def test_playlist_parsed_and_thumbnails_remembered() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/playlist/PLabc"
        assert request.headers["authorization"] == "Bearer " + "x" * 16
        return httpx.Response(
            200,
            json={
                "playlist_id": "PLabc",
                "title": "Mix",
                "author": "Curator",
                "video_count": 1,
                "items": [
                    {
                        "video_id": "dQw4w9WgXcQ",
                        "title": "T1",
                        "thumbnail_url": "https://i.ytimg.com/t1.jpg",
                    }
                ],
            },
        )

    c = _client(httpx.MockTransport(handle))
    try:
        info = await c.playlist("PLabc")
        assert info.title == "Mix"
        assert info.items[0].video_id == "dQw4w9WgXcQ"
        # Item thumbnail remembered for extraction-free getCoverArt.
        url, _ = c._video_art_source("dQw4w9WgXcQ")  # type: ignore[attr-defined]
        assert url == "https://i.ytimg.com/t1.jpg"
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_video_art_falls_back_to_ytimg() -> None:
    c = _client(httpx.MockTransport(lambda r: httpx.Response(404)))
    try:
        url, _ = c._video_art_source("dQw4w9WgXcQ")  # type: ignore[attr-defined]
        assert url == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_playlist_art_uses_first_item_thumbnail() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/playlist/PLxyz":
            return httpx.Response(
                200,
                json={
                    "playlist_id": "PLxyz",
                    "title": "Mix",
                    "video_count": 1,
                    "items": [
                        {"video_id": "abcdefghijk", "title": "T", "thumbnail_url": "https://i/y.jpg"}
                    ],
                },
            )
        # The art fetch itself.
        return httpx.Response(200, content=b"img", headers={"content-type": "image/jpeg"})

    c = _client(httpx.MockTransport(handle))
    try:
        content, media_type = await c.fetch_art("playlist", "PLxyz")
        assert content == b"img"
        assert media_type == "image/jpeg"
    finally:
        await c.close()


# ----- ytimg variant sizing (spec §3.5) -------------------------------------


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (None, "https://i.ytimg.com/vi/abc/hqdefault.jpg"),
        (90, "https://i.ytimg.com/vi/abc/default.jpg"),
        (300, "https://i.ytimg.com/vi/abc/mqdefault.jpg"),
        (1000, "https://i.ytimg.com/vi/abc/hqdefault.jpg"),  # capped at hqdefault
    ],
)
def test_ytimg_variant_rewrites_by_size(size: int | None, expected: str) -> None:
    assert _ytimg_variant("https://i.ytimg.com/vi/abc/hqdefault.jpg", size) == expected


def test_ytimg_variant_passes_through_non_ytimg() -> None:
    signed = "http://hum.local/proxy/thumbnail/abc?itag=0&exp=1&sig=x"
    assert _ytimg_variant(signed, 300) == signed


# ----- error envelope mapping (spec §5 / error envelopes) -------------------


def test_unplayable_maps_to_not_found() -> None:
    r = httpx.Response(422, json={"error": "LIVE_NOT_SUPPORTED", "message": "live"})
    with pytest.raises(SubsonicError) as exc:
        _raise_for_hum_error(r)
    assert exc.value.code == NOT_FOUND
    assert "LIVE_NOT_SUPPORTED" in exc.value.message
    assert "live" in exc.value.message


def test_upstream_5xx_maps_to_generic() -> None:
    r = httpx.Response(502, json={"error": "UPSTREAM_ERROR", "message": "boom"})
    with pytest.raises(SubsonicError) as exc:
        _raise_for_hum_error(r)
    assert exc.value.code == GENERIC
    assert "502" in exc.value.message


def test_200_does_not_raise() -> None:
    _raise_for_hum_error(httpx.Response(200, json={"ok": True}))


@pytest.mark.asyncio
async def test_transport_error_becomes_subsonic_error() -> None:
    # Hum down/unreachable must surface as a Subsonic error (failed envelope),
    # not an unhandled httpx.RequestError → HTTP 500.
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    c = _client(httpx.MockTransport(boom))
    try:
        with pytest.raises(SubsonicError) as exc:
            await c.search("anything", limit=5)
        assert exc.value.code == GENERIC
        assert "unreachable" in exc.value.message.lower()
    finally:
        await c.close()
