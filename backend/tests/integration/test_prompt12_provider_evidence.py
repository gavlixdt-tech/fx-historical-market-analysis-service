"""Prompt 12 provider evidence tests (mock-based, no real market data)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from backend.app.clients.base import UpstreamState
from backend.app.clients.market_data import MarketDataClient
from backend.app.core.config import Settings
from backend.app.services.forecasting_service import ForecastingService

FIXTURES = Path(__file__).parent.parent / "contract" / "fixtures"


def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _client(handler, **kwargs):
    return MarketDataClient(
        base_url="https://upstream.test.invalid",
        api_key=kwargs.pop("api_key", "test-upstream-key"),
        transport=handler,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_test_adapter_is_classified_as_synthetic():
    payload = _fixture("upstream_history_synthetic.json")

    def handler(request):
        return httpx.Response(200, json=payload)

    client = _client(httpx.MockTransport(handler))
    settings = Settings(
        environment="testing",
        log_format="console",
        log_level="warning",
        upstream_market_data_base_url="https://upstream.test.invalid",
    )
    service = ForecastingService(settings, client)
    req = SimpleNamespace(
        instrument="SYNTH/USD",
        timeframe="D1",
        price_basis="bid",
        start=None,
        end=None,
        provider_id="synthetic-test-adapter",
        limit=5,
    )
    result = await service.retrieve_historical_dataset(req, "prompt12-synthetic")
    assert result["synthetic"] is True
    assert result["provenance"]["provider_type"] == "test"
    assert result["provenance"]["provenance_status"] == "synthetic_fixture"
    assert result["provenance"]["verified_real_market_data"] is False
    assert result["provenance"]["real_market_research_accepted"] is False


@pytest.mark.asyncio
async def test_non_test_provider_is_not_verified_real_data():
    payload = _fixture("upstream_history_synthetic.json")
    payload["data"]["provider_id"] = "candidate-provider"
    payload["data"]["candles"][0]["source"] = "candidate-provider"
    payload["data"]["candles"][0]["metadata"]["fixture"] = False
    payload["data"]["candles"][0]["metadata"]["source_metadata"]["fixture"] = False

    def handler(request):
        return httpx.Response(200, json=payload)

    client = _client(httpx.MockTransport(handler))
    settings = Settings(
        environment="testing",
        log_format="console",
        log_level="warning",
        upstream_market_data_base_url="https://upstream.test.invalid",
    )
    service = ForecastingService(settings, client)
    req = SimpleNamespace(
        instrument="EURUSD",
        timeframe="D1",
        price_basis="bid",
        start=None,
        end=None,
        provider_id="candidate-provider",
        limit=5,
    )
    result = await service.retrieve_historical_dataset(req, "prompt12-candidate")
    assert result["synthetic"] is False
    assert result["provenance"]["provider_type"] == "genuine"
    assert result["provenance"]["provenance_status"] == "genuine_source_unverified"
    assert result["provenance"]["verified_real_market_data"] is False


@pytest.mark.asyncio
async def test_research_readiness_blocks_synthetic_provider():
    payload = _fixture("upstream_history_synthetic.json")

    def handler(request):
        return httpx.Response(200, json=payload)

    client = _client(httpx.MockTransport(handler))
    settings = Settings(
        environment="testing",
        log_format="console",
        log_level="warning",
        upstream_market_data_base_url="https://upstream.test.invalid",
    )
    service = ForecastingService(settings, client)
    from backend.app.schemas.forecasting import ForecastingProblemInput

    problem = ForecastingProblemInput(
        problem_id="real_market_research",
        version="1.0.0",
        instrument_scope=["SYNTH/USD"],
        input_timeframe="D1",
        required_historical_coverage=1,
    )
    req = SimpleNamespace(
        observations=None,
        instrument="SYNTH/USD",
        timeframe="D1",
        start=None,
        end=None,
        provider_id="synthetic-test-adapter",
        price_basis="bid",
        limit=5,
        problem=problem,
        required_historical_coverage=1,
    )
    result = await service.assess_research_readiness(req, "prompt12-readiness")
    assert result["ready"] is False
    assert any(f.get("code") == "synthetic_data" for f in result["findings"])
