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
