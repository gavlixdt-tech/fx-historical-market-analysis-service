"""Orchestrate provider-sourced, attested historical analogue retrieval."""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import UTC

from backend.app.analysis.historical_analogues import FEATURE_SET_VERSION, retrieve_historical_analogues
from backend.app.analysis.observations import Observation
from backend.app.analysis.data_quality import validate_historical_payload
from backend.app.clients.historical_attestation import verify_historical_dataset_attestation
from backend.app.clients.market_data import MarketDataClient
from backend.app.core.config import Settings
from backend.app.core.errors import DependencyUnavailableError, ValidationError
from backend.app.schemas.historical_analogues import (
    HistoricalAnalogueRequest,
    HistoricalAnalogueResponseData,
)
from backend.app.services.market_data_policy import (
    require_approved_real_instrument,
    require_historical_provider,
)


class HistoricalAnalogueService:
    """Read-only historical analogue service; no prediction or execution authority."""

    def __init__(self, settings: Settings, upstream_client: MarketDataClient) -> None:
        self._settings = settings
        self._upstream = upstream_client

    async def retrieve(
        self,
        request: HistoricalAnalogueRequest,
        *,
        request_id: str,
    ) -> HistoricalAnalogueResponseData:
        started = time.perf_counter()
        analysis_id = str(uuid.uuid4())
        instrument = require_approved_real_instrument(request.instrument)
        if not self._upstream.is_configured:
            raise DependencyUnavailableError(
                "fx-market-data-service",
                "Historical analogue retrieval requires the Service 1 upstream.",
            )
        provider = await require_historical_provider(
            self._upstream,
            request.provider_id,
            request_id=request_id,
            environment=self._settings.environment,
            real_only=True,
        )
        data = await self._upstream.fetch_historical_candles(
            instrument,
            provider_id=provider.provider_id,
            start=request.start,
            end=request.end,
            timeframe=str(request.timeframe),
            price_basis=str(request.price_basis),
            limit=request.limit,
            request_id=request_id,
        )
        if data.provider_id != provider.provider_id or data.canonical_instrument != instrument:
            raise ValidationError("Historical analogue dataset identity does not match the request.")
        if str(data.timeframe) != str(request.timeframe) or str(data.price_basis) != str(request.price_basis):
            raise ValidationError("Historical analogue timeframe or price basis does not match the request.")

        source_quality = validate_historical_payload(
            data,
            expected_instrument=instrument,
            expected_timeframe=str(request.timeframe),
            expected_price_basis=str(request.price_basis),
        )
        if (
            not source_quality["valid"]
            or not data.coverage.complete
            or data.coverage.rejected_count
            or data.coverage.duplicate_count
            or data.coverage.returned_count != len(data.candles)
            or data.coverage.valid_count != len(data.candles)
            or data.validation_summary.total_received != len(data.candles)
            or data.validation_summary.valid != len(data.candles)
            or data.validation_summary.rejected != 0
            or data.validation_summary.duplicates != 0
            or data.pagination.has_more
        ):
            raise ValidationError(
                "Historical analogue search requires complete, valid, untruncated source coverage."
            )

        candle_records = [candle.model_dump(mode="json") for candle in data.candles]
        integrity_status = verify_historical_dataset_attestation(
            settings=self._settings,
            attestation=data.provenance,
            instrument=data.canonical_instrument,
            timeframe=str(data.timeframe),
            provider_id=data.provider_id,
            candles=candle_records,
            retrieved_at=data.retrieved_at.isoformat(),
            effective_price_basis=str(data.price_basis),
            coverage=data.coverage.model_dump(mode="json"),
            validation_summary=data.validation_summary.model_dump(mode="json"),
            limitations=list(data.limitations),
        )

        observations: list[Observation] = []
        for candle in data.candles:
            if (
                not candle.valid
                or candle.completeness != "complete"
                or candle.open is None
                or candle.high is None
                or candle.low is None
                or candle.close is None
                or candle.close_time is None
                or candle.close_time.tzinfo is None
            ):
                raise ValidationError("Historical analogue dataset contains an incomplete candle.")
            close_time = candle.close_time.astimezone(UTC)
            if close_time > request.end:
                raise ValidationError("Historical analogue dataset contains data after the requested cutoff.")
            observations.append(Observation(
                timestamp=close_time,
                open=float(candle.open),
                high=float(candle.high),
                low=float(candle.low),
                close=float(candle.close),
                volume=float(candle.volume) if candle.volume is not None else None,
            ))
        if any(observations[index].timestamp >= observations[index + 1].timestamp for index in range(len(observations) - 1)):
            raise ValidationError("Historical analogue candles must have unique chronological close times.")

        analysis = retrieve_historical_analogues(
            observations,
            instrument=instrument,
            timeframe=str(request.timeframe),
            context_lookback=request.context_lookback,
            outcome_horizons=request.outcome_horizons,
            top_k=request.top_k,
            minimum_analogue_count=request.minimum_analogue_count,
        )
        fingerprint_payload = {
            "instrument": instrument,
            "timeframe": str(request.timeframe),
            "price_basis": str(request.price_basis),
            "provider_id": provider.provider_id,
            "observations": [
                {
                    "timestamp": item.timestamp.isoformat(),
                    "open": item.open,
                    "high": item.high,
                    "low": item.low,
                    "close": item.close,
                    "volume": item.volume,
                }
                for item in observations
            ],
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        source_provenance = {
            "provider_id": provider.provider_id,
            "provider_type": provider.provider_type.value,
            "retrieved_at": data.retrieved_at.isoformat(),
            "source_integrity_status": integrity_status,
            "availability_provenance": "availability_assumed",
            "historical_publication_time_verified": False,
            "data_quality": source_quality,
            "coverage": data.coverage.model_dump(mode="json"),
            "limitations": list(data.limitations),
        }
        warnings = list(source_quality.get("warnings", []))
        if integrity_status != "verified":
            warnings.append(
                "The Service 1 dataset signature is not verified against a configured out-of-band key; this result is descriptive research only."
            )
        if analysis["status"] != "completed":
            warnings.append("The retrieved history does not contain the minimum number of independent matured analogues.")
        status = (
            "completed"
            if analysis["status"] == "completed" and integrity_status == "verified"
            else "partial"
            if analysis["analogue_count"] > 0
            else "insufficient_data"
        )
        limitations = [
            "A similarity score ranks historical OHLC shape; it is not a probability, forecast, or causal explanation.",
            "Every analogue's outcome horizon is required to mature strictly before the current query window begins.",
            "Top analogues are selected as non-overlapping windows; the baseline distribution includes overlapping candidate windows and is descriptive only.",
            "Historical vendor availability remains assumed from candle close; a verified Service 1 signature authenticates the configured Service 1 signer, not the upstream vendor or original publication time.",
            "OHLC candle anatomy cannot identify institutional participants, dealer inventory, or hidden liquidity.",
            "No prediction or execution authority is granted by this research endpoint.",
        ]
        return HistoricalAnalogueResponseData(
            status=status,
            analysis_id=analysis_id,
            instrument=instrument,
            timeframe=str(request.timeframe),
            provider_id=provider.provider_id,
            price_basis=str(data.price_basis),
            observation_count=len(observations),
            query_window={
                "start": observations[int(analysis["query_start_index"])].timestamp.isoformat(),
                "end": observations[int(analysis["query_end_index"])].timestamp.isoformat(),
            },
            query_features=analysis["query_features"],
            candidate_window_count=int(analysis["candidate_window_count"]),
            analogue_count=int(analysis["analogue_count"]),
            top_k=request.top_k,
            minimum_analogue_count=request.minimum_analogue_count,
            similarity_method="robust_mad_scaled_weighted_euclidean",
            feature_set_version=FEATURE_SET_VERSION,
            analogues=analysis["analogues"],
            outcome_comparison=analysis["outcome_comparison"],
            dataset_fingerprint=fingerprint,
            data_provenance=source_provenance,
            source_integrity_status=integrity_status,
            forecast_eligible=False,
            confidence=None,
            confidence_calibration_status="NOT_CALIBRATED",
            prediction_authorized=False,
            execution_authorized=False,
            warnings=warnings,
            limitations=limitations,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )
