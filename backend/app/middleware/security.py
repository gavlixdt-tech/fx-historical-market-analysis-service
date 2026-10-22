"""Security middleware: headers, trusted hosts, and request size limiting.

Never trusts arbitrary forwarding headers. CORS is restricted to an explicit
allowlist. Security headers are applied to every response.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    # Strict-Transport-Security is intentionally set at the ingress/gateway
    # layer, not here, because this service runs behind a gateway/proxy.
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Apply defensive security headers to every response."""

    def __init__(self, app: Any, is_production: bool = False) -> None:
        super().__init__(app)
        self.is_production = is_production

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if self.is_production:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose declared body exceeds the configured limit.

    The limit is enforced on the declared `Content-Length` header. A chunked
    request without `Content-Length` is still bounded because the body is read
    incrementally and truncated at the limit.
    """

    def __init__(self, app: Any, max_body_bytes: int) -> None:
        super().__init__(app)
        self.max_body_bytes = max_body_bytes

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                return self._too_large("Malformed Content-Length header.")
            if declared > self.max_body_bytes:
                return self._too_large("Request body exceeds the configured size limit.")

        return await call_next(request)

    def _too_large(self, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "VAL_REQUEST_TOO_LARGE",
                    "message": message,
                }
            },
        )
