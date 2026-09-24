"""Run every integration test once per YouTube backend (spike/ytdlp-backend).

`test_video_endpoint_to_audio_first_chunk[ytdlp]` is the important one: it
proves yt-dlp's CDN URLs actually stream through /proxy/audio with our
upstream client (yt-dlp URLs can be tied to the client that fetched them).
"""
from __future__ import annotations

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True, params=["pytubefix", "ytdlp"])
def yt_backend(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    backend = str(request.param)
    monkeypatch.setattr(get_settings(), "yt_backend", backend)
    return backend
