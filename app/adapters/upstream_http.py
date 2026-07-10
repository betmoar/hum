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


async def _enforce_allowlist_per_request(request: httpx.Request) -> None:
    """Request event hook: runs for EVERY outgoing request, including each hop
    of a redirect chain. Callers check the initial URL, but with
    follow_redirects=True an upstream 3xx could otherwise send us to an
    arbitrary host (SSRF via redirect). This hook makes that impossible.
    """
    host = request.url.host or ""
    if not _is_youtube_host(host):
        raise UpstreamHostError(f"host {host!r} not in allowlist (redirect target?)")


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
            event_hooks={"request": [_enforce_allowlist_per_request]},
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


# fetch_range asks for a specific byte window. If the upstream ignores our
# Range header it may reply 200 with the *entire* file — buffering that into
# RAM defeats the point of asking for a small window. We allow some slack
# (the upstream may pad slightly) but reject bodies wildly larger than what
# we asked for. See docs/BACKLOG.md "fetch_range can buffer an entire file".
_RANGE_OVER_FETCH_FACTOR = 2


class UpstreamRangeError(Exception):
    """Raised when the upstream ignores our Range request and returns (or
    starts streaming) a 200 body far larger than the requested window."""

    def __init__(self, declared_length: int | None, limit: int) -> None:
        self.declared_length = declared_length
        self.limit = limit
        size_desc = "unknown size" if declared_length is None else f"{declared_length} bytes"
        super().__init__(
            f"upstream ignored Range and returned a 200 body of {size_desc}, "
            f"exceeding the {limit}-byte limit"
        )


async def fetch_range(url: str, *, start: int, end: int) -> bytes:
    """One-shot Range GET of `bytes=start-end`. Returns the body buffered.

    Used by the HLS path to grab the first ~64 KB of a stream so we can
    parse the sidx without engaging the streaming body iterator. Raises
    `UpstreamHostError` for off-allowlist hosts, `UpstreamStatusError` for
    non-2xx upstream responses, and `UpstreamRangeError` if the upstream
    ignores the Range header and returns a 200 body far larger than the
    requested window (which would otherwise buffer the whole file in RAM).
    """
    host = urlparse(url).hostname or ""
    if not _is_youtube_host(host):
        raise UpstreamHostError(f"host {host!r} not in allowlist")

    limit = (end - start + 1) * _RANGE_OVER_FETCH_FACTOR

    client = _get_client()
    req = client.build_request(
        "GET",
        url,
        headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"},
    )
    resp = await client.send(req, stream=True)
    try:
        if resp.status_code not in (200, 206):
            raise UpstreamStatusError(resp.status_code)

        if resp.status_code == 206:
            # Range honored — the body is bounded by the window we asked
            # for, same as before this fix.
            return await resp.aread()

        # status_code == 200: upstream ignored our Range header. Reject
        # cheaply via Content-Length when present; otherwise stream and
        # abort as soon as we exceed the limit, so a lying/absent header
        # can't force a full-file buffer either.
        content_length = resp.headers.get("content-length")
        try:
            declared = int(content_length) if content_length is not None else None
        except ValueError:
            # Malformed header (e.g. "not-a-number"). Treat as absent and fall
            # through to the streaming-abort guard rather than raising a bare
            # ValueError — no handler in app/main.py catches that, so it would
            # surface as a 500 (violating the "no bare 500s" invariant).
            declared = None
        if declared is not None and declared > limit:
            raise UpstreamRangeError(declared, limit)

        chunks: list[bytes] = []
        total = 0
        async for chunk in resp.aiter_bytes():
            chunks.append(chunk)
            total += len(chunk)
            if total > limit:
                raise UpstreamRangeError(declared, limit)
        return b"".join(chunks)
    finally:
        await resp.aclose()


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
