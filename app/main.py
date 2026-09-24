"""Hum FastAPI application entry point."""
from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.adapters import upstream_http, youtube
from app.adapters.upstream_http import UpstreamHostError, UpstreamRangeError, UpstreamStatusError
from app.adapters.youtube import YouTubeError
from app.api import channel, hls, live, playlist, radio, search, video
from app.config import get_settings
from app.proxy import audio, live_segment, thumbnail
from app.proxy import video as proxy_video

# ----- Logging --------------------------------------------------------------


class _RedactCdnUrls(logging.Filter):
    """Backstop for invariant 3 in logs: every record reaching a root handler
    has signed googlevideo URLs redacted, whichever library logged it."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Filters run outside Handler.emit()'s error handling: a malformed
        # record (bad %-args) must stay logging's problem, not raise into the
        # caller. Leave it untouched; emit() reports it via handleError.
        try:
            msg = record.getMessage()
        except Exception:
            return True
        redacted = youtube.redact_cdn_urls(msg)
        if redacted != msg:
            record.msg, record.args = redacted, None
        # Tracebacks are formatted after filters run: pre-render them here
        # (Formatter reuses record.exc_text) and drop exc_info.
        if record.exc_info:
            record.exc_text = youtube.redact_cdn_urls(
                logging.Formatter().formatException(record.exc_info)
            )
            record.exc_info = None
        if record.stack_info:
            record.stack_info = youtube.redact_cdn_urls(record.stack_info)
        return True


def _configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    if settings.log_json:
        fmt = '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
    else:
        fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    logging.basicConfig(level=level, format=fmt)
    # httpx logs every request URL at INFO; for media those are signed
    # googlevideo URLs with the server's IP. hum.access already logs requests.
    logging.getLogger("httpx").setLevel(max(level, logging.WARNING))
    # Root handlers catch everything that propagates. uvicorn's loggers have
    # their own handlers and propagate=False, so they get the filter directly
    # (logger filters apply to records logged there; handler filters to all
    # records those handlers emit).
    targets: list[logging.Filterer] = list(logging.getLogger().handlers)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        targets.append(lg)
        targets.extend(lg.handlers)
    for t in targets:
        if not any(isinstance(f, _RedactCdnUrls) for f in t.filters):
            t.addFilter(_RedactCdnUrls())


# ----- App ------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    _configure_logging()
    logging.getLogger("hum").info("starting up")
    youtube.check_backend_requirements()
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
        # Exception handlers below stash the mapped error code on request.state
        # so it lands in this single access-log line without touching the
        # response body/status the client sees.
        error_code = getattr(request.state, "error_code", None)
        if error_code:
            logging.getLogger("hum.access").info(
                "%s %s -> %d (%dms) rid=%s code=%s",
                request.method, request.url.path, response.status_code, duration_ms,
                rid, error_code,
            )
        else:
            logging.getLogger("hum.access").info(
                "%s %s -> %d (%dms) rid=%s",
                request.method, request.url.path, response.status_code, duration_ms, rid,
            )
        return response

    # Global error mapping. Routes may still catch these for bespoke messages;
    # these handlers are the safety net that keeps upstream failures from
    # surfacing as bare 500s (expired itag, dead video, YouTube down, ...).
    # Each handler records the error code on request.state so the access-log
    # middleware above can append it to the log line; response status/body are
    # unchanged.
    @app.exception_handler(YouTubeError)
    async def _handle_youtube_error(request: Request, exc: YouTubeError) -> JSONResponse:
        request.state.error_code = exc.code
        return JSONResponse(
            {"error": exc.code, "message": exc.message}, status_code=exc.status
        )

    @app.exception_handler(UpstreamHostError)
    async def _handle_upstream_host(request: Request, exc: UpstreamHostError) -> JSONResponse:
        request.state.error_code = "UPSTREAM_HOST_BLOCKED"
        return JSONResponse(
            {"error": "UPSTREAM_HOST_BLOCKED", "message": str(exc)}, status_code=502
        )

    @app.exception_handler(UpstreamStatusError)
    async def _handle_upstream_status(request: Request, exc: UpstreamStatusError) -> JSONResponse:
        request.state.error_code = "UPSTREAM_ERROR"
        return JSONResponse(
            {"error": "UPSTREAM_ERROR", "message": str(exc)}, status_code=502
        )

    @app.exception_handler(UpstreamRangeError)
    async def _handle_upstream_range(request: Request, exc: UpstreamRangeError) -> JSONResponse:
        request.state.error_code = "UPSTREAM_ERROR"
        return JSONResponse(
            {"error": "UPSTREAM_ERROR", "message": str(exc)}, status_code=502
        )

    @app.exception_handler(httpx.HTTPError)
    async def _handle_httpx_error(request: Request, exc: httpx.HTTPError) -> JSONResponse:
        # Connect/read failures against YouTube — the "YouTube is down/slow" case.
        logging.getLogger("hum").warning("upstream transport error: %r", exc)
        request.state.error_code = "UPSTREAM_UNREACHABLE"
        return JSONResponse(
            {"error": "UPSTREAM_UNREACHABLE", "message": "upstream request failed"},
            status_code=502,
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
