from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.app.core.config import Settings
from backend.app.core.errors import (
    DependencyUnavailableError,
    ServiceUnavailableError,
)
from backend.app.core.errors import (
    ValidationError as AppValidationError,
)
from backend.app.schemas.forecasting import ForecastingProblemInput
from backend.app.schemas.replay_market_data import HistoricalReplayMarketDataRequest
from backend.app.schemas.upstream import (
    PriceBasis,
    ProviderCapability,
    ProviderConnectionStatus,
    ProviderType,
    Timeframe,
    UpstreamCoverageReport,
    UpstreamHistoricalCandle,
    UpstreamHistoricalCandleData,
    UpstreamPaginationMetadata,
    UpstreamValidationSummary,
)
from backend.app.services.replay_market_data import run_market_data_replay

START = datetime(2024, 1, 1, tzinfo=UTC)


def _request() -> HistoricalReplayMarketDataRequest:
    return HistoricalReplayMarketDataRequest(
        instrument="EUR/USD",
        timeframe="D1",
        price_basis="midpoint",
        provider_id="real-provider",
        source_dataset_id="provider-dataset-2024",
        start=START,
        end=START + timedelta(days=52),
        limit=2000,
        problem=ForecastingProblemInput(
            problem_id="market-data-replay",
            instrument_scope=["EUR/USD"],
            input_timeframe="D1",
            price_basis="close",
            prediction_horizon=1,
            required_historical_coverage=20,
        ),
    )


def _upstream_data(*, complete: bool = True) -> UpstreamHistoricalCandleData:
    candles = []
    for index in range(52):
        open_time = START + timedelta(days=index)
        close_time = open_time + timedelta(days=1)
        close = Decimal("1.1") + Decimal(index) / Decimal("10000")
        candles.append(
            UpstreamHistoricalCandle(
                provider_id="real-provider",
                instrument="EUR/USD",
                base_currency="EUR",
                quote_currency="USD",
                timeframe="D1",
                price_basis="midpoint",
                open_time=open_time,
                close_time=close_time,
                open=close,
                high=close + Decimal("0.001"),
                low=close - Decimal("0.001"),
                close=close,
                volume=None,
                completeness="complete",
                valid=True,
            )
        )
    return UpstreamHistoricalCandleData(
        provider_id="real-provider",
        canonical_instrument="EUR/USD",
        requested_start=START,
        requested_end=START + timedelta(days=52),
        effective_start=START,
        effective_end=START + timedelta(days=52),
        timeframe=Timeframe.D1,
        price_basis=PriceBasis.MIDPOINT,
        candles=candles,
        coverage=UpstreamCoverageReport(
            requested_start=START,
            requested_end=START + timedelta(days=52),
            actual_start=START,
            actual_end=START + timedelta(days=52),
            returned_count=52,
            valid_count=52,
            rejected_count=0,
            duplicate_count=0,
            status="complete" if complete else "partial",
            complete=complete,
        ),
        validation_summary=UpstreamValidationSummary(
            total_received=52,
            valid=52,
            rejected=0,
            duplicates=0,
        ),
        pagination=UpstreamPaginationMetadata(limit=2000, has_more=False),
        retrieved_at=START + timedelta(days=53),
    )


class _FakeMarketDataClient:
    is_configured = True

    def __init__(
        self,
        *,
        provider_type: ProviderType = ProviderType.REAL,
        data: UpstreamHistoricalCandleData | None = None,
        connection_success: bool = True,
    ) -> None:
        self.provider_type = provider_type
        self.data = data or _upstream_data()
        self.connection_success = connection_success

    async def list_providers(self, *, request_id: str) -> SimpleNamespace:
        provider = SimpleNamespace(
            provider_id="real-provider",
            provider_type=self.provider_type,
            configured=True,
            connection_status=ProviderConnectionStatus.AVAILABLE,
            capabilities=[ProviderCapability.HISTORICAL_CANDLES],
        )
        return SimpleNamespace(data=[provider], errors=[])

    async def test_provider_connection(
        self,
        provider_id: str,
        *,
        request_id: str,
    ) -> bool:
        assert provider_id == "real-provider"
        assert request_id == "request-1"
        return self.connection_success

    async def fetch_historical_candles(self, instrument: str, **kwargs: object):
        assert instrument == "EUR/USD"
        assert kwargs["request_id"] == "request-1"
        return self.data


def _settings(delay: int | None = 60) -> Settings:
    return Settings(
        upstream_market_data_base_url="https://market-data.example",
        upstream_api_key="test-key",
        upstream_replay_availability_delay_seconds=delay,
    )


@pytest.mark.asyncio
async def test_market_data_replay_derives_and_reports_availability_assumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    def fake_run(replay_request):
        captured["request"] = replay_request
        return {
            "status": "completed",
            "warnings": [],
            "limitations": [],
            "reproducibility": {},
        }

    monkeypatch.setattr(
        "backend.app.services.replay_market_data.run_historical_replay",
        fake_run,
    )
    result = await run_market_data_replay(
        _request(),
        settings=_settings(),
        upstream=_FakeMarketDataClient(),
        request_id="request-1",
    )

    replay_request = captured["request"]
    assert replay_request.observations[0].timestamp == START + timedelta(days=1)
    assert replay_request.observations[0].available_at == START + timedelta(days=1, seconds=60)
    assert replay_request.observations[0].source_record_id.startswith("market-data:")
    assert result["provenance_status"] == "provider_asserted_unverified"
    assert result["status"] == "completed_with_warnings"
    assert (
        result["reproducibility"]["data_source"]["availability_provenance"]
        == "assumption_not_provider_timestamp"
    )


@pytest.mark.asyncio
async def test_market_data_replay_requires_availability_lag_configuration() -> None:
    with pytest.raises(ServiceUnavailableError, match="UPSTREAM_REPLAY_AVAILABILITY_DELAY_SECONDS"):
        await run_market_data_replay(
            _request(),
            settings=_settings(None),
            upstream=_FakeMarketDataClient(),
            request_id="request-1",
        )


@pytest.mark.asyncio
async def test_market_data_replay_rejects_test_providers() -> None:
    with pytest.raises(AppValidationError, match="real historical-candle provider"):
        await run_market_data_replay(
            _request(),
            settings=_settings(),
            upstream=_FakeMarketDataClient(provider_type=ProviderType.TEST),
            request_id="request-1",
        )


@pytest.mark.asyncio
async def test_market_data_replay_requires_successful_live_provider_test() -> None:
    with pytest.raises(DependencyUnavailableError):
        await run_market_data_replay(
            _request(),
            settings=_settings(),
            upstream=_FakeMarketDataClient(connection_success=False),
            request_id="request-1",
        )


@pytest.mark.asyncio
async def test_market_data_replay_rejects_incomplete_provider_coverage() -> None:
    with pytest.raises(AppValidationError, match="coverage is incomplete"):
        await run_market_data_replay(
            _request(),
            settings=_settings(),
            upstream=_FakeMarketDataClient(data=_upstream_data(complete=False)),
            request_id="request-1",
        )
