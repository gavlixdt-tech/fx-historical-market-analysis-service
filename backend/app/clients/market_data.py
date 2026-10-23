"""Typed client for the upstream `fx-market-data-service`.

CONTRACT VERIFICATION STATUS
----------------------------
The request paths, query parameters, response envelopes and payload fields
used by this client were read from the Service 1 source tree and are
**VERIFIED**. The authentication mechanism is **PROPOSED — NOT YET VERIFIED**
(Service 1's `AuthMiddleware` reads `X-API-Key`, but Service 1's OpenAPI
document is a placeholder with no declared security schemes).

This client is intentionally read-only: it requests historical datasets and
provider/provenance metadata from Service 1. It performs no provider calls, no
quote collection, and no source-quality computation of its own.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx

from backend.app.clients.base import (
    UpstreamCheckResult,
    UpstreamContractStatus,
    UpstreamState,
)
from backend.app.core.errors import UpstreamError
from backend.app.schemas.upstream import (
    UpstreamHistoricalCandleData,
    UpstreamHistoricalResponse,
    UpstreamProviderListResponse,
)

logger = logging.getLogger("fx-historical-market-analysis-service.upstream")

# Verified Service 1 route paths (Service 1 mounts its v1 router at /api/v1).
UPSTREAM_HISTORY_PATH = "/api/v1/market-data/history/{instrument}"
UPSTREAM_PROVIDERS_PATH = "/api/v1/market-data/providers"
UPSTREAM_LIVE_PATH = "/api/v1/health/live"

# Verified Service 1 query parameter names.
HISTORY_QUERY_PARAMS = (
    "provider_id",
    "start",
    "end",
    "timeframe",
    "price_basis",
    "limit",
)

# Verified Service 1 limit bounds for the history endpoint (ge=1, le=5000).
MAX_HISTORY_LIMIT = 5000
MIN_HISTORY_LIMIT = 1


class MarketDataClient:
    """Read-only client for the upstream market-data service.

    The client is configured with a base URL and an optional credential. It
    enforces a request timeout, propagates the platform correlation ID
    downstream, and converts every upstream failure into a sanitised
    `UpstreamError` so that internal topology never leaks to the caller.
    """

    def __init__(
        self,
        base_url: str | None,
        api_key: str | None = None,
        timeout_seconds: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
        max_retries: int = 2,
        retry_max_duration_seconds: float = 10.0,
        connect_timeout_seconds: float | None = None,
        read_timeout_seconds: float | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") if base_url else None
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._connect_timeout = (
            connect_timeout_seconds if connect_timeout_seconds is not None else timeout_seconds
        )
        self._read_timeout = (
            read_timeout_seconds if read_timeout_seconds is not None else timeout_seconds
        )
        self._timeout = httpx.Timeout(
            connect=self._connect_timeout,
            read=self._read_timeout,
            write=self._read_timeout,
            pool=self._connect_timeout,
        )
        self._max_retries = max(0, int(max_retries))
        self._retry_max_duration_seconds = max(1.0, float(retry_max_duration_seconds))
        self._transport = transport
        self._client = client
        self._owns_client = client is None

    # ---- Configuration ----

    @property
    def is_configured(self) -> bool:
        """True when a base URL has been supplied."""
        return bool(self._base_url)

    @property
    def has_credential(self) -> bool:
        """True when an upstream credential has been supplied."""
        return bool(self._api_key)

    @property
    def base_url(self) -> str | None:
        """The configured base URL, if any."""
        return self._base_url

    # ---- HTTP plumbing ----

    def _build_headers(self, request_id: str | None = None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._api_key:
            # Header name verified from Service 1 `backend/middleware/auth.py`.
            headers["X-API-Key"] = self._api_key
        if request_id:
            # Propagate the platform correlation ID downstream.
            headers["X-Request-ID"] = request_id
            headers["X-Correlation-ID"] = request_id
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        self._client = httpx.AsyncClient(
            base_url=self._base_url or "",
            timeout=self._timeout,
            transport=self._transport,
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )
        return self._client

    async def aclose(self) -> None:
        """Release the underlying HTTP connection pool."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Perform an HTTP request with bounded retries for transient failures."""
        self._require_configured()
        client = await self._get_client()
        started = time.perf_counter()
        attempt = 0
        while True:
            try:
                response = await client.request(method, path, params=params, headers=headers)
            except (httpx.TimeoutException, httpx.HTTPError):
                if (
                    attempt < self._max_retries
                    and (time.perf_counter() - started) < self._retry_max_duration_seconds
                ):
                    attempt += 1
                    await asyncio.sleep(min(0.25 * attempt, 1.0))
                    continue
                raise

            retryable_status = response.status_code in {408, 500, 502, 503, 504}
            if (
                retryable_status
                and attempt < self._max_retries
                and (time.perf_counter() - started) < self._retry_max_duration_seconds
            ):
                attempt += 1
                await asyncio.sleep(min(0.25 * attempt, 1.0))
                continue
            return response

    def _require_configured(self) -> str:
        if not self._base_url:
            raise UpstreamError(
                "Upstream market-data service is not configured.",
                details={"dependency": "fx-market-data-service"},
            )
        return self._base_url

    async def check_connectivity(self, request_id: str | None = None) -> UpstreamCheckResult:
        """Verify that the upstream service is reachable.

        Performs a liveness probe against the upstream service. This is a
        connectivity check only: it does not request market data and does not
        alter any upstream state.
        """
        if not self._base_url:
            return UpstreamCheckResult(
                state=UpstreamState.UNCONFIGURED,
                message="No upstream base URL is configured.",
                contract_status=UpstreamContractStatus.VERIFIED,
            )

        started = time.perf_counter()
        try:
            response = await self._request(
                "GET", UPSTREAM_LIVE_PATH, headers=self._build_headers(request_id)
            )
        except httpx.TimeoutException:
            return UpstreamCheckResult(
                state=UpstreamState.UNAVAILABLE,
                message=f"Upstream did not respond within {self._connect_timeout:g}s.",
                checked_at=_utc_now(),
                contract_status=UpstreamContractStatus.VERIFIED,
            )
        except httpx.HTTPError as exc:
            logger.warning("upstream_connectivity_failed", extra={"reason": type(exc).__name__})
            return UpstreamCheckResult(
                state=UpstreamState.UNAVAILABLE,
                message="Upstream service could not be reached.",
                checked_at=_utc_now(),
                contract_status=UpstreamContractStatus.VERIFIED,
            )

        latency_ms = round((time.perf_counter() - started) * 1000, 2)

        if response.status_code == 429:
            return UpstreamCheckResult(
                state=UpstreamState.RATE_LIMITED,
                message="Upstream rate limited the connectivity probe.",
                latency_ms=latency_ms,
                checked_at=_utc_now(),
                contract_status=UpstreamContractStatus.VERIFIED,
            )
        if response.status_code == 401 or response.status_code == 403:
            return UpstreamCheckResult(
                state=UpstreamState.AUTH_FAILED,
                message="Upstream rejected the configured credential.",
                latency_ms=latency_ms,
                checked_at=_utc_now(),
                contract_status=UpstreamContractStatus.VERIFIED,
            )
        if response.status_code >= 500:
            return UpstreamCheckResult(
                state=UpstreamState.UNAVAILABLE,
                message="Upstream service reported an internal error.",
                latency_ms=latency_ms,
                checked_at=_utc_now(),
                contract_status=UpstreamContractStatus.VERIFIED,
            )
        if response.status_code >= 400:
            return UpstreamCheckResult(
                state=UpstreamState.UNAVAILABLE,
                message="Upstream service rejected the connectivity probe.",
                latency_ms=latency_ms,
                checked_at=_utc_now(),
                contract_status=UpstreamContractStatus.VERIFIED,
            )

        return UpstreamCheckResult(
            state=UpstreamState.CONNECTED,
            message="Upstream service responded successfully.",
            latency_ms=latency_ms,
            checked_at=_utc_now(),
            contract_status=UpstreamContractStatus.VERIFIED,
        )

    async def fetch_historical_candles(
        self,
        instrument: str,
        *,
        provider_id: str = "test-adapter",
        start: datetime | None = None,
        end: datetime | None = None,
        timeframe: str = "D1",
        price_basis: str = "bid",
        limit: int = 500,
        request_id: str | None = None,
    ) -> UpstreamHistoricalCandleData:
        """Request a historical dataset from Service 1.

        Maps one-to-one onto the verified Service 1 route
        `GET /api/v1/market-data/history/{instrument}` and returns the
        validated payload including Service 1's coverage report and validation
        summary (the source-quality metadata Service 1 owns).

        The client does not interpret, re-validate, or re-price the data: it
        validates the *shape* of the response and leaves all data-quality
        judgements to Service 1.
        """
        self._require_configured()

        if not instrument or not instrument.strip():
            raise UpstreamError("An instrument identifier is required.")

        if limit < MIN_HISTORY_LIMIT or limit > MAX_HISTORY_LIMIT:
            raise UpstreamError(
                f"limit must be between {MIN_HISTORY_LIMIT} and {MAX_HISTORY_LIMIT}.",
                details={"limit": limit},
            )

        params: dict[str, Any] = {
            "provider_id": provider_id,
            "timeframe": timeframe,
            "price_basis": price_basis,
            "limit": limit,
        }
        if start is not None:
            params["start"] = _to_iso(start)
        if end is not None:
            params["end"] = _to_iso(end)

        path = UPSTREAM_HISTORY_PATH.format(instrument=instrument)

        try:
            response = await self._request(
                "GET", path, params=params, headers=self._build_headers(request_id)
            )
        except httpx.TimeoutException as exc:
            raise UpstreamError(
                f"Upstream market-data service timed out after {self._connect_timeout:g}s.",
                details={"dependency": "fx-market-data-service", "error_type": "timeout"},
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamError(
                "Upstream market-data service could not be reached.",
                details={"dependency": "fx-market-data-service", "error_type": "connection_error"},
            ) from exc

        if response.status_code == 429:
            raise UpstreamError(
                "Upstream market-data service rate limited the request.",
                upstream_status=429,
                details={"dependency": "fx-market-data-service", "error_type": "rate_limited"},
            )
        if response.status_code == 401 or response.status_code == 403:
            raise UpstreamError(
                "Upstream market-data service rejected the configured credential.",
                upstream_status=response.status_code,
                details={"dependency": "fx-market-data-service", "error_type": "auth_failed"},
            )
        if response.status_code >= 400:
            raise UpstreamError(
                f"Upstream market-data service returned HTTP {response.status_code}.",
                upstream_status=response.status_code,
                details={"dependency": "fx-market-data-service", "error_type": "http_error"},
            )

        try:
            parsed = UpstreamHistoricalResponse.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise UpstreamError(
                "Upstream market-data service returned an unexpected payload shape.",
                details={"dependency": "fx-market-data-service", "error_type": "invalid_response"},
            ) from exc

        if parsed.data is None:
            raise UpstreamError(
                "Upstream market-data service returned an empty payload.",
                details={"dependency": "fx-market-data-service"},
            )

        return parsed.data

    async def list_providers(
        self,
        *,
        request_id: str | None = None,
    ) -> UpstreamProviderListResponse:
        """List the providers configured in Service 1.

        Used to confirm which upstream provider identifiers are available.
        The response never contains credentials (Service 1 guarantees this).
        """
        self._require_configured()

        client = await self._get_client()
        try:
            response = await client.get(
                UPSTREAM_PROVIDERS_PATH,
                headers=self._build_headers(request_id),
            )
        except httpx.TimeoutException as exc:
            raise UpstreamError(
                f"Upstream market-data service timed out after {self._connect_timeout:g}s.",
                details={"dependency": "fx-market-data-service"},
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamError(
                "Upstream market-data service could not be reached.",
                details={"dependency": "fx-market-data-service"},
            ) from exc

        if response.status_code >= 400:
            raise UpstreamError(
                f"Upstream market-data service returned HTTP {response.status_code}.",
                upstream_status=response.status_code,
                details={"dependency": "fx-market-data-service"},
            )

        try:
            return UpstreamProviderListResponse.model_validate(response.json())
        except ValueError as exc:
            raise UpstreamError(
                "Upstream market-data service returned an unexpected payload shape.",
                details={"dependency": "fx-market-data-service"},
            ) from exc


def _utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_iso(value: datetime) -> str:
    """Render a datetime as an ISO-8601 UTC string.

    Service 1 documents its `start`/`end` parameters as ISO-8601 UTC
    timestamps. A naive datetime is assumed to be UTC.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
