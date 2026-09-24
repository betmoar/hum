"""The single boundary to yt-dlp (and thus YouTube).

All other modules consume the normalised models in app.models. If YouTube
changes its API shape or yt-dlp's surface, the fix lives in this file.
Raw CDN URLs never leave this module except into the server-side
_stream_url_cache (invariant 3); clients only ever get /proxy/... paths.

yt-dlp needs a JavaScript runtime (deno) for YouTube's signature/n
challenges; see check_backend_requirements.
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from app.adapters.search_params import build_search_sp
from app.config import get_settings
from app.models import (
    AudioFormat,
    ChannelInfo,
    PlaylistInfo,
    PlaylistItem,
    SearchHit,
    VideoDetails,
    VideoFormat,
)

logger = logging.getLogger("hum.youtube")

# Cache: (video_id, itag) -> (upstream_url, expiry_epoch) for VOD streams.
# Also stores ("live", video_id) -> (master_hls_url, expiry_epoch) for live.
_stream_url_cache: dict[tuple[Any, ...], tuple[str, float]] = {}

# In-flight cache refreshes, keyed by video_id. Collapses concurrent cache-miss
# refreshes of the same video onto a single yt-dlp extraction. Self-cleaning:
# entries exist only while a refresh is running (popped in a finally), so this
# never grows unbounded.
_inflight_refresh: dict[str, asyncio.Task[None]] = {}

# Cache TTL caps how long we trust an upstream URL beyond YouTube's own `expire=`.
# Long enough to cover a typical listening session without forcing a yt-dlp
# re-extraction (expensive: ~2 s of HTTPS + deno challenge solving).
_CACHE_MAX_TTL = 3600.0  # 1 hour

# Cache: video_id -> (VideoDetails, expiry_epoch). Holds the canonical UNSIGNED
# copy — /api/video signs by MUTATING the object it gets, so readers always
# receive model_copy(deep=True), never the cached instance. Live videos are
# never stored (post-fetch discard: live state goes stale fast) — but they
# still go through the single-flight join in video(); only the cache *write*
# is skipped. The clamp to _CACHE_MAX_TTL is for metadata freshness
# (title/views/format availability drift) — the cached proxy paths are
# unsigned and stable, with no expiry coupling to _stream_url_cache.
_video_details_cache: dict[str, tuple[VideoDetails, float]] = {}

# Cache: (query, category, live, limit) -> (hits, expiry_epoch). Read/write
# logic lives in search(); swept by _evict_expired.
_search_cache: dict[tuple[str, str | None, bool, int], tuple[list[SearchHit], float]] = {}

# In-flight video() fetches, keyed by video_id — same single-flight shape as
# _inflight_refresh. Self-cleaning: popped in a done-callback.
_inflight_video: dict[str, asyncio.Task[VideoDetails]] = {}

# In-flight search() fetches, keyed by the same tuple as _search_cache.
# Self-cleaning: popped in a done-callback.
_inflight_search: dict[tuple[str, str | None, bool, int], asyncio.Task[list[SearchHit]]] = {}


class YouTubeError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message
        super().__init__(message)



@dataclass(frozen=True)
class LiveStreamInfo:
    """Adapter-internal shape for live-stream metadata. Never crosses the API boundary."""
    video_id: str
    title: str
    author: str
    channel_id: str
    thumbnail_url: str
    master_hls_url: str



# ---- yt-dlp plumbing ------------------------------------------------------


class _YdlLogger:
    """Route yt-dlp's own output into Hum's logging. Without a logger it
    prints ERROR lines to stderr even with quiet=True; the actual failure is
    already surfaced as a mapped YouTubeError, so these are debug detail."""

    def debug(self, msg: str) -> None:
        logger.debug("yt-dlp: %s", msg)

    def info(self, msg: str) -> None:
        logger.debug("yt-dlp: %s", msg)

    def warning(self, msg: str) -> None:
        # Hum never downloads or merges formats, so a missing ffmpeg is
        # irrelevant — yet yt-dlp warns about it on every extraction.
        if "ffmpeg not found" in msg:
            logger.debug("yt-dlp: %s", msg)
            return
        logger.warning("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:
        logger.debug("yt-dlp error (raised as YouTubeError): %s", msg)


_BASE_OPTS: dict[str, Any] = {
    "logger": _YdlLogger(),
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "noplaylist": True,
    "noprogress": True,
}

# Flat listing: one page request, no per-entry player call. Used for search,
# channel and playlist listings.
_FLAT_OPTS: dict[str, Any] = {"extract_flat": "in_playlist"}

# Substrings of yt-dlp error messages. yt-dlp errors are strings, not a
# class hierarchy, so this is the mapping. New wording from YouTube → add a
# marker here and a row in test_youtube_adapter.py::test_error_mapping.
_BLOCKED_MARKERS = (
    "sign in to confirm", "po token", "not a bot", "confirm your age", "age-restricted",
)
_UNAVAILABLE_MARKERS = (
    "video unavailable", "video is unavailable", "private video", "has been removed",
    "is not available", "account associated with this video has been terminated",
    "does not exist",
)

_AUDIO_MIME = {"m4a": "audio/mp4", "mp4": "audio/mp4", "webm": "audio/webm"}
_VIDEO_MIME = {"mp4": "video/mp4", "webm": "video/webm"}


def _make_ydl(opts: dict[str, Any]) -> Any:
    """Factory seam for tests. A YoutubeDL instance is not thread-safe, so
    every call builds its own (these run in asyncio.to_thread workers)."""
    return yt_dlp.YoutubeDL(opts)


_CDN_URL_RE = re.compile(r"https?://[^\s'\"]*googlevideo\.com[^\s'\"]*")


def _redact_cdn_urls(text: str) -> str:
    return _CDN_URL_RE.sub("<googlevideo-url>", text)


def _map_error(e: BaseException) -> YouTubeError:
    """Translate a yt-dlp failure into a YouTubeError with a sane HTTP status.

    Buckets:
      - anti-bot / auth walls -> 503 YOUTUBE_BLOCKED (operator: we are being blocked)
      - gone/private/removed  -> 404 VIDEO_UNAVAILABLE
      - anything else         -> 502 UPSTREAM_FAILURE (yt-dlp broke / YouTube changed)
    """
    # YouTubeError.message is returned to clients; yt-dlp's text can carry
    # signed googlevideo URLs (invariant 3). Raw text stays in the server log.
    msg = str(e)
    low = msg.lower()
    # Signed googlevideo URLs are redacted even from the server log.
    logger.info("yt-dlp failure (%s): %s", type(e).__name__, _redact_cdn_urls(msg))
    if any(m in low for m in _BLOCKED_MARKERS):
        return YouTubeError(503, "YOUTUBE_BLOCKED", "YouTube is blocking requests")
    if any(m in low for m in _UNAVAILABLE_MARKERS):
        return YouTubeError(404, "VIDEO_UNAVAILABLE", "video unavailable")
    return YouTubeError(502, "UPSTREAM_FAILURE", "YouTube extraction failed")


def _extract(url: str, extra: dict[str, Any]) -> dict[str, Any]:
    try:
        with _make_ydl({**_BASE_OPTS, **extra}) as ydl:
            info = ydl.extract_info(url, download=False)
    except YouTubeError:
        raise
    except (DownloadError, ExtractorError) as e:
        raise _map_error(e) from e
    except Exception as e:
        # Anything else is yt-dlp breaking or YouTube changing shape: a mapped
        # 502, never a bare 500 (the frontend's recovery keys off statuses).
        raise _map_error(e) from e
    if not isinstance(info, dict):
        raise YouTubeError(502, "UPSTREAM_FAILURE", "yt-dlp returned no info")
    return info


def _int(v: Any) -> int | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _kbps_to_bps(v: Any) -> int:
    try:
        return int(round(float(v) * 1000))
    except (TypeError, ValueError):
        return 0


def _author(info: dict[str, Any]) -> str | None:
    for key in ("channel", "uploader", "creator"):
        v = info.get(key)
        if isinstance(v, str) and v:
            return v
    return None



# ---- Public API ----------------------------------------------------------


async def search(
    query: str,
    limit: int = 20,
    *,
    category: str | None = None,
    live: bool = False,
) -> list[SearchHit]:
    cache_key = (query, category, live, limit)
    cached = _search_cache.get(cache_key)
    if cached and cached[1] > time.time():
        # Shallow list copy: a caller may reorder/filter its own list, but the
        # SearchHits inside are shared with the cache — SearchHit is frozen so
        # in-place mutation raises rather than poisoning them.
        return list(cached[0])
    # Single-flight, same shape and rationale as video(): concurrent identical
    # queries (two tabs, a retry after a slow response) collapse onto one
    # yt-dlp extraction instead of stampeding.
    task = _inflight_search.get(cache_key)
    if task is None:
        task = asyncio.create_task(_run_search(query, limit, category=category, live=live,
                                               cache_key=cache_key))
        _inflight_search[cache_key] = task
        task.add_done_callback(_release_inflight_search)
    # shield: see video() — one caller's cancellation must not cancel the fetch
    # that other callers are waiting on.
    return list(await asyncio.shield(task))


async def _run_search(
    query: str,
    limit: int,
    *,
    category: str | None,
    live: bool,
    cache_key: tuple[str, str | None, bool, int],
) -> list[SearchHit]:
    """The uncached search fetch, run inside search()'s single-flight task."""
    sp = build_search_sp(category=category, live=live)
    hits = await asyncio.to_thread(_search_hits, query, limit, sp)
    _store_search_hits(hits, cache_key)
    return hits


