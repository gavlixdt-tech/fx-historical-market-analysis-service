"""Common response envelope and error schemas.

All successful responses use the standard envelope, matching the platform
convention verified in `fx-market-data-service`:

    {
      "data": {...},
      "meta": { "api_version": "...", "request_id": "...", "timestamp_utc": "..." },
      "errors": []
    }
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ErrorDetail(BaseModel):
    """A single structured error entry."""

    model_config = ConfigDict(frozen=True)

    code: str = Field(..., description="Stable, machine-readable error code")
    message: str = Field(..., description="Human-readable error description")
    request_id: str | None = Field(
        default=None, description="Correlation ID for the failing request"
    )
    details: dict[str, Any] | None = Field(
        default=None, description="Optional structured detail (never secrets)"
    )


class ResponseMeta(BaseModel):
    """Response metadata included in every envelope."""

    model_config = ConfigDict(frozen=True)

    api_version: str = Field(..., description="API version, e.g. 'v1'")
    request_id: str = Field(..., description="Correlation ID for the request")
    timestamp_utc: str = Field(..., description="UTC ISO 8601 response timestamp")


class ApiResponse(BaseModel, Generic[T]):
    """Standard API response envelope."""

    model_config = ConfigDict(frozen=True)

    data: T | None = Field(default=None, description="Response payload")
    meta: ResponseMeta = Field(..., description="Response metadata")
    errors: list[ErrorDetail] = Field(default_factory=list, description="Error entries, if any")


class HealthResponseData(BaseModel):
    """Health-check response payload."""

    model_config = ConfigDict(frozen=True)

    status: str = Field(..., description="'healthy', 'degraded' or 'unhealthy'")
    service: str = Field(..., description="Service identifier")
    mode: str = Field(..., description="Operating mode")
    check: str = Field(..., description="Type of check performed")


class VersionResponseData(BaseModel):
    """Version endpoint response payload."""

    model_config = ConfigDict(frozen=True)

    service: str = Field(..., description="Service identifier")
    application_version: str = Field(..., description="Application version")
    api_version: str = Field(..., description="API version")
    environment: str = Field(..., description="Deployment environment")
