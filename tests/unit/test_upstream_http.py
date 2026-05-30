"""Tests for the upstream HTTP client wrapper."""
from __future__ import annotations

import pytest

from app.adapters import upstream_http


@pytest.fixture(autouse=True)
def reset_client() -> None:
    yield
    upstream_http._client = None


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
    import httpx

    async def fake_get(self, url: str, *, headers: dict[str, str]) -> httpx.Response:
        return httpx.Response(
            403, content=b"forbidden", request=httpx.Request("GET", url)
        )

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    with pytest.raises(upstream_http.UpstreamStatusError) as ei:
        await upstream_http.fetch_range(
            "https://rr1---sn-test.googlevideo.com/videoplayback?id=x",
            start=0, end=1023,
        )
    assert ei.value.status == 403


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
