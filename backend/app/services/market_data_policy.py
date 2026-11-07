"""Shared policy for selecting historical providers and approved instruments."""

from __future__ import annotations

from typing import Protocol

from backend.app.core.errors import DependencyUnavailableError, ValidationError
from backend.app.schemas.instruments import (
    GFX_INSTRUMENT_REGISTRY_VERSION,
    canonicalize_gfx_instrument,
)
from backend.app.schemas.upstream import (
    ProviderCapability,
    ProviderType,
    UpstreamProviderListResponse,
    UpstreamProviderSummary,
)


class HistoricalProviderClient(Protocol):
    async def list_providers(self, *, request_id: str) -> UpstreamProviderListResponse: ...

    async def test_provider_connection(self, provider_id: str, *, request_id: str) -> bool: ...


def require_approved_real_instrument(instrument: str) -> str:
    canonical = canonicalize_gfx_instrument(instrument)
    if canonical is None:
        raise ValidationError(
            "The instrument is outside the approved GFX scope "
            f"({GFX_INSTRUMENT_REGISTRY_VERSION})."
        )
    return canonical


async def require_historical_provider(
    client: HistoricalProviderClient,
    provider_id: str | None,
    *,
    request_id: str,
    environment: str,
    real_only: bool = False,
) -> UpstreamProviderSummary:
    """Resolve and enforce an explicitly selected historical provider."""
    from backend.app.core.errors import UpstreamError

    if provider_id is None or not provider_id.strip():
        raise ValidationError("A historical provider must be explicitly selected.")

    try:
        inventory = await client.list_providers(request_id=request_id)
    except UpstreamError as exc:
        raise DependencyUnavailableError(
            "fx-market-data-service", "The provider inventory could not be verified."
        ) from exc

    providers = inventory.data
    if inventory.errors or providers is None:
        raise DependencyUnavailableError(
            "fx-market-data-service", "The provider inventory is unavailable or invalid."
        )

    provider = next(
        (candidate for candidate in providers if candidate.provider_id == provider_id),
        None,
    )
    if provider is None:
        raise ValidationError("The selected historical provider is not registered.")
    if not provider.configured:
        raise ValidationError("The selected historical provider is not configured.")
    if ProviderCapability.HISTORICAL_CANDLES not in provider.capabilities:
        raise ValidationError(
            "The selected provider does not advertise historical-candle capability."
        )

    if provider.provider_type == ProviderType.TEST:
        if real_only or environment not in {"development", "testing"}:
            raise ValidationError(
                "Test providers are permitted only for explicitly selected development or test data."
            )
        return provider
    if provider.provider_type != ProviderType.REAL:
        raise ValidationError("The selected provider type is not supported.")
    if environment == "production":
        raise DependencyUnavailableError(
            "fx-security-access-service",
            "An approved Service 64 workload identity and outbound grant are unavailable.",
        )

    try:
        connected = await client.test_provider_connection(provider_id, request_id=request_id)
    except UpstreamError as exc:
        raise DependencyUnavailableError(
            "fx-market-data-service", "The selected provider connection test failed."
        ) from exc
    if not connected:
        raise DependencyUnavailableError(
            "fx-market-data-service", "The selected provider connection test failed."
        )
    return provider