def _release_inflight(registry: dict[Any, Any], task: asyncio.Task[Any]) -> None:
    """Done-callback for a single-flight task: drop its registry entry, then
    mark its exception observed.

    That second step is not bookkeeping. Callers await these tasks through
    asyncio.shield, so a task whose callers were ALL cancelled has nobody left
    to retrieve its result, and asyncio logs "Task exception was never
    retrieved" at GC time for any failure. Reading it here marks it observed.
    """
    for key, inflight in list(registry.items()):
        if inflight is task:
            registry.pop(key, None)
            break
    if not task.cancelled():
        task.exception()


def _release_inflight_video(task: asyncio.Task[VideoDetails]) -> None:
    _release_inflight(_inflight_video, task)


def _release_inflight_search(task: asyncio.Task[list[SearchHit]]) -> None:
    _release_inflight(_inflight_search, task)


async def video(video_id: str) -> VideoDetails:
    # Metadata cache hit: deep-copy so per-request signing can't touch the
    # cached canonical (see _video_details_cache comment).
    cached = _video_details_cache.get(video_id)
    if cached and cached[1] > time.time():
        return cached[0].model_copy(deep=True)
    # Single-flight: concurrent misses for the same id share one fetch. The
    # check-and-create is atomic within the event loop (no await between the
    # .get() and the assignment), mirroring _refresh_cache_once.
    task = _inflight_video.get(video_id)
    if task is None:
        task = asyncio.create_task(asyncio.to_thread(_fetch_video_cached, video_id))
        _inflight_video[video_id] = task
        # Only the creator clears the entry — a joiner popping it would let a
        # later caller start a second fetch while this one is still running.
        task.add_done_callback(_release_inflight_video)
    # shield() so one caller's cancellation (client disconnect mid-fetch) can't
    # cancel the SHARED task out from under every other caller waiting on it.
    # Without it, an unlucky joiner gets CancelledError — which is BaseException,
    # so it escapes every handler in app.main and the client gets a torn
    # connection instead of the mapped 4xx/5xx the frontend recovers from.
    # Copy on the way out: the caller signs by mutating what it receives, and
    # all callers here share one task result.
    return (await asyncio.shield(task)).model_copy(deep=True)


