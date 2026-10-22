"""Application factory and entrypoint for the Historical Market Analysis Service.

The `create_app` factory builds a fully configured FastAPI application from
validated settings. Tests construct their own instance through the factory,
which keeps every layer (routing, middleware, exception handlers) testable
without global state.

This module intentionally exposes NO analytical endpoints. The historical
analysis engine is not implemented in this foundation phase.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from backend.app.api.v1.router import router as api_v1_router
from backend.app.clients.market_data import MarketDataClient
from backend.app.core.config import Settings, get_settings
from backend.app.core.errors import (
    AppError,
    app_error_handler,
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from backend.app.core.logging import configure_logging
from backend.app.middleware.auth import AuthMiddleware
from backend.app.middleware.correlation import CorrelationIDMiddleware
from backend.app.middleware.request_logging import HTTPRequestLoggingMiddleware
from backend.app.middleware.security import (
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from backend.app.observability.metrics import SERVICE_UP, metrics_response
from backend.app.observability.tracing import init_observability
from backend.app.services.health_service import HealthService

logger = logging.getLogger("fx-historical-market-analysis-service")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage graceful startup and shutdown."""
    settings: Settings = app.state.settings
    logger.info(
        "application_starting",
        extra={
            "service": settings.service_name,
            "version": settings.service_version,
            "environment": settings.environment,
            "mode": settings.service_mode,
        },
    )

    app.state.start_time = None
    app.state.health_service = HealthService(
        settings=settings,
        upstream_client=app.state.upstream_client,
    )

    init_observability(settings, app)
    SERVICE_UP.set(1)
    logger.info("application_started")

    try:
        yield
    finally:
        SERVICE_UP.set(0)
        await app.state.upstream_client.aclose()
        logger.info("application_shutting_down")
        logger.info("application_shutdown_complete")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the FastAPI application.

    Args:
        settings: Validated settings. When omitted the cached process settings
            are used. Tests should pass explicit settings.
    """
    resolved = settings or get_settings()
    configure_logging(resolved)

    application = FastAPI(
        title=resolved.service_name,
        version=resolved.service_version,
        description=(
            "Forex AI Platform - Historical Market Analysis Service. "
            "Research/simulation only. The historical analysis engine is not "
            "implemented in this foundation phase."
        ),
        docs_url=None
        if resolved.is_production and not resolved.docs_enabled_in_production
        else "/docs",
        redoc_url=None
        if resolved.is_production and not resolved.docs_enabled_in_production
        else "/redoc",
        openapi_url="/api/v1/openapi.json"
        if not resolved.is_production or resolved.docs_enabled_in_production
        else None,
        lifespan=lifespan,
    )

    application.state.settings = resolved
    application.state.upstream_client = MarketDataClient(
        base_url=resolved.upstream_market_data_base_url,
        api_key=resolved.upstream_api_key,
        timeout_seconds=resolved.upstream_timeout_seconds,
    )

    _register_middleware(application, resolved)
    _register_exception_handlers(application)
    application.include_router(api_v1_router, prefix=resolved.api_prefix)
    _register_operational_routes(application, resolved)

    logger.info(
        "application_configured",
        extra={
            "api_prefix": resolved.api_prefix,
            "environment": resolved.environment,
            "upstream_configured": resolved.upstream_configured,
        },
    )
    return application


def _register_middleware(application: FastAPI, settings: Settings) -> None:
    """Register middleware.

    Middleware order matters: Starlette executes the most recently added
    middleware first, so the list below is added inner-to-outer. The resulting
    request flow is:

        SecurityHeaders -> RequestLogging -> RequestSizeLimit -> TrustedHost
        -> CORS -> CorrelationID -> Auth -> routes
    """
    application.add_middleware(
        AuthMiddleware, require_auth=settings.require_auth, api_key=settings.api_key
    )
    application.add_middleware(CorrelationIDMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_method_list,
        allow_headers=settings.cors_header_list,
        expose_headers=["X-Request-ID", "X-Correlation-ID"],
        max_age=600,
    )
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.trusted_host_list,
    )
    application.add_middleware(
        RequestSizeLimitMiddleware,
        max_body_bytes=settings.max_request_body_bytes,
    )
    application.add_middleware(
        HTTPRequestLoggingMiddleware,
        service_name=settings.service_name,
        service_version=settings.service_version,
    )
    application.add_middleware(SecurityHeadersMiddleware, is_production=settings.is_production)


def _register_exception_handlers(application: FastAPI) -> None:
    """Register handlers that normalise every error into one envelope."""
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    # The handler signatures are narrowed to the concrete exception type for
    # readability; Starlette accepts any callable taking (Request, Exception).
    application.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]
    application.add_exception_handler(Exception, unhandled_exception_handler)  # type: ignore[arg-type]
    application.add_exception_handler(  # type: ignore[arg-type]
        StarletteHTTPException,
        http_exception_handler,  # type: ignore[arg-type]
    )
    application.add_exception_handler(  # type: ignore[arg-type]
        RequestValidationError, validation_exception_handler
    )


def _register_operational_routes(application: FastAPI, settings: Settings) -> None:
    """Register the metrics endpoint and the legacy health alias."""

    @application.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        payload, content_type = metrics_response()
        return Response(content=payload, media_type=content_type)

    @application.get("/health", include_in_schema=False)
    async def legacy_health() -> JSONResponse:
        """Legacy health alias retained for infrastructure compatibility."""
        return JSONResponse(
            {
                "status": "ok",
                "service": settings.service_name,
                "mode": settings.service_mode,
            }
        )

    @application.get("/", include_in_schema=False)
    async def root() -> JSONResponse:
        """Service banner describing the current implementation status."""
        return JSONResponse(
            {
                "service": settings.service_name,
                "version": settings.service_version,
                "api_version": settings.api_version,
                "mode": settings.service_mode,
                "status": "foundation",
                "note": (
                    "Service foundation only - the historical analysis engine is "
                    "not implemented in this phase."
                ),
                "docs": "/docs",
            }
        )


app = create_app()
