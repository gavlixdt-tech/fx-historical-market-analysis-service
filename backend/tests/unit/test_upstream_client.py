"""Tests for the upstream market-data client."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from backend.app.clients.base import UpstreamContractStatus, UpstreamState
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


def _status_payload(*, authentication_required: bool = True) -> dict:
    return {
        "data": {"api_key_authentication_required": authentication_required},
        "meta": {
            "api_version": "v1",
            "request_id": "status-check",
            "timestamp_utc": "2026-01-01T00:00:00Z",
        },
        "errors": [],
    }


def _provider_payload(
    *,
    provider_type: str = "real",
    connection_status: str = "available",
    configured: bool = True,
    capabilities: list[str] | None = None,
    connection_test_succeeded: bool | None = True,
) -> dict:
    return {
        "data": [
            {
                "provider_id": "provider-live" if provider_type == "real" else "test-adapter",
                "provider_type": provider_type,
                "configured": configured,
                "connection_status": connection_status,
                "capabilities": capabilities or ["historical_candles"],
                "last_connection_test_at": "2026-01-01T00:00:00Z",
                "last_connection_test_success": connection_test_succeeded,
            }
        ],
        "meta": {
            "api_version": "v1",
            "request_id": "provider-check",
            "timestamp_utc": "2026-01-01T00:00:00Z",
        },
        "errors": [],
    }


def test_unconfigured_client_reports_unconfigured() -> None:
    client = MarketDataClient(base_url=None)

    assert client.is_configured is False
    assert client.has_credential is False


async def test_connectivity_check_requires_authenticated_real_history_provider() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/status":
            assert "x-api-key" not in request.headers
            return httpx.Response(200, json=_status_payload())
        assert request.url.path == "/api/v1/market-data/providers"
        assert request.headers["x-api-key"] == "test-upstream-key"
        return httpx.Response(200, json=_provider_payload())

    client = _client(httpx.MockTransport(handler))
    result = await client.check_connectivity()

    assert result.state == UpstreamState.CONNECTED
    assert result.latency_ms is not None
    assert result.checked_at is not None
    assert result.contract_status == UpstreamContractStatus.VERIFIED
    assert result.authentication_status == "verified"
    assert result.provider_status == "available"
    assert result.provider_tested_at == "2026-01-01T00:00:00Z"


async def test_connectivity_check_reports_missing_required_credential() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/status"
        return httpx.Response(200, json=_status_payload(authentication_required=True))

    client = _client(httpx.MockTransport(handler), api_key=None)
    result = await client.check_connectivity()

    assert result.state == UpstreamState.AUTH_FAILED
    assert result.contract_status == UpstreamContractStatus.VERIFIED
    assert result.authentication_status == "missing"


async def test_connectivity_check_reports_rejected_credential() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/status":
            return httpx.Response(200, json=_status_payload())
        return httpx.Response(401, json={"error": {"code": "unauthenticated"}})

    client = _client(httpx.MockTransport(handler))
    result = await client.check_connectivity()

    assert result.state == UpstreamState.AUTH_FAILED
    assert result.authentication_status == "rejected"


async def test_connectivity_check_does_not_count_test_provider_as_live() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/status":
            return httpx.Response(200, json=_status_payload())
        return httpx.Response(
            200,
            json=_provider_payload(provider_type="test", connection_status="configured_not_tested"),
        )

    client = _client(httpx.MockTransport(handler))
    result = await client.check_connectivity()

    assert result.state == UpstreamState.UNAVAILABLE
    assert result.contract_status == UpstreamContractStatus.VERIFIED
    assert result.authentication_status == "verified"
    assert result.provider_status == "test_adapter_only"


async def test_connectivity_check_requires_a_successful_real_provider_test() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/status":
            return httpx.Response(200, json=_status_payload())
        return httpx.Response(
            200,
            json=_provider_payload(connection_test_succeeded=None),
        )

    client = _client(httpx.MockTransport(handler))
    result = await client.check_connectivity()

    assert result.state == UpstreamState.UNAVAILABLE
    assert result.provider_status == "not_tested"


async def test_connectivity_check_rejects_malformed_status_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {}, "meta": {}, "errors": []})

    client = _client(httpx.MockTransport(handler))
    result = await client.check_connectivity()

    assert result.state == UpstreamState.CONTRACT_MISMATCH


async def test_connectivity_check_reports_unavailable_on_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    client = _client(httpx.MockTransport(handler))
    result = await client.check_connectivity()

    assert result.state == UpstreamState.UNAVAILABLE


async def test_connectivity_check_reports_auth_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/status":
            return httpx.Response(200, json=_status_payload())
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
        await client.fetch_historical_candles(
            "SYNTH/USD",
            provider_id="synthetic-test-adapter",
            limit=99999,
        )


async def test_fetch_historical_candles_requires_configuration() -> None:
    client = MarketDataClient(base_url=None)

    with pytest.raises(UpstreamError):
        await client.fetch_historical_candles(
            "SYNTH/USD",
            provider_id="synthetic-test-adapter",
        )


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
        await client.fetch_historical_candles(
            "SYNTH/USD",
            provider_id="synthetic-test-adapter",
        )

    assert "abc123" not in excinfo.value.message
    assert excinfo.value.status_code == 502


async def test_malformed_upstream_payload_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    client = _client(httpx.MockTransport(handler))

    with pytest.raises(UpstreamError):
        await client.fetch_historical_candles(
            "SYNTH/USD",
            provider_id="synthetic-test-adapter",
        )


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


async def test_provider_connection_test_forwards_auth_and_validates_identity() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == ("/api/v1/market-data/providers/real-provider/test-connection")
        assert request.headers["x-api-key"] == "test-upstream-key"
        return httpx.Response(
            200,
            json={
                "data": {
                    "provider_id": "real-provider",
                    "success": True,
                    "latency_ms": 12.0,
                    "started_at": "2026-01-01T00:00:00Z",
                    "completed_at": "2026-01-01T00:00:01Z",
                    "message": "connected",
                    "request_id": "req-42",
                },
                "meta": {
                    "api_version": "v1",
                    "request_id": "req-42",
                    "timestamp_utc": "2026-01-01T00:00:01Z",
                },
                "errors": [],
            },
        )

    client = _client(httpx.MockTransport(handler))

    assert await client.test_provider_connection("real-provider", request_id="req-42")