_EJS_WIKI_URL = "https://github.com/yt-dlp/yt-dlp/wiki/EJS"


def check_backend_requirements() -> None:
    """Startup check (app.main lifespan). yt-dlp needs a JS runtime for
    YouTube; without one it degrades (formats missing) or fails. Logs loudly
    and keeps serving — failures then surface per request as the usual mapped
    502/503, never a crashed app."""
    if shutil.which("deno") is None:
        logger.error(
            "the deno JavaScript runtime is not on PATH; yt-dlp's YouTube "
            "extraction will degrade or fail. Install deno: %s", _EJS_WIKI_URL,
        )


async def channel(channel_id: str) -> ChannelInfo:
    return await asyncio.to_thread(_fetch_channel, channel_id)


async def playlist(playlist_id: str) -> PlaylistInfo:
    return await asyncio.to_thread(_fetch_playlist, playlist_id)


async def resolve_upstream_url(video_id: str, itag: int) -> str:
    """Return the real YouTube CDN URL for the given (video_id, itag).

    Uses an in-memory cache that respects both our TTL and YouTube's own `expire`.
    """
    now = time.time()
    cached = _stream_url_cache.get((video_id, itag))
    if cached and cached[1] > now:
        return cached[0]
    # Cache miss — refresh off-thread (so the event loop isn't blocked by
    # deno challenge solving) and de-duplicated, so concurrent misses for the same
    # video don't each fire a redundant fetch.
    await _refresh_cache_once(video_id)
    cached = _stream_url_cache.get((video_id, itag))
    # Re-check expiry, not just existence: a refresh that no longer offers this
    # itag leaves any prior (now-stale) entry untouched. Serving it would hand
    # back a dead URL (YouTube 403) instead of a clean 404.
    if not cached or cached[1] <= time.time():
        raise YouTubeError(404, "ITAG_NOT_FOUND", f"itag {itag} not available for {video_id}")
    return cached[0]


