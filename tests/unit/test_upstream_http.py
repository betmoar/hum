"""Tests for the upstream HTTP client wrapper."""
from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from app.adapters import upstream_http


@pytest.fixture(autouse=True)
def reset_client() -> None:
    yield
    upstream_http._client = None


def _mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    """A client wired to a MockTransport, with the same allowlist hook the
    real client installs (so redirect/host behavior matches production)."""
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        event_hooks={"request": [upstream_http._enforce_allowlist_per_request]},
    )


async def test_get_client_returns_singleton() -> None:
    c1 = upstream_http._get_client()
    c2 = upstream_http._get_client()
    assert c1 is c2


async def test_close_resets_client() -> None:
    upstream_http._get_client()
    await upstream_http.close()
    assert upstream_http._client is None


async def test_hostname_allowed() -> None:
    assert upstream_http._is_youtube_host("rr1---sn-abc.googlevideo.com")
    assert upstream_http._is_youtube_host("i.ytimg.com")
    assert not upstream_http._is_youtube_host("evil.example.com")


async def test_open_stream_rejects_disallowed_host() -> None:
    with pytest.raises(upstream_http.UpstreamHostError):
        await upstream_http.open_stream("https://evil.example.com/foo", headers={})


async def test_fetch_range_rejects_disallowed_host() -> None:
    with pytest.raises(upstream_http.UpstreamHostError):
        await upstream_http.fetch_range(
            "https://evil.example.com/foo", start=0, end=1023
        )


async def test_fetch_range_translates_upstream_non_2xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 403/5xx from googlevideo becomes UpstreamStatusError, not a
    bare httpx exception or successful return of garbage bytes."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, content=b"forbidden")

    client = _mock_client(handler)
    monkeypatch.setattr(upstream_http, "_client", client)
    try:
        with pytest.raises(upstream_http.UpstreamStatusError) as ei:
            await upstream_http.fetch_range(
                "https://rr1---sn-test.googlevideo.com/videoplayback?id=x",
                start=0, end=1023,
            )
        assert ei.value.status == 403
    finally:
        await client.aclose()


async def test_fetch_range_returns_body_when_range_honored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The common case: upstream honors Range and replies 206 with exactly
    the requested window. No change in behavior from before the fix."""
    payload = b"x" * 1024

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["range"] == "bytes=0-1023"
        return httpx.Response(206, content=payload)

    client = _mock_client(handler)
    monkeypatch.setattr(upstream_http, "_client", client)
    try:
        body = await upstream_http.fetch_range(
            "https://rr1---sn-test.googlevideo.com/videoplayback?id=x",
            start=0, end=1023,
        )
        assert body == payload
    finally:
        await client.aclose()


async def test_fetch_range_rejects_oversized_200_via_content_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upstream ignores Range and replies 200 with a Content-Length far
    larger than the requested window (e.g. the whole media file). This must
    be rejected before the body is read into RAM — the point of the fix."""
    requested = 1024  # bytes=0-1023

    def handler(request: httpx.Request) -> httpx.Response:
        assert "range" in request.headers
        # Declare a huge body but don't actually send the bytes; if the
        # implementation tried to read them all, this test would hang/OOM
        # instead of failing fast on the Content-Length check.
        return httpx.Response(
            200,
            headers={"content-length": str(100 * 1024 * 1024)},
            content=b"",
        )

    client = _mock_client(handler)
    monkeypatch.setattr(upstream_http, "_client", client)
    try:
        with pytest.raises(upstream_http.UpstreamRangeError) as ei:
            await upstream_http.fetch_range(
                "https://rr1---sn-test.googlevideo.com/videoplayback?id=x",
                start=0, end=requested - 1,
            )
        assert ei.value.declared_length == 100 * 1024 * 1024
    finally:
        await client.aclose()


