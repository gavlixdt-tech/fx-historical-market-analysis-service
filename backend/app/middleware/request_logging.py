"""HTTP request logging middleware.

Emits one structured log record per request containing the method, path,
status code, duration, and the correlation ID. Credentials are never logged:
only the request path (which excludes the query string) is recorded.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("fx-historical-market-analysis-service.http")


class HTTPRequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log the outcome and latency of every HTTP request."""

    def __init__(self, app: Any, service_name: str, service_version: str) -> None:
        super().__init__(app)
        self.service_name = service_name
        self.service_version = service_version

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "http_request_failed",
                extra={
                    "request_id": getattr(request.state, "request_id", None),
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(duration_ms, 2),
                    "service": self.service_name,
                },
            )
            raise

        duration_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "http_request_completed",
            extra={
                "request_id": getattr(request.state, "request_id", None),
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
                "service": self.service_name,
                "service_version": self.service_version,
            },
        )
        return response