def evict_stream_url(video_id: str, itag: int) -> None:
    """Drop a single (video_id, itag) cache entry.

    Used by the proxy's evict-and-retry-once flow on upstream 403/410 (see
    app/proxy/_common.py) — YouTube can invalidate a cached CDN URL early (IP
    change), and retrying with the same stale entry just repeats the 403.
    A single dict.pop is GIL-atomic, consistent with the cache-mutation rules
    in docs/PLAYBOOKS.md §4 (writers run in asyncio.to_thread workers, readers
    on the event loop — no compound read-modify-write).
    """
    _stream_url_cache.pop((video_id, itag), None)


async def resolve_live_master_url(video_id: str) -> str:
    """Return the YouTube master HLS URL for a live video.

    Cached in `_stream_url_cache` under key `("live", video_id)` with TTL
    = min(5 min, upstream `expire` query param). Raises YouTubeError(502,
    "LIVE_UNAVAILABLE", ...) if the manifest can't be resolved.
    """
    now = time.time()
    key = ("live", video_id)
    cached = _stream_url_cache.get(key)
    if cached and cached[1] > now:
        return cached[0]
    info = await asyncio.to_thread(_fetch_live_manifest, video_id)
    if info is None:
        raise YouTubeError(
            502, "LIVE_UNAVAILABLE",
            f"live manifest unavailable for {video_id}",
        )
    _cache_live_master(video_id, info.master_hls_url)
    return info.master_hls_url


def _cache_live_master(video_id: str, master_url: str) -> None:
    """Cache a live master URL under ("live", video_id) with TTL
    min(5 min, upstream `expire`). Single dict write (GIL-atomic)."""
    now = time.time()
    # _url_expire_epoch already returns a future fallback when `expire` is
    # missing or garbage, so a past value means the URL is dead: don't cache
    # it (/api/live would keep serving it until the TTL ran out).
    expiry = min(now + 300.0, _url_expire_epoch(master_url, now=now))
    if expiry > now:
        _stream_url_cache[("live", video_id)] = (master_url, expiry)


