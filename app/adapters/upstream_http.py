"""Shared httpx.AsyncClient + a single hostname allowlist check for upstream calls."""
from __future__ import annotations

from urllib.parse import urlparse

import httpx

from app.config import get_settings

# Module-level singleton client.
_client: httpx.AsyncClient | None = None


_ALLOWED_HOST_SUFFIXES = (
    ".googlevideo.com",
    ".ytimg.com",
    ".youtube.com",
)


class UpstreamHostError(Exception):
    """Raised when a proxy target URL is outside the allowed host suffixes."""


def _is_youtube_host(host: str) -> bool:
    host = host.lower()
    return any(host.endswith(s) for s in _ALLOWED_HOST_SUFFIXES)


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        s = get_settings()
        # No overall timeout: long-running media streams are normal. We rely on
        # per-phase timeouts (connect + read) to catch dead connections.
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                None,
                connect=s.upstream_connect_timeout,
                read=s.upstream_read_timeout,
                write=10.0,
                pool=5.0,
            ),
            limits=httpx.Limits(max_connections=s.upstream_pool_max),
            follow_redirects=True,
        )
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def open_stream(url: str, *, headers: dict[str, str]) -> httpx.Response:
    """Open a streaming GET against `url` after host-allowlist check.

    Returns the live `httpx.Response`. The caller is responsible for closing it
    (typically by awaiting `resp.aclose()` in the `finally` of the body iterator).
    """
    host = urlparse(url).hostname or ""
    if not _is_youtube_host(host):
        raise UpstreamHostError(f"host {host!r} not in allowlist")

    client = _get_client()
    req = client.build_request("GET", url, headers=headers)
    resp = await client.send(req, stream=True)
    return resp


class UpstreamStatusError(Exception):
    """Raised when an upstream one-shot fetch returns a non-2xx status."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"upstream returned {status}")


async def fetch_range(url: str, *, start: int, end: int) -> bytes:
    """One-shot Range GET of `bytes=start-end`. Returns the body buffered.

    Used by the HLS path to grab the first ~64 KB of a stream so we can
    parse the sidx without engaging the streaming body iterator. Raises
    `UpstreamHostError` for off-allowlist hosts and `UpstreamStatusError`
    for non-2xx upstream responses.
    """
    host = urlparse(url).hostname or ""
    if not _is_youtube_host(host):
        raise UpstreamHostError(f"host {host!r} not in allowlist")

    client = _get_client()
    resp = await client.get(
        url,
        headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"},
    )
    if resp.status_code not in (200, 206):
        raise UpstreamStatusError(resp.status_code)
    return resp.content


def is_allowed_host(url: str) -> bool:
    """Non-raising version of the host allowlist check used by signed proxies."""
    host = urlparse(url).hostname or ""
    return _is_youtube_host(host)


async def fetch_text(url: str) -> tuple[str, str]:
    """One-shot GET that returns (text, final_url). Follows redirects.

    Raises UpstreamHostError for off-allowlist hosts and
    UpstreamStatusError for non-2xx responses. The returned `final_url`
    is the URL after redirects — callers use it as the base for resolving
    relative URIs in HLS playlists.
    """
    if not is_allowed_host(url):
        raise UpstreamHostError(f"host not in allowlist: {url!r}")
    client = _get_client()
    resp = await client.get(url, headers={"Accept-Encoding": "identity"})
    if resp.status_code < 200 or resp.status_code >= 300:
        raise UpstreamStatusError(resp.status_code)
    return resp.text, str(resp.url)
