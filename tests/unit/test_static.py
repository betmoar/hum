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


def test_spa_response_has_csp_header(app_with_dist: Any) -> None:
    client = TestClient(app_with_dist)
    r = client.get("/")
    assert r.status_code == 200
    csp = r.headers.get("content-security-policy")
    assert csp is not None
    assert "default-src 'self'" in csp
    assert "img-src" in csp and "i.ytimg.com" in csp
    assert "media-src" in csp and "blob:" in csp


def test_spa_fallback_route_also_has_csp_header(app_with_dist: Any) -> None:
    client = TestClient(app_with_dist)
    r = client.get("/queue")
    assert r.status_code == 200
    assert r.headers.get("content-security-policy") is not None


def test_api_route_has_no_spa_csp_header(app_with_dist: Any) -> None:
    """API/proxy JSON responses must not carry the SPA's CSP — a different
    origin/response-type contract; asserting its absence here guards against
    someone "helpfully" moving the header into global middleware later.
    """
    client = TestClient(app_with_dist)
    r = client.get("/health")
    assert r.status_code == 200
    assert "content-security-policy" not in {k.lower() for k in r.headers}


def test_csp_script_src_hash_matches_built_inline_script() -> None:
    """The CSP pins the sha256 of the pre-paint theme-bootstrap <script> in
    frontend/index.html (Vite copies it verbatim into dist). A stale hash
    fails silently — CSP violations don't throw, the bootstrap just doesn't
    run and the page falls back to the 'glass' theme. This test recomputes the
    hash from the committed source so any edit to that inline script forces a
    matching _CSP update, with no build step required (frontend/dist is
    gitignored, so the test reads the durable source).
    """
    import base64
    import hashlib
    import re

    from app import static as static_mod

    # static_mod.__file__ is app/static.py -> parent=app/ -> parent=repo root.
    source_index = (
        Path(static_mod.__file__).resolve().parent.parent / "frontend" / "index.html"
    )
    html = source_index.read_text()
    match = re.search(r"<script>(.*?)</script>", html, re.S)
    assert match, "expected an inline <script> (theme bootstrap) in frontend/index.html"

    digest = "sha256-" + base64.b64encode(hashlib.sha256(match.group(1).encode()).digest()).decode()
    assert f"'{digest}'" in static_mod._CSP, (
        f"CSP script-src hash is stale: the inline <script> in {source_index} "
        f"hashes to {digest!r}, which is not in _CSP. Recompute and update "
        f"app/static.py:_CSP (see the recompute recipe in its comment)."
    )