async def _refresh_cache_once(video_id: str) -> None:
    """Run _refresh_cache(video_id) under single-flight.

    Concurrent callers for the same video await one shared task instead of each
    firing a redundant (expensive) yt-dlp extraction. The check-and-create below
    is atomic within the event loop — there is no await between the .get() and
    the assignment — so two coroutines cannot both create a task for the same id.
    """
    task = _inflight_refresh.get(video_id)
    if task is not None:
        await task
        return
    task = asyncio.create_task(asyncio.to_thread(_refresh_cache, video_id))
    _inflight_refresh[video_id] = task
    try:
        await task
    finally:
        _inflight_refresh.pop(video_id, None)


# ---- Thread-bound fetchers (called via asyncio.to_thread) ----------------


def _fetch_video(video_id: str) -> VideoDetails:
    """Thread-bound (call via asyncio.to_thread). Writes the stream cache."""
    info = _extract(f"https://www.youtube.com/watch?v={video_id}", {})
    if info.get("live_status") == "is_live":
        # The client only ever gets the /api/live route. Don't advertise it
        # without a manifest behind it; do prime the master-URL cache, which
        # saves resolve_live_master_url a second extraction at play time.
        live = _live_info(video_id, info)
        if not live.master_hls_url:
            raise YouTubeError(502, "LIVE_UNAVAILABLE", f"live manifest unavailable for {video_id}")
        _cache_live_master(video_id, live.master_hls_url)
        return _live_video_details(video_id, live)

    audio: list[AudioFormat] = []
    video: list[VideoFormat] = []
    seen: set[int] = set()
    now = time.time()
    for f in info.get("formats") or []:
        if not isinstance(f, dict):
            continue
        # Direct progressive/DASH URLs only; manifests and storyboards are not
        # proxyable byte streams. Non-numeric ids ("140-drc", "sb0") are
        # variants we don't expose.
        if f.get("protocol") not in ("https", "http"):
            continue
        fid = str(f.get("format_id") or "")
        url = f.get("url")
        if not fid.isdigit() or not isinstance(url, str) or not url:
            continue
        itag = int(fid)
        if itag in seen:
            continue  # first occurrence wins (yt-dlp may list one itag per client)
        seen.add(itag)
        vcodec = str(f.get("vcodec") or "none")
        acodec = str(f.get("acodec") or "none")
        ext = str(f.get("ext") or "")
        if vcodec == "none" and acodec != "none":
            mime = f'{_AUDIO_MIME.get(ext, "audio/" + ext)}; codecs="{acodec}"'
            audio.append(AudioFormat(
                itag=itag, mime_type=mime, bitrate=_kbps_to_bps(f.get("abr") or f.get("tbr")),
                codec=_extract_codec(mime), sample_rate=_int(f.get("asr")),
                channels=_int(f.get("audio_channels")), url=_proxy_path_for(video_id, itag, mime),
            ))
        elif vcodec != "none":
            codecs = vcodec if acodec == "none" else f"{vcodec}, {acodec}"
            mime = f'{_VIDEO_MIME.get(ext, "video/" + ext)}; codecs="{codecs}"'
            video.append(VideoFormat(
                itag=itag, mime_type=mime, bitrate=_kbps_to_bps(f.get("tbr")),
                codec=_extract_codec(mime), width=_int(f.get("width")) or 0,
                height=_int(f.get("height")) or 0, fps=_int(f.get("fps")),
                has_audio=acodec != "none", url=_proxy_path_for(video_id, itag, mime),
            ))
        else:
            continue
        # Trust YouTube's `expire=`, clamp to _CACHE_MAX_TTL (CLAUDE.md landmine).
        expiry = min(_url_expire_epoch(url, now=now), now + _CACHE_MAX_TTL)
        _stream_url_cache[(video_id, itag)] = (url, expiry)

    return VideoDetails(
        video_id=video_id,
        title=str(info.get("title") or ""),
        description=info.get("description") if isinstance(info.get("description"), str) else None,
        author=_author(info) or "",
        channel_id=str(info.get("channel_id") or ""),
        duration_seconds=_int(info.get("duration")) or 0,
        view_count=_int(info.get("view_count")),
        thumbnail_url=f"/proxy/thumbnail/{video_id}",
        audio_formats=audio,
        video_formats=video,
    )



