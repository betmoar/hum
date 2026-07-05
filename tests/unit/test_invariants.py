"""Architecture invariants, enforced as tests.

These lock in the three load-bearing rules from ARCHITECTURE.md plus the auth
posture of the route table. If one of these fails you are probably about to
break the design, not the test. Read docs/PLAYBOOKS.md before changing them.

Invariant 1: pytubefix is imported in exactly one file (app/adapters/youtube.py).
Invariant 2: exactly one httpx.AsyncClient is constructed (app/adapters/upstream_http.py).
Invariant 3: every route is protected — /api/* by bearer or signature, /proxy/*
             by signature — and URLs the adapter hands out are always relative
             proxy paths, never raw YouTube CDN URLs.
"""
from __future__ import annotations

import ast
from pathlib import Path

from fastapi.routing import APIRoute

APP_DIR = Path(__file__).resolve().parents[2] / "app"

# Routes that are deliberately public. Grow this list only with a review of
# what the route exposes (see docs/PLAYBOOKS.md, "Adding an endpoint").
_PUBLIC_PATHS = {"/health", "/{full_path:path}"}


def _py_files() -> list[Path]:
    return sorted(APP_DIR.rglob("*.py"))


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    return mods


def test_invariant_1_pytubefix_only_in_the_adapter() -> None:
    offenders = [
        str(p.relative_to(APP_DIR))
        for p in _py_files()
        if "pytubefix" in _imports_of(p) and p.name != "youtube.py"
    ]
    assert not offenders, (
        f"pytubefix imported outside app/adapters/youtube.py: {offenders}. "
        "All YouTube access goes through the adapter so pytubefix breakage "
        "stays a one-file fix."
    )


def test_invariant_2_single_httpx_client_construction() -> None:
    offenders: list[str] = []
    for p in _py_files():
        if p.name == "upstream_http.py":
            continue
        tree = ast.parse(p.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "AsyncClient"
            ):
                offenders.append(f"{p.relative_to(APP_DIR)}:{node.lineno}")
    assert not offenders, (
        f"httpx.AsyncClient constructed outside upstream_http.py: {offenders}. "
        "One shared client = one connection pool, one timeout policy, one "
        "host allowlist. Use upstream_http.open_stream/fetch_text/fetch_range."
    )


def test_invariant_3_every_route_is_authed_or_signed() -> None:
    from app.main import app

    unprotected: list[str] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path in _PUBLIC_PATHS:
            continue
        has_bearer = any(
            getattr(d.call, "__name__", "") == "require_bearer"
            for d in route.dependant.dependencies
        )
        has_sig = any(p.name == "sig" for p in route.dependant.query_params)
        if not (has_bearer or has_sig):
            unprotected.append(route.path)
    assert not unprotected, (
        f"routes with neither bearer auth nor a signature param: {unprotected}. "
        "Every /api/* route needs Depends(require_bearer) or signed-URL "
        "verification; every /proxy/* route needs a sig query param."
    )


def test_invariant_3_adapter_never_hands_out_cdn_urls() -> None:
    """The URLs embedded in VideoDetails must be relative proxy paths. A raw
    googlevideo URL here would bypass signing entirely."""
    from app.adapters.youtube import _proxy_path_for

    for mime in ("audio/mp4", "audio/webm", "video/mp4"):
        path = _proxy_path_for("dQw4w9WgXcQ", 140, mime)
        assert path.startswith("/proxy/"), path
        assert "googlevideo" not in path
