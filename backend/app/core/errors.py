"""Structured error handling with stable error codes.

All application errors derive from `AppError` and produce consistent JSON error
responses with stable error codes, HTTP status mapping, and safe messages.

The error envelope mirrors the platform convention verified in
`fx-market-data-service`:

    {"error": {"code": "...", "message": "...", "request_id": "..."}}
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

# Error code categories:
#   CFG - configuration
#   VAL - validation
#   AUTH - authentication/authorisation
#   SVR - service/internal
#   DEP - dependency/external


class AppError(Exception):
    """Base application error with a stable code and optional payload."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 500,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self, request_id: str | None = None) -> dict[str, Any]:
        error: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.details:
            error["details"] = self.details
        if request_id:
            error["request_id"] = request_id
        return {"error": error}

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return f"[{self.code}] {self.message}"


class ConfigurationError(AppError):
    """Raised when mandatory configuration is missing or invalid."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("CFG_INVALID", message, status_code=500, details=details)


class ValidationError(AppError):
    """Raised when request or domain validation fails."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("VAL_INVALID", message, status_code=400, details=details)


class NotFoundError(AppError):
    """Raised when a requested resource does not exist."""

    def __init__(self, resource: str, identifier: str) -> None:
        super().__init__(
            "NOT_FOUND",
            f"{resource} not found: {identifier}",
            status_code=404,
            details={"resource": resource, "identifier": identifier},
        )


class DependencyUnavailableError(AppError):
    """Raised when an external dependency required for readiness is unavailable."""

    def __init__(self, dependency: str, reason: str) -> None:
        super().__init__(
            "DEP_UNAVAILABLE",
            f"Dependency unavailable: {dependency}",
            status_code=503,
            details={"dependency": dependency, "reason": reason},
        )


class ServiceUnavailableError(AppError):
    """Raised when the service cannot perform its responsibilities."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("SVR_UNAVAILABLE", message, status_code=503, details=details)


class UpstreamError(AppError):
    """Raised when the upstream market-data service returns an error.

    The upstream body is never echoed verbatim: upstream error messages are
    sanitised so that internal topology or credential details cannot leak
    through this service's public API.
    """

    def __init__(
        self,
        message: str,
        upstream_status: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__("DEP_UPSTREAM_ERROR", message, status_code=502, details=details)
        self.upstream_status = upstream_status


def _resolve_request_id(request: Any) -> str:
    """Resolve the correlation ID for the active request, tolerating absence."""
    try:
        from backend.app.middleware.correlation import current_correlation_id

        resolved = current_correlation_id()
        if resolved:
            return resolved
    except ImportError:
        # The correlation middleware module is optional at import time.
        pass
    return str(getattr(getattr(request, "state", None), "request_id", None) or "unknown")


def app_error_handler(request: Any, exc: AppError) -> JSONResponse:
    """FastAPI exception handler for AppError subclasses."""
    request_id = _resolve_request_id(request)
    return JSONResponse(status_code=exc.status_code, content=exc.to_dict(request_id=request_id))


def http_exception_handler(request: Any, exc: HTTPException) -> JSONResponse:
    """Convert Starlette HTTPException into the standard error envelope."""
    request_id = _resolve_request_id(request)
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    body = {
        "error": {
            "code": f"HTTP_{exc.status_code}",
            "message": detail,
            "request_id": request_id,
        }
    }
    return JSONResponse(status_code=exc.status_code, content=body)


def validation_exception_handler(request: Any, exc: Exception) -> JSONResponse:
    """Convert a request-validation failure into the standard error envelope.

    FastAPI's default 422 body is verbose and does not match the platform
    envelope, so it is normalised here. Field-level details are preserved but
    truncated so that a malformed payload cannot inflate the response.
    """
    request_id = _resolve_request_id(request)
    errors = getattr(exc, "errors", None)
    details: dict[str, Any] | None = None
    if isinstance(errors, list) and errors:
        trimmed: list[dict[str, Any]] = []
        for item in errors[:10]:
            if not isinstance(item, dict):
                continue
            location = item.get("loc")
            trimmed.append(
                {
                    "field": ".".join(str(part) for part in location) if location else "",
                    "message": str(item.get("msg", "invalid value")),
                    "type": str(item.get("type", "value_error")),
                }
            )
        details = {"fields": trimmed}
    body: dict[str, Any] = {
        "error": {
            "code": "VAL_INVALID",
            "message": "Request validation failed.",
            "request_id": request_id,
        }
    }
    if details:
        body["error"]["details"] = details
    return JSONResponse(status_code=422, content=body)


def unhandled_exception_handler(request: Any, exc: Exception) -> JSONResponse:
    """Catch-all handler that returns a safe, non-leaky 500 response."""
    request_id = _resolve_request_id(request)
    # Never leak exception internals to the client.
    body = {
        "error": {
            "code": "SVR_INTERNAL",
            "message": "An internal server error occurred.",
            "request_id": request_id,
        }
    }
    return JSONResponse(status_code=500, content=body)