def _fetch_video_cached(video_id: str) -> VideoDetails:
    """_fetch_video plus the metadata-cache write. Runs in a to_thread worker
    (yt-dlp extraction touches network + deno)."""
    details = _fetch_video(video_id)
    if not details.is_live:
        ttl = min(float(get_settings().video_cache_ttl_seconds), _CACHE_MAX_TTL)
        _video_details_cache[video_id] = (details.model_copy(deep=True), time.time() + ttl)
    # Sweep here too: a metadata-only session (repeated /api/video with no
    # playback and no search) reaches neither of the other two sweep sites, so
    # without this _video_details_cache would accumulate expired entries.
    _evict_expired()
    return details


def _live_info(video_id: str, info: dict[str, Any]) -> LiveStreamInfo:
    """LiveStreamInfo from a yt-dlp info dict. master_hls_url is the HLS master
    manifest shared by all of the info's m3u8 formats ("" when absent)."""
    master = ""
    for f in info.get("formats") or []:
        if not isinstance(f, dict):
            continue
        url = f.get("manifest_url")
        if f.get("protocol") in ("m3u8", "m3u8_native") and isinstance(url, str) and url:
            master = url
            break
    return LiveStreamInfo(
        video_id=video_id,
        title=str(info.get("title") or ""),
        author=_author(info) or "",
        channel_id=str(info.get("channel_id") or ""),
        thumbnail_url=f"/proxy/thumbnail/{video_id}",
        master_hls_url=master,
    )


def _fetch_live_manifest(video_id: str) -> LiveStreamInfo | None:
    """Live master-manifest lookup. Returns None on any failure (not live,
    no manifest, extraction error) so callers can degrade rather than 500."""
    try:
        info = _extract(f"https://www.youtube.com/watch?v={video_id}", {})
    except YouTubeError:
        return None
    if info.get("live_status") != "is_live":
        return None
    live = _live_info(video_id, info)
    return live if live.master_hls_url else None


def _refresh_cache(video_id: str) -> None:
    _fetch_video(video_id)
    _evict_expired()


def _evict_expired(now: float | None = None) -> None:
    """Drop expired entries from all adapter caches.

    Without this the caches grow unbounded over a long-running process.
    Called off the request hot path, from all three cache-write sites: after a
    stream-URL refresh (_refresh_cache), after a metadata fetch
    (_fetch_video_cached), and after a search-cache write
    (_collect_and_cache_search). Each of those is already a cache MISS, so the
    sweep never runs on a hit. All three are needed: a session that only
    searches, or only reads metadata, reaches just one of them.

    Keys are snapshotted first: writers run in asyncio.to_thread workers, so a
    concurrent writer could otherwise mutate a dict mid-iteration.

    Note this evicts only EXPIRED entries — there is no cap on live entries
    within a TTL window. Bounded in practice by _CACHE_MAX_TTL (1 h) and the
    single-user threat model; revisit if either changes.
    """
    cutoff = now if now is not None else time.time()
    caches: tuple[dict[Any, Any], ...] = (
        _stream_url_cache,
        _video_details_cache,
        _search_cache,
    )
    for cache in caches:
        for key in list(cache.keys()):
            entry = cache.get(key)
            if entry is not None and entry[1] <= cutoff:
                cache.pop(key, None)


