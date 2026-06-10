"""Hum FastAPI application entry point."""
from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.adapters import upstream_http
from app.api import channel, hls, live, playlist, radio, search, video
from app.config import get_settings
from app.proxy import audio, live_segment, thumbnail
from app.proxy import video as proxy_video

# ----- Logging --------------------------------------------------------------


def _configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    if settings.log_json:
        fmt = '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
    else:
        fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    logging.basicConfig(level=level, format=fmt)


# ----- Errors ---------------------------------------------------------------


class HumError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message


# ----- App ------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    _configure_logging()
    logging.getLogger("hum").info("starting up")
    yield
    await upstream_http.close()
    logging.getLogger("hum").info("shut down")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list(),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Authorization", "Range"],
    )

    @app.middleware("http")
    async def request_id_and_timing(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - start) * 1000)
        response.headers["X-Request-ID"] = rid
        logging.getLogger("hum.access").info(
            "%s %s -> %d (%dms) rid=%s",
            request.method, request.url.path, response.status_code, duration_ms, rid,
        )
        return response

    @app.exception_handler(HumError)
    async def _handle_st(_: Request, exc: HumError) -> JSONResponse:
        return JSONResponse(
            {"error": exc.code, "message": exc.message}, status_code=exc.status
        )

    # Routes
    app.include_router(search.router)
    app.include_router(radio.router)
    app.include_router(video.router)
    app.include_router(channel.router)
    app.include_router(playlist.router)
    app.include_router(audio.router)
    app.include_router(proxy_video.router)
    app.include_router(thumbnail.router)
    app.include_router(live_segment.router)
    app.include_router(hls.router)
    app.include_router(live.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "healthy"}

    # Mount built frontend at / (no-op in dev when frontend/dist/ doesn't exist).
    from app import static as _static
    _static.mount(app)

    return app


app = create_app()


def main() -> None:
    import sys

    # The `hum` script takes no subcommands; `hum shim` is a common slip — the
    # shim has its own entry point. Fail loudly instead of silently starting Hum.
    if len(sys.argv) > 1:
        raise SystemExit(
            f"hum: unknown argument {sys.argv[1]!r} — did you mean 'hum-shim'?"
        )

    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
