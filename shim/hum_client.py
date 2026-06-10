"""HTTP adapter to the Hum backend — the only place the bearer token lives.

Also owns the details cache (spec §5): /api/video/{id} is the expensive call
(cold pytubefix extraction takes seconds), so responses are cached with
ttl = min(max_ttl, exp − now − safety) derived from the signed URLs' `exp`,
and cover art is sourced without ever triggering an extraction (spec §3.5).
"""
from __future__ import annotations

import contextlib
import time
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from shim.config import get_settings
from shim.models import HumSearchHit, HumVideoDetails
from shim.subsonic import GENERIC, NOT_FOUND, SubsonicError


def _exp_param(url: str) -> float | None:
    values = parse_qs(urlparse(url).query).get("exp")
    if not values:
        return None
    try:
        return float(values[0])
    except ValueError:
        return None


def _raise_for_hum_error(r: httpx.Response) -> None:
    if r.status_code == 200:
        return
    if r.status_code == 404:
        raise SubsonicError(NOT_FOUND, "not found on Hum")
    detail = ""
    with contextlib.suppress(ValueError, KeyError, TypeError):
        detail = str(r.json().get("message", ""))
    raise SubsonicError(GENERIC, f"Hum upstream error {r.status_code}: {detail}")


class HumClient:
    def __init__(
        self,
        base_url: str,
        bearer_token: str,
        *,
        connect_timeout: float,
        read_timeout: float,
        cache_max_ttl: float,
        cache_safety: float,
    ) -> None:
        timeout = httpx.Timeout(connect_timeout, read=read_timeout)
        self._base_url = base_url.rstrip("/")
        self._hum = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {bearer_token}"},
            timeout=timeout,
        )
        # External fetches (raw i.ytimg thumbnails) must not carry the Hum token.
        self._ext = httpx.AsyncClient(timeout=timeout)
        self._cache_max_ttl = cache_max_ttl
        self._cache_safety = cache_safety
        self._details: dict[str, tuple[HumVideoDetails, float]] = {}
        self._art_urls: dict[str, str] = {}

    async def close(self) -> None:
        await self._hum.aclose()
        await self._ext.aclose()

    def absolute(self, signed_path: str) -> str:
        """Resolve a Hum-relative signed URL against the Hum base."""
        return urljoin(self._base_url + "/", signed_path.lstrip("/"))

    # ----- search -------------------------------------------------------

    async def search(self, q: str, limit: int) -> list[HumSearchHit]:
        r = await self._hum.get("/api/search", params={"q": q, "limit": limit})
        _raise_for_hum_error(r)
        hits = [HumSearchHit.model_validate(item) for item in r.json()["items"]]
        # Remember raw thumbnail URLs so getCoverArt never needs an extraction.
        for hit in hits:
            if hit.kind == "video" and hit.thumbnail_url:
                self._art_urls[hit.id] = hit.thumbnail_url
        return hits

    # ----- video details (cached) ----------------------------------------

    async def video_details(self, video_id: str) -> HumVideoDetails:
        now = time.time()
        cached = self._details.get(video_id)
        if cached and cached[1] > now:
            return cached[0]
        r = await self._hum.get(f"/api/video/{video_id}")
        _raise_for_hum_error(r)
        details = HumVideoDetails.model_validate(r.json())
        ttl = self._cache_ttl(details, now=now)
        if ttl > 0:
            self._details[video_id] = (details, now + ttl)
        return details

    def _cache_ttl(self, details: HumVideoDetails, *, now: float) -> float:
        """Eviction rule from spec §5: min(max_ttl, exp − now − safety)."""
        exps = [e for f in details.audio_formats if (e := _exp_param(f.url)) is not None]
        if not exps:
            return 0.0
        return min(self._cache_max_ttl, min(exps) - now - self._cache_safety)

    # ----- cover art ------------------------------------------------------

    async def fetch_art(self, video_id: str) -> tuple[bytes, str]:
        """Fetch cover art bytes server-side (spec §3.5): signed Hum thumbnail
        when details are already cached, remembered search-hit thumbnail next,
        and the predictable i.ytimg URL as last resort — never an extraction.
        """
        now = time.time()
        cached = self._details.get(video_id)
        if cached and cached[1] > now and cached[0].thumbnail_url:
            url, client = self.absolute(cached[0].thumbnail_url), self._hum
        elif video_id in self._art_urls:
            url, client = self._art_urls[video_id], self._ext
        else:
            url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
            client = self._ext
        r = await client.get(url)
        if r.status_code != 200:
            raise SubsonicError(NOT_FOUND, f"cover art unavailable for {video_id}")
        return r.content, r.headers.get("content-type", "image/jpeg")


# ----- module-level singleton (mirrors app/adapters/upstream_http.py) -------

_client: HumClient | None = None


def get_client() -> HumClient:
    global _client
    if _client is None:
        s = get_settings()
        _client = HumClient(
            s.hum_base_url,
            s.hum_bearer_token,
            connect_timeout=s.upstream_connect_timeout,
            read_timeout=s.upstream_read_timeout,
            cache_max_ttl=s.details_cache_max_ttl_seconds,
            cache_safety=s.details_cache_safety_seconds,
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