# ---- Normalisation -------------------------------------------------------


def _live_video_details(video_id: str, info: LiveStreamInfo) -> VideoDetails:
    return VideoDetails(
        video_id=video_id,
        title=info.title,
        description=None,
        author=info.author,
        channel_id=info.channel_id,
        duration_seconds=0,
        view_count=None,
        thumbnail_url=info.thumbnail_url,
        audio_formats=[],
        video_formats=[],
        is_live=True,
        live_stream_url=f"/api/live/{video_id}/manifest.m3u8",
    )


def _store_search_hits(hits: list[SearchHit], cache_key: tuple[str, str | None, bool, int]) -> None:
    """Search-cache write + eviction sweep. Runs in the to_thread worker: the
    sweep runs HERE because a search-only session never reaches _refresh_cache."""
    # Clamped like the video-metadata TTL: an operator-set value is defence in
    # depth away from serving hours-stale search results.
    ttl = min(float(get_settings().search_cache_ttl_seconds), _CACHE_MAX_TTL)
    _search_cache[cache_key] = (list(hits), time.time() + ttl)
    _evict_expired()


def _best_thumb(thumbs: Any, *, prefer_id: str | None = None) -> str | None:
    """Pick a thumbnail URL from a yt-dlp `thumbnails` list: the entry with id
    `prefer_id` if present, else the widest, else the last."""
    if not isinstance(thumbs, list):
        return None
    good = [t for t in thumbs if isinstance(t, dict) and isinstance(t.get("url"), str) and t["url"]]
    if not good:
        return None
    if prefer_id is not None:
        for t in good:
            if t.get("id") == prefer_id:
                return str(t["url"])
    best = max(good, key=lambda t: _int(t.get("width")) or 0)
    url = str(best["url"])
    return "https:" + url if url.startswith("//") else url


def _fetch_channel(channel_id: str) -> ChannelInfo:
    # playlistend=1: we only need the channel's own metadata, not its tabs.
    info = _extract(f"https://www.youtube.com/channel/{channel_id}",
                    {**_FLAT_OPTS, "playlistend": 1})
    return ChannelInfo(
        channel_id=str(info.get("channel_id") or info.get("id") or channel_id),
        title=str(info.get("channel") or info.get("title") or ""),
        description=info.get("description") if isinstance(info.get("description"), str) else None,
        subscriber_count=_int(info.get("channel_follower_count")),
        thumbnail_url=_best_thumb(info.get("thumbnails"), prefer_id="avatar_uncropped") or "",
    )


def _fetch_playlist(playlist_id: str) -> PlaylistInfo:
    info = _extract(f"https://www.youtube.com/playlist?list={playlist_id}", _FLAT_OPTS)
    items: list[PlaylistItem] = []
    for entry in info.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        vid = entry.get("id")
        if not isinstance(vid, str) or not vid:
            continue
        items.append(PlaylistItem(
            video_id=vid,
            title=str(entry.get("title") or ""),
            author=_author(entry),
            duration_seconds=_int(entry.get("duration")),
            thumbnail_url=_best_thumb(entry.get("thumbnails")) or "",
        ))
    return PlaylistInfo(
        playlist_id=playlist_id,
        title=str(info.get("title") or "") or f"Playlist {playlist_id}",
        author=_author(info),
        video_count=_int(info.get("playlist_count")) or len(items),
        items=items,
    )


def _thumb(entry: dict[str, Any]) -> str | None:
    thumbs = entry.get("thumbnails")
    if isinstance(thumbs, list):
        for t in reversed(thumbs):
            u = t.get("url") if isinstance(t, dict) else None
            if isinstance(u, str) and u:
                return "https:" + u if u.startswith("//") else u
    return None


