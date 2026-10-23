"""Prompt 11 integration validation tests (mock-based local software validation)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from backend.app.clients.base import UpstreamState
from backend.app.clients.market_data import MarketDataClient
from backend.app.core.config import Settings
from backend.app.core.errors import UpstreamError, ValidationError
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
async def test_missing_configuration_fails_clearly():
    client = MarketDataClient(base_url=None)
    assert not client.is_configured
    with pytest.raises(UpstreamError):
        await client.fetch_historical_candles("EURUSD")


@pytest.mark.asyncio
async def test_connection_timeout_is_reported():
    def handler(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    client = _client(httpx.MockTransport(handler))
    result = await client.check_connectivity()
    assert result.state == UpstreamState.UNAVAILABLE
    with pytest.raises(UpstreamError) as exc:
        await client.fetch_historical_candles("EURUSD")
    assert exc.value.details.get("error_type") == "timeout"


@pytest.mark.asyncio
async def test_connection_refusal_is_reported():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    client = _client(httpx.MockTransport(handler))
    result = await client.check_connectivity()
    assert result.state == UpstreamState.UNAVAILABLE
    with pytest.raises(UpstreamError):
        await client.fetch_historical_candles("EURUSD")


@pytest.mark.asyncio
async def test_upstream_error_is_sanitised():
    def handler(request):
        return httpx.Response(409, json={"error": {"code": "x", "message": "secret"}})

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(UpstreamError) as exc:
        await client.fetch_historical_candles("EURUSD")
    assert exc.value.status_code == 502
    assert "secret" not in str(exc.value)


@pytest.mark.asyncio
async def test_malformed_payload_is_rejected():
    def handler(request):
        return httpx.Response(200, json={"unexpected": "shape"})

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(UpstreamError):
        await client.fetch_historical_candles("EURUSD")


@pytest.mark.asyncio
async def test_correlation_id_is_propagated():
    captured = {}

    def handler(request):
        captured["h"] = dict(request.headers)
        return httpx.Response(200, json=_fixture("upstream_history_synthetic.json"))

    client = _client(httpx.MockTransport(handler))
    await client.fetch_historical_candles("SYNTH/USD", request_id="corr-123")
    assert captured["h"]["x-request-id"] == "corr-123"


@pytest.mark.asyncio
async def test_retrieve_does_not_silently_fallback():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    client = _client(httpx.MockTransport(handler))
    settings = Settings(environment="testing", log_format="console", log_level="warning",
                       upstream_market_data_base_url="https://upstream.test.invalid")
    service = ForecastingService(settings, client)
    from types import SimpleNamespace
    req = SimpleNamespace(instrument="EURUSD", timeframe="D1", price_basis="bid",
                          start=None, end=None, provider_id="test-adapter", limit=5)
    with pytest.raises((UpstreamError, ValidationError)):
        await service.retrieve_historical_dataset(req, "req-1")


@pytest.mark.asyncio
async def test_empty_response_quality():
    payload = _fixture("upstream_history_synthetic.json")
    payload["data"]["candles"] = []
    payload["data"]["coverage"]["returned_count"] = 0
    payload["data"]["coverage"]["valid_count"] = 0
    payload["data"]["validation_summary"]["valid"] = 0
    payload["data"]["validation_summary"]["total_received"] = 0

    def handler(request):
        return httpx.Response(200, json=payload)

    client = _client(httpx.MockTransport(handler))
    settings = Settings(environment="testing", log_format="console", log_level="warning",
                       upstream_market_data_base_url="https://upstream.test.invalid")
    service = ForecastingService(settings, client)
    from types import SimpleNamespace
    req = SimpleNamespace(instrument="SYNTH/USD", timeframe="D1", price_basis="bid",
                          start=None, end=None, provider_id="synthetic-test-adapter", limit=5)
    result = await service.retrieve_historical_dataset(req, "req-2")
    assert result["quality"]["row_count"] == 0


@pytest.mark.asyncio
async def test_live_upstream_if_available():
    base_url = os.getenv("UPSTREAM_MARKET_DATA_BASE_URL")
    if not base_url or os.getenv("RUN_LIVE_UPSTREAM_TESTS") != "1":
        pytest.skip("live upstream prerequisites unavailable")
    client = MarketDataClient(base_url=base_url, timeout_seconds=10.0)
    try:
        check = await client.check_connectivity(request_id="prompt11-live")
        assert check.state in {UpstreamState.CONNECTED, UpstreamState.UNAVAILABLE, UpstreamState.AUTH_FAILED}
        if check.state == UpstreamState.CONNECTED:
            data = await client.fetch_historical_candles(
                os.getenv("PROMPT11_TEST_INSTRUMENT", "EURUSD"),
                provider_id=os.getenv("UPSTREAM_DEFAULT_PROVIDER_ID", "test-adapter"),
                timeframe="D1", price_basis="bid", limit=5,
                request_id="prompt11-live-history")
            assert data.canonical_instrument
    finally:
        await client.aclose()