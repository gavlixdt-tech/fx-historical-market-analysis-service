"""Tests for the upstream market-data client."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from backend.app.clients.base import UpstreamState
from backend.app.clients.market_data import MarketDataClient
from backend.app.core.errors import UpstreamError

FIXTURES = Path(__file__).parent.parent / "contract" / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _client(handler: httpx.MockTransport, **kwargs: object) -> MarketDataClient:
    return MarketDataClient(
        base_url="https://upstream.test.invalid",
        api_key=kwargs.pop("api_key", "test-upstream-key"),  # type: ignore[arg-type]
        transport=handler,
        **kwargs,  # type: ignore[arg-type]
    )


def test_unconfigured_client_reports_unconfigured() -> None:
    client = MarketDataClient(base_url=None)

    assert client.is_configured is False
    assert client.has_credential is False


async def test_connectivity_check_reports_connected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/health/live"
        return httpx.Response(200, json={"data": {"status": "healthy"}})

    client = _client(httpx.MockTransport(handler))
    result = await client.check_connectivity()

    assert result.state == UpstreamState.CONNECTED
    assert result.latency_ms is not None
    assert result.checked_at is not None


async def test_connectivity_check_reports_unavailable_on_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    client = _client(httpx.MockTransport(handler))
    result = await client.check_connectivity()

    assert result.state == UpstreamState.UNAVAILABLE


async def test_connectivity_check_reports_auth_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"code": "unauthenticated"}})

    client = _client(httpx.MockTransport(handler))
    result = await client.check_connectivity()

    assert result.state == UpstreamState.AUTH_FAILED
    assert "credential" in result.message.lower()


async def test_connectivity_check_reports_server_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"code": "unavailable"}})

    client = _client(httpx.MockTransport(handler))
    result = await client.check_connectivity()

    assert result.state == UpstreamState.UNAVAILABLE


async def test_fetch_historical_candles_sends_verified_parameters() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        captured["headers"] = dict(request.headers)
        return httpx.Response(200, json=_fixture("upstream_history_synthetic.json"))

    client = _client(httpx.MockTransport(handler))
    data = await client.fetch_historical_candles(
        "SYNTH/USD",
        provider_id="synthetic-test-adapter",
        timeframe="D1",
        price_basis="bid",
        limit=500,
        request_id="req-42",
    )

    assert captured["path"] == "/api/v1/market-data/history/SYNTH_USD"
    params = captured["params"]
    assert isinstance(params, dict)
    assert params["provider_id"] == "synthetic-test-adapter"
    assert params["timeframe"] == "D1"
    assert params["price_basis"] == "bid"
    assert params["limit"] == "500"

    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["x-api-key"] == "test-upstream-key"
    assert headers["x-request-id"] == "req-42"

    assert data.canonical_instrument == "SYNTH/USD"
    assert len(data.candles) == 2


async def test_fetch_historical_candles_rejects_out_of_range_limit() -> None:
    client = MarketDataClient(base_url="https://upstream.test.invalid")

    with pytest.raises(UpstreamError):
        await client.fetch_historical_candles("SYNTH/USD", limit=99999)


async def test_fetch_historical_candles_requires_configuration() -> None:
    client = MarketDataClient(base_url=None)

    with pytest.raises(UpstreamError):
        await client.fetch_historical_candles("SYNTH/USD")


async def test_upstream_error_body_is_not_echoed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": "bad_request",
                    "message": "internal upstream detail with secret abc123",
                }
            },
        )

    client = _client(httpx.MockTransport(handler))

    with pytest.raises(UpstreamError) as excinfo:
        await client.fetch_historical_candles("SYNTH/USD")

    assert "abc123" not in excinfo.value.message
    assert excinfo.value.status_code == 502


async def test_malformed_upstream_payload_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    client = _client(httpx.MockTransport(handler))

    with pytest.raises(UpstreamError):
        await client.fetch_historical_candles("SYNTH/USD")


async def test_list_providers_returns_validated_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/market-data/providers"
        return httpx.Response(200, json=_fixture("upstream_providers_synthetic.json"))

    client = _client(httpx.MockTransport(handler))
    parsed = await client.list_providers()

    assert parsed.data is not None
    assert parsed.data[0].provider_id == "synthetic-test-adapter"


async def test_list_providers_rejects_the_obsolete_object_envelope() -> None:
    """The client must not accept the retired `data.providers` object shape."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = _fixture("upstream_providers_synthetic.json")
        payload["data"] = {"providers": payload["data"]}
        return httpx.Response(200, json=payload)

    client = _client(httpx.MockTransport(handler))

    with pytest.raises(UpstreamError):
        await client.list_providers()


async def test_list_providers_rejects_an_unknown_provider_type() -> None:
    """An unrecognised upstream provider type must be rejected, not coerced."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = _fixture("upstream_providers_synthetic.json")
        payload["data"][0]["provider_type"] = "mock"
        return httpx.Response(200, json=payload)

    client = _client(httpx.MockTransport(handler))

    with pytest.raises(UpstreamError):
        await client.list_providers()