def _hit(entry: Any) -> SearchHit | None:
    if not isinstance(entry, dict):
        return None
    eid = entry.get("id")
    if not isinstance(eid, str) or not eid:
        return None
    url = str(entry.get("url") or "")
    title = str(entry.get("title") or "")
    if entry.get("ie_key") == "Youtube":
        return SearchHit(
            kind="video", id=eid, title=title, author=_author(entry),
            # Search-grid thumbnails stay raw i.ytimg.com URLs (CLAUDE.md landmine).
            thumbnail_url=_thumb(entry) or f"https://i.ytimg.com/vi/{eid}/hqdefault.jpg",
            duration_seconds=_int(entry.get("duration")),
            is_live=True if entry.get("live_status") == "is_live" else None,
        )
    if "list=" in url:
        if eid.startswith("RD"):
            # YouTube "Mix" radios: listed in search, but unviewable as a
            # playlist ("This playlist type is unviewable").
            return None
        return SearchHit(
            kind="playlist", id=eid, title=title, author=_author(entry),
            thumbnail_url=_thumb(entry) or "", video_count=_int(entry.get("playlist_count")),
        )
    if "/channel/" in url or "/@" in url:
        return SearchHit(kind="channel", id=eid, title=title, thumbnail_url=_thumb(entry) or "")
    return None


def _search_hits(query: str, limit: int, sp: str | None) -> list[SearchHit]:
    """Thread-bound. One flat results-page extraction: title, channel and
    duration come from the search response itself (no per-hit player call)."""
    params = {"search_query": query}
    if sp:
        params["sp"] = sp
    url = "https://www.youtube.com/results?" + urllib.parse.urlencode(params)
    info = _extract(url, {"extract_flat": "in_playlist", "playlistend": limit})
    hits: list[SearchHit] = []
    for entry in info.get("entries") or []:
        try:
            hit = _hit(entry)
        except Exception:
            logger.debug("skipping malformed yt-dlp search entry", exc_info=True)
            continue
        # Any filter means "videos only" (see search_params.build_search_sp),
        # but YouTube ignores type=Video once a topic is set — enforce it here.
        if hit is not None and (sp is None or hit.kind == "video"):
            hits.append(hit)
            if len(hits) >= limit:
                break
    return hits

# ---- Helpers -------------------------------------------------------------


_PATH_EXPIRE_RE = re.compile(r"/expire/(\d+)(?:/|$)")


def _url_expire_epoch(url: str, *, now: float | None = None) -> float:
    """Return the URL's `expire=` epoch, or a far-future fallback if absent.

    Returning a far-future value (now + cache_max_ttl) on absence means the
    caller's `min(expire, now + cache_max_ttl)` clamps to our cache TTL —
    equivalent to "no explicit upstream constraint."
    """
    parsed = urllib.parse.urlparse(url)
    val = urllib.parse.parse_qs(parsed.query).get("expire", [None])[0]
    if val is None:
        # Live HLS manifest URLs carry it as a path segment: /expire/<epoch>/.
        m = _PATH_EXPIRE_RE.search(parsed.path)
        val = m.group(1) if m else None
    _now = now if now is not None else time.time()
    try:
        return float(val) if val else _now + _CACHE_MAX_TTL
    except (TypeError, ValueError):
        return _now + _CACHE_MAX_TTL


_CODEC_RE = re.compile(r'codecs="([^"]+)"')

_CODEC_ALIASES: tuple[tuple[str, str], ...] = (
    ("mp4a", "aac"),
    ("opus", "opus"),
    ("avc1", "avc1"),
    ("vp9", "vp9"),
    ("av01", "av01"),
)


def _extract_codec(mime: str) -> str:
    m = _CODEC_RE.search(mime)
    if not m:
        return ""
    primary = m.group(1).split(",")[0].strip()
    return next(
        (alias for prefix, alias in _CODEC_ALIASES if primary.startswith(prefix)),
        primary,
    )


def _proxy_path_for(video_id: str, itag: int, mime: str) -> str:
    base = "/proxy/audio" if mime.startswith("audio/") else "/proxy/stream"
    return f"{base}/{video_id}?itag={itag}"


