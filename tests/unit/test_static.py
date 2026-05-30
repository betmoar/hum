"""Tests for the SPA static-file mount."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Build a fake frontend/dist tree and re-import the app."""
    dist = tmp_path / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><html><body>STUB</body></html>")
    (dist / "assets" / "app.js").write_text("// js")

    from app import static as static_mod

    monkeypatch.setattr(static_mod, "FRONTEND_DIST", dist)

    from importlib import reload

    from app import main as main_mod

    reload(main_mod)
    yield main_mod.app


def test_root_returns_index_html(app_with_dist: Any) -> None:
    client = TestClient(app_with_dist)
    r = client.get("/")
    assert r.status_code == 200
    assert "STUB" in r.text


def test_arbitrary_path_returns_index_html_for_spa(app_with_dist: Any) -> None:
    client = TestClient(app_with_dist)
    r = client.get("/queue")
    assert r.status_code == 200
    assert "STUB" in r.text


def test_assets_served_directly(app_with_dist: Any) -> None:
    client = TestClient(app_with_dist)
    r = client.get("/assets/app.js")
    assert r.status_code == 200
    assert "// js" in r.text


def test_health_route_unaffected(app_with_dist: Any) -> None:
    client = TestClient(app_with_dist)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "healthy"}
