"""Typed client for the upstream `fx-market-data-service`.

CONTRACT VERIFICATION STATUS
----------------------------
The request paths, response envelopes, payload fields, and authentication
policy used by this client are verified against Service 1's source contract.
Connectivity is only reported as connected after the protected provider
inventory accepts the configured credential and an available real historical
candle provider is present.

This client is intentionally read-only: it requests historical datasets and
provider/provenance metadata from Service 1. It performs no provider calls, no
quote collection, and no source-quality computation of its own.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from backend.app.clients.base import (
    UpstreamCheckResult,
    UpstreamContractStatus,
    UpstreamState,
)
from backend.app.core.errors import UpstreamError
from backend.app.schemas.upstream import (
    PriceBasis,
    Timeframe,
    UpstreamConnectionTestResponse,
    UpstreamHistoricalCandleData,
    UpstreamHistoricalResponse,
    UpstreamProviderListResponse,
)

logger = logging.getLogger("fx-historical-market-analysis-service.upstream")

# Verified Service 1 route paths (Service 1 mounts its v1 router at /api/v1).
UPSTREAM_HISTORY_PATH = "/api/v1/market-data/history/{instrument}"
UPSTREAM_PROVIDERS_PATH = "/api/v1/market-data/providers"
UPSTREAM_PROVIDER_TEST_PATH = "/api/v1/market-data/providers/{provider_id}/test-connection"
UPSTREAM_STATUS_PATH = "/api/v1/status"

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
        max_concurrent_requests: int = 4,
        max_response_bytes: int = 16_777_216,
    ) -> None:
        if max_concurrent_requests < 1:
            raise ValueError("max_concurrent_requests must be positive")
        if max_response_bytes < 1024:
            raise ValueError("max_response_bytes must be at least 1024")
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
        self._request_semaphore = asyncio.Semaphore(max_concurrent_requests)
        self._max_response_bytes = max_response_bytes
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
        async with self._request_semaphore:
            while True:
                try:
                    async with client.stream(
                        method, path, params=params, headers=headers
                    ) as streamed_response:
                        content_length = streamed_response.headers.get("content-length")
                        if content_length is not None:
                            try:
                                declared_size = int(content_length)
                            except ValueError as exc:
                                raise UpstreamError(
                                    "Upstream market-data service returned invalid response metadata.",
                                    details={"dependency": "fx-market-data-service"},
                                ) from exc
                            if declared_size > self._max_response_bytes:
                                raise UpstreamError(
                                    "Upstream market-data service response exceeded the configured size limit.",
                                    details={
                                        "dependency": "fx-market-data-service",
                                        "error_type": "response_too_large",
                                    },
                                )

                        content = bytearray()
                        async for chunk in streamed_response.aiter_bytes():
                            if len(content) + len(chunk) > self._max_response_bytes:
                                raise UpstreamError(
                                    "Upstream market-data service response exceeded the configured size limit.",
                                    details={
                                        "dependency": "fx-market-data-service",
                                        "error_type": "response_too_large",
                                    },
                                )
                            content.extend(chunk)
                        response = httpx.Response(
                            streamed_response.status_code,
                            headers=streamed_response.headers,
                            content=bytes(content),
                            request=streamed_response.request,
                        )
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
        """Verify Service 1's status contract, authentication, and real provider."""
        if not self._base_url:
            return UpstreamCheckResult(
                state=UpstreamState.UNCONFIGURED,
                message="No upstream base URL is configured.",
                contract_status=UpstreamContractStatus.PROPOSED_NOT_YET_VERIFIED,
            )

        started = time.perf_counter()
        status_headers = {"Accept": "application/json"}
        if request_id:
            status_headers["X-Request-ID"] = request_id
            status_headers["X-Correlation-ID"] = request_id
        try:
            response = await self._request(
                "GET",
                UPSTREAM_STATUS_PATH,
                headers=status_headers,
            )
        except httpx.TimeoutException:
            return UpstreamCheckResult(
                state=UpstreamState.UNAVAILABLE,
                message=f"Upstream status check timed out after {self._connect_timeout:g}s.",
                checked_at=_utc_now(),
                contract_status=UpstreamContractStatus.PROPOSED_NOT_YET_VERIFIED,
            )
        except httpx.HTTPError as exc:
            logger.warning("upstream_connectivity_failed", extra={"reason": type(exc).__name__})
            return UpstreamCheckResult(
                state=UpstreamState.UNAVAILABLE,
                message="Upstream service could not be reached.",
                checked_at=_utc_now(),
                contract_status=UpstreamContractStatus.PROPOSED_NOT_YET_VERIFIED,
            )

        auth_policy_error = self._response_failure(response.status_code, started)
        if auth_policy_error is not None:
            return auth_policy_error

        try:
            status_payload = response.json()
            status_data = status_payload["data"]
            status_meta = status_payload["meta"]
            if (
                not isinstance(status_data, dict)
                or not isinstance(status_data.get("api_key_authentication_required"), bool)
                or not isinstance(status_meta, dict)
                or not all(
                    isinstance(status_meta.get(field), str) and status_meta[field]
                    for field in ("api_version", "request_id", "timestamp_utc")
                )
                or status_payload.get("errors") != []
            ):
                raise ValueError("invalid Service 1 status contract")
            authentication_required = status_data["api_key_authentication_required"]
        except (ValueError, KeyError, TypeError):
            return self._connectivity_result(
                UpstreamState.CONTRACT_MISMATCH,
                "Upstream status response does not match the verified contract.",
                started,
                contract_status=UpstreamContractStatus.PROPOSED_NOT_YET_VERIFIED,
            )

        contract_status = UpstreamContractStatus.VERIFIED
        if authentication_required and not self._api_key:
            return self._connectivity_result(
                UpstreamState.AUTH_FAILED,
                "Upstream requires an API key, but no credential is configured.",
                started,
                contract_status=contract_status,
                authentication_status="missing",
            )

        try:
            providers_response = await self._request(
                "GET",
                UPSTREAM_PROVIDERS_PATH,
                headers=self._build_headers(request_id),
            )
        except httpx.TimeoutException:
            return self._connectivity_result(
                UpstreamState.UNAVAILABLE,
                f"Upstream provider check timed out after {self._connect_timeout:g}s.",
                started,
                contract_status=contract_status,
                authentication_status="verified" if authentication_required else "not_required",
            )
        except httpx.HTTPError as exc:
            logger.warning("upstream_provider_check_failed", extra={"reason": type(exc).__name__})
            return self._connectivity_result(
                UpstreamState.UNAVAILABLE,
                "Upstream provider check could not reach the service.",
                started,
                contract_status=contract_status,
                authentication_status="verified" if authentication_required else "not_required",
            )

        provider_http_failure = self._response_failure(
            providers_response.status_code,
            started,
            contract_status=contract_status,
            authentication_status="rejected" if providers_response.status_code in {401, 403}
            else ("verified" if authentication_required else "not_required"),
        )
        if provider_http_failure is not None:
            return provider_http_failure

        try:
            providers = UpstreamProviderListResponse.model_validate(providers_response.json())
            if providers.errors or providers.data is None:
                raise ValueError("invalid Service 1 provider inventory")
        except (ValueError, TypeError):
            return self._connectivity_result(
                UpstreamState.CONTRACT_MISMATCH,
                "Upstream provider response does not match the verified contract.",
                started,
                contract_status=UpstreamContractStatus.PROPOSED_NOT_YET_VERIFIED,
                authentication_status="verified" if authentication_required else "not_required",
            )

        real_providers = [
            provider for provider in providers.data
            if provider.provider_type.value == "real" and provider.configured
        ]
        available_provider = next(
            (
                provider for provider in real_providers
                if provider.connection_status.value == "available"
                and provider.last_connection_test_success is True
                and self._is_utc_timestamp(provider.last_connection_test_at)
                and any(capability.value == "historical_candles" for capability in provider.capabilities)
            ),
            None,
        )
        auth_status = "verified" if authentication_required else "not_required"
        if available_provider is not None:
            return self._connectivity_result(
                UpstreamState.CONNECTED,
                "Upstream authentication, contracts, and real historical provider are verified.",
                started,
                contract_status=contract_status,
                authentication_status=auth_status,
                provider_status="available",
                provider_tested_at=available_provider.last_connection_test_at,
            )
        if real_providers:
            provider_status = (
                "not_tested"
                if any(
                    provider.connection_status.value == "configured_not_tested"
                    or provider.last_connection_test_success is None
                    for provider in real_providers
                )
                else "historical_candles_unavailable"
            )
        elif any(provider.provider_type.value == "test" and provider.configured for provider in providers.data):
            provider_status = "test_adapter_only"
        else:
            provider_status = "not_configured"
        return self._connectivity_result(
            UpstreamState.UNAVAILABLE,
            "No configured real provider is verified available for historical candles.",
            started,
            contract_status=contract_status,
            authentication_status=auth_status,
            provider_status=provider_status,
        )

    def _response_failure(
        self,
        status_code: int,
        started: float,
        *,
        contract_status: UpstreamContractStatus = (
            UpstreamContractStatus.PROPOSED_NOT_YET_VERIFIED
        ),
        authentication_status: str = "unverified",
    ) -> UpstreamCheckResult | None:
        if status_code < 400:
            return None
        if status_code == 429:
            state, message = UpstreamState.RATE_LIMITED, "Upstream rate limited the connectivity probe."
        elif status_code in {401, 403}:
            state, message = UpstreamState.AUTH_FAILED, "Upstream rejected the configured credential."
        elif status_code >= 500:
            state, message = UpstreamState.UNAVAILABLE, "Upstream service reported an internal error."
        else:
            state, message = UpstreamState.UNAVAILABLE, "Upstream service rejected the connectivity probe."
        return self._connectivity_result(
            state,
            message,
            started,
            contract_status=contract_status,
            authentication_status=authentication_status,
        )

    @staticmethod
    def _is_utc_timestamp(value: str | None) -> bool:
        if not value:
            return False
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)

    @staticmethod
    def _connectivity_result(
        state: UpstreamState,
        message: str,
        started: float,
        *,
        contract_status: UpstreamContractStatus,
        authentication_status: str = "unverified",
        provider_status: str = "not_checked",
        provider_tested_at: str | None = None,
    ) -> UpstreamCheckResult:
        return UpstreamCheckResult(
            state=state,
            message=message,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            checked_at=_utc_now(),
            contract_status=contract_status,
            authentication_status=authentication_status,
            provider_status=provider_status,
            provider_tested_at=provider_tested_at,
        )

    async def fetch_historical_candles(
        self,
        instrument: str,
        *,
        provider_id: str,
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
        if not provider_id.strip():
            raise UpstreamError("A provider identifier must be explicitly selected.")

        if limit < MIN_HISTORY_LIMIT or limit > MAX_HISTORY_LIMIT:
            raise UpstreamError(
                f"limit must be between {MIN_HISTORY_LIMIT} and {MAX_HISTORY_LIMIT}.",
                details={"limit": limit},
            )
        try:
            Timeframe(timeframe)
        except ValueError as exc:
            raise UpstreamError("The requested timeframe is not supported.") from exc
        if price_basis not in {PriceBasis.BID, PriceBasis.ASK, PriceBasis.MIDPOINT}:
            raise UpstreamError("The requested price basis is not supported.")
        if start is not None and (start.tzinfo is None or start.utcoffset() is None):
            raise UpstreamError("The requested start timestamp must include a timezone.")
        if end is not None and (end.tzinfo is None or end.utcoffset() is None):
            raise UpstreamError("The requested end timestamp must include a timezone.")
        if start is not None and end is not None:
            if start >= end:
                raise UpstreamError("The requested start must precede the end.")
            if end.astimezone(UTC) - start.astimezone(UTC) > timedelta(days=365):
                raise UpstreamError("The requested history range exceeds the supported window.")

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

        path_instrument = quote(instrument.strip().replace("/", "_"), safe="")
        path = UPSTREAM_HISTORY_PATH.format(instrument=path_instrument)

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
        if (
            parsed.data.provider_id != provider_id
            or parsed.data.timeframe != Timeframe(timeframe)
            or parsed.data.price_basis != PriceBasis(price_basis)
        ):
            raise UpstreamError(
                "Upstream market-data response identity does not match the request.",
                details={
                    "dependency": "fx-market-data-service",
                    "error_type": "identity_mismatch",
                },
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

        try:
            response = await self._request(
                "GET",
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

    async def test_provider_connection(
        self,
        provider_id: str,
        *,
        request_id: str | None = None,
    ) -> bool:
        """Perform the upstream's real-provider connectivity test."""
        self._require_configured()
        if not provider_id.strip():
            raise UpstreamError("A provider identifier is required.")
        path = UPSTREAM_PROVIDER_TEST_PATH.format(
            provider_id=quote(provider_id, safe=""),
        )
        try:
            response = await self._request(
                "POST",
                path,
                headers=self._build_headers(request_id),
            )
        except httpx.TimeoutException as exc:
            raise UpstreamError(
                "Upstream market-data provider connection test timed out.",
                details={"dependency": "fx-market-data-service", "error_type": "timeout"},
            ) from exc
        except httpx.HTTPError as exc:
            raise UpstreamError(
                "Upstream market-data provider connection test failed.",
                details={"dependency": "fx-market-data-service", "error_type": "connection_error"},
            ) from exc

        if response.status_code >= 400:
            raise UpstreamError(
                "Upstream market-data provider connection test was rejected.",
                upstream_status=response.status_code,
                details={"dependency": "fx-market-data-service"},
            )
        try:
            parsed = UpstreamConnectionTestResponse.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise UpstreamError(
                "Upstream market-data service returned an invalid connection-test response.",
                details={"dependency": "fx-market-data-service"},
            ) from exc
        if parsed.errors or parsed.data is None or parsed.data.provider_id != provider_id:
            raise UpstreamError(
                "Upstream market-data service returned an inconsistent connection-test result.",
                details={"dependency": "fx-market-data-service"},
            )
        return parsed.data.success


def _utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_iso(value: datetime) -> str:
    """Render a datetime as an ISO-8601 UTC string.

    Service 1 documents its `start`/`end` parameters as ISO-8601 UTC
    timestamps. Naive datetimes are rejected rather than guessed.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise UpstreamError("Historical request timestamps must include a timezone.")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
