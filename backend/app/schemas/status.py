"""Service status response schemas.

The status endpoint reports truthful operational state. It deliberately
separates *what is implemented* from *what is planned* so that a client can
never mistake a reserved capability for a working one.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CapabilityStatus(BaseModel):
    """Status of a single capability."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="Capability identifier")
    implemented: bool = Field(..., description="Whether the capability is implemented")
    detail: str | None = Field(default=None, description="Human-readable description")


class UpstreamIntegrationStatus(BaseModel):
    """Connection state of the configured upstream market-data service.

    The state vocabulary is deliberately explicit so that the dashboard can
    distinguish *not configured* from *configured but never verified* from
    *verified reachable* and from *authentication failed*.
    """

    model_config = ConfigDict(frozen=True)

    service: str = Field(..., description="Upstream service identifier")
    state: str = Field(
        ...,
        description=("One of: unconfigured, unverified, connected, unavailable, auth_failed"),
    )
    base_url_configured: bool = Field(
        default=False, description="Whether an upstream base URL is configured"
    )
    credential_configured: bool = Field(
        default=False, description="Whether an upstream credential is configured"
    )
    base_url: str | None = Field(
        default=None,
        description="Configured upstream base URL (no credentials are ever included)",
    )
    last_checked_at: str | None = Field(
        default=None, description="UTC timestamp of the last connectivity check"
    )
    last_check_succeeded: bool | None = Field(
        default=None, description="Outcome of the last connectivity check"
    )
    last_check_message: str | None = Field(
        default=None, description="Safe summary of the last connectivity check"
    )
    contract_status: str = Field(
        default="verified",
        description=(
            "Upstream contract verification status: 'verified' or " "'proposed-not-yet-verified'"
        ),
    )
    latency_ms: float | None = Field(
        default=None, description="Latency of the last successful check in milliseconds"
    )


class StatusResponseData(BaseModel):
    """Status endpoint response payload."""

    model_config = ConfigDict(frozen=True)

    service_id: str = Field(..., description="Service identifier")
    application_version: str = Field(..., description="Application version")
    api_version: str = Field(..., description="API version")
    environment: str = Field(..., description="Deployment environment")
    service_mode: str = Field(..., description="Operating mode")
    operational_state: str = Field(
        ...,
        description="'operational', 'degraded' or 'maintenance'",
    )
    uptime_seconds: float | None = Field(
        default=None, description="Process uptime in seconds, if available"
    )
    capabilities: list[CapabilityStatus] = Field(
        default_factory=list, description="Implemented and planned capabilities"
    )
    dependencies: list[dict[str, Any]] = Field(
        default_factory=list, description="Dependency health summary"
    )
    upstream_integration: UpstreamIntegrationStatus = Field(
        default_factory=lambda: UpstreamIntegrationStatus(
            service="fx-market-data-service",
            state="unconfigured",
        ),
        description="Status of the upstream market-data integration",
    )
    timestamp_utc: str = Field(..., description="UTC ISO 8601 status timestamp")
