"""hum-subsonic-shim FastAPI entry point (spec: docs/SONOS_SPEC.md)."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from shim import hum_client
from shim.config import get_settings
from shim.rest import router
from shim.subsonic import MISSING_PARAMETER, SubsonicError, error_response


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    logging.getLogger("shim").info("starting up")
    yield
    await hum_client.close_client()
    logging.getLogger("shim").info("shut down")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="hum-subsonic-shim",
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.exception_handler(SubsonicError)
    async def _handle_subsonic(_: Request, exc: SubsonicError) -> JSONResponse:
        return error_response(exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Subsonic clients expect protocol error 10, not an HTTP 422.
        return error_response(MISSING_PARAMETER, "missing or invalid request parameter")

    app.include_router(router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "healthy"}

    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "shim.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
