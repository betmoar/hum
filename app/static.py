"""Mount the built frontend at / if dist exists."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

_SPA_RESERVED_PREFIXES = ("api/", "proxy/", "health", "docs", "redoc", "openapi.json")


def mount(app: FastAPI) -> None:
    if not FRONTEND_DIST.exists():
        return  # dev mode — frontend served by vite separately

    app.mount(
        "/assets",
        StaticFiles(directory=FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> FileResponse:
        if any(full_path.startswith(p) for p in _SPA_RESERVED_PREFIXES):
            raise HTTPException(status_code=404)
        return FileResponse(FRONTEND_DIST / "index.html")
