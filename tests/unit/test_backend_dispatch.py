"""Settings.yt_backend routes video()/search() to pytubefix or yt-dlp,
inside the same cache + single-flight wrappers (spike/ytdlp-backend)."""
from __future__ import annotations

import logging
from typing import Any

import pytest

from app.adapters import youtube
from app.adapters import youtube_ytdlp as ytdlp
from app.config import get_settings
from app.models import AudioFormat, SearchHit, VideoDetails


def _details(video_id: str) -> VideoDetails:
    return VideoDetails(
        video_id=video_id, title="T", author="A", channel_id="C", duration_seconds=10,
        thumbnail_url=f"/proxy/thumbnail/{video_id}",
        audio_formats=[AudioFormat(itag=140, mime_type='audio/mp4; codecs="mp4a.40.2"', bitrate=1,
                                   codec="aac", url=f"/proxy/audio/{video_id}?itag=140")],
    )


@pytest.fixture
def use_ytdlp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "yt_backend", "ytdlp")


def test_default_backend_is_pytubefix() -> None:
    assert get_settings().yt_backend == "pytubefix"


async def test_video_routes_to_ytdlp_and_caches(use_ytdlp: None, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_fetch(video_id: str) -> VideoDetails:
        calls.append(video_id)
        return _details(video_id)

    monkeypatch.setattr(ytdlp, "fetch_video", fake_fetch)
    monkeypatch.setattr(youtube, "_make_youtube", lambda vid: pytest.fail("pytubefix used"))
    d1 = await youtube.video("abc12345678")
    d2 = await youtube.video("abc12345678")
    assert d1.title == d2.title == "T"
    assert calls == ["abc12345678"]  # second call served from the metadata cache


async def test_stream_refresh_routes_to_ytdlp(use_ytdlp: None, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch(video_id: str) -> VideoDetails:
        youtube._stream_url_cache[(video_id, 140)] = ("https://rr.googlevideo.com/x", 9e12)
        return _details(video_id)

    monkeypatch.setattr(ytdlp, "fetch_video", fake_fetch)
    assert await youtube.resolve_upstream_url("abc12345678", 140) == "https://rr.googlevideo.com/x"


async def test_video_uses_pytubefix_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ytdlp, "fetch_video", lambda vid: pytest.fail("yt-dlp used"))
    monkeypatch.setattr(youtube, "_fetch_video", lambda vid: _details(vid))
    assert (await youtube.video("abc12345678")).title == "T"


@pytest.mark.parametrize(
    ("category", "live", "sp"),
    [(None, False, None), ("music", False, "Eg0IAZoBCC9tLzA0cmxm"), (None, True, "EgQIAUAB")],
)
async def test_search_routes_to_ytdlp_with_sp(
    use_ytdlp: None, monkeypatch: pytest.MonkeyPatch, category: str | None, live: bool, sp: str | None
) -> None:
    seen: list[tuple[str, int, str | None]] = []

    def fake_search(query: str, limit: int, sp_: str | None) -> list[SearchHit]:
        seen.append((query, limit, sp_))
        return [SearchHit(kind="video", id="v1", title="Hit", thumbnail_url="")]

    monkeypatch.setattr(ytdlp, "search_hits", fake_search)
    monkeypatch.setattr(youtube, "_make_search", lambda *a, **k: pytest.fail("pytubefix used"))
    hits = await youtube.search("q", 7, category=category, live=live)
    again = await youtube.search("q", 7, category=category, live=live)
    assert [h.title for h in hits] == [h.title for h in again] == ["Hit"]
    assert seen == [("q", 7, sp)]  # cached after the first call


def test_requirement_check_warns_without_deno(
    use_ytdlp: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(youtube.shutil, "which", lambda name: None)
    with caplog.at_level(logging.ERROR):
        youtube.check_backend_requirements()
    assert any("deno" in r.getMessage() for r in caplog.records if r.levelno == logging.ERROR)


def test_requirement_check_quiet_with_deno_or_pytubefix(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(youtube.shutil, "which", lambda name: None)
    with caplog.at_level(logging.ERROR):
        youtube.check_backend_requirements()  # default backend: no requirement
    monkeypatch.setattr(get_settings(), "yt_backend", "ytdlp")
    monkeypatch.setattr(youtube.shutil, "which", lambda name: "/usr/bin/deno")
    with caplog.at_level(logging.ERROR):
        youtube.check_backend_requirements()
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_lifespan_runs_requirement_check(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    ran: list[Any] = []
    monkeypatch.setattr(youtube, "check_backend_requirements", lambda: ran.append(True))
    with TestClient(create_app()):
        pass
    assert ran == [True]
