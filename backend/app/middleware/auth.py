"""API key authentication middleware.

When `require_auth` is enabled, all endpoints except health, metrics, and
OpenAPI require a valid `X-API-Key` header matching the configured `api_key`.

Health and observability endpoints remain unauthenticated so that load
balancers, monitoring systems, and service discovery can probe the service.

The header name matches the platform convention verified in
`fx-market-data-service` (`backend/middleware/auth.py`).
"""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Paths that never require authentication, even when require_auth is true.
PUBLIC_PATHS = {
    "/api/v1/health/live",
    "/api/v1/health/ready",
    "/api/v1/status",
    "/api/v1/version",
    "/metrics",
    "/api/v1/openapi.json",
    "/docs",
    "/redoc",
    "/health",
}


class AuthMiddleware(BaseHTTPMiddleware):
    """API key authentication middleware.

    When the service is configured with `require_auth=true`, every request to
    a non-public path must include an `X-API-Key` header matching the
    configured `api_key`. Requests without a valid key receive a 401.
    """

    def __init__(self, app: Any, require_auth: bool, api_key: str | None) -> None:
        super().__init__(app)
        self.require_auth = require_auth
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        if not self.require_auth:
            return await call_next(request)

        # Allow public paths without authentication.
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Allow CORS preflight to pass through unauthenticated.
        if request.method == "OPTIONS":
            return await call_next(request)

        provided_key = request.headers.get("x-api-key")
        if not provided_key or not secrets.compare_digest(provided_key, self.api_key or ""):
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "unauthenticated",
                        "message": "Missing or invalid API key",
                        "request_id": getattr(request.state, "request_id", "unknown"),
                    }
                },
            )

        return await call_next(request)
