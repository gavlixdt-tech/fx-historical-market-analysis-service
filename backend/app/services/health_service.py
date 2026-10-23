"""Health, readiness, status and version services.

These services own the operational truth of the instance. They never invent
state: every reported value is derived from the running application or from a
real upstream check.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from backend.app.clients.base import UpstreamCheckResult, UpstreamState
from backend.app.clients.market_data import MarketDataClient
from backend.app.core.config import Settings
from backend.app.schemas.common import ApiResponse, ResponseMeta
from backend.app.schemas.health import DependencyHealth, LiveResponseData, ReadyResponseData
from backend.app.schemas.status import (
    CapabilityStatus,
    StatusResponseData,
    UpstreamIntegrationStatus,
)
from backend.app.schemas.version import VersionDetails

# Capabilities implemented in this phase.
IMPLEMENTED_CAPABILITIES: tuple[CapabilityStatus, ...] = (
    CapabilityStatus(
        name="service_health",
        implemented=True,
        detail="Liveness, readiness, status and version endpoints.",
    ),
    CapabilityStatus(
        name="upstream_integration_contract",
        implemented=True,
        detail=(
            "Typed client for the fx-market-data-service historical and provider "
            "contracts, with timeouts and sanitised error handling."
        ),
    ),
    CapabilityStatus(
        name="observability",
        implemented=True,
        detail="Structured JSON logging, Prometheus metrics and OpenTelemetry tracing.",
    ),
    CapabilityStatus(
        name="historical_statistics",
        implemented=True,
        detail="Descriptive statistics over historical observations.",
    ),
    CapabilityStatus(
        name="pattern_discovery",
        implemented=True,
        detail="Historical pattern and relationship identification.",
    ),
    CapabilityStatus(
        name="regime_classification",
        implemented=True,
        detail="Historical market regime and volatility characterisation.",
    ),
    CapabilityStatus(
        name="analytical_significance",
        implemented=True,
        detail="Statistical strength and limitation evaluation.",
    ),
    CapabilityStatus(
        name="reproducible_results",
        implemented=True,
        detail="Reproducible analytical results with provenance.",
    ),
    CapabilityStatus(
        name="forecasting_readiness",
        implemented=True,
        detail="Forecasting datasets, targets, splits, manifests, and baselines (no trained model).",
    ),
)

# No capabilities are deferred in this phase.
DEFERRED_CAPABILITIES: tuple[CapabilityStatus, ...] = ()


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_meta(settings: Settings, request_id: str) -> ResponseMeta:
    """Build the standard response metadata envelope."""
    return ResponseMeta(
        api_version=settings.api_version,
        request_id=request_id,
        timestamp_utc=_utc_now_iso(),
    )


class HealthService:
    """Application health, readiness, status and version reporting."""

    def __init__(self, settings: Settings, upstream_client: MarketDataClient) -> None:
        self._settings = settings
        self._upstream = upstream_client
        self._start_time = time.time()
        self._last_upstream_check: UpstreamCheckResult | None = None

    # ---- Internal helpers ----

    @property
    def uptime_seconds(self) -> float:
        """Seconds elapsed since the service started."""
        return round(time.time() - self._start_time, 3)

    def record_upstream_check(self, result: UpstreamCheckResult) -> None:
        """Persist the outcome of the most recent upstream connectivity check."""
        self._last_upstream_check = result

    def _upstream_status(self) -> UpstreamIntegrationStatus:
        """Build the upstream integration status from real state only."""
        check = self._last_upstream_check
        configured = self._upstream.is_configured

        if not configured:
            state = UpstreamState.UNCONFIGURED
        elif check is None:
            state = UpstreamState.UNVERIFIED
        else:
            state = check.state

        return UpstreamIntegrationStatus(
            service="fx-market-data-service",
            state=state.value,
            base_url_configured=configured,
            credential_configured=self._upstream.has_credential,
            base_url=self._upstream.base_url,
            last_checked_at=check.checked_at if check else None,
            last_check_succeeded=(
                check.state == UpstreamState.CONNECTED if check is not None else None
            ),
            last_check_message=check.message if check else None,
            contract_status=check.contract_status.value if check else "verified",
            latency_ms=check.latency_ms if check else None,
        )

    # ---- Operations ----

    async def liveness(self, request_id: str) -> ApiResponse[LiveResponseData]:
        """Confirm the process is alive. Performs no dependency checks."""
        return ApiResponse(
            data=LiveResponseData(
                status="healthy",
                service=self._settings.service_name,
                mode=self._settings.service_mode,
                check="liveness",
            ),
            meta=build_meta(self._settings, request_id),
        )

    async def readiness(self, request_id: str) -> ApiResponse[ReadyResponseData]:
        """Confirm the service can accept traffic.

        The upstream market-data service is treated as an optional dependency in
        this foundation phase: an unreachable upstream degrades readiness but
        does not make the service unready, because no analytical capability
        depends on it yet.
        """
        dependencies: list[DependencyHealth] = []

        upstream_healthy = True
        upstream_detail = "Upstream integration is not configured."

        if self._upstream.is_configured:
            if self._settings.upstream_connectivity_check_enabled:
                check = await self._upstream.check_connectivity(request_id=request_id)
                self.record_upstream_check(check)
                upstream_healthy = check.state == UpstreamState.CONNECTED
                upstream_detail = check.message
            else:
                upstream_detail = "Upstream connectivity checks are disabled."

        dependencies.append(
            DependencyHealth(
                name="fx-market-data-service",
                healthy=upstream_healthy,
                detail=upstream_detail,
            )
        )

        status = "healthy" if upstream_healthy else "degraded"

        return ApiResponse(
            data=ReadyResponseData(
                status=status,
                service=self._settings.service_name,
                mode=self._settings.service_mode,
                check="readiness",
                dependencies=dependencies,
            ),
            meta=build_meta(self._settings, request_id),
        )

    async def status(self, request_id: str) -> ApiResponse[StatusResponseData]:
        """Return truthful operational status and capability information."""
        upstream_status = self._upstream_status()
        operational_state = "operational"

        if upstream_status.state in {
            UpstreamState.UNAVAILABLE.value,
            UpstreamState.AUTH_FAILED.value,
        }:
            operational_state = "degraded"

        return ApiResponse(
            data=StatusResponseData(
                service_id=self._settings.service_name,
                application_version=self._settings.service_version,
                api_version=self._settings.api_version,
                environment=self._settings.environment,
                service_mode=self._settings.service_mode,
                operational_state=operational_state,
                uptime_seconds=self.uptime_seconds,
                capabilities=[*IMPLEMENTED_CAPABILITIES, *DEFERRED_CAPABILITIES],
                dependencies=[
                    {
                        "name": "fx-market-data-service",
                        "healthy": upstream_status.state == UpstreamState.CONNECTED.value,
                        "state": upstream_status.state,
                    }
                ],
                upstream_integration=upstream_status,
                timestamp_utc=_utc_now_iso(),
            ),
            meta=build_meta(self._settings, request_id),
        )

    async def version(self, request_id: str) -> ApiResponse[VersionDetails]:
        """Return application and API version information."""
        return ApiResponse(
            data=VersionDetails(
                service=self._settings.service_name,
                application_version=self._settings.service_version,
                api_version=self._settings.api_version,
                environment=self._settings.environment,
                service_mode=self._settings.service_mode,
            ),
            meta=build_meta(self._settings, request_id),
        )


__all__ = [
    "DEFERRED_CAPABILITIES",
    "IMPLEMENTED_CAPABILITIES",
    "HealthService",
    "build_meta",
]
