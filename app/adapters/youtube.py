"""The single boundary to pytubefix (and thus YouTube).

All other modules consume the normalised models in app.models. If YouTube
changes its API shape or pytubefix's surface, the fix lives in this file.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from pytubefix import Channel, Playlist, Search, YouTube
from pytubefix import exceptions as pytubefix_exceptions

try:
    from pytubefix.contrib.search import Filter as _SearchFilter
except Exception:
    _SearchFilter = None

try:
    from pytubefix.protobuf import encode_protobuf as _encode_protobuf
except Exception:
    _encode_protobuf = None

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
# refreshes of the same video onto a single pytubefix fetch. Self-cleaning:
# entries exist only while a refresh is running (popped in a finally), so this
# never grows unbounded.
_inflight_refresh: dict[str, asyncio.Task[None]] = {}

# Cache TTL caps how long we trust an upstream URL beyond YouTube's own `expire=`.
# Long enough to cover a typical listening session without forcing a pytubefix
# re-fetch (which is expensive: HTTPS + Node cipher deobfuscation).
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
# _inflight_refresh. Self-cleaning: popped in a finally.
_inflight_video: dict[str, asyncio.Task[VideoDetails]] = {}


class YouTubeError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message
        super().__init__(message)


# pytubefix errors that mean "YouTube is refusing us", not "this video is gone".
# Mapped to 503 so an operator can tell a blocking incident apart from dead links.
_BLOCKED_ERROR_NAMES = frozenset(
    {"BotDetection", "PoTokenRequired", "LoginRequired", "AgeCheckRequiredError",
     "AgeCheckRequiredAccountError", "AgeRestrictedError", "SABRError"}
)


def _map_pytubefix_error(e: Exception) -> YouTubeError:
    """Translate a pytubefix exception into a YouTubeError with a sane HTTP status.

    Buckets:
      - anti-bot / auth walls        -> 503 YOUTUBE_BLOCKED (operator: we are being blocked)
      - VideoUnavailable subtree     -> 404 VIDEO_UNAVAILABLE (video gone/private/etc.)
      - anything else from pytubefix -> 502 UPSTREAM_FAILURE (pytubefix broke / YouTube changed)
    """
    name = e.__class__.__name__
    if name in _BLOCKED_ERROR_NAMES:
        return YouTubeError(503, "YOUTUBE_BLOCKED", f"YouTube is blocking requests ({name})")
    if isinstance(e, pytubefix_exceptions.VideoUnavailable):
        return YouTubeError(404, "VIDEO_UNAVAILABLE", f"video unavailable ({name})")
    return YouTubeError(502, "UPSTREAM_FAILURE", f"pytubefix failed ({name}: {e})")


@dataclass(frozen=True)
class LiveStreamInfo:
    """Adapter-internal shape for live-stream metadata. Never crosses the API boundary."""
    video_id: str
    title: str
    author: str
    channel_id: str
    thumbnail_url: str
    master_hls_url: str


# ---- Factory helpers (monkeypatchable for tests) -------------------------


def _make_youtube(video_id: str) -> Any:
    return YouTube(f"https://www.youtube.com/watch?v={video_id}")


def _make_search(query: str, *, filters: Any = None) -> Any:
    if filters is not None:
        return Search(query, filters=filters)
    return Search(query)


def _make_channel(channel_id: str) -> Any:
    return Channel(f"https://www.youtube.com/channel/{channel_id}")


def _make_playlist(playlist_id: str) -> Any:
    return Playlist(f"https://www.youtube.com/playlist?list={playlist_id}")


# ---- Public API ----------------------------------------------------------


_T = TypeVar("_T")


async def _to_thread_mapped(fn: Callable[..., _T], /, *args: Any, **kwargs: Any) -> _T:
    """asyncio.to_thread with pytubefix exceptions translated to YouTubeError.

    Every pytubefix call MUST go through this (or swallow errors itself, like
    `_fetch_live_manifest`). A raw PytubeFixError escaping the adapter turns
    into a 500 at the route layer; YouTubeError turns into a clean 4xx/5xx via
    the global handler in app.main.
    """
    try:
        return await asyncio.to_thread(fn, *args, **kwargs)
    except YouTubeError:
        raise
    except pytubefix_exceptions.PytubeFixError as e:
        raise _map_pytubefix_error(e) from e


async def search(
    query: str,
    limit: int = 20,
    *,
    category: str | None = None,
    live: bool = False,
) -> list[SearchHit]:
    raw_filters = _build_search_filters(category=category, live=live)
    pytubefix_filters: dict[str, Any] | None = None
    wants_music = False
    if raw_filters is not None:
        wants_music = raw_filters.pop("_music_topic", False)
        pytubefix_filters = raw_filters if raw_filters else None
    s = await _to_thread_mapped(_make_search, query, filters=pytubefix_filters)
    if wants_music:
        # pytubefix's `Search.__init__` doesn't accept an `sp` kwarg; the encoded
        # filter protobuf lives on `s.filter` and is read at request time. Rebuild
        # it with the music-topic field merged in. On encoder failure, leave
        # `s.filter` untouched so the search degrades to type=Video + features.
        _inject_music_topic(s, pytubefix_filters)
    return await _to_thread_mapped(_collect_search_hits, s, limit)


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
    if task is not None:
        # Joiners copy too — sharing the creator's instance would double-sign.
        return (await task).model_copy(deep=True)
    task = asyncio.create_task(_to_thread_mapped(_fetch_video_cached, video_id))
    _inflight_video[video_id] = task
    try:
        # Copy here too — the caller signs by mutating the returned object, and
        # joiners share this same task result, so returning the raw instance
        # races joiners' copies against the creator's caller's mutation.
        return (await task).model_copy(deep=True)
    finally:
        _inflight_video.pop(video_id, None)


async def channel(channel_id: str) -> ChannelInfo:
    return await _to_thread_mapped(_fetch_channel, channel_id)


async def playlist(playlist_id: str) -> PlaylistInfo:
    return await _to_thread_mapped(_fetch_playlist, playlist_id)


async def resolve_upstream_url(video_id: str, itag: int) -> str:
    """Return the real YouTube CDN URL for the given (video_id, itag).

    Uses an in-memory cache that respects both our TTL and YouTube's own `expire`.
    """
    now = time.time()
    cached = _stream_url_cache.get((video_id, itag))
    if cached and cached[1] > now:
        return cached[0]
    # Cache miss — refresh off-thread (so the event loop isn't blocked by
    # Node-cipher work) and de-duplicated, so concurrent misses for the same
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
    upstream_expire = _url_expire_epoch(info.master_hls_url)
    # Clamp by upstream `expire` only when it lies in the future; an already-past
    # value is treated as no constraint (the URL is either ageless or the param
    # is sentinel/garbage). 5-minute ceiling still applies.
    soft_ceiling = now + 300.0
    expiry = min(soft_ceiling, upstream_expire) if upstream_expire > now else soft_ceiling
    _stream_url_cache[key] = (info.master_hls_url, expiry)
    return info.master_hls_url


async def _refresh_cache_once(video_id: str) -> None:
    """Run _refresh_cache(video_id) under single-flight.

    Concurrent callers for the same video await one shared task instead of each
    firing a redundant (expensive) pytubefix fetch. The check-and-create below
    is atomic within the event loop — there is no await between the .get() and
    the assignment — so two coroutines cannot both create a task for the same id.
    """
    task = _inflight_refresh.get(video_id)
    if task is not None:
        await task
        return
    task = asyncio.create_task(_to_thread_mapped(_refresh_cache, video_id))
    _inflight_refresh[video_id] = task
    try:
        await task
    finally:
        _inflight_refresh.pop(video_id, None)


# ---- Thread-bound fetchers (called via asyncio.to_thread) ----------------


def _fetch_video(video_id: str) -> VideoDetails:
    yt = _make_youtube(video_id)
    return _normalise_video(video_id, yt)


def _fetch_video_cached(video_id: str) -> VideoDetails:
    """_fetch_video plus the metadata-cache write. Runs in a to_thread worker
    (construction + stream iteration touch network + Node-cipher work)."""
    details = _fetch_video(video_id)
    if not details.is_live:
        ttl = min(float(get_settings().video_cache_ttl_seconds), _CACHE_MAX_TTL)
        _video_details_cache[video_id] = (details.model_copy(deep=True), time.time() + ttl)
    return details


def _fetch_live_manifest(video_id: str) -> LiveStreamInfo | None:
    """Read the live HLS manifest URL from pytubefix's vid_info, bypassing
    `check_availability()` which raises `LiveStreamError` for live videos.

    Returns None on any failure (missing key, network error, exception)
    so callers can degrade rather than 500.
    """
    try:
        yt = _make_youtube(video_id)
        vid_info = yt.vid_info
        streaming = vid_info.get("streamingData", {}) or {}
        master_url = streaming.get("hlsManifestUrl")
        if not master_url:
            return None
        details = vid_info.get("videoDetails", {}) or {}
        return LiveStreamInfo(
            video_id=video_id,
            title=str(details.get("title", "") or ""),
            author=str(details.get("author", "") or ""),
            channel_id=str(details.get("channelId", "") or ""),
            thumbnail_url=f"/proxy/thumbnail/{video_id}",
            master_hls_url=str(master_url),
        )
    except Exception:
        return None


def _fetch_channel(channel_id: str) -> ChannelInfo:
    ch = _make_channel(channel_id)
    return _normalise_channel(channel_id, ch)


def _fetch_playlist(playlist_id: str) -> PlaylistInfo:
    pl = _make_playlist(playlist_id)
    return _normalise_playlist(playlist_id, pl)


def _refresh_cache(video_id: str) -> None:
    _fetch_video(video_id)
    _evict_expired()


def _evict_expired(now: float | None = None) -> None:
    """Drop expired entries from the stream URL cache.

    Without this the cache grows unbounded over a long-running process — every
    (video_id, itag) ever requested would linger forever. Called after each
    refresh (i.e. on a cache miss, already off the hot path). We snapshot the
    keys first: refreshes run in asyncio.to_thread workers, so a concurrent
    writer could otherwise mutate the dict mid-iteration.
    """
    cutoff = now if now is not None else time.time()
    for key in list(_stream_url_cache.keys()):
        entry = _stream_url_cache.get(key)
        if entry is not None and entry[1] <= cutoff:
            _stream_url_cache.pop(key, None)


# ---- Normalisation -------------------------------------------------------


def _normalise_video(video_id: str, yt: Any) -> VideoDetails:
    # Some live videos don't trigger LiveStreamError (pytubefix still returns
    # iterable streams) but vid_info marks them as currently broadcasting and
    # exposes an hlsManifestUrl. Prefer the live path in that case so we don't
    # hand stale/fake VOD streams to the client.
    if _is_currently_live(yt):
        info = _fetch_live_manifest(video_id)
        if info is not None:
            return _live_video_details(video_id, info)
        # Fall through to VOD path if no manifest — better than 422-ing.
    try:
        return _normalise_vod_video(video_id, yt)
    except Exception as e:
        # Detect pytubefix's LiveStreamError without importing it at top level
        # (keeps test isolation; the exception class is checked by name).
        if e.__class__.__name__ == "LiveStreamError":
            info = _fetch_live_manifest(video_id)
            if info is None:
                raise YouTubeError(
                    422, "LIVE_NOT_SUPPORTED",
                    "Live stream metadata unavailable",
                ) from e
            return _live_video_details(video_id, info)
        raise


def _is_currently_live(yt: Any) -> bool:
    """True when vid_info marks the video as actively broadcasting.

    `isLive` is true only during an active broadcast; `isLiveContent` is true
    for any live broadcast including finished ones — we only want the former.
    We require the value to be a real bool so MagicMock-shaped test fixtures
    don't accidentally take the live path.
    """
    try:
        vid_info = yt.vid_info
        details = vid_info.get("videoDetails", {}) or {}
        value = details.get("isLive")
        return value is True
    except Exception:
        return False


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


def _normalise_vod_video(video_id: str, yt: Any) -> VideoDetails:
    audio_formats: list[AudioFormat] = []
    video_formats: list[VideoFormat] = []

    now = time.time()
    for s in _iter_streams(yt):
        url, itag = _cache_stream(video_id, s, now=now)
        if not url or not itag:
            continue
        mime = str(getattr(s, "mime_type", "") or "")

        af = _stream_to_audio_format(s, video_id, itag=itag, mime=mime)
        if af:
            audio_formats.append(af)
            continue

        vf = _stream_to_video_format(s, video_id, itag=itag, mime=mime)
        if vf:
            video_formats.append(vf)

    return VideoDetails(
        video_id=video_id,
        title=str(getattr(yt, "title", "") or ""),
        description=_safe_str(getattr(yt, "description", None)),
        author=str(getattr(yt, "author", "") or ""),
        channel_id=str(getattr(yt, "channel_id", "") or ""),
        duration_seconds=int(getattr(yt, "length", 0) or 0),
        view_count=_safe_int(getattr(yt, "views", None)),
        thumbnail_url=f"/proxy/thumbnail/{video_id}",
        audio_formats=audio_formats,
        video_formats=video_formats,
    )


def _cache_stream(video_id: str, s: Any, *, now: float | None = None) -> tuple[str | None, int]:
    """Extract URL and itag from a pytubefix stream, writing to the cache.

    Returns (url, itag). Both are falsy when the stream is unusable.
    """
    url = getattr(s, "url", None)
    itag = int(getattr(s, "itag", 0) or 0)
    if url and itag:
        _now = now if now is not None else time.time()
        expiry = min(_url_expire_epoch(url, now=_now), _now + _CACHE_MAX_TTL)
        _stream_url_cache[(video_id, itag)] = (url, expiry)
    return url, itag


def _stream_to_audio_format(
    s: Any, video_id: str, *, itag: int, mime: str
) -> AudioFormat | None:
    """Build an AudioFormat from a pytubefix stream, or None if not audio."""
    if not mime.startswith("audio/"):
        return None
    return AudioFormat(
        itag=itag,
        mime_type=mime,
        bitrate=int(getattr(s, "bitrate", 0) or 0),
        codec=_extract_codec(mime),
        sample_rate=_safe_int(getattr(s, "audio_sample_rate", None)),
        channels=None,
        url=_proxy_path_for(video_id, itag, mime),
    )


def _stream_to_video_format(
    s: Any, video_id: str, *, itag: int, mime: str
) -> VideoFormat | None:
    """Build a VideoFormat from a pytubefix stream, or None if not video."""
    if not mime.startswith("video/"):
        return None
    return VideoFormat(
        itag=itag,
        mime_type=mime,
        bitrate=int(getattr(s, "bitrate", 0) or 0),
        codec=_extract_codec(mime),
        width=int(getattr(s, "width", 0) or 0),
        height=int(getattr(s, "height", 0) or 0),
        fps=_safe_int(getattr(s, "fps", None)),
        has_audio=bool(getattr(s, "includes_audio_track", False)),
        url=_proxy_path_for(video_id, itag, mime),
    )


def _iter_streams(yt: Any) -> Any:
    try:
        streams = getattr(yt, "streams", None)
        if streams is None:
            return iter([])
        return iter(streams)
    except TypeError:
        # `streams` isn't directly iterable but may be list-able. Reuse the
        # already-resolved value rather than re-accessing the (potentially
        # lazy, network-touching) property a second time.
        try:
            return iter(list(streams or []))
        except Exception:
            logger.debug("streams not iterable for %r; yielding none", yt, exc_info=True)
            return iter([])
    except Exception:
        # Catch pytubefix errors like LiveStreamError, MembersOnly, VideoUnavailable.
        # Log at debug so operators can diagnose pytubefix breakage without noise.
        logger.debug("stream enumeration failed; yielding none", exc_info=True)
        return iter([])


def _collect_search_hits(s: Any, limit: int) -> list[SearchHit]:
    """Collect up to `limit` SearchHits across pytubefix's video/channel/playlist results.

    Each pytubefix item is lazy — accessing .title / .author / etc. triggers a
    network call and can raise VideoUnavailable, MembersOnly, etc. We skip any
    item whose conversion raises so a single dead video doesn't 500 the whole search.
    """
    hits: list[SearchHit] = []
    for v in _safe_iter(getattr(s, "videos", None)):
        hit = _safe_call(_hit_from_pytube_video, v)
        if hit:
            hits.append(hit)
            if len(hits) >= limit:
                return hits
    for c in _safe_iter(getattr(s, "channels", None)):
        hit = _safe_call(_hit_from_pytube_channel, c)
        if hit:
            hits.append(hit)
            if len(hits) >= limit:
                return hits
    for p in _safe_iter(getattr(s, "playlists", None)):
        hit = _safe_call(_hit_from_pytube_playlist, p)
        if hit:
            hits.append(hit)
            if len(hits) >= limit:
                return hits
    return hits


def _safe_call(fn: Any, arg: Any) -> Any:
    """Call fn(arg); return None on ANY exception (including pytubefix unavailability errors)."""
    try:
        return fn(arg)
    except Exception:
        return None


def _safe_get(obj: Any, name: str, default: Any = None) -> Any:
    """Read obj.<name> defensively. Returns default if the attribute access raises
    (pytubefix's lazy properties can throw, not just be missing)."""
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _hit_from_pytube_video(v: Any) -> SearchHit:
    return SearchHit(
        kind="video",
        id=str(_safe_get(v, "video_id", "")),
        title=str(_safe_get(v, "title", "") or ""),
        author=_safe_str(_safe_get(v, "author", None)),
        thumbnail_url=str(_safe_get(v, "thumbnail_url", "") or ""),
        duration_seconds=_safe_int(_safe_get(v, "length", None)),
        is_live=_safe_bool(_safe_get(v, "is_live", None)),
    )


def _hit_from_pytube_channel(c: Any) -> SearchHit:
    return SearchHit(
        kind="channel",
        id=str(_safe_get(c, "channel_id", "") or ""),
        title=str(_safe_get(c, "channel_name", "") or ""),
        thumbnail_url=_safe_str(_safe_get(c, "thumbnail_url", None)) or "",
    )


def _hit_from_pytube_playlist(p: Any) -> SearchHit:
    return SearchHit(
        kind="playlist",
        id=str(_safe_get(p, "playlist_id", "") or ""),
        title=_safe_str(_safe_get(p, "title", None)) or "",
        author=_safe_str(_safe_get(p, "owner", None)),
        thumbnail_url="",
        video_count=_safe_int(_safe_get(p, "length", None)),
    )


def _normalise_channel(channel_id: str, ch: Any) -> ChannelInfo:
    # pytubefix doesn't reliably expose subscriber_count or thumbnail_url as
    # top-level attributes — they require digging into initial_data. We accept
    # the trade-off and leave them None / empty rather than maintaining a
    # parallel scraper. If you really need them, extract from ch.initial_data
    # at call time.
    return ChannelInfo(
        channel_id=str(getattr(ch, "channel_id", channel_id) or channel_id),
        title=str(getattr(ch, "channel_name", "") or ""),
        description=_safe_str(getattr(ch, "description", None)),
        subscriber_count=None,
        thumbnail_url=_extract_channel_thumbnail(ch) or "",
    )


def _extract_channel_thumbnail(ch: Any) -> str | None:
    """Best-effort extract the highest-resolution avatar from pytubefix initial_data."""
    try:
        data = getattr(ch, "initial_data", None) or {}
        header = (
            data.get("header", {}).get("c4TabbedHeaderRenderer")
            or data.get("header", {}).get("pageHeaderRenderer")
            or {}
        )
        thumbs = (header.get("avatar") or {}).get("thumbnails") or []
        if thumbs:
            return str(max(thumbs, key=lambda t: int(t.get("width", 0))).get("url", ""))
        meta_thumbs = (
            data.get("metadata", {}).get("channelMetadataRenderer", {}).get("avatar", {}).get(
                "thumbnails", []
            )
        )
        if meta_thumbs:
            return str(meta_thumbs[0].get("url", ""))
    except Exception:
        return None
    return None


def _normalise_playlist(playlist_id: str, pl: Any) -> PlaylistInfo:
    title = _safe_str(_safe_get(pl, "title")) or f"Playlist {playlist_id}"
    length = _safe_int(_safe_get(pl, "length")) or 0
    owner = _safe_str(_safe_get(pl, "owner"))

    items: list[PlaylistItem] = []
    for v in _safe_iter(_safe_get(pl, "videos")):
        item = _safe_call(_playlist_item_from_video, v)
        if item:
            items.append(item)

    return PlaylistInfo(
        playlist_id=playlist_id,
        title=title,
        author=owner,
        video_count=length or len(items),
        items=items,
    )


def _playlist_item_from_video(v: Any) -> PlaylistItem | None:
    """Convert a single pytubefix video to a PlaylistItem, or None if unusable."""
    vid = _safe_get(v, "video_id")
    if not vid:
        return None
    return PlaylistItem(
        video_id=str(vid),
        title=str(_safe_get(v, "title", "") or ""),
        author=_safe_str(_safe_get(v, "author")),
        duration_seconds=_safe_int(_safe_get(v, "length")),
        thumbnail_url=str(_safe_get(v, "thumbnail_url", "") or ""),
    )


# ---- Helpers -------------------------------------------------------------


def _safe_iter(obj: Any) -> Any:
    """Iterate obj if possible; otherwise return empty iterator. Swallows pytubefix errors."""
    if obj is None:
        return iter([])
    try:
        return iter(obj)
    except Exception:
        return iter([])


def _safe_str(v: Any) -> str | None:
    try:
        if v is None:
            return None
        return str(v)
    except Exception:
        return None


def _safe_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _safe_bool(v: Any) -> bool | None:
    if v is None:
        return None
    try:
        return bool(v)
    except Exception:
        return None


def _url_expire_epoch(url: str, *, now: float | None = None) -> float:
    """Return the URL's `expire=` epoch, or a far-future fallback if absent.

    Returning a far-future value (now + cache_max_ttl) on absence means the
    caller's `min(expire, now + cache_max_ttl)` clamps to our cache TTL —
    equivalent to "no explicit upstream constraint."
    """
    qs = urllib.parse.urlparse(url).query
    params = urllib.parse.parse_qs(qs)
    val = params.get("expire", [None])[0]
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


def _build_search_filters(*, category: str | None, live: bool) -> dict[str, Any] | None:
    """Construct the pytubefix `filters` dict + sentinels for the given options.

    Returns None when no filters are needed. The `_music_topic` sentinel
    key is read (and stripped) by `search()` before passing to pytubefix.
    """
    if _SearchFilter is None:
        return None
    if not category and not live:
        return None
    out: dict[str, Any] = {"type": _SearchFilter.get_type("Video")}
    if live:
        out.setdefault("features", []).append(_SearchFilter.get_features("Live"))
    if category == "music":
        out["_music_topic"] = True
    return out


# YouTube's "Music" topic ID; used to narrow search to category=music.
# This identifier is hard-coded into YouTube's UI and stable in practice,
# but it is NOT a public API contract. If YouTube changes the topic id,
# the music filter silently degrades to type=Video (see search()).
_MUSIC_TOPIC_ID = "/m/04rlf"


def _encode_music_topic_sp() -> str:
    """Encode a stand-alone `sp=` protobuf for the Music topic.

    Returns the encoded value, or "" on failure. Kept as a utility for
    isolated testing of the encoder; production code goes through
    `_inject_music_topic`, which merges the topic with any existing filters.
    """
    if _encode_protobuf is None:  # pragma: no cover — defensive import
        return ""
    try:
        combined = {2: {19: _MUSIC_TOPIC_ID}}
        return str(_encode_protobuf(str(combined)))
    except Exception:
        return ""


def _inject_music_topic(search_instance: Any, pytubefix_filters: dict[str, Any] | None) -> None:
    """Overwrite `search_instance.filter` with a protobuf that includes the music topic.

    Mirrors pytubefix's `Filter.get_filters_params` shape: everything goes under
    the root field `2`. We rebuild that nested dict from the same legacy filter
    inputs pytubefix accepts, then merge field 19 (topic). Sorted for determinism.

    On any failure (missing encoder, malformed input), leaves `s.filter` untouched
    so the search proceeds with whatever pytubefix already computed.
    """
    if _encode_protobuf is None:  # pragma: no cover — defensive import
        return
    try:
        inner: dict[int, Any] = {}
        if pytubefix_filters:
            for key in ("type", "duration", "upload_date"):
                value = pytubefix_filters.get(key)
                if value:
                    inner.update(value)
            for feature in pytubefix_filters.get("features", []) or []:
                inner.update(feature)
        inner[19] = _MUSIC_TOPIC_ID
        combined = {2: dict(sorted(inner.items()))}
        search_instance.filter = _encode_protobuf(str(combined))
    except Exception:
        return
