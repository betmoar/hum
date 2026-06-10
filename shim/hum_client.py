"""HTTP adapter to the Hum backend — the only place the bearer token lives.

Also owns the details cache (spec §5): /api/video/{id} is the expensive call
(cold pytubefix extraction takes seconds), so responses are cached with
ttl = min(max_ttl, exp − now − safety) derived from the signed URLs' `exp`,
and cover art is sourced without ever triggering an extraction (spec §3.5).
"""
from __future__ import annotations

import contextlib
import time
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

import httpx

from shim.config import get_settings
from shim.models import HumPlaylistInfo, HumSearchHit, HumVideoDetails
from shim.subsonic import GENERIC, NOT_FOUND, SubsonicError

# YouTube thumbnail hosts and the always-present size variants. We cap at
# hqdefault (480x360): sddefault/maxresdefault 404 for many uploads, and a 404
# here would surface as "no cover art". default/mqdefault/hqdefault always exist.
_YTIMG_HOSTS = {"i.ytimg.com", "img.youtube.com", "i9.ytimg.com"}
_YTIMG_EXTS = (".jpg", ".jpeg", ".webp")


def _exp_param(url: str) -> float | None:
    values = parse_qs(urlparse(url).query).get("exp")
    if not values:
        return None
    try:
        return float(values[0])
    except ValueError:
        return None


def _ytimg_variant(url: str, size: int | None) -> str:
    """Rewrite a YouTube thumbnail URL to the variant nearest `size` (spec §3.5
    cover-art sizing without decoding/resizing). Non-ytimg URLs pass through."""
    if size is None:
        return url
    parsed = urlparse(url)
    if parsed.hostname not in _YTIMG_HOSTS:
        return url
    base, sep, name = parsed.path.rpartition("/")
    if not sep or "." not in name or not name.lower().endswith(_YTIMG_EXTS):
        return url
    ext = name[name.rfind(".") :]
    variant = "default" if size <= 120 else "mqdefault" if size <= 320 else "hqdefault"
    return urlunparse(parsed._replace(path=f"{base}/{variant}{ext}"))


def _raise_for_hum_error(r: httpx.Response) -> None:
    if r.status_code == 200:
        return
    code = ""
    message = ""
    with contextlib.suppress(ValueError, KeyError, TypeError):
        body = r.json()
        code = str(body.get("error", ""))
        message = str(body.get("message", ""))
    detail = message or f"HTTP {r.status_code}"
    if code:
        detail = f"{detail} ({code})"
    # Client-side conditions (not found / unplayable / region-locked / live)
    # → Subsonic 70; transient/upstream → generic 0.
    if r.status_code in (403, 404, 410, 415, 422, 451):
        raise SubsonicError(NOT_FOUND, detail)
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
        # Keyed by full Subsonic id ("vid:<id>" / "pl:<id>") so cover art for
        # both videos and playlists is served without triggering extraction.
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
            if not hit.thumbnail_url:
                continue
            if hit.kind == "video":
                self._art_urls[f"vid:{hit.id}"] = hit.thumbnail_url
            elif hit.kind == "playlist":
                self._art_urls[f"pl:{hit.id}"] = hit.thumbnail_url
        return hits

    # ----- playlist -------------------------------------------------------

    async def playlist(self, playlist_id: str) -> HumPlaylistInfo:
        r = await self._hum.get(f"/api/playlist/{playlist_id}")
        _raise_for_hum_error(r)
        info = HumPlaylistInfo.model_validate(r.json())
        # Remember item thumbnails so per-track getCoverArt stays extraction-free.
        for item in info.items:
            if item.thumbnail_url:
                self._art_urls.setdefault(f"vid:{item.video_id}", item.thumbnail_url)
        return info

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

    async def fetch_art(
        self, kind: str, value: str, size: int | None = None
    ) -> tuple[bytes, str]:
        """Fetch cover art bytes server-side (spec §3.5) — never an extraction.

        Video: cached signed Hum thumbnail → remembered search-hit thumbnail →
        the predictable i.ytimg URL. Playlist: remembered playlist thumbnail →
        the playlist's first item thumbnail (cheap /api/playlist call). `size`
        selects a ytimg variant where applicable; signed Hum thumbnails are
        served as-is (resizing them would mean decoding).
        """
        if kind == "video":
            url, client = self._video_art_source(value)
        elif kind == "playlist":
            url, client = await self._playlist_art_source(value)
        else:
            raise SubsonicError(NOT_FOUND, f"no cover art for {kind} ids")
        r = await client.get(_ytimg_variant(url, size))
        if r.status_code != 200:
            raise SubsonicError(NOT_FOUND, f"cover art unavailable for {kind}:{value}")
        return r.content, r.headers.get("content-type", "image/jpeg")

    def _video_art_source(self, video_id: str) -> tuple[str, httpx.AsyncClient]:
        now = time.time()
        cached = self._details.get(video_id)
        if cached and cached[1] > now and cached[0].thumbnail_url:
            return self.absolute(cached[0].thumbnail_url), self._hum
        remembered = self._art_urls.get(f"vid:{video_id}")
        if remembered:
            return remembered, self._ext
        return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg", self._ext

    async def _playlist_art_source(self, playlist_id: str) -> tuple[str, httpx.AsyncClient]:
        remembered = self._art_urls.get(f"pl:{playlist_id}")
        if remembered:
            return remembered, self._ext
        info = await self.playlist(playlist_id)
        for item in info.items:
            if item.thumbnail_url:
                return item.thumbnail_url, self._ext
        raise SubsonicError(NOT_FOUND, f"no cover art for playlist {playlist_id}")


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
