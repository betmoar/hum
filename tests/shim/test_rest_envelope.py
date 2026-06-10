"""Phase 0/1 exit tests: envelope correctness for ping/getLicense and auth.

Subsonic errors travel inside HTTP 200 envelopes — these tests pin that down.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_ping_ok_envelope(shim_client: TestClient, subsonic_auth: dict[str, str]) -> None:
    r = shim_client.get("/rest/ping", params=subsonic_auth)
    assert r.status_code == 200
    body = r.json()["subsonic-response"]
    assert body["status"] == "ok"
    assert body["version"] == "1.16.1"
    assert body["type"] == "hum-subsonic-shim"


def test_ping_view_suffix(shim_client: TestClient, subsonic_auth: dict[str, str]) -> None:
    r = shim_client.get("/rest/ping.view", params=subsonic_auth)
    assert r.status_code == 200
    assert r.json()["subsonic-response"]["status"] == "ok"


def test_ping_wrong_token_fails_in_envelope(
    shim_client: TestClient, subsonic_auth: dict[str, str]
) -> None:
    r = shim_client.get("/rest/ping", params={**subsonic_auth, "t": "0" * 32})
    assert r.status_code == 200  # protocol errors are not HTTP errors
    body = r.json()["subsonic-response"]
    assert body["status"] == "failed"
    assert body["error"]["code"] == 40


def test_ping_missing_user(shim_client: TestClient) -> None:
    r = shim_client.get("/rest/ping", params={"f": "json"})
    body = r.json()["subsonic-response"]
    assert body["status"] == "failed"
    assert body["error"]["code"] == 10


def test_get_license(shim_client: TestClient, subsonic_auth: dict[str, str]) -> None:
    r = shim_client.get("/rest/getLicense", params=subsonic_auth)
    body = r.json()["subsonic-response"]
    assert body["status"] == "ok"
    assert body["license"]["valid"] is True


def test_health_is_unauthenticated(shim_client: TestClient) -> None:
    r = shim_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "healthy"}


def test_root_is_not_404(shim_client: TestClient) -> None:
    # Amperfy's Auto-Detect probes GET / before /rest/; a 404 aborts it.
    r = shim_client.get("/")
    assert r.status_code == 200
    assert r.json()["api"] == "/rest"
