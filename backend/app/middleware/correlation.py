"""Correlation ID middleware.

Propagates a validated incoming `X-Request-ID` / `X-Correlation-ID` header, or
generates one when absent. Correlation IDs are bounded in length and sanitised
to prevent header injection. Stored in a context variable so structured logging
can attach the ID to every log record.
"""

from __future__ import annotations

import secrets
import string
from contextvars import ContextVar
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Context variable holding the current correlation ID for the active request.
_current_correlation_id: ContextVar[str] = ContextVar("current_correlation_id", default="")

# Safe characters for correlation IDs: alphanumeric plus hyphen.
_SAFE_CHARS = set(string.ascii_letters + string.digits + "-")
_MAX_CORRELATION_ID_LENGTH = 128


def current_correlation_id() -> str:
    """Return the correlation ID for the current request context."""
    return _current_correlation_id.get()


def set_correlation_id(value: str) -> None:
    """Set the correlation ID for the current request context."""
    _current_correlation_id.set(value)


def _sanitise_correlation_id(raw: str | None) -> str:
    """Sanitise and bound a client-supplied correlation ID.

    Strips unsafe characters, truncates to the maximum length, and returns a
    server-generated ID if the result would be empty.
    """
    if not raw:
        return _generate_id()
    cleaned = "".join(ch for ch in raw if ch in _SAFE_CHARS).strip("-")
    if not cleaned or len(cleaned) > _MAX_CORRELATION_ID_LENGTH:
        return _generate_id()
    return cleaned[:_MAX_CORRELATION_ID_LENGTH]


def _generate_id() -> str:
    """Generate a cryptographically random correlation ID."""
    return "fx-" + secrets.token_urlsafe(16)[:48]


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Middleware that sets, validates, and echoes the correlation ID."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        raw_id = (
            request.headers.get("x-request-id") or request.headers.get("x-correlation-id") or ""
        )
        correlation_id = _sanitise_correlation_id(raw_id)

        # Store in context var for logging and in request state for handlers.
        token = _current_correlation_id.set(correlation_id)
        request.state.request_id = correlation_id
        try:
            response = await call_next(request)
        finally:
            _current_correlation_id.reset(token)

        # Echo the correlation ID back to the client for distributed tracing.
        response.headers["X-Request-ID"] = correlation_id
        response.headers["X-Correlation-ID"] = correlation_id
        return response
