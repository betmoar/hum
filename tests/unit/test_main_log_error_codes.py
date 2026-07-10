"""Error codes must land in the hum.access log line without changing the
response status code or JSON body clients receive (see CLAUDE.md: global
exception handlers MUST map upstream failures to 4xx/5xx JSON).

Uses routes whose adapter errors are NOT caught locally (api/channel, which
has no try/except of its own) so the exception actually reaches the global
handlers in app/main.py that this change instruments. Routes like
/api/video and /api/live catch YouTubeError themselves and build their own
JSONResponse, never touching these handlers."""
from __future__ import annotations

import logging

from fastapi.testclient import TestClient


def test_youtube_error_code_in_access_log(monkeypatch, bearer_token, caplog):
    from app.adapters import youtube as adapter

    async def fake_channel(channel_id: str) -> None:
        raise adapter.YouTubeError(503, "YOUTUBE_BLOCKED", "blocked")

    monkeypatch.setattr(adapter, "channel", fake_channel)
    from app.main import app
    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="hum.access"):
        r = client.get(
            "/api/channel/UC1234567890abcdefghij",
            headers={"Authorization": "Bearer test-bearer-token"},
        )

    # Response contract: unchanged status code and body.
    assert r.status_code == 503
    assert r.json() == {"error": "YOUTUBE_BLOCKED", "message": "blocked"}

    access_records = [rec for rec in caplog.records if rec.name == "hum.access"]
    assert len(access_records) == 1
    line = access_records[0].getMessage()
    assert "-> 503" in line
    assert "code=YOUTUBE_BLOCKED" in line


def test_upstream_host_error_code_in_access_log(monkeypatch, bearer_token, caplog):
    from app.adapters import youtube as adapter
    from app.adapters.upstream_http import UpstreamHostError

    async def fake_channel(channel_id: str) -> None:
        raise UpstreamHostError("host not allowed")

    monkeypatch.setattr(adapter, "channel", fake_channel)
    from app.main import app
    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="hum.access"):
        r = client.get(
            "/api/channel/UC1234567890abcdefghij",
            headers={"Authorization": "Bearer test-bearer-token"},
        )

    assert r.status_code == 502
    assert r.json() == {"error": "UPSTREAM_HOST_BLOCKED", "message": "host not allowed"}

    access_records = [rec for rec in caplog.records if rec.name == "hum.access"]
    assert len(access_records) == 1
    assert "code=UPSTREAM_HOST_BLOCKED" in access_records[0].getMessage()


def test_api_video_local_catch_emits_code_in_access_log(monkeypatch, bearer_token, caplog):
    """The headline case: /api/video catches YouTubeError LOCALLY (never reaches
    app/main.py's global handler), yet the mapped code must still land in the
    hum.access line so `docker logs | grep YOUTUBE_BLOCKED` finds the route most
    likely to fail. Response body/status stay unchanged."""
    from app.adapters import youtube as adapter

    async def fake_video(video_id: str) -> None:
        raise adapter.YouTubeError(503, "YOUTUBE_BLOCKED", "blocked")

    monkeypatch.setattr(adapter, "video", fake_video)
    from app.main import app
    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="hum.access"):
        r = client.get(
            "/api/video/abc12345678",
            headers={"Authorization": "Bearer test-bearer-token"},
        )

    assert r.status_code == 503
    assert r.json() == {"error": "YOUTUBE_BLOCKED", "message": "blocked"}

    access_records = [rec for rec in caplog.records if rec.name == "hum.access"]
    assert len(access_records) == 1
    line = access_records[0].getMessage()
    assert "-> 503" in line
    assert "code=YOUTUBE_BLOCKED" in line


def test_api_hls_local_error_helper_emits_code_in_access_log(
    monkeypatch, signing_key_hex, caplog
):
    """hls.py's local UpstreamStatusError catch returns via its own _error()
    helper (never the global handler). The code must still reach the log line."""
    import time

    from app.adapters import upstream_http
    from app.adapters import youtube as adapter
    from app.adapters.upstream_http import UpstreamStatusError
    from app.auth import sign_url

    async def fake_resolve(video_id: str, itag: int) -> str:
        return "https://rr1---sn-test.googlevideo.com/videoplayback?id=" + video_id

    async def fake_fetch_range(url: str, *, start: int, end: int) -> bytes:
        raise UpstreamStatusError(502)

    monkeypatch.setattr(adapter, "resolve_upstream_url", fake_resolve)
    monkeypatch.setattr(upstream_http, "fetch_range", fake_fetch_range)
    from app.main import app
    client = TestClient(app)

    key = bytes.fromhex(signing_key_hex)
    exp = int(time.time()) + 60
    path = "/api/hls/abc12345678.m3u8"
    sig = sign_url(path, itag=140, exp=exp, key=key)

    with caplog.at_level(logging.INFO, logger="hum.access"):
        r = client.get(f"{path}?itag=140&exp={exp}&sig={sig}")

    assert r.status_code == 502
    assert r.json() == {"error": "UPSTREAM_ERROR", "message": "upstream returned 502"}
    access_records = [rec for rec in caplog.records if rec.name == "hum.access"]
    assert len(access_records) == 1
    assert "code=UPSTREAM_ERROR" in access_records[0].getMessage()


def test_success_response_has_no_code_suffix(caplog):
    """Happy-path requests keep the original log line shape (no code= suffix)."""
    from app.main import app
    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger="hum.access"):
        r = client.get("/health")

    assert r.status_code == 200
    access_records = [rec for rec in caplog.records if rec.name == "hum.access"]
    assert len(access_records) == 1
    line = access_records[0].getMessage()
    assert "-> 200" in line
    assert "code=" not in line
