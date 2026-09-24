"""Scrubbing in scripts/capture_ytdlp_fixtures.py (fixtures get committed)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "capture_ytdlp_fixtures.py"
_spec = importlib.util.spec_from_file_location("capture_ytdlp_fixtures", _PATH)
assert _spec and _spec.loader
cap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cap)

_MASTER = (
    "https://manifest.googlevideo.com/api/manifest/hls_variant/expire/1790273790/ei/x"
    "/ip/203.0.113.9/id/abc.7/source/yt_live_broadcast/sig/SECRET/file/index.m3u8"
)


def test_scrub_keeps_live_master_as_hls_manifest() -> None:
    info = {"id": "abc", "live_status": "is_live", "formats": [{
        "format_id": "233", "protocol": "m3u8_native", "url": _MASTER + "?x=1", "manifest_url": _MASTER,
    }]}
    f = cap.scrub_video_info(info)["formats"][0]
    assert f["manifest_url"].startswith("https://manifest.googlevideo.com/api/manifest/hls_variant/")
    assert f["manifest_url"].endswith(".m3u8") and "/expire/4102444800/" in f["manifest_url"]
    assert "203.0.113.9" not in str(f) and "SECRET" not in str(f)


def test_scrub_replaces_signed_videoplayback_urls() -> None:
    info = {"id": "abc", "formats": [{
        "format_id": "140", "protocol": "https",
        "url": "https://rr3---sn-x.googlevideo.com/videoplayback?expire=1790000000&ip=203.0.113.9&sig=S&itag=140",
    }]}
    url = cap.scrub_video_info(info)["formats"][0]["url"]
    assert url == "https://rr1---sn.googlevideo.com/videoplayback?itag=140&expire=4102444800"
