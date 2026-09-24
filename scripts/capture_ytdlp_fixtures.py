"""Capture scrubbed yt-dlp responses into tests/fixtures/ytdlp/.

Needs network access to YouTube and deno on PATH. Never run in CI.

    uv run python scripts/capture_ytdlp_fixtures.py

Signed, IP-bound CDN URLs are replaced by placeholders keeping only itag +
expire (what the adapter reads), so the output is safe to commit. The unit
tests in tests/unit/test_youtube_adapter.py load these files when present.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "ytdlp"

# Ids verified 2026-09-24. The live id must be broadcasting at capture time.
VOD_ID = "dQw4w9WgXcQ"
LIVE_ID = "4xDzrJKXOOY"
SEARCH_QUERY = "rick astley never gonna give you up"

_GV_URL = re.compile(r"https?://[^\"'\s]*googlevideo\.com[^\"'\s]*")
_VIDEO_KEYS = (
    "id", "title", "channel", "uploader", "channel_id", "duration", "view_count",
    "live_status", "description",
)
_FORMAT_KEYS = (
    "format_id", "ext", "protocol", "vcodec", "acodec", "abr", "tbr", "asr",
    "audio_channels", "width", "height", "fps", "url", "manifest_url",
)
_ENTRY_KEYS = (
    "_type", "ie_key", "id", "title", "channel", "uploader", "duration",
    "live_status", "url", "thumbnails", "playlist_count",
)


# Fixed far-future expiry: a real one would make fixture-based tests fail
# hours after capture (the adapter drops expired live master URLs).
_FIXTURE_EXPIRE = "4102444800"  # 2100-01-01


def _scrub_url(url: str, format_id: str) -> str:
    expire = _FIXTURE_EXPIRE
    if urllib.parse.urlparse(url).hostname == "manifest.googlevideo.com":
        # Live HLS master: keep the manifest shape the adapter relies on
        # (host, path-style /expire/, .m3u8), drop ip/sig/ids.
        return (f"https://manifest.googlevideo.com/api/manifest/hls_variant/expire/{expire}"
                f"/itag/{format_id}/file/index.m3u8")
    return f"https://rr1---sn.googlevideo.com/videoplayback?itag={format_id}&expire={expire}"


def _assert_clean(out: dict[str, Any]) -> None:
    for leftover in _GV_URL.findall(json.dumps(out)):
        if re.search(r"[?&/](ip|sig|lsig|signature|n)[=/]", leftover):
            raise ValueError("scrub left a signed URL behind")


def scrub_video_info(info: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {k: info[k] for k in _VIDEO_KEYS if k in info}
    if isinstance(out.get("description"), str):
        out["description"] = out["description"][:200]
    formats = []
    for f in info.get("formats") or []:
        g = {k: f[k] for k in _FORMAT_KEYS if k in f}
        fid = str(g.get("format_id", ""))
        for key in ("url", "manifest_url"):
            if isinstance(g.get(key), str) and "googlevideo.com" in g[key]:
                g[key] = _scrub_url(g[key], fid)
        formats.append(g)
    out["formats"] = formats
    _assert_clean(out)
    return out


def scrub_listing_info(info: dict[str, Any]) -> dict[str, Any]:
    """Search / channel / playlist flat listings: top-level metadata + entries."""
    top_keys = ("_type", "id", "title", "channel", "uploader", "channel_id", "description",
                "channel_follower_count", "playlist_count")
    out: dict[str, Any] = {k: info[k] for k in top_keys if k in info}
    if isinstance(out.get("description"), str):
        out["description"] = out["description"][:200]
    thumbs = [t for t in info.get("thumbnails") or [] if isinstance(t, dict)]
    if thumbs:
        out["thumbnails"] = [{k: t[k] for k in ("id", "url", "width") if k in t} for t in thumbs]
    entries = []
    for e in info.get("entries") or []:
        if not isinstance(e, dict):
            continue
        g = {k: e[k] for k in _ENTRY_KEYS if k in e}
        if isinstance(g.get("thumbnails"), list) and g["thumbnails"]:
            g["thumbnails"] = [g["thumbnails"][-1]]
        entries.append(g)
    out["entries"] = entries
    _assert_clean(out)
    return out


def main() -> int:
    from app.adapters import youtube

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    flat = {"extract_flat": "in_playlist", "playlistend": 20}
    jobs: list[tuple[str, str, dict[str, Any], Any]] = [
        ("video_vod.json", f"https://www.youtube.com/watch?v={VOD_ID}", {}, scrub_video_info),
        ("video_live.json", f"https://www.youtube.com/watch?v={LIVE_ID}", {}, scrub_video_info),
        ("search_flat.json",
         "https://www.youtube.com/results?"
         + urllib.parse.urlencode({"search_query": SEARCH_QUERY}),
         flat, scrub_listing_info),
    ]
    for name, url, extra, scrub in jobs:
        info = youtube._extract(url, extra)
        text = json.dumps(scrub(info), indent=1, ensure_ascii=False) + "\n"
        (FIXTURE_DIR / name).write_text(text)
        print(f"wrote {FIXTURE_DIR / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
