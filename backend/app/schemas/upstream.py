"""Typed schemas for the upstream `fx-market-data-service` contract.

PROVENANCE OF THESE SCHEMAS
---------------------------
Every field below was read directly from the Service 1 source tree
(`fx-market-data-service/backend/`) on 2026-10-22. Each model cites the
Service 1 file it mirrors so that a future contract drift is easy to detect.

The one item that could NOT be verified is Service 1's *authentication*
contract for server-to-server calls: Service 1's `AuthMiddleware` reads the
`X-API-Key` header, but the OpenAPI document at
`fx-market-data-service/docs/api/openapi.yaml` is a placeholder that declares
no security schemes, and the shared `Pipline` package (which supplies the
platform's production middleware) is not vendored in either repository.
See `contracts/upstream-market-data-contract.md` for the full analysis.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Timeframe(StrEnum):
    """Supported candle granularities.

    Mirrors `backend/domain/market_data.py::Timeframe` in Service 1.
    """

    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"
    W1 = "W1"
    MN1 = "MN1"


class PriceBasis(StrEnum):
    """Price basis of a candle series.

    Mirrors `backend/domain/market_data.py::PriceBasis` in Service 1.
    """

    BID = "bid"
    ASK = "ask"
    MIDPOINT = "midpoint"
    UNKNOWN = "unknown"


class UpstreamErrorDetail(BaseModel):
    """A single structured error entry from Service 1."""

    model_config = ConfigDict(frozen=True)

    code: str = Field(..., description="Stable, machine-readable error code")
    message: str = Field(..., description="Human-readable error description")
    request_id: str | None = Field(default=None, description="Correlation ID")
    details: dict[str, Any] | None = Field(default=None, description="Structured detail")


class UpstreamErrorResponse(BaseModel):
    """Service 1 error envelope.

    Mirrors `backend/core/errors.py::AppError.to_dict` in Service 1:
    ``{"error": {"code", "message", "request_id", "details"}}``.
    """

    model_config = ConfigDict(frozen=True)

    error: UpstreamErrorDetail = Field(..., description="Error detail object")


class UpstreamResponseMeta(BaseModel):
    """Service 1 response metadata.

    Mirrors `backend/schemas/common.py::ResponseMeta` in Service 1.
    """

    model_config = ConfigDict(frozen=True)

    api_version: str = Field(..., description="API version, e.g. 'v1'")
    request_id: str = Field(..., description="Correlation ID for the request")
    timestamp_utc: str = Field(..., description="UTC ISO 8601 response timestamp")


class UpstreamHistoricalCandle(BaseModel):
    """A single historical candle.

    Mirrors `backend/schemas/market_data.py::HistoricalCandleSchema` in
    Service 1.
    """

    model_config = ConfigDict(frozen=True)

    provider_id: str
    instrument: str
    base_currency: str
    quote_currency: str
    timeframe: str
    price_basis: str
    open_time: datetime
    close_time: datetime | None = None
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None
    volume: Decimal | None = None
    volume_kind: str | None = None
    source: str = ""
    retrieved_at: datetime | None = None
    completeness: str
    valid: bool
    validation_error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpstreamCoverageReport(BaseModel):
    """Coverage report for a historical request.

    Mirrors `backend/schemas/market_data.py::CoverageReportSchema` in
    Service 1.
    """

    model_config = ConfigDict(frozen=True)

    requested_start: datetime
    requested_end: datetime
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    expected_intervals: int | None = None
    returned_count: int
    valid_count: int
    rejected_count: int
    duplicate_count: int
    missing_intervals: list[str] = Field(default_factory=list)
    status: str
    complete: bool
    provider_limited: bool = False
    notes: list[str] = Field(default_factory=list)


class UpstreamValidationSummary(BaseModel):
    """Validation summary for a historical request.

    Mirrors `backend/schemas/market_data.py::ValidationSummary` in Service 1.
    """

    model_config = ConfigDict(frozen=True)

    total_received: int
    valid: int
    rejected: int
    duplicates: int


class UpstreamPaginationMetadata(BaseModel):
    """Pagination metadata.

    Mirrors `backend/schemas/market_data.py::PaginationMetadata` in Service 1.
    """

    model_config = ConfigDict(frozen=True)

    limit: int
    has_more: bool


class UpstreamHistoricalCandleData(BaseModel):
    """Payload of Service 1's historical endpoint.

    Mirrors `backend/schemas/market_data.py::HistoricalCandleResponse` in
    Service 1.
    """

    model_config = ConfigDict(frozen=True)

    provider_id: str
    canonical_instrument: str
    requested_start: datetime | None = None
    requested_end: datetime | None = None
    effective_start: datetime | None = None
    effective_end: datetime | None = None
    timeframe: Timeframe
    price_basis: PriceBasis
    candles: list[UpstreamHistoricalCandle] = Field(default_factory=list)
    coverage: UpstreamCoverageReport
    validation_summary: UpstreamValidationSummary
    pagination: UpstreamPaginationMetadata
    retrieved_at: datetime
    limitations: list[str] = Field(default_factory=list)


class UpstreamHistoricalResponse(BaseModel):
    """Service 1 historical endpoint envelope.

    Mirrors `backend/schemas/common.py::ApiResponse` in Service 1.
    """

    model_config = ConfigDict(frozen=True)

    data: UpstreamHistoricalCandleData | None = None
    meta: UpstreamResponseMeta
    errors: list[UpstreamErrorDetail] = Field(default_factory=list)


class UpstreamProviderSummary(BaseModel):
    """Safe provider summary.

    Mirrors `backend/schemas/market_data.py::ProviderSummarySchema` in
    Service 1. Never contains credentials.
    """

    model_config = ConfigDict(frozen=True)

    provider_id: str
    provider_type: str
    configured: bool
    connection_status: str
    capabilities: list[str] = Field(default_factory=list)
    last_connection_test_at: str | None = None
    last_connection_test_success: bool | None = None
    last_connection_test_message: str | None = None
    last_quote_retrieved_at: str | None = None
    last_error: str | None = None
    rate_limit_remaining: int | None = None
    rate_limit_limit: int | None = None


class UpstreamProviderListData(BaseModel):
    """Payload of Service 1's provider listing endpoint."""

    model_config = ConfigDict(frozen=True)

    providers: list[UpstreamProviderSummary] = Field(default_factory=list)


class UpstreamProviderListResponse(BaseModel):
    """Service 1 provider listing envelope."""

    model_config = ConfigDict(frozen=True)

    data: UpstreamProviderListData | None = None
    meta: UpstreamResponseMeta
    errors: list[UpstreamErrorDetail] = Field(default_factory=list)