async def test_fetch_range_accepts_200_within_slack_factor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 200 body that's only slightly larger than requested (e.g. upstream
    rounds up to a chunk boundary) is still accepted — the guard targets
    whole-file buffering, not minor over-fetch."""
    requested = 1024
    body = b"y" * (requested + 100)  # comfortably within the 2x slack factor

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    client = _mock_client(handler)
    monkeypatch.setattr(upstream_http, "_client", client)
    try:
        result = await upstream_http.fetch_range(
            "https://rr1---sn-test.googlevideo.com/videoplayback?id=x",
            start=0, end=requested - 1,
        )
        assert result == body
    finally:
        await client.aclose()


async def test_fetch_range_rejects_oversized_200_without_content_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upstream ignores Range, replies 200, and omits/lies about
    Content-Length. The guard must still catch this by aborting the stream
    once the accumulated body exceeds the limit, never buffering the whole
    thing."""
    requested = 1024
    limit = requested * upstream_http._RANGE_OVER_FETCH_FACTOR
    oversized_body = b"z" * (limit + 1)

    def handler(request: httpx.Request) -> httpx.Response:
        resp = httpx.Response(200, content=oversized_body)
        del resp.headers["content-length"]
        return resp

    client = _mock_client(handler)
    monkeypatch.setattr(upstream_http, "_client", client)
    try:
        with pytest.raises(upstream_http.UpstreamRangeError) as ei:
            await upstream_http.fetch_range(
                "https://rr1---sn-test.googlevideo.com/videoplayback?id=x",
                start=0, end=requested - 1,
            )
        assert ei.value.declared_length is None
    finally:
        await client.aclose()


def test_is_allowed_host_accepts_googlevideo() -> None:
    from app.adapters.upstream_http import is_allowed_host
    assert is_allowed_host("https://rr1---sn-abc.googlevideo.com/videoplayback?x=1") is True


def test_is_allowed_host_accepts_ytimg() -> None:
    from app.adapters.upstream_http import is_allowed_host
    assert is_allowed_host("https://i.ytimg.com/vi/abc/maxresdefault.jpg") is True


def test_is_allowed_host_rejects_other() -> None:
    from app.adapters.upstream_http import is_allowed_host
    assert is_allowed_host("https://evil.example.com/path") is False
    assert is_allowed_host("https://googlevideo.com.evil.com/x") is False


def test_fetch_text_returns_body_and_base(monkeypatch) -> None:
    """fetch_text returns (text, base_url) where base_url is the URL after redirects."""
    import asyncio

    from app.adapters import upstream_http

    class FakeResponse:
        status_code = 200
        text = "#EXTM3U\n"
        url = "https://manifest.googlevideo.com/api/manifest/hls_variant/expire/123"

    class FakeClient:
        async def get(self, url, headers=None):
            return FakeResponse()

    monkeypatch.setattr(upstream_http, "_get_client", lambda: FakeClient())
    text, base = asyncio.run(upstream_http.fetch_text(
        "https://manifest.googlevideo.com/api/manifest/hls_variant/expire/123"
    ))
    assert text == "#EXTM3U\n"
    assert "manifest.googlevideo.com" in base


def test_fetch_text_rejects_disallowed_host() -> None:
    import asyncio

    import pytest

    from app.adapters import upstream_http

    with pytest.raises(upstream_http.UpstreamHostError):
        asyncio.run(upstream_http.fetch_text("https://evil.example.com/x"))


def test_fetch_text_raises_on_non_2xx(monkeypatch) -> None:
    import asyncio

    import pytest

    from app.adapters import upstream_http

    class FakeResponse:
        status_code = 403
        text = ""
        url = "https://manifest.googlevideo.com/x"

    class FakeClient:
        async def get(self, url, headers=None):
            return FakeResponse()

    monkeypatch.setattr(upstream_http, "_get_client", lambda: FakeClient())
    with pytest.raises(upstream_http.UpstreamStatusError) as exc_info:
        asyncio.run(upstream_http.fetch_text("https://manifest.googlevideo.com/x"))
    assert exc_info.value.status == 403
