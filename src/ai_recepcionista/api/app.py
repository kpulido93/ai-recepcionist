from __future__ import annotations

import logging
import platform
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..core.config import Settings, get_settings
from ..core.logging import configure_logging
from .schemas import HealthResponse, ReadyResponse, VersionResponse

LOGGER_NAME = "ai_recepcionista.api"
SERVICE_NAME = "admin-api"


def _ready_checks(settings: Settings) -> dict[str, bool]:
    return {
        "config_loaded": True,
        "api_port_valid": settings.api_port > 0,
        "rtp_port_range_valid": settings.media_rtp_start_port <= settings.media_rtp_end_port,
    }


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(
        service=SERVICE_NAME,
        environment=settings.environment,
        level=settings.log_level,
    )

    logger = logging.getLogger(LOGGER_NAME)
    logger.info("admin_api_startup")
    app.state.settings = settings
    yield
    logger.info("admin_api_shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="ai-recepcionista admin-api",
        version=settings.version,
        lifespan=lifespan,
    )

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        current_settings = get_settings()
        return HealthResponse(
            status="ok",
            service=SERVICE_NAME,
            appName=current_settings.app_name,
            version=current_settings.version,
            environment=current_settings.environment,
        )

    @app.get("/ready", response_model=ReadyResponse, tags=["system"])
    def ready() -> ReadyResponse:
        current_settings = get_settings()
        return ReadyResponse(
            status="ready",
            service=SERVICE_NAME,
            checks=_ready_checks(current_settings),
        )

    @app.get("/version", response_model=VersionResponse, tags=["system"])
    def version() -> VersionResponse:
        current_settings = get_settings()
        return VersionResponse(
            version=current_settings.version,
            appName=current_settings.app_name,
            stasisAppName=current_settings.stasis_app_name,
            environment=current_settings.environment,
            pythonVersion=platform.python_version(),
        )

    return app


app = create_app()
