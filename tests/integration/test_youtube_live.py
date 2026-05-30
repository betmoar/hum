"""Live tests against real YouTube via the adapter.

Run with: pytest -m integration

Skipped by default; the unit suite uses mocks for normal CI runs.
"""
from __future__ import annotations

import pytest

from app.adapters import youtube

pytestmark = pytest.mark.integration


async def test_search_live() -> None:
    hits = await youtube.search("rick astley never gonna give you up", limit=5)
    assert hits, "expected at least one search hit"
    assert any(h.kind == "video" for h in hits)


async def test_video_live() -> None:
    v = await youtube.video("dQw4w9WgXcQ")
    assert v.duration_seconds > 0
    assert v.title
    assert v.audio_formats, "expected audio formats"
    assert v.video_formats, "expected video formats"
    # Spot-check itag presence — 140 (aac 128k) or 251 (opus 160k) are common.
    audio_itags = {a.itag for a in v.audio_formats}
    assert audio_itags & {140, 251}, f"expected itag 140 or 251 in {audio_itags}"


async def test_resolve_upstream_url_live() -> None:
    v = await youtube.video("dQw4w9WgXcQ")
    itag = v.audio_formats[0].itag
    url = await youtube.resolve_upstream_url("dQw4w9WgXcQ", itag)
    assert url.startswith("https://"), f"expected https URL, got {url[:80]}"
    assert "googlevideo.com" in url


async def test_channel_live() -> None:
    info = await youtube.channel("UCuAXFkgsw1L7xaCfnd5JJOw")
    assert info.title  # "Rick Astley" or similar
    assert info.channel_id
