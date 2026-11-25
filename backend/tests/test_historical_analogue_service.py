from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from backend.app.schemas.historical_analogues import HistoricalAnalogueRequest
from backend.app.schemas.upstream import (
    PriceBasis,
    Timeframe,
    UpstreamCoverageReport,
    UpstreamHistoricalCandle,
    UpstreamHistoricalCandleData,
    UpstreamPaginationMetadata,
    UpstreamValidationSummary,
)
from backend.app.services import historical_analogue_service as service_module


def _history(now: datetime) -> UpstreamHistoricalCandleData:
    candles = []
    previous = 100.0
    start = now - timedelta(minutes=501)
    for index in range(500):
        change = 0.0012 * math.sin(index / 3.0) + 0.0004 * math.cos(index / 7.0)
        close = previous * math.exp(change)
        open_time = start + timedelta(minutes=index)
        candles.append(UpstreamHistoricalCandle(
            provider_id="twelve-data",
            instrument="EUR/USD",
            base_currency="EUR",
            quote_currency="USD",
            timeframe="M1",
            price_basis="vendor_defined",
            open_time=open_time,
            close_time=open_time + timedelta(minutes=1),
            open=str(previous),
            high=str(max(previous, close) * 1.0005),
            low=str(min(previous, close) * 0.9995),
            close=str(close),
            volume=None,
            price_basis=PriceBasis.VENDOR_DEFINED,
            volume_kind=None,
            source="twelve-data",
            retrieved_at=now,
            completeness="complete",
            valid=True,
            validation_error=None,
            metadata={},
        ))
        previous = close
    coverage = UpstreamCoverageReport(
        requested_start=candles[0].open_time,
        requested_end=candles[-1].open_time,
        actual_start=candles[0].open_time,
        actual_end=candles[-1].open_time,
        expected_intervals=500,
        returned_count=500,
        valid_count=500,
        rejected_count=0,
        duplicate_count=0,
        missing_intervals=[],
        max_consecutive_missing_intervals=0,
        status="complete",
        complete=True,
        provider_limited=False,
        notes=[],
    )
    return UpstreamHistoricalCandleData(
        provider_id="twelve-data",
        canonical_instrument="EUR/USD",
        requested_start=candles[0].open_time,
        requested_end=candles[-1].open_time,
        effective_start=candles[0].open_time,
        effective_end=candles[-1].open_time,
        timeframe=Timeframe.M1,
        price_basis=PriceBasis.VENDOR_DEFINED,
        candles=candles,
        coverage=coverage,
        validation_summary=UpstreamValidationSummary(
            total_received=500, valid=500, rejected=0, duplicates=0
        ),
        pagination=UpstreamPaginationMetadata(limit=5000, has_more=False),
        retrieved_at=now,
        limitations=[],
        provenance={"test": "signature-is-mocked"},
    )


def test_historical_analogue_service_uses_provider_history_and_requires_attestation(monkeypatch: Any) -> None:
    now = datetime.now(UTC)
    data = _history(now)
    provider = SimpleNamespace(provider_id="twelve-data", provider_type=SimpleNamespace(value="real"))

    async def fake_provider(*args: Any, **kwargs: Any) -> Any:
        return provider

    def fake_instrument(value: str) -> str:
        return "EUR/USD"

    def fake_verify(**kwargs: Any) -> str:
        assert kwargs["instrument"] == "EUR/USD"
        assert kwargs["provider_id"] == "twelve-data"
        assert len(kwargs["candles"]) == 500
        return "verified"

    class FakeUpstream:
        is_configured = True

        async def fetch_historical_candles(self, *args: Any, **kwargs: Any) -> UpstreamHistoricalCandleData:
            assert kwargs["provider_id"] == "twelve-data"
            assert kwargs["price_basis"] == "vendor_defined"
            assert kwargs["limit"] == 5000
            return data

    monkeypatch.setattr(service_module, "require_historical_provider", fake_provider)
    monkeypatch.setattr(service_module, "require_approved_real_instrument", fake_instrument)
    monkeypatch.setattr(service_module, "verify_historical_dataset_attestation", fake_verify)

    from backend.app.core.config import Settings

    settings = Settings.model_construct(
        environment="research-simulation",
        upstream_historical_attestation_required=False,
        upstream_historical_attestation_public_keys_json="{}",
    )
    service = service_module.HistoricalAnalogueService(settings, FakeUpstream())
    request = HistoricalAnalogueRequest(
        instrument="EUR/USD",
        timeframe=Timeframe.M1,
        provider_id="twelve-data",
        price_basis=PriceBasis.VENDOR_DEFINED,
        end=now,
        limit=5000,
        context_lookback=20,
        outcome_horizons=[1, 3, 5, 10, 20],
        top_k=10,
        minimum_analogue_count=5,
    )
    result = asyncio.run(service.retrieve(request, request_id="test-request"))
    assert result.status == "completed"
    assert result.source_integrity_status == "verified"
    assert result.analogue_count >= 5
    assert result.forecast_eligible is False
    assert result.confidence is None
    assert result.prediction_authorized is False
    assert result.execution_authorized is False
