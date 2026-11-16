from __future__ import annotations

from datetime import UTC, datetime, timedelta
import base64
import hashlib
from decimal import Decimal
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from backend.app.core.config import Settings
from backend.app.clients.historical_attestation import canonical_json
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
            expected_intervals=52,
            returned_count=52,
            valid_count=52,
            rejected_count=0,
            duplicate_count=0,
            missing_intervals=[],
            max_consecutive_missing_intervals=0,
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


def _attested_data() -> tuple[UpstreamHistoricalCandleData, str]:
    private_key = Ed25519PrivateKey.generate()
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key = base64.b64encode(public_bytes).decode("ascii")
    data = _upstream_data()
    candles = [item.model_copy(update={"source": "real-provider"}) for item in data.candles]
    data = data.model_copy(update={"candles": candles})
    retrieved_at = data.retrieved_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    projected = [
        {
            "timestamp": item.close_time.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "open": str(item.open),
            "high": str(item.high),
            "low": str(item.low),
            "close": str(item.close),
            "volume": str(item.volume) if item.volume is not None else None,
        }
        for item in sorted(candles, key=lambda item: item.close_time or START, reverse=True)
    ]
    digest = hashlib.sha256(
        canonical_json({"instrument": "EUR/USD", "timeframe": "1D", "candles": projected})
    ).hexdigest()
    source_metadata = {
        "provider_id": "real-provider",
        "service1_timeframe": "D1",
        "indicator_timeframe": "1D",
        "price_basis": "midpoint",
        "retrieved_at": retrieved_at,
        "coverage": data.coverage.model_dump(mode="json"),
        "validation_summary": data.validation_summary.model_dump(mode="json"),
        "candle_sources": ["real-provider"],
        "volume_kinds": [],
        "limitations": data.limitations,
    }
    attestation = {
        "version": "1",
        "purpose": "indicator-candle-dataset",
        "algorithm": "Ed25519",
        "provider_id": "real-provider",
        "source_id": f"historical:real-provider:{digest[:24]}",
        "key_id": "service1-historical-test",
        "issued_at": retrieved_at,
        "observed_at": retrieved_at,
        "instrument": "EUR/USD",
        "timeframe": "1D",
        "dataset_sha256": digest,
        "quality": {
            "is_final": True,
            "valid": True,
            "coverage_complete": True,
            "rejected_count": 0,
            "duplicate_count": 0,
            "candle_count": len(candles),
        },
        "volume_semantics": "not_supplied",
        "source_metadata": source_metadata,
    }
    attestation["signature"] = "ed25519=" + base64.b64encode(
        private_key.sign(canonical_json(attestation))
    ).decode("ascii")
    return data.model_copy(update={"provenance": attestation}), (
        '{"service1-historical-test":"' + public_key + '"}'
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


def _settings(
    delay: int | None = 60,
    *,
    public_keys_json: str = "{}",
    attestation_required: bool = False,
) -> Settings:
    return Settings(
        upstream_market_data_base_url="https://market-data.example",
        upstream_api_key="test-key",
        upstream_replay_availability_delay_seconds=delay,
        upstream_historical_attestation_public_keys_json=public_keys_json,
        upstream_historical_attestation_required=attestation_required,
    )


def test_market_data_replay_requires_canonical_instrument() -> None:
    body = _request().model_dump()
    body["instrument"] = "EURUSD"
    with pytest.raises(ValueError, match="canonical slash-delimited"):
        HistoricalReplayMarketDataRequest.model_validate(body)


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
    assert result["provenance_status"] == "service1_attestation_missing"
    assert result["source_authenticity"] == "not_independently_attested"
    assert result["source_content_integrity"] == "not_independently_verified"
    assert result["vendor_signature_verified"] is False
    assert result["forecast_eligible"] is False
    assert result["trading_authorization"] is False
    assert result["status"] == "completed_with_warnings"
    assert (
        result["reproducibility"]["data_source"]["availability_provenance"]
        == "availability_assumed"
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
    with pytest.raises(AppValidationError, match="Test providers are permitted"):
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
async def test_market_data_replay_blocks_unapproved_production_workload_identity() -> None:
    settings = Settings(
        environment="production",
        require_auth=True,
        api_key="t" * 32,
        upstream_market_data_base_url="https://market-data.example",
        upstream_api_key="u" * 32,
        upstream_replay_availability_delay_seconds=60,
        upstream_historical_attestation_public_keys_json='{"service1-key":"'
        + "a2tra2tra2tra2tra2tra2tra2tra2tra2tra2tra2s="
        + '"}',
        upstream_historical_attestation_required=True,
    )
    with pytest.raises(DependencyUnavailableError, match="fx-security-access-service"):
        await run_market_data_replay(
            _request(),
            settings=settings,
            upstream=_FakeMarketDataClient(),
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



def test_replay_request_accepts_provider_defined_price_basis() -> None:
    body = _request().model_dump(mode="json")
    body["price_basis"] = "vendor_defined"
    request = HistoricalReplayMarketDataRequest.model_validate(body)
    assert request.price_basis == "vendor_defined"
    assert PriceBasis.VENDOR_DEFINED.value == "vendor_defined"



@pytest.mark.asyncio
async def test_market_data_replay_verifies_service1_historical_attestation(
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
    data, public_keys = _attested_data()
    result = await run_market_data_replay(
        _request(),
        settings=_settings(public_keys_json=public_keys, attestation_required=True),
        upstream=_FakeMarketDataClient(data=data),
        request_id="request-1",
    )

    assert result["provenance_status"] == "service1_attestation_verified"
    assert result["source_authenticity"] == "service1_signer_authenticated"
    assert result["source_content_integrity"] == "sha256_and_ed25519_verified"
    assert result["vendor_signature_verified"] is False
    assert result["forecast_eligible"] is False
    assert result["reproducibility"]["data_source"]["historical_attestation_status"] == "verified"
    assert captured["request"].observations
