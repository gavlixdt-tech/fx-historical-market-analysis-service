"""Fetch verified-source market data and prepare a research replay."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from starlette.concurrency import run_in_threadpool

from backend.app.analysis.replay import run_historical_replay
from backend.app.clients.historical_attestation import verify_historical_dataset_attestation
from backend.app.clients.market_data import MarketDataClient
from backend.app.clients.operational_settings import (
    ReplayOperationalParameters,
    resolve_historical_replay_settings,
)
from backend.app.clients.session_context import (
    SessionContextIntegrationError,
    fetch_historical_session_contexts,
)
from backend.app.core.config import Settings
from backend.app.core.errors import (
    DependencyUnavailableError,
    ServiceUnavailableError,
    ValidationError,
)
from backend.app.schemas.replay import HistoricalReplayRequest, ReplayObservationInput
from backend.app.schemas.replay_market_data import HistoricalReplayMarketDataRequest
from backend.app.services.market_data_policy import (
    require_approved_real_instrument,
    require_historical_provider,
)


async def run_market_data_replay(
    payload: HistoricalReplayMarketDataRequest,
    *,
    settings: Settings,
    upstream: MarketDataClient,
    request_id: str,
) -> dict[str, Any]:
    if not upstream.is_configured:
        raise DependencyUnavailableError(
            "fx-market-data-service",
            "UPSTREAM_MARKET_DATA_BASE_URL is not configured.",
        )
    if not settings.upstream_api_key:
        raise DependencyUnavailableError(
            "fx-market-data-service",
            "UPSTREAM_API_KEY is not configured.",
        )
    availability_delay = settings.upstream_replay_availability_delay_seconds
    if availability_delay is None:
        raise ServiceUnavailableError(
            "Historical replay requires UPSTREAM_REPLAY_AVAILABILITY_DELAY_SECONDS "
            "because the market-data contract has no historical publication timestamp."
        )

    provider = await require_historical_provider(
        upstream,
        payload.provider_id,
        request_id=request_id,
        environment=settings.environment,
        real_only=True,
    )
    expected_instrument = require_approved_real_instrument(payload.instrument)

    data = await upstream.fetch_historical_candles(
        payload.instrument,
        provider_id=provider.provider_id,
        start=payload.start,
        end=payload.end,
        timeframe=payload.timeframe,
        price_basis=payload.price_basis,
        limit=payload.limit,
        request_id=request_id,
    )
    service2_received_at = datetime.now(UTC).isoformat()
    if (
        data.provider_id != provider.provider_id
        or data.canonical_instrument != expected_instrument
        or data.timeframe.value != payload.timeframe
        or data.price_basis.value != payload.price_basis
    ):
        raise ValidationError("Market-data response identity does not match the replay request.")
    retrieved_at_attestation = data.retrieved_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    attestation_status = verify_historical_dataset_attestation(
        settings=settings,
        attestation=data.provenance,
        instrument=data.canonical_instrument,
        timeframe=data.timeframe.value,
        provider_id=data.provider_id,
        candles=[candle.model_dump(mode="json") for candle in data.candles],
        retrieved_at=retrieved_at_attestation,
        effective_price_basis=data.price_basis.value,
        coverage=data.coverage.model_dump(mode="json"),
        validation_summary=data.validation_summary.model_dump(mode="json"),
        limitations=data.limitations,
    )
    if not data.coverage.complete:
        raise ValidationError(
            "Market-data coverage is incomplete; replay requires a complete validated interval."
        )
    if data.coverage.rejected_count or data.coverage.duplicate_count:
        raise ValidationError("Market-data response contains rejected or duplicate observations.")
    if data.pagination.has_more:
        raise ValidationError(
            "Market-data response is truncated; reduce the date range before replay."
        )

    session_context_timestamps: list[datetime] = []
    for candle in data.candles:
        if candle.close_time is None:
            raise ValidationError(
                "Market-data response contains a candle without complete close-time data."
            )
        session_context_timestamps.append(candle.close_time)

    try:
        session_contexts = await fetch_historical_session_contexts(
            base_url=settings.upstream_feature_engineering_base_url,
            auth_token=settings.upstream_feature_engineering_auth_token,
            timestamps=session_context_timestamps,
            instrument=data.canonical_instrument,
            timeout_seconds=settings.upstream_timeout_seconds,
            request_id=request_id,
        )
    except SessionContextIntegrationError as exc:
        raise DependencyUnavailableError(
            "fx-feature-engineering-service",
            "Historical session context could not be validated.",
        ) from exc

    observations: list[ReplayObservationInput] = []
    for index, candle in enumerate(data.candles):
        if (
            not candle.valid
            or candle.completeness != "complete"
            or candle.open is None
            or candle.high is None
            or candle.low is None
            or candle.close is None
            or candle.close_time is None
        ):
            raise ValidationError(
                "Market-data response contains a candle without complete OHLC and close-time data."
            )
        if (
            candle.open_time.tzinfo is None
            or candle.close_time.tzinfo is None
            or candle.close_time <= candle.open_time
        ):
            raise ValidationError("Market-data candle timestamps are invalid.")
        if candle.open_time < payload.start or candle.close_time > payload.end:
            raise ValidationError(
                "Market-data response includes candles outside the requested time range."
            )
        source_id = _source_record_id(
            provider_id=payload.provider_id,
            instrument=data.canonical_instrument,
            timeframe=payload.timeframe,
            price_basis=payload.price_basis,
            open_time=candle.open_time.isoformat(),
            source=candle.source,
        )
        observations.append(
            ReplayObservationInput(
                timestamp=candle.close_time,
                available_at=candle.close_time + timedelta(seconds=availability_delay),
                open=_finite_float(candle.open),
                high=_finite_float(candle.high),
                low=_finite_float(candle.low),
                close=_finite_float(candle.close),
                volume=_finite_float(candle.volume) if candle.volume is not None else None,
                source_record_id=source_id,
                session_context=session_contexts[index] if session_contexts is not None else None,
            )
        )

    resolved_settings = await run_in_threadpool(
        resolve_historical_replay_settings,
        settings=settings,
        instrument=data.canonical_instrument,
        timeframe=payload.timeframe,
    )
    if resolved_settings is not None:
        operational_parameters = resolved_settings.parameters
        settings_source = "admin_console"
    else:
        operational_parameters = ReplayOperationalParameters(
            lookback=payload.lookback,
            min_train_samples=payload.min_train_samples,
            validation_mode=payload.validation_mode,
            rolling_window=payload.rolling_window or max(payload.min_train_samples, 250),
            embargo_periods=payload.embargo_periods,
            random_seed=payload.random_seed,
        )
        settings_source = (
            "request_fallback_settings_unavailable" if settings.gfx_settings_enabled else "request"
        )

    replay_request = HistoricalReplayRequest(
        instrument=data.canonical_instrument,
        timeframe=payload.timeframe,
        price_basis="close",
        source_dataset_id=payload.source_dataset_id,
        synthetic=False,
        observations=observations,
        problem=payload.problem,
        lookback=operational_parameters.lookback,
        min_train_samples=operational_parameters.min_train_samples,
        validation_mode=operational_parameters.validation_mode,
        rolling_window=(
            operational_parameters.rolling_window
            if operational_parameters.validation_mode == "rolling"
            else None
        ),
        embargo_periods=operational_parameters.embargo_periods,
        model_families=payload.model_families,
        random_seed=operational_parameters.random_seed,
        final_holdout_start=payload.final_holdout_start,
    )
    result = await run_in_threadpool(run_historical_replay, replay_request)
    result["reproducibility"]["operational_settings"] = {
        "source": settings_source,
        "scope_id": resolved_settings.scope_id if resolved_settings is not None else None,
        "active_version_id": (
            resolved_settings.active_version_id if resolved_settings is not None else None
        ),
        "active_scope_versions": (
            [layer.model_dump(mode="json") for layer in resolved_settings.active_scope_versions]
            if resolved_settings is not None
            else []
        ),
        "content_sha256": (
            resolved_settings.content_sha256 if resolved_settings is not None else None
        ),
        "parameters": operational_parameters.model_dump(mode="json"),
        "rejected_candidate_version_ids": (
            resolved_settings.rejected_candidate_version_ids
            if resolved_settings is not None
            else []
        ),
    }
    if resolved_settings is not None and resolved_settings.rejected_candidate_version_ids:
        result["warnings"].append(
            "One or more pending Admin Console settings versions were rejected by Service 2 "
            "validation and cannot be activated until corrected: "
            + ", ".join(resolved_settings.rejected_candidate_version_ids)
        )
    if settings_source == "request_fallback_settings_unavailable":
        result["warnings"].append(
            "Central Admin Console replay settings were unavailable; explicit request parameters were used."
        )
    result["provenance_status"] = (
        "service1_attestation_verified"
        if attestation_status == "verified"
        else f"service1_attestation_{attestation_status}"
    )
    result["source_authenticity"] = (
        "service1_signer_authenticated"
        if attestation_status == "verified"
        else "not_independently_attested"
    )
    result["source_content_integrity"] = (
        "sha256_and_ed25519_verified"
        if attestation_status == "verified"
        else "not_independently_verified"
    )
    result["vendor_signature_verified"] = False
    result["forecast_eligible"] = False
    result["trading_authorization"] = False
    result["warnings"].append(
        "Historical availability uses candle close time plus a configured lag; "
        "the provider does not supply original publication timestamps."
    )
    result["warnings"].append(
        "The Service 1 Ed25519 signature authenticates the configured Service 1 "
        "signer and exact dataset; it is not a vendor signature over market prices."
        if attestation_status == "verified"
        else "Historical dataset provenance is not independently attested for this replay."
    )
    result["limitations"].extend(
        [
            "The Service 1 signature, when verified, authenticates the configured Service 1 signer; it does not prove that the vendor digitally signed the market prices.",
            "Historical source revisions and original provider publication timestamps are not independently available.",
            "Availability timestamps are derived from bar close time and the configured "
            "publication-lag assumption; this is not point-in-time proof.",
            "Fetched candles and model artifacts are not durably archived by this service.",
        ]
    )
    result["reproducibility"]["data_source"] = {
        "service": "fx-market-data-service",
        "provider_id": payload.provider_id,
        "price_basis": payload.price_basis,
        "retrieved_at": data.retrieved_at.isoformat(),
        "service2_received_at": service2_received_at,
        "observation_timestamp_semantics": "candle_close_time",
        "availability_policy": "candle_close_plus_configured_publication_lag",
        "availability_delay_seconds": availability_delay,
        "availability_provenance": "availability_assumed",
        "historical_attestation_status": attestation_status,
        "historical_attestation_key_id": (
            data.provenance.get("key_id") if isinstance(data.provenance, dict) else None
        ),
        "availability_assumption": (
            "available_at is candle close time plus the configured delay; "
            "Service 1 does not provide original historical publication timestamps."
        ),
        "source_record_identity": (
            "Derived SHA-256 identity from provider, instrument, timeframe, price basis, "
            "candle open time, and source label; Service 1 supplies no stable source-record ID."
        ),
        "coverage": data.coverage.model_dump(mode="json"),
        "validation_summary": data.validation_summary.model_dump(mode="json"),
    }
    result["reproducibility"]["data_source"]["session_context_integration"] = {
        "service": "fx-feature-engineering-service",
        "contract_version": "fx-session-context/v1",
        "state": "contract_verified" if session_contexts is not None else "not_configured",
        "observations": len(session_contexts) if session_contexts is not None else 0,
        "availability_semantics": (
            "deterministic_calendar_context_available_at_candle_close"
            if session_contexts is not None
            else "not_available"
        ),
    }
    if session_contexts is None:
        result["warnings"].append(
            "Historical session context was not integrated because "
            "UPSTREAM_FEATURE_ENGINEERING_BASE_URL is not configured."
        )
        result["limitations"].append(
            "Session-context features are absent from this replay until the "
            "feature-engineering upstream is configured."
        )
    result["status"] = "completed_with_warnings"
    return result


def _finite_float(value: Decimal) -> float:
    try:
        converted = float(value)
    except OverflowError as exc:
        raise ValidationError("Market-data candle contains an out-of-range numeric value.") from exc
    if not (-float("inf") < converted < float("inf")):
        raise ValidationError("Market-data candle contains a non-finite numeric value.")
    return converted


def _source_record_id(
    *,
    provider_id: str,
    instrument: str,
    timeframe: str,
    price_basis: str,
    open_time: str,
    source: str,
) -> str:
    identity = {
        "provider_id": provider_id,
        "instrument": instrument,
        "timeframe": timeframe,
        "price_basis": price_basis,
        "open_time": open_time,
        "source": source,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"market-data:{digest}"
