"""Fetch verified-source market data and prepare a research replay."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

from starlette.concurrency import run_in_threadpool

from backend.app.analysis.replay import run_historical_replay
from backend.app.clients.market_data import MarketDataClient
from backend.app.core.config import Settings
from backend.app.core.errors import (
    DependencyUnavailableError,
    ServiceUnavailableError,
    ValidationError,
)
from backend.app.schemas.replay import HistoricalReplayRequest, ReplayObservationInput
from backend.app.schemas.replay_market_data import HistoricalReplayMarketDataRequest
from backend.app.schemas.upstream import (
    ProviderCapability,
    ProviderType,
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

    providers = await upstream.list_providers(request_id=request_id)
    if providers.errors or providers.data is None:
        raise DependencyUnavailableError(
            "fx-market-data-service",
            "Provider inventory is unavailable or invalid.",
        )
    provider = next(
        (item for item in providers.data if item.provider_id == payload.provider_id),
        None,
    )
    if (
        provider is None
        or provider.provider_type != ProviderType.REAL
        or not provider.configured
        or ProviderCapability.HISTORICAL_CANDLES not in provider.capabilities
    ):
        raise ValidationError(
            "The selected provider must be configured as a real historical-candle provider."
        )
    if not await upstream.test_provider_connection(
        payload.provider_id,
        request_id=request_id,
    ):
        raise DependencyUnavailableError(
            "fx-market-data-service",
            "The selected real market-data provider failed its live connection test.",
        )

    data = await upstream.fetch_historical_candles(
        payload.instrument,
        provider_id=payload.provider_id,
        start=payload.start,
        end=payload.end,
        timeframe=payload.timeframe,
        price_basis=payload.price_basis,
        limit=payload.limit,
        request_id=request_id,
    )
    if (
        data.provider_id != payload.provider_id
        or data.canonical_instrument != payload.instrument
        or data.timeframe.value != payload.timeframe
        or data.price_basis.value != payload.price_basis
    ):
        raise ValidationError("Market-data response identity does not match the replay request.")
    if not data.coverage.complete:
        raise ValidationError(
            "Market-data coverage is incomplete; replay requires a complete validated interval."
        )
    if data.coverage.rejected_count or data.coverage.duplicate_count:
        raise ValidationError(
            "Market-data response contains rejected or duplicate observations."
        )
    if data.pagination.has_more:
        raise ValidationError(
            "Market-data response is truncated; reduce the date range before replay."
        )

    observations: list[ReplayObservationInput] = []
    for candle in data.candles:
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
            )
        )

    replay_request = HistoricalReplayRequest(
        instrument=data.canonical_instrument,
        timeframe=payload.timeframe,
        price_basis="close",
        source_dataset_id=payload.source_dataset_id,
        synthetic=False,
        observations=observations,
        problem=payload.problem,
        lookback=payload.lookback,
        min_train_samples=payload.min_train_samples,
        validation_mode=payload.validation_mode,
        rolling_window=payload.rolling_window,
        embargo_periods=payload.embargo_periods,
        model_families=payload.model_families,
        random_seed=payload.random_seed,
        final_holdout_start=payload.final_holdout_start,
    )
    result = await run_in_threadpool(run_historical_replay, replay_request)
    result["provenance_status"] = "provider_asserted_unverified"
    result["warnings"].append(
        "Historical availability uses candle close time plus a configured lag; "
        "the provider does not supply original publication timestamps."
    )
    result["limitations"].extend(
        [
            "Market-data provider identity is configured and connection-tested, "
            "but source records and historical revisions are not independently signed.",
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
        "availability_policy": "candle_close_plus_configured_publication_lag",
        "availability_delay_seconds": availability_delay,
        "availability_provenance": "assumption_not_provider_timestamp",
        "coverage": data.coverage.model_dump(mode="json"),
        "validation_summary": data.validation_summary.model_dump(mode="json"),
    }
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
