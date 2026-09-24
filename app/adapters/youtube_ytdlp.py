"""yt-dlp backend for video() and search() — SPIKE (see docs/dev ytdlp spike).

The only module allowed to import yt_dlp (enforced in test_invariants.py).
Selected by Settings.yt_backend == "ytdlp"; app.adapters.youtube dispatches
here from inside its existing cache + single-flight wrappers, so caching,
refresh and error behaviour around these calls is identical to pytubefix's.

Everything this returns has the same shape the pytubefix path produces:
signed-later proxy paths for formats, the /api/live route for live, and the
same (video_id, itag) -> (url, expiry) stream-cache writes. Raw CDN URLs
never leave this module except into that server-side cache (invariant 3).

Requires a JavaScript runtime for YouTube (deno by default); see
app.main's startup check.
"""
from __future__ import annotations

import logging
import time
import urllib.parse
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from app.adapters.youtube import (
    _CACHE_MAX_TTL,
    LiveStreamInfo,
    YouTubeError,
    _extract_codec,
    _live_video_details,
    _proxy_path_for,
    _stream_url_cache,
    _url_expire_epoch,
)
from app.models import AudioFormat, SearchHit, VideoDetails, VideoFormat

logger = logging.getLogger(__name__)

class _YdlLogger:
    """Route yt-dlp's own output into Hum's logging. Without a logger it
    prints ERROR lines to stderr even with quiet=True; the actual failure is
    already surfaced as a mapped YouTubeError, so these are debug detail."""

    def debug(self, msg: str) -> None:
        logger.debug("yt-dlp: %s", msg)

    def info(self, msg: str) -> None:
        logger.debug("yt-dlp: %s", msg)

    def warning(self, msg: str) -> None:
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

# Substrings of yt-dlp error messages, checked in order. yt-dlp errors are
# strings, not a class hierarchy like pytubefix's, so this is the mapping.
_BLOCKED_MARKERS = (
    "sign in to confirm", "po token", "not a bot", "confirm your age", "age-restricted",
)
_UNAVAILABLE_MARKERS = (
    "video unavailable", "video is unavailable", "private video", "has been removed", "is not available",
    "account associated with this video has been terminated",
)

_AUDIO_MIME = {"m4a": "audio/mp4", "mp4": "audio/mp4", "webm": "audio/webm"}
_VIDEO_MIME = {"mp4": "video/mp4", "webm": "video/webm"}


def _make_ydl(opts: dict[str, Any]) -> Any:
    """Factory seam for tests. A YoutubeDL instance is not thread-safe, so
    every call builds its own (these run in asyncio.to_thread workers)."""
    return yt_dlp.YoutubeDL(opts)


def _map_error(e: BaseException) -> YouTubeError:
    msg = str(e)
    low = msg.lower()
    if any(m in low for m in _BLOCKED_MARKERS):
        return YouTubeError(503, "YOUTUBE_BLOCKED", f"YouTube is blocking requests (yt-dlp: {msg})")
    if any(m in low for m in _UNAVAILABLE_MARKERS):
        return YouTubeError(404, "VIDEO_UNAVAILABLE", f"video unavailable (yt-dlp: {msg})")
    return YouTubeError(502, "UPSTREAM_FAILURE", f"yt-dlp failed ({type(e).__name__}: {msg})")


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


# ---- video ----------------------------------------------------------------


def fetch_video(video_id: str) -> VideoDetails:
    """Thread-bound (call via asyncio.to_thread). Writes the stream cache."""
    info = _extract(f"https://www.youtube.com/watch?v={video_id}", {})
    if info.get("live_status") == "is_live":
        # The client only ever gets the /api/live route; the master URL is
        # resolved server-side by youtube.resolve_live_master_url (pytubefix
        # in this spike — out of scope to move).
        return _live_video_details(video_id, LiveStreamInfo(
            video_id=video_id,
            title=str(info.get("title") or ""),
            author=_author(info) or "",
            channel_id=str(info.get("channel_id") or ""),
            thumbnail_url=f"/proxy/thumbnail/{video_id}",
            master_hls_url="",
        ))

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
        # Same cache contract as youtube._cache_stream: trust `expire=`, clamp to 1 h.
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


# ---- search ---------------------------------------------------------------


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
        return SearchHit(
            kind="playlist", id=eid, title=title, author=_author(entry),
            thumbnail_url=_thumb(entry) or "", video_count=_int(entry.get("playlist_count")),
        )
    if "/channel/" in url or "/@" in url:
        return SearchHit(kind="channel", id=eid, title=title, thumbnail_url=_thumb(entry) or "")
    return None


def search_hits(query: str, limit: int, sp: str | None) -> list[SearchHit]:
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
        if hit is not None:
            hits.append(hit)
            if len(hits) >= limit:
                break
    return hits
