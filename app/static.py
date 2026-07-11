"""Mount the built frontend at / if dist exists."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"

_SPA_RESERVED_PREFIXES = ("api/", "proxy/", "health", "docs", "redoc", "openapi.json")

# Content-Security-Policy for the SPA shell (index.html only — /assets/*.js and
# .css are subresources governed by the document's CSP, not their own headers).
#
# style-src needs 'unsafe-inline': Svelte 5's compiled runtime writes reactive
# inline styles via element.style.cssText (e.g. the --progress custom property
# in Player.svelte / NowPlaying.svelte), which is dynamic per render and can't
# be hashed. There is no way to avoid this without patching Svelte's output.
#
# script-src's hash is the pre-paint theme-bootstrap <script> in
# frontend/index.html (the one that reads localStorage and sets data-theme
# before first paint). If that inline script's text changes, recompute the
# hash with:
#   python3 -c "
#   import hashlib, base64, re
#   html = open('frontend/dist/index.html').read()
#   s = re.search(r'<script>(.*?)</script>', html, re.S).group(1)
#   print('sha256-' + base64.b64encode(hashlib.sha256(s.encode()).digest()).decode())
#   "
# and update _CSP below. A stale hash fails silently (CSP violations don't
# throw — the bootstrap just won't run, defaulting to the 'glass' theme).
#
# img-src allows i.ytimg.com (video search-hit thumbnails, app/adapters/youtube.py
# _hit_from_pytube_video) and yt3.ggpht.com / yt3.googleusercontent.com (channel
# search-hit avatars, app/adapters/youtube.py _extract_channel_thumbnail — a
# DIFFERENT host than video thumbnails). data: is needed for the CSS grain-
# texture background-image (frontend/src/app.css / built CSS, --grain-image
# custom prop).
#
# style-src / font-src allow Google Fonts (frontend/index.html <link> tags —
# not self-hosted).
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'sha256-J03Yqg7SM1LzbD5cOpeyfBlUptzg3Vs99ztMW+Yavgs='; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data: https://i.ytimg.com "
    "https://yt3.ggpht.com https://yt3.googleusercontent.com; "
    "media-src 'self' blob:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)


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
        return FileResponse(
            FRONTEND_DIST / "index.html",
            headers={"Content-Security-Policy": _CSP},
        )
