"""Tests for the evict-and-retry-once behaviour on upstream 403/410
(backlog item cache-evict-403). Exercised through /proxy/audio; the same
code path in app/proxy/_common.py backs /proxy/stream."""
from __future__ import annotations

import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth import sign_url


def _signed_url(path: str, itag: int, signing_key_hex: str, ttl: int = 60) -> str:
    key = bytes.fromhex(signing_key_hex)
    exp = int(time.time()) + ttl
    sig = sign_url(path, itag=itag, exp=exp, key=key)
    return f"{path}?itag={itag}&exp={exp}&sig={sig}"


def _resp(status: int, body: bytes) -> httpx.Response:
    request = httpx.Request("GET", "https://rr1---sn-test.googlevideo.com/videoplayback")
    return httpx.Response(status, headers={"Content-Type": "audio/mp4"}, content=body, request=request)


@pytest.fixture
def wired_client(monkeypatch: pytest.MonkeyPatch):
    from app.adapters import upstream_http
    from app.adapters import youtube as adapter

    calls = {"resolve": 0, "open": 0, "evict": [], "open_responses": [200]}

    async def fake_resolve(video_id: str, itag: int) -> str:
        calls["resolve"] += 1
        return f"https://rr1---sn-test.googlevideo.com/videoplayback?attempt={calls['resolve']}"

    async def fake_open_stream(url: str, *, headers: dict[str, str]) -> httpx.Response:
        idx = calls["open"]
        calls["open"] += 1
        statuses = calls["open_responses"]
        status = statuses[min(idx, len(statuses) - 1)]
        body = b"ok-bytes" if status == 200 else b"denied"
        return _resp(status, body)

    def fake_evict(video_id: str, itag: int) -> None:
        calls["evict"].append((video_id, itag))

    monkeypatch.setattr(adapter, "resolve_upstream_url", fake_resolve)
    monkeypatch.setattr(adapter, "evict_stream_url", fake_evict)
    monkeypatch.setattr(upstream_http, "open_stream", fake_open_stream)

    from app.main import app
    return TestClient(app), calls


def test_403_then_200_evicts_and_retries_once(wired_client, signing_key_hex: str) -> None:
    client, calls = wired_client
    calls["open_responses"] = [403, 200]
    url = _signed_url("/proxy/audio/dQw4w9WgXcQ", 140, signing_key_hex)

    r = client.get(url)

    assert r.status_code == 200
    assert r.content == b"ok-bytes"
    assert calls["open"] == 2
    assert calls["resolve"] == 2
    assert calls["evict"] == [("dQw4w9WgXcQ", 140)]


def test_410_then_200_evicts_and_retries_once(wired_client, signing_key_hex: str) -> None:
    client, calls = wired_client
    calls["open_responses"] = [410, 200]
    url = _signed_url("/proxy/audio/dQw4w9WgXcQ", 140, signing_key_hex)

    r = client.get(url)

    assert r.status_code == 200
    assert calls["evict"] == [("dQw4w9WgXcQ", 140)]


def test_persistent_403_retries_exactly_once_then_streams_error(
    wired_client, signing_key_hex: str
) -> None:
    client, calls = wired_client
    calls["open_responses"] = [403, 403]
    url = _signed_url("/proxy/audio/dQw4w9WgXcQ", 140, signing_key_hex)

    r = client.get(url)

    assert r.status_code == 403
    assert calls["open"] == 2  # bounded — no third attempt
    assert calls["evict"] == [("dQw4w9WgXcQ", 140)]


def test_non_retriable_status_does_not_retry(wired_client, signing_key_hex: str) -> None:
    client, calls = wired_client
    calls["open_responses"] = [500]
    url = _signed_url("/proxy/audio/dQw4w9WgXcQ", 140, signing_key_hex)

    r = client.get(url)

    assert r.status_code == 500
    assert calls["open"] == 1
    assert calls["evict"] == []


def test_success_first_try_does_not_evict(wired_client, signing_key_hex: str) -> None:
    client, calls = wired_client
    calls["open_responses"] = [200]
    url = _signed_url("/proxy/audio/dQw4w9WgXcQ", 140, signing_key_hex)

    r = client.get(url)

    assert r.status_code == 200
    assert calls["open"] == 1
    assert calls["evict"] == []
